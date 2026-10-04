#!/usr/bin/env bash
# Lint the GitHub Actions configuration, which is load-bearing now: it builds
# the images that ship and publishes them.
#
# Two passes, because one tool does not cover both halves.
#
# Pass 1 is actionlint over .github/workflows. It also reads local action.yml
# metadata, so a call site that forgets a required input fails here.
#
# Pass 2 exists because actionlint does not inspect the *body* of
# .github/actions/*/action.yml for context availability — measured, not
# assumed: a composite action referencing `vars.REGISTRY` lints clean in pass 1
# and then fails every job at load time with "Unrecognized named-value:
# 'vars'". That is not a step failure in a log; the workflow does not parse, so
# every job dies before its first step. It cost two pushes.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

cd "$REPO_ROOT"

# ---- pass 1: the workflows -------------------------------------------------

image="$(pinned_image ACTIONLINT_IMAGE)"

log "actionlint over .github/workflows"
# actionlint exits 3 with "no project was found" if the mount or working
# directory is wrong, so this pass cannot silently assert nothing.
podman run --rm -v "$REPO_ROOT:/repo:z" -w /repo "$image"

# ---- pass 2: contexts inside composite actions -----------------------------

# Every action.yml in the repository, wherever it sits: `uses: ./tools/x` is
# legal, and a nested .github/actions/group/inner/action.yml is as well. Both
# tracked and untracked, so a new action is covered before it is committed —
# the same basis build-images.sh hashes.
mapfile -t -d '' actions < <(
    git ls-files -z --cached --others --exclude-standard \
        -- '*action.yml' '*action.yaml'
)

[[ ${#actions[@]} -gt 0 ]] \
    || die "no action.yml found anywhere in the repository — pass 2 is asserting nothing"

log "composite action contexts (${#actions[@]} action(s))"

# An allow-list, not a deny-list of vars/secrets/needs. Inverting it means an
# unavailable context nobody thought of is still caught, and it sidesteps a
# question I could not settle from documentation: whether `strategy` and
# `matrix` really are reachable from a composite action. They are permitted
# here, so a wrong guess costs a miss on a form nothing in this repo uses,
# rather than a false failure on correct YAML.
allowed='github inputs env runner steps job strategy matrix'

if ! printf '%s\n' "${actions[@]}" \
    | ALLOWED="$allowed" perl -lne '
    BEGIN { %ok = map { $_ => 1 } split " ", $ENV{ALLOWED}; $bad = 0 }

    my $file = $_;
    open my $fh, "<", $file or next;
    my @lines = <$fh>;
    close $fh;

    # Only the sections GitHub evaluates. An expression written inside an
    # input `description:` to document a call site is prose, not code, and
    # flagging it would constrain how the contract may be documented.
    my ($text, @map, $section) = ("", (), "");
    for my $i (0 .. $#lines) {
        my $l = $lines[$i];
        $section = $1 if $l =~ /^([A-Za-z_][\w-]*):/;
        next unless $section eq "runs" or $section eq "outputs";
        $l = "\n" if $l =~ /^\s*#/;      # a whole-line comment is not code
        push @map, [length($text), $i + 1];
        $text .= $l;
    }

    # Non-greedy and across newlines: YAML folds a wrapped scalar, so
    # `${{\n  vars.X }}` is exactly `${{ vars.X }}` by the time GitHub sees it.
    while ($text =~ /\$\{\{(.*?)\}\}/gs) {
        my ($expr, $at) = ($1, $-[0]);
        my $line = 1;
        for my $m (@map) { $line = $m->[1] if $m->[0] <= $at }

        # The head of a reference only: not preceded by a word character, a
        # dot, or a closing paren, so `fromJSON(inputs.x).vars.y` and
        # `inputs.secrets.path` are references to `fromJSON`/`inputs`, not to
        # `vars`/`secrets`. Case-insensitive, because context names are.
        while ($expr =~ /(?<![\w.\-)\$"'"'"'])([A-Za-z_][\w-]*)\s*\./g) {
            next if $ok{ lc $1 };
            printf "  \033[31m%s\033[0m %s:%d: \${{%s}} uses the %s context\n",
                   "x", $file, $line, $expr, lc $1;
            $bad++;
        }
    }

    END { exit($bad > 0 ? 1 : 0) }
'; then
    die "a composite action uses a context it cannot see. Available: $allowed. Pass anything else in as an input."
fi

log "GitHub Actions configuration is valid"
