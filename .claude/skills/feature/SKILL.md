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

## 5. Code review (the code reviewer)

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
