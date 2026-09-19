---
name: feature
description: Build an eoehelp feature through the reviewed workflow. Plan it, have the architect agent approve the plan, implement it, have the code-reviewer agent pass the changes, then commit, push to development, and watch CI. Use for every new feature or substantial change, including when the user describes a feature without naming this skill.
---

# Reviewed feature workflow

The feature to build: $ARGUMENTS

Work through these phases in order, without skipping any. Report progress to
the user in a line or two at each phase boundary.

## 1. Understand

Read the code and docs the feature touches: the relevant domain packages, the
ADRs, and the product plan at
`~/.claude/plans/i-own-the-domain-pure-babbage.md` if the feature is described
there. If a decision belongs to the user (product scope, legal, cost, clinical
wording they must own) and the code cannot answer it, ask now, before writing
the plan.

## 2. Plan

Write `docs/plans/<yyyy-mm-dd>-<feature-slug>.md` from the template in
`docs/plans/README.md`. Be concrete: name the files, endpoints, tables,
components, and tests. A plan the architect cannot check is not a plan.

## 3. Architect review (loop)

Spawn the `architect` agent with the plan's path and a one-paragraph summary
of the feature. When it returns:

- **APPROVED:** go to phase 4. Fix any advisory findings in the plan if they
  are cheap; otherwise note in the plan why they were not taken.
- **CHANGES REQUESTED:** revise the plan to address every blocking finding.
  If you disagree with a finding, say why in the plan rather than silently
  ignoring it. Then send the revised plan back to the same architect agent
  (SendMessage) so it checks its earlier findings.

Append each round to the plan's **Review log**: round number, verdict, and
what changed. After three rounds without approval, stop and bring the
disagreement to the user with both positions stated. Do not start
implementing without an APPROVED verdict.

## 4. Implement

Build exactly what the approved plan says. If implementation shows the plan
is wrong in a way that matters (a new table, a changed endpoint, a different
clinical rule), update the plan and get the architect to re-approve that
change before continuing. Record small deviations in the review log.

Then run everything CI runs:
- `make lint`, `make typecheck`, and `make test-api` for API changes
- `make openapi` and `make api-types` when the API surface changed
- `make web-check` for web changes

For UI work, also run the app and look at it: screenshot the affected screens
at phone width in light and dark mode, and fix what you see.

## 5. Code review (loop)

Spawn the `code-reviewer` agent with the plan's path. When it returns:

- **PASS:** go to phase 6.
- **FIX REQUIRED:** fix every blocking finding, rerun the checks from phase 4,
  and send the fixes back to the same reviewer (SendMessage).

Record each round in the plan's review log. After three rounds without a pass,
bring the remaining findings to the user.

## 6. Ship

Commit the feature and its plan together on `development`, never `main`
unless the user asks, with a message that says what the feature does and
why. Push, watch CI to completion, and fix any failure. Tell the user what
shipped, what the reviews caught, and any open questions left for them.
