# eoehelp

A patient-owned health record for eosinophilic esophagitis: FastAPI and
Postgres (row-level security) in `apps/api`, Angular 22 in `apps/web`, the
OpenAPI contract in `packages/openapi`, and decisions in `docs/adr`. Treat it
as a production medical-adjacent product.

## How features are built

Every new feature or substantial change goes through the reviewed workflow
in `.claude/skills/feature/SKILL.md` (`/feature <description>`):

1. For anything a patient or clinician sees, the `eoe-specialist` agent
   writes the clinical brief first: what matters to the patient, what may
   never be claimed, and the wording to use.
2. The `architect` agent designs the feature and writes its plan in
   `docs/plans/`.
3. You implement the plan and run the checks CI runs. Design problems go
   back to the architect, not into improvised code.
4. The `legal-reviewer` agent reviews changes to patient-facing legal
   wording, and changes that make an existing document's claims stale (a new
   third party, a new field collected, changed retention or logging). Build,
   refactor and dependency work skips it.
5. The `code-reviewer` agent reviews the changes; fix until it passes.
6. Changes that touch the attack surface (auth, patient data access, public
   endpoints, outbound calls, crypto, database grants, dependencies, headers,
   parsing) then go to the `security-reviewer` agent.
7. Build, container, CI and infrastructure changes go to the
   `devops-reviewer` agent.
8. Changes to models, migrations, indexes, constraints, grants or query
   shape go to the `database-reviewer` agent.
9. Commit with the plan, push to `development`, and watch CI.

Reviews run only when they apply, and a plan's review log records which ran
and which were skipped.

Scale the review to what the change can break, and say in the review log why:

- **Presentation only** (styling, copy that makes no claim, a component split):
  the code reviewer alone.
- **Anything reaching patient data, auth, migrations, grants, public endpoints
  or outbound calls:** the reviewers that cover it, without exception. These are
  where every expensive finding so far has come from.
- **Legal and clinical wording:** the legal reviewer, and the specialist for
  anything a patient reads about their own health.

Small fixes (a typo, a one-line bug, a dependency bump) can skip the
architect, but still get a code review before committing.

Three habits this project learned the expensive way:

- **Reviewers that run things find what reviewers that read things do not.** The
  rate-limit bypass, the writable consent table, the grants that were cosmetic,
  and the deadlocked test suite were all demonstrated, not deduced.
- **Ask what would make a new test fail.** Three tests here have been committed
  that could not fail, including one guarding a privacy-policy claim.
- **Do not run two test suites at once.** Each drops and recreates its own
  database; overlapping runs produce failures in whichever test was unlucky.

## Commands

Everything runs in Podman containers; start the machine with
`podman machine start` if a command cannot connect. The command surface is
`just` (pinned 1.58.0, `brew install just`).

`just --list` is the index; every recipe is a thin wrapper over a script in
`scripts/` that CI calls directly.

- `just up`: start the stack (web :4200, API :8000, Mailhog :8025)
- `just test`, `just lint`, `just typecheck`, `just format`: API checks
- `just check`: everything CI runs against the API, in one command
- `just web-check`, `just web-format`: web formatting, tests, and build
- `just contract` after any change to the API surface, `just contract-check`
  to assert it is current
- `just seed`: synthetic patients for local development
- `just build`, `just verify-image`: images, tagged by the content they are
  built from; `scripts/build-images.sh` is the only thing that builds one
- `just shellcheck`: the scripts are the command surface, so they are linted
- `just doctor`: what is wrong before a command fails confusingly

## Rules that carry weight

- Patient data is reached only through repositories scoped by the token's
  patient id, under `/me` routes. New tables get RLS policies and grants
  (ADR 0002).
- The package layout and its dependency rules are in ADR 0010 and enforced by
  `apps/api/tests/test_architecture.py`.
- No PHI in logs, errors, or the audit trail: field names and counts only.
- Clinical wording is descriptive, never prescriptive, and never calls a food
  "safe".
- Migrations can still be edited in place; nothing is deployed yet and
  backwards compatibility is not required.
- Push to `development`, never `main` unless asked.
