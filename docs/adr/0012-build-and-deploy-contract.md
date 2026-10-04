# 12. The build system, and the contract a deployment must satisfy

Date: 2026-09-25 (amended 2026-10-04)

## Status

Accepted. Amends ADR 0005 (Podman) and ADR 0006 (buildah and skopeo) on tooling
detail; neither decision changes.

## Context

The Makefile and `.github/workflows/ci.yml` were two independent implementations
of the same eight checks, with different mechanics — containers locally, host
toolchains in CI. "It passed locally" and "CI is green" were therefore different
claims, and ADR 0006's premise that production runs the artifact which passed
the tests was not true: CI `pip install`ed on the runner and built images nothing
executed.

Measuring the loop found more than duplication. A one-line source change cost
**34 seconds** before any check could start, because every edit reinstalled the
whole dependency closure. A few days of local work left **36 GB** of dangling
images in a 60 GB virtual machine. The development database ran musl Postgres,
which collates by byte, so text ordering and `citext` folding differed from any
glibc build — including the deployed one.

## Decision

**`just` is the command surface and `scripts/` holds the work.** Every recipe is
a thin wrapper over a script that CI calls directly, so there is one definition
of each check. `just --list` is the index.

**Images are tagged by their content.** `scripts/build-images.sh` hashes the
target name, repo-relative paths, and the working tree — tracked and untracked —
and skips any image that already matches. `compose.yaml` has no `build:` keys and
uses `pull_policy: never`: compose describes the runtime, one script owns
building, and neither can silently rebuild nor silently run something stale.

**The local stack has two tiers.** `just up` keeps the reload loop, because the
measured alternative is an image rebuild per edit paid dozens of times an hour.
`just up-prod` runs the artifact that ships — real runtime images, one origin
through Caddy, `ENVIRONMENT=staging` with generated secrets, the API connected as
`app_runtime` — and `just smoke` drives a real sign-in, onboarding and symptom
write through it.

**CI runs the checks inside those images**, and publishes by digest. Publishing
is a job in the same workflow, gated on the API, web and image jobs, so a red
suite cannot produce a candidate; it runs the full image gate — assertions, the
promotion check, and the production-shaped stack under a real request — on the
image it then pushes as `candidate-<sha>`. `promote.yml` is manual, takes
digests, and refuses a source that is not digest-pinned. Registry host and namespace are workflow variables, so ECR is a
variable change and an OIDC login rather than a new pipeline.

## The deploy contract

What a deployment must provide, whatever runs it:

| | |
|---|---|
| Ports | API 8000, web 8080 |
| Health | `GET /healthz` on both |
| Architecture | ARM64 end to end; nothing is cross-built or emulated |
| Images | referenced by `@sha256:`, never by tag |
| Migrations | a separate task, **as the owner role**, completing before the service updates |
| The service | connects as **`app_runtime`**, never the owner, or row-level security does not bind (ADR 0002) |

Environment the API requires: `ENVIRONMENT`, `DATABASE_URL`, `REDIS_URL`,
`APP_BASE_URL`, `API_BASE_URL`, `CORS_ORIGINS`, `SMTP_HOST`, `SMTP_PORT`,
`FORWARDED_ALLOW_IPS`. From a secret store, never a task definition:
`JWT_SECRET`, `FIELD_ENCRYPTION_KEY`, `SMTP_PASSWORD`, `USDA_FDC_API_KEY`, and
the password inside `DATABASE_URL`.

**`FORWARDED_ALLOW_IPS` must name the edge, as narrowly as possible** — and a
subnet is the wrong shape. uvicorn walks `X-Forwarded-For` right to left and
takes the first *untrusted* hop, so every workload inside a trusted range can
choose what lands in `audit_log.ip_address` and which rate-limit bucket it
spends. When the edge is a process on the same host, the correct value is
`127.0.0.1`; it is never a whole subnet because that is convenient.

Measured through the production-shaped stack: with the edge trusted and
rewriting the header, a client-supplied `X-Forwarded-For` does not reach the
audit trail; reaching the API directly, it does. **The API must therefore be
unreachable except through the edge** — enforced by a security group, not by
convention.

**`ENVIRONMENT` is not a safety boundary.** One string decides whether
unreviewed legal documents may be served, whether development secrets are
refused, whether HSTS is sent, and whether the synthetic seeder will run. A
deployment labelled `staging` — which the first one must be, because the legal
documents are drafts — relaxes the secret checks. The task definition's value is
therefore asserted in CI, and the secret checks are proved from outside rather
than inferred from the label.

## Migrations, and what happens when one fails

The contract above says migrations run as a separate task under the owner role
before the service updates. That is not enough to write infrastructure from, so:

- **A snapshot is taken before the migration task runs**, by the deploy, not by
  hand. For health data an irreversible bad migration is permanent loss, and the
  restore path is the only thing standing behind it.
- **Each revision is one transaction**, so a failure leaves the schema at the
  previous revision rather than halfway.
- **A migration must be forward-compatible with the running image.** The
  previous version serves traffic throughout the roll, so a revision that
  removes or renames something the old code reads takes the service down.
  Expand, deploy, contract — in separate releases.
- **A half-applied revision is a named procedure, not improvisation**: stop the
  deploy, restore the snapshot, fix forward. It is written down because the
  moment it is needed is the moment nobody wants to be deciding.
- RPO, RTO and the restore drill live in
  `docs/plans/2026-09-23-aws-infrastructure.md`, which is where the backup
  mechanism is designed.

## Knowing what is running, and going back

Promotion's output is a mutable tag (`:staging`, `:production`), while this
contract says images are referenced by digest. Both are true only if the deploy
records the digest it applied:

- **The deploy writes down the digest it used** — on the task definition, or a
  file alongside it — so "what is running right now" has an answer that does not
  depend on a job summary from months ago.
- **Rollback is re-running Promote with the previous digest**, and it is
  expected to be exercised once before the first real release rather than
  discovered during one.
- **The `production` environment gets a required reviewer** the day it exists.
  Until then the human gate is only the button, which this ADR should not
  describe as more than it is.

## Consequences

- A one-line source edit costs **3.6 s** for the local loop and **18 s** for the
  CI path, against 34 s before. `just up` with nothing changed is 2.4 s.
- Publishing text, or any image, now requires the content tag to move, so a
  stale artifact cannot be served under a current name.
- **Three failures found by the production-shaped stack** that nothing else could
  see: the runtime image could not import itself, because setuptools skips a
  source file that is not newer than its copy under `build/` and `COPY`
  preserves host mtimes; and a readiness check that waited on the web container
  reported ready while the API was still starting. The development stack hides
  both, because it mounts source and sets `PYTHONPATH`. The third was a smoke
  assertion of mine that checked a status code while claiming to check the
  audit trail — now it reads the row that was written.
- The `app_runtime` question the plan carried as a spike is answered: the
  application runs as the unprivileged role end to end. That removes an unknown
  from the first deployment rather than discovering it there.
- CI builds cold until the publish job has populated the layer cache once.
