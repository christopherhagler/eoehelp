# Feature plans

Every feature starts as a plan in this folder. The architect agent reviews it
before any code is written, and the code-reviewer agent reviews the result
before it is committed. The workflow lives in `.claude/skills/feature/` (run it
with `/feature <description>`), and the reviewers' criteria are in
`.claude/agents/`.

A plan is committed with the feature it describes. Its review log records
what each review round found and what changed, so the reasoning behind the
code outlives the conversation that produced it.

Name files `<yyyy-mm-dd>-<feature-slug>.md`.

## Template

```markdown
# <Feature name>

**Status:** Draft | Approved | Implemented · <date>

## Goal
What the patient (or clinician) can do afterwards that they cannot now, and
why it matters for EoE care.

## Clinical basis
The instruments, thresholds, or published methods this relies on, with
citations. What must be confirmed by a clinician (mark it "pending clinical
confirmation"). The wording rules the feature follows.

## Scope
In scope, and explicitly out of scope.

## Design
- **Data model and migrations:** tables, columns, constraints, RLS policies,
  and grants.
- **API:** endpoints, request and response schemas, and status codes.
- **Services:** where the logic lives and the package it belongs to (ADR 0010).
- **Frontend:** screens, components, states (loading, empty, error, not enough
  data), and accessibility.

## Security and privacy
What patient data it touches, how isolation is kept, what is audited, and
what never reaches the logs.

## Testing
The tests that prove it works: API, isolation, web, and synthetic ground truth
for analytics.

## Open questions
Decisions that belong to the user or a clinician.

## Review log
| Round | Reviewer | Verdict | What changed |
|---|---|---|---|
```
