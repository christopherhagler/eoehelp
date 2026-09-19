---
name: feature
description: Build an eoehelp feature through the reviewed workflow. The architect agent designs it and writes the plan, you implement the plan, the code-reviewer agent checks the changes, then you commit, push to development, and watch CI. Use for every new feature or substantial change, including when the user describes a feature without naming this skill.
---

# Reviewed feature workflow

The feature to build: $ARGUMENTS

Work through these phases in order, without skipping any. Report progress to
the user in a line or two at each phase boundary.

## 1. Frame the request

Gather what the architect needs: the user's request in their words, any
decisions they have already made, and the relevant product-plan section at
`~/.claude/plans/i-own-the-domain-pure-babbage.md` if the feature is described
there. If something only the user can decide blocks the design entirely, ask
now. Otherwise, let the architect list it as an open question with a default.

## 2. Design (the architect)

Spawn the `architect` agent with the feature request and that context. It
writes the plan to `docs/plans/<yyyy-mm-dd>-<feature-slug>.md` and returns a
summary with its open questions.

Read the plan in full before building anything.
- **Open questions:** bring any that the user has not answered to them, and
  record their answers in the plan. Where the user is not available, use the
  architect's defaults and say so in the plan.
- **Design problems:** if the plan is unclear, contradicts the code, or
  would not work, send the problem back to the same architect agent
  (SendMessage) rather than improvising. Record each round in the plan's
  review log.
- **Stuck:** after three rounds on the same problem, bring it to the user
  with both positions stated.

## 3. Confirm

Tell the user in a few lines what the architect designed and what it
decided on their behalf. Then go straight to implementation unless an open
question needs their answer first.

## 4. Implement (you)

Build exactly what the plan says. If implementation shows the plan is wrong
in a way that matters (a new table, a changed endpoint, a different clinical
rule), send it back to the architect to revise the design before continuing.
Record small deviations in the review log yourself.

Then run everything CI runs:
- `make lint`, `make typecheck`, and `make test-api` for API changes
- `make openapi` and `make api-types` when the API surface changed
- `make web-check` for web changes

For UI work, also run the app and look at it: screenshot the affected screens
at phone width in light and dark mode, and fix what you see.

## 4a. Legal review (only when a document's claims change)

Spawn the `legal-reviewer` agent when the change either:

- **alters patient-facing legal wording:** the terms, the privacy policy, the
  consumer health data disclosure, consent text, or any claim the product
  makes about liability, safety, or data use; or
- **makes an existing document's factual claims stale**, even with no wording
  change: a new third party or outbound call, a new field collected, a change
  to retention, deletion, encryption, logging, the audit trail, what research
  sharing includes, or who can reach a record.

The second case is the one that is easy to miss. A privacy policy that
overstates what the software does is a misrepresentation, and the code can
drift away from it without anyone editing a document.

**It does not run** for work that changes no such claim: build and tooling,
refactors, dependency bumps, performance, tests, or a screen that displays
data already described. Note in the plan's review log when it was skipped and
why, so the decision is visible rather than forgotten.

Loop on its blocking findings the way the other reviews loop. It is not a
substitute for the attorney review the launch gate requires; it makes that
review cheaper and stops untrue claims from shipping in the meantime.

## 5. Code review (the code reviewer)

Spawn the `code-reviewer` agent with the plan's path. When it returns:

- **PASS:** go to phase 6.
- **FIX REQUIRED:** fix every blocking finding, rerun the checks from phase 4,
  and send the fixes back to the same reviewer (SendMessage).

Record each round in the plan's review log. After three rounds without a pass,
bring the remaining findings to the user.

## 5a. Security review (when the change touches the attack surface)

If the change touches authentication, sessions, patient data access, an
unauthenticated endpoint, outbound requests, cryptography, database
permissions, dependencies, response headers, or any parsing or rendering of
input, spawn the `security-reviewer` agent after the code review passes. Fix
its critical and high findings before shipping, record each round in the
plan's review log, and note in the log when a feature did not need this pass
and why.

It is not the independent penetration test the launch gate requires. It
exists because a per-feature code review is not an adversarial pass: the
review on 2026-09-17 found that production would accept the public
development encryption key, that nothing was rate-limited, and that
concurrent sign-ins raced, and none of those would have surfaced from
reading one diff against one plan.

## 5b. DevOps review (build, containers, CI, and infrastructure)

If the change touches Dockerfiles, compose, the task runner or scripts,
GitHub Actions, Terraform or AWS configuration, or anything affecting how the
app is built, started, deployed, migrated, backed up, or rolled back, spawn
the `devops-reviewer` agent after the code review. Fix its blocking findings,
and record each round in the plan's review log.

Infrastructure fails in ways a code review does not look for: an image that
only builds on the machine that built it, a deploy with no way back, a secret
in a layer, a migration that runs in the wrong order against live data, a
backup nobody has restored, and a bill that arrives at the end of the month.
One person operates this, so anything needing a remembered step will
eventually not happen.

## 6. Ship

Commit the feature and its plan together on `development`, never `main`
unless the user asks, with a message that says what the feature does and
why. Push, watch CI to completion, and fix any failure. Tell the user what
shipped, what the reviews caught, and any open questions left for them.
