# Build system, local/production parity, and the path to AWS

**Status:** Draft · 2026-09-19

## Goal

Three things a developer (or an agent) can do afterwards that they cannot now:

1. **Run one discoverable entry point that CI also runs.** `just --list` is the
   command index; every recipe is a thin wrapper over a script in `scripts/`,
   and CI calls the same scripts. Today the Makefile and `.github/workflows/ci.yml`
   are two independent implementations of the same eight checks, with different
   mechanics (containers locally, host toolchains in CI), so "it passed locally"
   and "CI is green" are different claims.
2. **Get feedback in seconds instead of half a minute per edit.** A one-line
   source change today forces a full dependency reinstall inside the API image
   before lint, type-check, or tests can run: **34.0 s measured**, every time.
   After this change the same edit rebuilds nothing (**3.6 s, all layers cached**,
   and in the normal path no build is attempted at all).
3. **Run the artifact that will actually be deployed, on one origin, and prove
   it works.** `just up-prod` runs the real runtime images behind a local edge
   that stands in for CloudFront, and `just smoke` drives a sign-in and a symptom
   entry through them. Today nothing ever runs the runtime web image or the
   same-origin `/api/v1` path that production will use.

It matters for EoE care indirectly but concretely: the three findings in
*Parity defects found while measuring* are wrong answers that local development
currently hides — text sorting that differs from RDS, an audit trail that would
record the load balancer's address instead of the patient's, and row-level
security that is inert in the dev stack.

## Clinical basis

No instrument, threshold, or clinical computation changes. No patient-facing
wording changes. Three clinically relevant consequences are in scope because the
build is what hides them:

- **Collation.** `postgres:16-alpine` is musl-linked, and musl implements only
  byte ordering, so `ORDER BY` on text differs from the glibc `en_US.UTF-8`
  ordering an RDS instance uses. Measured on identical server versions
  (PostgreSQL 16.15, `datcollate = en_US.utf8`, `datlocprovider = c`):

  | Image | `ORDER BY x` over `apple, Apple, banana, _under, Zebra, ápple` |
  |---|---|
  | `postgres:16-alpine` (musl) | `Apple Zebra _under apple banana ápple` |
  | `postgres:16-bookworm` (glibc) | `apple Apple ápple banana _under Zebra` |

  Ingredient, medication, and food-product lists are the patient-facing surfaces
  that read from an ordered query, so today's local ordering is not the ordering
  a patient will see. The same image mismatch also applies to `citext`, which is
  case folding, and musl's folding of non-ASCII differs — that is the uniqueness
  rule for email addresses.
- **Audit truthfulness.** `deps.py` records `request.client.host` in
  `audit_log.ip_address`, and `core/ratelimit.py` keys limits on the same value.
  uvicorn 0.53 enables proxy headers by default but trusts only `127.0.0.1`
  unless `FORWARDED_ALLOW_IPS` is set (verified from `uvicorn --help` and
  `ProxyHeadersMiddleware.__init__`, which defaults `trusted_hosts="127.0.0.1"`).
  Behind an ALB, with no such variable, every audit row would record the
  balancer's address and every patient would share one rate-limit bucket. The
  code comment in `ratelimit.py` already states the requirement; nothing sets it
  or proves it. This plan makes it provable locally; M0b sets the value in the
  task definition.
- **Row-level security is inert in the dev stack.** `compose.yaml` gives the API
  `postgresql+asyncpg://eoehelp:eoehelp@postgres:5432/eoehelp` — the table
  *owner*, which bypasses RLS by design (ADR 0002). Only
  `tests/db/test_patient_isolation.py` connects as `app_runtime`. Production must
  connect as `app_runtime`, and that path has never been exercised by a running
  application. This plan adds the experiment that answers whether it works
  (*Stage 4 spike*); it does not attempt the fix, because migration 0001's
  policies have no explicit `WITH CHECK` and sign-up inserts a `patients` row
  before any scope exists, so making it work is a service-layer feature, not a
  build change.

Nothing here is pending clinical confirmation.

## Scope

**In scope**

- Delete the `Makefile`. Replace it with a `justfile` plus `scripts/*.sh`, and
  update every reference to a `make` target in the repository.
- Restructure `apps/api/Dockerfile` so the dependency layer is keyed on
  `pyproject.toml` alone, and add a `dev` stage for the local check loop.
- Add a `deps` stage to `apps/web/Dockerfile` that owns `node_modules`, and
  delete the `web_node_modules` named volume.
- Content-addressed image tags, so `just up` and `just test` build only when
  their inputs changed, and repeat builds stop orphaning images.
- `compose.yaml` restructured: images referenced by tag with `pull_policy: never`,
  migrations as a one-shot service, pinned glibc Postgres, web tooling as a
  compose service instead of an ad-hoc `podman run node:24`.
- `compose.prod.yaml`: the runtime images, one origin through a local edge nginx,
  `ENVIRONMENT=staging`, generated secrets, `FORWARDED_ALLOW_IPS` set.
- `scripts/smoke.sh`: an end-to-end sign-in and symptom entry against whichever
  stack is up.
- CI rewritten to run the checks **inside the images it builds**, with
  registry-backed layer caching, and to assert the runtime image carries no test
  tooling.
- `scripts/publish.sh` and `scripts/promote.sh` plus the two workflows that call
  them, targeting **GHCR today** so they are runnable rather than aspirational.
- A new ADR recording all of the above, including a "what the runtime needs from
  the platform" section that M0b's Terraform must satisfy.
- Removing `ALTER DEFAULT PRIVILEGES` from `infra/postgres/init/01-extensions.sql`
  and running that same file in CI instead of CI's divergent heredoc.

**Out of scope — stays in M0b**

- AWS Organization, the two accounts, the BAA in Artifact.
- All Terraform: VPC, RDS, ElastiCache, ECS/Fargate, ALB, CloudFront, S3,
  Route 53, ACM, SES, WAF, KMS, Secrets Manager, CloudWatch, CloudTrail.
- ECR repositories, tag immutability, scan-on-push, the GitHub OIDC role, and
  any workflow that deploys. The publish/promote workflows written here take the
  registry as a variable; pointing them at ECR is a variable change and a login
  step, not a rewrite.
- **No Terraform skeleton.** ADR 0006 refused to commit unrunnable YAML for the
  same reason: a Terraform root with no account, no state backend, and no way to
  `plan` is a file that rots and lies. The deploy contract is written as prose
  in the ADR instead, which is what actually makes M0b faster.

**Out of scope — separate features, named so they are not lost**

- Running the application as `app_runtime` (the RLS gap above). Stage 4 measures
  it; fixing it is its own feature, and the product plan puts full RLS work in M4.
- Parallelising the API suite. The suite is **2 m 25 s** measured in-container and
  dominates every check run; `pytest-xdist` with per-worker databases
  (`eoehelp_test_gw0`, …) is the mechanism. It is excluded here because the suite
  is not currently reliable enough to parallelise: on a full run during
  measurement, 5 tests errored (`tests/synthetic/…`, `tests/symptoms/…`) that pass
  in isolation. Diagnosing that flake comes first.
- A Python lock file. Dependencies are declared as floating ranges
  (`fastapi>=0.115`), so two cold builds a week apart can produce different
  images. That is a reproducibility problem worth fixing for a medical-adjacent
  artifact, but it is dependency management, not build plumbing, and the layer
  split below removes the *speed* reason to care. See *Open questions* 6.
- `shellcheck` in CI for the new scripts. Cheap and worth doing later; not a
  prerequisite for this change.

## What the current build actually does (measured)

All figures from this machine (macOS on Apple Silicon, `podman machine` applehv,
6 CPUs, 8 GiB) on 2026-09-19. Raw logs were kept in the session scratchpad.

| What | How | Measured |
|---|---|---|
| API image rebuild, nothing changed | `podman build --target runtime apps/api` | **4.5 s** (18/18 layers cached) |
| API image rebuild, one-line source edit | `podman build --target test apps/api` | **34.0 s** — `COPY src` misses, so `pip install .` reinstalls every dependency, and the `test` stage then reinstalls `[dev]` on top |
| Same edit, proposed `dev` stage | `--target dev` on the restructured file | **3.6 s** (14 cache hits, nothing rebuilt) |
| Same edit, proposed `test` stage | `--target test` on the restructured file | **19.8 s** |
| Cold build, proposed file | `--no-cache --target test` | **56.5 s** |
| Cold build in an **empty container store**, restoring from a registry cache | `podman build --layers --cache-from …` in an isolated store inside the VM | **12.2 s**, 18/18 layers cached |
| Populating that cache | `podman build --cache-to 127.0.0.1:5003/eoehelp-cache` | **27.6 s**, cache repo created |
| API suite, in-container | `pytest -q` against the compose Postgres | **2 m 25 s** |
| Web production build, in-container, `.angular` deleted first | `ng build --configuration production` | **3.8 s** |
| Web unit tests | `ng test --watch=false` | **4.2 s**, 63 tests |
| Cold web builder image | `podman build --no-cache --target builder apps/web` | **15.0 s** (of which `npm ci` is 5 s, 385 packages) |
| Image store after a few days of `make up` | `podman system df` | **36.16 GB, 98% reclaimable, 195 dangling images, 1572 layers** in a 60 GiB VM |

Five conclusions:

1. **The dependency layer is the whole API build problem.** `COPY src ./src`
   precedes `pip install .`, so every source edit reinstalls ~30 packages,
   including compiled ones. Fixing the layer order is worth 34 s → 3.6 s on the
   path used dozens of times a day.
2. **The web Dockerfile is already correctly layered.** `npm ci` sits behind
   `COPY package.json package-lock.json*`. The web problem is entirely in
   `make web-check`, which runs `npm ci` on every invocation (5 s) into a named
   volume shared with the dev server — the stale-`node_modules` breakage.
3. **`make up`'s `--build` is the disk leak.** Every invocation re-tags and
   orphans the previous image; 195 dangling images is 35 GB of a 60 GiB VM.
4. **Registry-backed caching works with the tools this project already uses**, and
   is worth having in CI: 56.5 s → 12.2 s on a cold runner with dependencies
   unchanged. `--cache-to` and `--cache-from` were both exercised against a local
   `registry:2`, the second in a container store with nothing in it.
5. **Nothing is redundant about building three images** — with `--layers` the
   `test` image reuses `runtime`'s layers. The redundancy is in CI, which
   installs the API's dependencies three times (`api`, `openapi-drift`,
   `security`) and `npm ci`s twice (`web`, and again inside the web image build).

### Parity defects found while measuring

Beyond the three in *Clinical basis*:

- **CI's Postgres bootstrap duplicates `infra/postgres/init/01-extensions.sql`**
  as a heredoc, and the two have already drifted: CI omits the `GRANT CONNECT`,
  `ALTER DEFAULT PRIVILEGES`, and schema grant. The local extras are the wrong
  side of the drift — `ALTER DEFAULT PRIVILEGES … GRANT … TO app_runtime` means a
  migration that forgets its explicit grants still works in the dev database,
  while every migration in the tree does grant explicitly (verified: 0001–0005
  each contain a `_apply_runtime_grants` block). Tests are unaffected either way,
  because `CREATE DATABASE eoehelp_test` does not inherit another database's
  default privileges.
- **The dev stack never exercises the production origin.**
  `core/api/api.ts` resolves the API base as `${origin}/api/v1` everywhere except
  localhost, where it hardcodes `http://localhost:8000/api/v1`. So local
  development exercises a cross-origin CORS path that production will not use,
  and never exercises the same-origin path that production will — including how
  the httpOnly refresh cookie behaves.
- **`apps/api/Dockerfile`'s final stage is `test`.** Nothing is broken today
  because every call passes `--target`, but the artifact that a future
  `buildah build -t …` without `--target` would publish is the image containing
  pytest, ruff, mypy, and `tests/`. The fix in this plan is an assertion, not an
  ordering convention (see *Design 2*).

## Design

### 1. The entry point: `just`, with the work in `scripts/`

**Decision: `just` (pinned 1.58.0), with every recipe at most three lines and all
real logic in `scripts/*.sh` that CI calls directly.**

Why `just` over the alternatives, for an audience of one developer on macOS, plus
CI, plus agents:

- Every Makefile target here is phony. make's value is file-timestamp dependency
  resolution, which this repo never uses, and its costs — tab significance, `$$`
  escaping, `.PHONY` bookkeeping, `$(or $(n),3)` for a default argument — are
  paid on every edit. `just` recipes are plain `sh`, so the current commands port
  across one-to-one.
- `just --list` is the help that the Makefile hand-rolls in awk, and `[group(…)]`
  attributes give it sections. Discoverability is the main reason the Makefile is
  referenced in four documents.
- Named parameters with defaults replace make's variable idioms:
  `just seed 3 18 1`, `just revision "add symptom entries"`,
  `just test tests/symptoms -k dsq`.
- One static binary, `brew install just` locally, and in CI a pinned tarball with
  a verified checksum — no third-party action in the supply chain:
  `just-1.58.0-aarch64-unknown-linux-musl.tar.gz`,
  `sha256 748237128c4c40cbdabc65e841d05ceba13cc23a91eaba395495894c1d9764df`
  (from the release's `SHA256SUMS`). The macOS tarball is
  `50ae3e996c974a0bf32ea7d10f495070df33f1b43e0616b2769e3d4821ed8f48` if the
  developer prefers not to use brew.
- Recipes run with the working directory set to the justfile's directory, which
  removes the `$(PWD)` fragility in the current `podman run -v "$(PWD)/apps/web:…"`
  lines.

Rejected:

- **go-task.** Its `sources:`/`status:` fingerprinting is a genuine advantage
  over `just`, and it is the only candidate that competes on "no needless
  rebuilds". Rejected because that problem is solved better one level down, by
  content-addressed image tags (*Design 2*), which also fix it for CI and for
  anyone invoking the scripts directly — a task-runner-level fingerprint would
  not. Its YAML-plus-Go-templates syntax is also a worse host for shell than
  `just`'s plain `sh`.
- **npm scripts at the repository root.** Requires host Node for every command
  including the Python ones, has no help output, passes arguments awkwardly, and
  conflates the repo's task surface with `apps/web`'s package manifest.
- **Shell scripts only, with a `./x` dispatcher.** Zero new dependencies, and the
  scripts exist either way under this design. Rejected as the *entry point* only
  because the dispatcher, its help text, and its argument parsing are ~80 lines
  of bespoke code to replace one 5 MB binary that a single `brew install`
  provides. If *Open question 1* comes back "no new tool", this is the fallback
  and the scripts do not change.
- **Compose profiles alone.** They orchestrate services; they cannot express
  `lint`, `openapi`, or `verify-promote`. Profiles are used inside this design,
  not as the entry point.

**Recipes** (`justfile` at the repository root, `default: @just --list`):

| Group | Recipe | Runs |
|---|---|---|
| stack | `up` | `scripts/build-images.sh dev` then `compose up -d`; prints the three URLs |
| stack | `down`, `clean`, `logs [svc]`, `ps` | compose equivalents; `clean` takes down both the dev and prod projects with `-v` |
| stack | `up-prod`, `down-prod` | the prod-shaped stack (*Design 3*) |
| stack | `doctor` | `scripts/doctor.sh`: podman machine running, free space in the VM, `skopeo` present, `just` version, compose provider found |
| db | `migrate` | `compose exec api alembic upgrade head` |
| db | `revision message` | autogenerate, then print the hand-review warning that the Makefile prints today |
| db | `psql`, `seed [patients] [months] [seed]` | as today |
| api | `test *args` | `scripts/api-checks.sh test $args` |
| api | `lint`, `format`, `typecheck` | `scripts/api-checks.sh <name>` |
| api | `check` | lint, typecheck, test, contract-check |
| web | `web-test`, `web-check`, `web-format` | `scripts/web-checks.sh <name>` |
| contract | `openapi`, `api-types`, `contract` | regenerate |
| contract | `contract-check` | both generators in `--check` mode: exactly what CI asserts |
| images | `build [target]`, `rebuild` | `scripts/build-images.sh` (`--no-cache` for `rebuild`) |
| images | `verify-image` | `scripts/verify-image.sh`: manifest media type, arch, non-root, no test tooling |
| images | `verify-promote` | existing script |
| images | `publish`, `promote digest` | stage 4 |
| quality | `preflight` | `check`, `web-check`, `verify-image`, then `up-prod` → `smoke` → `down-prod` — the gate before pushing |
| quality | `smoke` | `scripts/smoke.sh` against the running prod-shaped stack |
| housekeeping | `prune` | dangling images, stopped containers, build cache; never volumes |
| ci | `ci-api`, `ci-web`, `ci-images` | the exact sequences CI runs |

**Scripts** (`scripts/`, `bash` with `set -euo pipefail`):

| Script | Interface | Responsibility |
|---|---|---|
| `lib.sh` | sourced | `sha256_of FILES…` (uses `sha256sum`, falls back to `shasum -a 256` for macOS), `image_tag NAME`, `compose …` wrapper that passes `--env-file infra/images.env`, `require_cmd`, `log`/`die` |
| `build-images.sh` | `[dev\|runtime\|test\|web-deps\|web-runtime\|all] [--no-cache] [--cache-from REF] [--cache-to REF]` | computes each content tag, skips any image that already exists, otherwise builds with `--format docker --layers --target …`; prints `NAME=tag` lines that callers `eval` |
| `api-checks.sh` | `lint\|format\|typecheck\|test [pytest args]` | runs the tool in the `dev` image with `apps/api` mounted; `test` needs the stack up and fails with a clear message if Postgres is unreachable |
| `web-checks.sh` | `check\|test\|format\|build` | `compose run --rm --no-deps web-tools …` |
| `openapi.sh` | `[--check]` | regenerate `packages/openapi/schema.json` via a temp file (today's safety property), or diff and exit non-zero |
| `api-types.sh` | `[--check]` | regenerate `apps/web/src/app/api-client/schema.d.ts`, or diff and exit non-zero |
| `verify-image.sh` | `IMAGE…` | the four assertions, lifted out of `ci.yml` so they can run locally |
| `db-init.sh` | `HOST PORT` | applies `infra/postgres/init/01-extensions.sql`; used by CI so the file has one definition |
| `smoke.sh` | `EDGE_URL [DIRECT_API_URL]` | end-to-end through the edge: `/healthz`, magic link via the Mailhog API, `/api/v1/…` sign-in, POST a symptom entry, GET it back, assert the audit row count moved. Given the second argument, it also checks that `X-Forwarded-For` is honoured through the edge and ignored when sent directly to the API |
| `prod-stack.sh` | `up\|down` | brings up the prod-shaped stack with plain `podman` for CI (same env files as `compose.prod.yaml`) |
| `publish.sh` | `IMAGE REGISTRY REPO` | pushes and prints the digest (stage 4) |
| `promote.sh` | `SRC@digest DST:tag` | `skopeo copy --all` (stage 4) |
| `verify-promote.sh` | unchanged | already exists |

`scripts/` must not grow a second way to do anything the justfile already
exposes: recipes call scripts, scripts never call `just`.

### 2. Image structure, content tags, and caching

**`apps/api/Dockerfile` — stage graph** (no BuildKit-only syntax, per ADR 0006):

```
python:3.12-slim-bookworm ─ pydeps-base   apt build-essential libpq-dev; venv;
                            │             COPY pyproject.toml README.md;
                            │             a stub src/eoehelp_api/__init__.py
                            ├─ deps       pip install .            (key: pyproject.toml)
                            │   └─ builder  COPY src; pip install --no-deps --force-reinstall .
                            └─ devdeps    pip install ".[dev]"     (key: pyproject.toml)

python:3.12-slim-bookworm ─ runtime-base  runtime apt libs (Pango/Cairo/curl);
                            │             the app user; WORKDIR /app
                            ├─ runtime    COPY --from=builder /opt/venv; alembic.ini,
                            │   │         alembic, src; USER app; HEALTHCHECK; CMD uvicorn
                            │   └─ test   + ".[dev]" + tests   (unchanged semantics)
                            └─ dev        COPY --from=devdeps /opt/venv; PYTHONPATH=/app/src;
                                          caches to /tmp; source is mounted, never copied
```

The stub-package trick is what makes the dependency layer's cache key
`pyproject.toml` alone: `[tool.setuptools.packages.find] where = ["src"]` is
satisfied by an empty `src/eoehelp_api/__init__.py`, so `pip install .` resolves
and installs the third-party closure; `builder` then copies the real source and
reinstalls the package with `--no-deps --force-reinstall`, which uninstalls the
stub first. Measured above: 56.5 s cold, 19.8 s after a source edit, 3.6 s for
`dev` after a source edit. This exact file was built and measured during design;
the implementer should reproduce the three numbers.

`test` stays `FROM runtime`, so ADR 0005's property — the test image is built
from the image that ships — is preserved unchanged, and CI keeps paying the
19.8 s. The fast local loop moves to `dev`, which branches from `runtime-base`
before any source is copied and therefore never needs rebuilding when source
changes. `dev` and `test` install from the same `pyproject.toml` on the same base
image, so the drift between them is bounded to the presence of the app source,
and CI still runs the suite in `test`.

**The final-stage hazard** is closed by assertion rather than by ordering.
`scripts/verify-image.sh` adds, to the existing manifest/arch/non-root checks:

- `podman run --rm IMAGE sh -c '! command -v pytest && ! command -v ruff && ! command -v mypy'`
- `podman run --rm IMAGE sh -c '! test -e /app/tests'`

Reordering the file so `runtime` is last would require `test` not to descend from
`runtime`, which costs more than it buys; a stage alias at the end of the file
would make the default target implicit, which is worse than an asserted
invariant. `scripts/publish.sh` always passes `--target runtime`, and the
assertion is what proves it.

**`apps/web/Dockerfile` — stage graph:**

```
node:24-bookworm-slim ─ deps      COPY package.json package-lock.json angular.json
                        │         tsconfig*.json .postcssrc.json .prettierrc
                        │         .prettierignore; npm ci; npm i -g openapi-typescript@7.13.0
                        └─ builder  COPY . .; npm run build -- --configuration production
nginx:1.27-alpine ───── runtime   unchanged
```

`deps` is what the dev server and all web tooling run, with only `src/` and
`public/` mounted — which is why the `web_node_modules` volume can be deleted
outright. The volume's stated purpose ("keeps container-built node_modules from
being shadowed by the host mount") does not hold: the host mounts are `src/` and
`public/`, not `/build`, so nothing shadows `/build/node_modules`. What the
volume actually does is snapshot `node_modules` on first use and then never
update it, which is the failure the user already hit. Configuration files are
copied into the image rather than mounted so that a dependency or config change
is a content-tag change; they change rarely and the rebuild is 15 s.

`openapi-typescript` is installed **globally in the image** at its pinned
version. That keeps the peer-dependency conflict with TypeScript 6 out of
`package-lock.json` — the reason the Makefile used `npx -y` — while removing a
network fetch from every `just api-types` run and from CI.

No `.angular` cache volume. Measured, the production build is 3.8 s with the
cache deleted, so a persistent cache volume would buy nothing and would
reintroduce exactly the class of staleness this change is removing.

**Content-addressed tags.** `scripts/build-images.sh` computes
`tag = sha256(inputs)[0:12]` and names images `localhost/eoehelp-api-dev:<tag>`,
`localhost/eoehelp-api:<tag>`, `localhost/eoehelp-api-test:<tag>`,
`localhost/eoehelp-web-deps:<tag>`, `localhost/eoehelp-web:<tag>`. Inputs:

| Image | Hash inputs |
|---|---|
| `api-dev` | `apps/api/pyproject.toml`, `apps/api/Dockerfile` |
| `api-runtime`, `api-test` | the above plus `git ls-files -s apps/api/src apps/api/alembic apps/api/alembic.ini` (and `apps/api/tests` for `test`) |
| `web-deps` | `apps/web/package.json`, `package-lock.json`, `angular.json`, `tsconfig*.json`, `.postcssrc.json`, `.prettierrc`, `.prettierignore`, `Dockerfile` |
| `web-runtime` | the above plus `git ls-files -s apps/web/src apps/web/public apps/web/nginx` |

`git ls-files -s` is the source of truth for tracked content, which keeps the hash
stable against mtimes and untracked scratch files. A file must be `git add`-ed to
affect a content tag; `doctor` warns when `git status --porcelain` shows
untracked files under `apps/`, because that is the one confusing case.

Two properties follow. First, "no needless rebuilds": `podman image exists
<name>:<tag>` (~50 ms) replaces `compose up --build`, so the common case builds
nothing at all. Second, repeat builds stop orphaning images, because the tag is
the content; `just prune` handles the images left behind by genuine changes, and
the one-time cleanup of the current 35 GB is `podman system prune -a`, which
`doctor` suggests when the VM has less than 10 GB free.

**Registry cache in CI.** `--layers` is already passed. Add
`--cache-from ghcr.io/christopherhagler/eoehelp/cache-api` and `--cache-to` the
same reference on the two jobs that build (see *Design 4*); the `images` job
reads the cache and does not write it, so two jobs never race on the same cache
repo. Measured effect on a store with nothing in it: 12.2 s versus 56.5 s cold.
The cache repos hold layer blobs of a public repository's source and no secrets
or patient data; visibility is *Open question 3*.

### 3. The local stack: two tiers, and where the line is

**Tier 1 — `just up`, the default. Source-mounted, reload, `ng serve`.**

The reload loop stays. The measured alternative is a 19.8 s image rebuild plus a
container restart for every API edit and ~15 s for every web edit, paid dozens of
times an hour; the parity it buys is realised a few times a week. The line is
therefore: **anything that costs the reload loop nothing is made
production-shaped in tier 1 as well.** That is, in this tier:

- `postgres:16.15-bookworm` (glibc, verified to exist:
  `sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67` for
  linux/arm64), pinned by minor, in `infra/images.env` so CI reads the same value.
  `redis:7.4-alpine` pinned likewise.
- Migrations move out of the API's command into a one-shot `migrate` service;
  `api` depends on it with `condition: service_completed_successfully` (verified
  working with this compose provider). This is the shape ECS uses — a pre-deploy
  migration task — and it removes the race that `alembic upgrade head && uvicorn`
  would create the moment more than one task runs.
- Services reference images by tag with `pull_policy: never`, and no `build:`
  keys: compose describes the runtime, `scripts/build-images.sh` owns building,
  and both use the same flags CI uses. Verified that `localhost/…`-prefixed
  references and `pull_policy: never` work with the installed provider
  (`docker-compose` 5.5.1 over the podman socket).
- Web tooling becomes a `web-tools` service on the `web-deps` image
  (`profiles: ["tools"]`, so `up` does not start it), replacing the ad-hoc
  `podman run … node:24-bookworm-slim` with its shared named volume.

Deliberate tier-1 deviations, and why: console logging rather than JSON
(`observability.py` keys this on `ENVIRONMENT=local`, and readable logs are worth
more than parity at the keyboard); the dev JWT and field keys; the API published
on 8000 with CORS rather than behind one origin; the app connecting as the table
owner.

**Tier 2 — `just up-prod`, on demand. The artifact that ships.**

`compose.prod.yaml`, project name `eoehelp-prod`, self-contained (not an override
file — compose cannot *remove* a volume mount through an override, so an overlay
could not drop the source mounts) and reading the same `infra/images.env` so the
datastore versions cannot drift between the two files. Every published port is
shifted so both tiers can run at once: edge **8080**, api **8001**, postgres
**5433**, redis **6380**, Mailhog **8026** (UI) and **1026** (SMTP).

| Service | Tier 2 |
|---|---|
| `edge` | `nginx:1.27-alpine` with `infra/local-edge/edge.conf`: `/api/v1/` → `api:8000`, everything else → `web:8080`, published on **8080**. A local stand-in for CloudFront's routing, so the SPA's `${origin}/api/v1` resolution — the production path, never exercised today — is what runs. It sets `X-Forwarded-For`/`X-Forwarded-Proto` as the ALB will. |
| `web` | the `runtime` image: real nginx, real `app.conf`, real security headers, hashed assets, `/healthz` |
| `api` | the `runtime` image. No mounts, no `PYTHONPATH`, no `--reload`. `ENVIRONMENT=staging`, `DEBUG=false` (so `observability.py` emits JSON, as CloudWatch will receive; `/docs` stays available, as it will in staging), `APP_BASE_URL=API_BASE_URL=http://localhost:8080` so magic links point at the edge, `CORS_ORIGINS=http://localhost:8080`, `FORWARDED_ALLOW_IPS` set to the compose network's CIDR, secrets from `infra/local-prod.env`. Published on 8001 **only** so the spoofed-header test can reach it directly; the browser path goes through the edge |
| `migrate` | one-shot, the `runtime` image, `alembic upgrade head`, connecting as the owner |
| `postgres`, `redis`, `mailhog` | as tier 1, separate volumes |

Secrets: `infra/local-prod.env.example` is committed with placeholders and
`infra/local-prod.env` is git-ignored (an explicit `.gitignore` line is required —
the existing `.env.*` pattern does not match this name). `just secrets` generates
a 32-byte JWT secret and a urlsafe-base64 32-byte field key with `openssl rand`,
so tier 2 runs with non-development keys and `enforce_production_safety`'s
comparisons are exercised against real values. `ENVIRONMENT=staging` rather than
`production` because `synthetic/writer.py` refuses production outright and
`identity/documents.py` gates document drafts on it; staging is the environment
the first AWS deployment will be anyway.

Known tier-2 deviations, stated rather than implied: Mailhog instead of SES; one
nginx instead of CloudFront + ALB + WAF; plain HTTP on localhost (browsers treat
`http://localhost` as a secure context, so the `Secure` cookies that
`environment != "local"` sets are still stored); a single Postgres container
instead of Multi-AZ RDS with KMS; env-file secrets instead of Secrets Manager;
and the API connecting as the owner unless the spike below changes that.

**Stage 4 spike — does the app run as `app_runtime`?** Point tier 2's `api` at
`app_runtime` while `migrate` keeps the owner URL, then run `just smoke`. Two
possible outcomes, both acceptable, and the result is recorded in this plan's
review log:

- It works: tier 2 keeps `app_runtime`, and the first AWS deploy has one fewer
  unknown.
- It fails (expected — the `patients` policy has no explicit `WITH CHECK`, so
  `USING (id = current_setting(...))` governs inserts and sign-up has no scope
  yet): tier 2 reverts to the owner URL with a comment pointing at the follow-up
  feature, and the failure mode is written into the ADR so M0b does not discover
  it in Fargate.

### 4. CI: run the checks inside the images, and test what gets published

The premise of ADR 0006 is that production runs the artifact that passed the
tests. CI does not currently do that: the `api` job runs `pip install -e` on the
runner, and the `images` job builds images that nothing ever executes. This is
also the duplication the user is paying for twice (three `pip install`s, two
`npm ci`s) and the reason "it passed locally" and "CI is green" can disagree.

New shape — four jobs, all on `ubuntu-24.04-arm` except `security`:

| Job | Steps |
|---|---|
| `api` | install `buildah`, `podman`, `skopeo`, `just` (pinned + checksum) · start Postgres via `services:` on the pinned **bookworm** tag · `scripts/db-init.sh localhost 5432` (the real init file, replacing the drifted heredoc) · `just ci-api` → build `test` with `--cache-from`/`--cache-to` · `ruff check . && ruff format --check .` · `mypy src` · `pytest --cov` · alembic `upgrade/downgrade/upgrade` · `scripts/openapi.sh --check` |
| `web` | same tooling · `just ci-web` → build `web-deps` and `web-runtime` with cache · `format:check`, `ng test --watch=false`, production build inside the image · `scripts/api-types.sh --check` |
| `images` | `just ci-images` → build `runtime` + `web-runtime` from cache (read-only) · `scripts/verify-image.sh` (manifest, arch, non-root, **no test tooling, no `/app/tests`**) · `scripts/verify-promote.sh` · *(added in stage 4, once the prod-shaped stack exists)* `scripts/prod-stack.sh up` + `scripts/smoke.sh http://127.0.0.1:8080` + `down` |
| `security` | unchanged: `pip-audit --strict` on the frozen non-editable closure, `npm audit --audit-level=high`, on `ubuntu-latest` |

Notes the implementer needs:

- Tests run with `podman run --network=host` against the GitHub `services:`
  Postgres on `localhost:5432`. The unit of parity is the image and the command
  inside it, not the orchestrator; using the platform's health-checked service
  container is more reliable than standing Postgres up by hand, and `--network
  host` in a test container has no production meaning.
- No daemon is introduced. buildah builds, podman runs (fork/exec, daemonless),
  skopeo publishes — ADR 0006's "no container daemon in CI" claim survives, and
  the runner's preinstalled Docker is simply unused.
- `openapi-drift` disappears as a job; its check becomes a step in `api` using
  the same script the developer runs. Its error message changes from
  `Run 'make openapi'` to `Run 'just openapi'`.
- Error messages stay actionable: every failure names the `just` recipe that
  reproduces it locally.
- Expected wall clock: `api` ≈ 3–4 min (the 2 m 25 s suite dominates), `web` ≈
  1.5 min, `images` ≈ 2 min, `security` ≈ 1.5 min, in parallel as today. GitHub's
  hosted runners — including arm64 — are free for public repositories, and this
  repository is public.
- `concurrency`, `permissions: contents: read`, and the pinned action SHAs
  policy stay as they are. The publish workflow below is the only thing that
  needs `packages: write`.

### 5. Publish and promote: real today, ECR later

Two workflows, both runnable the day they land, because they target GHCR rather
than an account that does not exist:

- `.github/workflows/publish.yml` — on push to `development`, and on
  `workflow_dispatch`. Builds `runtime` and `web-runtime` on arm64 with the
  registry cache, runs `scripts/verify-image.sh`, pushes with
  `scripts/publish.sh` to `ghcr.io/<owner>/eoehelp-api:candidate-<sha>` and the
  web equivalent, reads back the digest with `skopeo inspect --format
  '{{.Digest}}'`, and writes both digests to the job summary and to an artifact
  named `digests.json`. `permissions: { contents: read, packages: write }`,
  authenticated with `GITHUB_TOKEN`; no long-lived credential exists.
- `.github/workflows/promote.yml` — `workflow_dispatch` only, inputs
  `api_digest`, `web_digest`, and `target` (`staging` | `production`, both GHCR
  repositories today). Calls `scripts/promote.sh`, which is
  `skopeo copy --all` from a digest-pinned source, then re-reads the destination
  digest and fails if it differs — the assertion `verify-promote.sh` already
  makes locally, now made against a real registry.

Registry host, repository names, and the login step are the only ECR-specific
parts, and they are workflow-level variables (`vars.REGISTRY`,
`vars.REGISTRY_NAMESPACE`). M0b replaces the `docker/login-action`-free
`GITHUB_TOKEN` login with an OIDC role assumption and `aws ecr get-login-password`
and changes two variables. Nothing else in the publish path changes, and the
promotion mechanism will already have been exercised on every push.

The ADR carries the **deploy contract** M0b's Terraform must satisfy, in prose:
container port 8000 and 8080; health checks `GET /healthz` on both;
`cpuArchitecture: ARM64`; images referenced by `@sha256:`; the exact environment
variables the API requires (`ENVIRONMENT`, `DATABASE_URL`, `REDIS_URL`,
`APP_BASE_URL`, `API_BASE_URL`, `CORS_ORIGINS`, `SMTP_*`, `USDA_FDC_API_KEY`,
`FORWARDED_ALLOW_IPS`) and which of them must come from Secrets Manager
(`JWT_SECRET`, `FIELD_ENCRYPTION_KEY`, `SMTP_PASSWORD`, `USDA_FDC_API_KEY`, and
the `DATABASE_URL` password); that migrations run as a separate task with the
owner role before the service updates, while the service connects as
`app_runtime`; and that `FORWARDED_ALLOW_IPS` must list the private subnet CIDRs
or every audit row records the balancer.

### 6. Documentation and references

Every reference to a `make` target must move in the same commit that deletes the
Makefile. The exhaustive list, from a repository-wide grep:

- `README.md` lines 18, 31–34, 98, and the `verify-promote` paragraph.
- `CLAUDE.md` lines 30–34 (the Commands section).
- `.claude/skills/feature/SKILL.md` lines 52–54 (phase 4's checks).
- `apps/api/README.md`: the *Running* section (`podman compose up --build`) and
  lines 28–29.
- `apps/web/src/app/core/api/api-types.ts` line 10 ("Regenerate with
  `make api-types`").
- `.github/workflows/ci.yml` lines 115, 145, 150 (error strings).
- `.gitignore`: the comment about "a failed `make openapi`".
- `docs/adr/0005` and `0006`: add an "Amended by ADR 00NN" line and a bracketed
  note at the two `make up` mentions. Do not rewrite their prose; they are a
  record of what was decided then.
- Older plans in `docs/plans/` keep their `make` references: they are history.

The new ADR takes the next free number (0012 at the time of writing — check
`docs/adr/` first, as another plan is in flight). It records: `just` plus scripts
as the single entry point; images as the unit of local/CI parity; the two-tier
local stack and the line between them; CI testing the artifact it publishes; GHCR
as the interim registry with ECR as a variable swap; and the deploy contract.

## Security and privacy

- **No patient data is touched.** No new table, column, endpoint, or query. RLS,
  grants, and the repository pattern are unchanged, and `tests/test_architecture.py`
  needs no change.
- **What improves.** The dev database stops granting `app_runtime` blanket
  default privileges, so grants must be explicit everywhere, as they already are
  in every migration. The RLS gap in the dev stack is measured and written down
  rather than unknown. `FORWARDED_ALLOW_IPS` becomes provable, which is what
  keeps the audit trail's `ip_address` truthful and the rate limiter per-client
  once an ALB is in front — both of which were flagged in the 2026-09-17 review.
- **Secrets.** Tier 2's generated keys live in a git-ignored file with an
  explicit `.gitignore` entry and are never passed on a command line. No secret
  enters an image: `config.py` reads the environment, and the Dockerfiles copy no
  `.env`. `verify-image.sh` asserts non-root; the implementer should also confirm
  `podman image inspect` shows no `Env` entry containing `SECRET`, `KEY`, or
  `PASSWORD` for either runtime image.
- **New third parties.** GHCR — GitHub already hosts this repository's source, and
  the images contain that same source plus public base layers. No patient data,
  no PHI, and therefore no BAA question. The pinned-and-checksummed `just`
  tarball is the only new binary in CI, and no third-party GitHub Action is added.
- **CI permissions.** `contents: read` stays the default; only `publish.yml` gets
  `packages: write`. Nothing gains `id-token: write` until M0b needs OIDC.
- **Logs.** The scripts print image tags, digests, and service names. `smoke.sh`
  creates a synthetic account and must print neither the magic-link token nor the
  email body; it fetches the link through the Mailhog API and logs only the HTTP
  status codes and the assertions it made.
- This change is in the *security review* categories in the feature workflow
  (dependencies, database permissions, CI, container privileges), so it should
  get that pass before shipping.

## Testing

The build is tested by being the thing that runs everything else; these are the
checks that prove each claim:

**Acceptance checks the implementer must record (numbers, not impressions)**

1. `just test` after a one-line edit to `apps/api/src/eoehelp_api/health.py`
   performs no image build (expect ≈ 0 s of build; the design measured 3.6 s when
   a build is forced).
2. `podman build --target test` after the same edit completes in ≈ 20 s
   (was 34.0 s).
3. `just up` twice in a row with no changes builds nothing the second time and
   creates no dangling image (`podman images --filter dangling=true -q | wc -l`
   unchanged).
4. A cold CI build with unchanged dependencies restores from the registry cache:
   the log shows cache hits for the apt and pip layers and the build step is
   under 30 s.
5. `just web-check` runs no `npm ci` and touches no `node_modules` volume
   (`podman volume ls` shows no `*_node_modules`).
6. Ordering parity: on the new Postgres image,
   `select string_agg(x,' ' order by x) from (values ('apple'),('Apple'),('banana'),('_under'),('Zebra'),('ápple')) t(x)`
   returns `apple Apple ápple banana _under Zebra`. Worth a test in
   `tests/db/` so a future image bump cannot silently revert it.

**Existing suites that must stay green, unchanged:** the full API suite,
`tests/db/test_patient_isolation.py`, `tests/test_architecture.py`, the Angular
unit tests, the OpenAPI drift check, and the generated-types check. If any of
them needs editing, the change has exceeded its scope — except
`tests/db/test_patient_isolation.py`, which may need the new Postgres image's
locale in a fixture if it asserts on ordering.

**New tests and assertions**

| What | Where |
|---|---|
| runtime image has no `pytest`/`ruff`/`mypy` and no `/app/tests` | `scripts/verify-image.sh`, run by `just verify-image` and the `images` job |
| manifest media type, arm64, non-root | same script (moved out of `ci.yml`, unchanged in substance) |
| promotion preserves the digest and media type | `verify-promote.sh` locally and in CI; `promote.yml` re-asserts against GHCR |
| end-to-end through the production origin: `/healthz`, magic-link sign-in, POST and GET a symptom entry | `scripts/smoke.sh`, run by `just smoke` and the `images` job |
| `X-Forwarded-For` is honoured through the edge, and is not honoured from an untrusted source | `scripts/smoke.sh` asserts the audit row's `ip_address` matches the header the edge forwarded, and that the same header sent straight to `127.0.0.1:8001` is ignored |
| collation ordering | a small `tests/db/` test, per acceptance check 6 |
| the init SQL applies identically in CI and locally | `scripts/db-init.sh` is the only definition; CI's heredoc is deleted |

**Failure paths to exercise by hand once:** `just test` with the stack down (must
say so, not time out); `just up` with `podman machine` stopped (`doctor` must say
what to run); a deliberately broken `pyproject.toml` (the build must fail loudly,
not fall back to a stale image); `just openapi` with the API failing to import
(the temp-file behaviour must leave the committed contract intact — the property
the current Makefile comment documents); `just promote` with a mismatched digest
(must exit non-zero).

## Staged delivery

Four commits, each independently green, in this order. No flag day.

| Stage | Contents | Risk |
|---|---|---|
| **1. Entry point** | `justfile`, `scripts/lib.sh` and the wrappers around today's exact commands, delete the `Makefile`, update all references in *Design 6*. CI is untouched, and CI never called `make`, so it cannot break. | Low |
| **2. Images and the local stack** | Dockerfile restructure (both apps), content tags, `compose.yaml` rewrite, `migrate` service, pinned glibc Postgres in `infra/images.env`, delete the `node_modules` volume, `db-init.sh` and the CI heredoc replaced, `ALTER DEFAULT PRIVILEGES` removed, `prune`/`doctor`. CI keeps its current jobs but its Postgres service tag and init step change. | Medium — `--target runtime`/`test` must keep working for the existing `images` job |
| **3. CI runs the images** | The four-job rewrite, registry cache, checks moved inside the images, `verify-image.sh`, the new assertions. Land alone so a revert is clean. | Highest |
| **4. Production shape and the publish path** | `compose.prod.yaml`, `infra/local-edge/`, `local-prod.env.example`, `smoke.sh`, `prod-stack.sh`, the smoke step added to the `images` job, `just preflight`, the `app_runtime` spike and its recorded outcome, `publish.yml`, `promote.yml`, the ADR, README updates. | Medium |

Stage 1 alone already satisfies "get rid of the Makefile", so if anything later
stalls, the repository is never left half-converted.

## Costs

- **Developer machine:** one `brew install just` (~5 MB). `skopeo` is already
  installed. Nothing else is added. Reclaims ~35 GB in the podman VM on first
  `podman system prune -a`.
- **GitHub Actions:** $0. Hosted runners, including `ubuntu-24.04-arm`, are free
  for public repositories, and this repository is public. Verify on the billing
  page before relying on it.
- **GHCR:** $0 if the packages are public. If they are private (recommended, see
  *Open question 3*), storage beyond the Free plan's 500 MB is about
  $0.25/GB/month; with a retention policy keeping the last three digests of two
  ~400–600 MB images plus two cache repos, expect **1–3 GB, i.e. under
  $1/month**. A weekly cleanup workflow that deletes untagged package versions
  keeps it bounded, and is cheap to add in stage 4.
- **AWS:** $0 from this feature. Nothing is provisioned. ADR 0004's $250–300/month
  begins when M0b begins, and *Open question 5* is when that is.

## Handed to this plan by the legal documents review (2026-09-21)

Two findings from the security review of `c6c1820` are infrastructure
assertions, not application code, so they are recorded here rather than fixed
in that commit. Both are cheap now and awkward later.

**1. Host-header open redirect on the API's trailing-slash redirect.** Starlette
rebuilds an absolute `Location` from the request scope, and the scope takes its
host from the `Host` header. Demonstrated against the running stack:

```
$ curl -sD- -o /dev/null -H "Host: evil.test" \
    "http://localhost:8000/api/v1/legal/documents/terms/"
HTTP/1.1 307 Temporary Redirect
location: http://evil.test/api/v1/legal/documents/terms
```

It matters now because `c6c1820` added the first public, link-shaped `GET`
routes — the kind a person follows from an email or a printed page. Exploitable
only through a proxy that forwards an arbitrary `Host`, which a host-based ALB
listener rule prevents. The fix belongs with the edge this plan designs:
`TrustedHostMiddleware` with the deployed hostnames (which also closes
Host-header cache poisoning generally), or `redirect_slashes=False`. The
prod-shaped local profile (`just up-prod`) is where it can be proven, since it
is the only place a real edge sits in front of the API.

**2. `ENVIRONMENT` is a self-declared string that gates two separate controls.**
`enforce_production_safety` refuses to start on a development JWT secret or
field-encryption key, and `enforce_review_status` refuses to serve an
unreviewed legal draft. Both key on `settings.environment == "production"`. A
production host deployed with `ENVIRONMENT=staging` silently turns off **both**,
and nothing would say so. The legal-text consequence is the least of it. That
one string also decides whether the API accepts:

- `DEV_JWT_SECRET` — a total authentication bypass, since the signing key is in
  this repository and anyone holding it can mint a token for any patient id;
- `DEV_FIELD_ENCRYPTION_KEY` — every encrypted note readable by anyone with a
  copy of the repository;
- a missing `redis_url`, which drops the rate limiter to an in-process store,
  so magic-link throttling stops holding across tasks;
- `debug=True`.

That is the reason this belongs in a CI check on the task definition rather
than in a sentence someone is expected to remember.

The mitigation is not in the API. The production task definition must assert
`ENVIRONMENT=production`, and a CI check on the infrastructure definition should
fail if it does not — which makes it part of the **deploy contract** this plan's
ADR already carries (ports, health checks, ARM64, `@sha256:` references, which
variables come from Secrets Manager, migrations as a separate task under the
owner role). Add `ENVIRONMENT` to that contract explicitly, with the two
controls it governs named, so the next person who reads it knows what a wrong
value costs.

A related note the same review raised, which is **not** this plan's to fix:
`review_status = attorney_reviewed` is a one-token edit in the same file as the
drafts, with no reviewer name or date behind it. Making that flag evidentiary
belongs to the legal documents work.

## Open questions

1. **A new local tool, `just`?** It is one `brew install` and the reason the plan
   gets a discoverable, CI-shared command surface. **Default: yes, adopt `just`
   1.58.0.** If you would rather add nothing to the machine, the fallback is a
   `./x` dispatcher script; the `scripts/` layer and everything in stages 2–4 are
   unaffected either way.
2. **How far does tier 2 go?** The plan draws the line at: the real runtime
   images, one origin through a local edge, real (generated) secrets, staging
   environment — but not TLS, not Multi-AZ, not SES. **Default: as described.**
   Adding local TLS with a self-signed certificate is the one extra step
   available; it would exercise HSTS and `Secure` cookies properly, at the cost
   of a certificate to trust on the machine. Recommended: not now.
3. **GHCR package visibility.** Public costs nothing; private costs under
   $1/month and stops anyone pulling the exact production artifact to hunt for
   vulnerabilities offline. **Default: private packages, with a weekly cleanup
   workflow.**
4. **Does the publish workflow run on every push to `development`, or only on a
   tag?** Every push keeps the promotion mechanism exercised and the cache warm;
   a tag keeps the registry tidier. **Default: every push to `development`, tagged
   `candidate-<sha>`, with cleanup keeping the last ten.**
5. **When does AWS spending start?** This feature does not begin it, and nothing
   here expires. M0b is the trigger, and it is your call whether it comes before
   or after the next clinical feature. **Default: not part of this change.**
6. **A Python lock file (`uv` or `pip-tools`)?** Floating ranges mean two cold
   builds can differ, which matters for a medical-adjacent artifact and for
   "production runs what was tested". **Default: not in this feature** — the layer
   split removes the speed argument, and dependency management deserves its own
   change with its own CI story.
7. **Does the `images` job run the end-to-end smoke test in CI?** It is the best
   evidence the runtime images work, and it is also the most likely new source of
   CI flakiness. **Default: yes, in CI, with `just preflight` as the local
   equivalent; if it proves flaky, demote it to local-only and say so in the
   review log rather than deleting it.**
8. **Which recipe names change?** The plan keeps today's names wherever they
   still fit and renames `test-api` → `test`, drops `image-test`/`image-api` in
   favour of `build`, and drops `rebuild`'s meaning onto `build --no-cache`.
   **Default: as tabulated in *Design 1*.** Your habits and the agent
   instructions are the constraint, so say if a name should stay.

## Review log

| Round | Reviewer | Verdict | What changed |
|---|---|---|---|
| 1 | architect (self-check) | Draft ready for implementation | Checked against every item in the architect's standard. **Clinical soundness:** no instrument, threshold, or patient-facing wording is touched; the three clinically relevant consequences (musl vs glibc collation, audit `ip_address` behind a balancer, RLS inert in the dev stack) are each backed by a measurement or a code citation rather than asserted, and the RLS one is scoped out as a service-layer feature rather than silently "fixed" in a build change. **Patient isolation:** no new table, route, or query; `/me` routing, repositories, and RLS are untouched, and `tests/test_architecture.py` and the isolation suite must stay green unmodified. The one isolation-adjacent change — removing `ALTER DEFAULT PRIVILEGES` — was verified safe by confirming that migrations 0001–0005 all grant explicitly and that `CREATE DATABASE eoehelp_test` never inherited those defaults. **Privacy and PHI:** no PHI anywhere near the build; the only new third party is GHCR, which already hosts this public repository's source and receives no patient data; `smoke.sh` is constrained to log status codes, never the magic-link token or an email body; secrets stay in a git-ignored file that needs a new `.gitignore` line because `.env.*` does not match it. **Architecture:** no package moves, no new dependency edges, ADR 0010 untouched. **Data model and migrations:** none added; the Postgres image change is asserted with a test so a future bump cannot revert the ordering silently. **API contract:** unchanged shapes; the drift checks move into scripts so the same command runs locally and in CI. **Frontend:** no component or token changes; the web change is tooling only, and the production origin path becomes exercisable for the first time. **Testing:** six numbered acceptance measurements, five new assertions, and five failure paths named. **Scope:** four staged commits, each green alone; a lock file, test parallelism, Terraform, and the `app_runtime` fix are each excluded with a reason. **Decisions:** eight open questions with defaults, including the three the user reserved (cost, how far parity goes, when AWS spending starts). Not resolved here: whether `--cache-from` behaves the same on a GitHub arm64 runner as it did in the isolated store measured locally (acceptance check 4 is the gate), and whether the app can run as `app_runtime` at all (the stage 4 spike answers it, with both outcomes pre-agreed). Also observed but not diagnosed: a full `pytest -q` run produced 5 errors in `tests/synthetic/` and `tests/symptoms/` that pass in isolation — reported to the implementer as a pre-existing flake, not a product of this design. |
| 2 | user | All eight defaults accepted | 2026-09-23. **1.** Adopt `just` 1.58.0. **2.** Tier 2 as described — real runtime images, one origin, generated secrets, `ENVIRONMENT=staging`, no local TLS. **3.** GHCR packages private, with the weekly untagged cleanup. **4.** Publish on every push to `development` as `candidate-<sha>`, keeping the last ten. **5.** AWS spending does not start here; a separate plan (`2026-09-23-aws-infrastructure.md`) is being designed for review, and the user has decided no resources are created until they have read it. **6.** No Python lock file in this change. **7.** The smoke test runs in CI, demoted to local-only and recorded here if it proves flaky. **8.** Recipe renames as tabulated — `test-api` → `test`, `image-*` → `build`, `rebuild` → `build --no-cache` — which means `CLAUDE.md`, both READMEs, `.claude/skills/feature/SKILL.md` and every reviewer agent that names a command are updated in the same commit as the rename. |
| 3 | implementer | Stage 1 built | `justfile` plus `scripts/{lib,api-checks,web-checks,openapi,api-types,doctor}.sh`; Makefile deleted; `just` 1.58.0 installed. Every recipe verified against the target it replaces. **Two deviations from Design 1, recorded because stage 2 reads that table.** `image-api` became **`build-api`**, not `build`: `rebuild` is still compose-wide in stage 1, so one name implying a relationship to the other would have been wrong until `build-images.sh` replaces both. And `scripts/` gained a **CI seam** the design did not call for — `TEST_NETWORK`, `TEST_DATABASE_URL`, and `--userns=keep-id` applied only when podman reports rootless — because without it stage 3 would re-implement these scripts rather than call them, which is the claim goal 1 rests on. **Deferred to stage 2, deliberately:** shellcheck (the devops reviewer argued for pulling it forward, and the pipe-race finding is exactly the class it catches, so it goes in with `build-images.sh`), and `openapi.sh`'s remaining dependence on a running compose stack — exporting the schema needs the app importable and nothing else, so stage 2 should run it in the test image and delete `require_stack` from that script, which also makes `just contract-check` work with the stack down. **Note for `git log` readers:** this commit also touches `0006_consent_document_digest.py`, comment-only — the `make` → `just` rename in an operator-facing error string, and a reworded comment above `PUBLISHED_REVISIONS`. No digest, date or statement changed. |
| 4 | devops-reviewer | FINDINGS, then NO BLOCKING FINDINGS | **Three blocking, all fixed and independently re-verified.** (1) `require_stack` and `doctor` piped `podman ps` into `grep -q`; grep exits at the first match, podman takes SIGPIPE, and under `pipefail` that is exit 141 — measured **11 of 60 calls** falsely reporting "the stack is not running" while it was demonstrably up, and `doctor` printing `eoehelp-api-1 is not running` against a container that was `Up (healthy)`. Now filtered by podman; **60/60 correct** on re-review. (2) Eleven files still named `make`, including three strings in `ci.yml` — CI's job is to tell you what to do when you are least able to work it out, and it would have named a deleted build system — plus `.prettierignore` and a runtime error string inside migration 0006, neither of which the plan predicted. (3) A fresh clone could not start: `README.md` promised podman was the only prerequisite three lines above a `just` command, and no `brew install just` appeared anywhere. **Advisories taken:** `compose()` now passes `-f "$REPO_ROOT/compose.yaml"` (stage 3's api job runs from `apps/api`, where `openapi.sh` died with a message that never mentioned this project); `doctor` warns above 50% reclaimable instead of ticking the fault it exists to catch, reports real VM free space, labels its columns, explains why volumes are never pruned, falls back off macOS, and no longer folds stderr into the parsed output; `prune all` adds `-a`, since `-f` alone leaves most of what `doctor` counts; `sha256_of` hashes names and per-file digests rather than the concatenation, and dies instead of hanging on no arguments; the ADRs got markers at the top where a reader starts, not only at the end. |
| 5 | user | Stage 4's local edge becomes Caddy | 2026-09-23. The AWS design (`docs/plans/2026-09-23-aws-infrastructure.md`) uses Caddy on the tier-0 instance, for a specific failure mode: a certbot renewal that succeeds while the reload never happens is silent for up to thirty days. Stage 4 here specified nginx for the local production-shaped edge. Using Caddy in both places gives one edge configuration instead of two kept equivalent by hand, and makes `just up-prod` a faithful rehearsal of the deployed shape rather than an approximation of it. Cheaper now than after stage 4 is built. |
| 6 | implementer | Stage 2 built | Both Dockerfiles restructured to the plan's stage graph; content-addressed tags in `scripts/build-images.sh`; `compose.yaml` rewritten with no `build:` keys, `pull_policy: never`, a one-shot `migrate` service and the `web_node_modules` volume deleted; glibc Postgres pinned in `infra/images.env`; `db-init.sh` replacing CI's heredoc; `verify-image.sh`. **Measured, reproducing the plan's numbers:** a one-line source edit costs **3.59 s** for `dev` (plan: 3.6) and **18.1 s** for `test` (plan: 19.8), against 34.0 s before; `just up` with nothing changed is **2.36 s**; `build-images.sh` with nothing changed is **0.36 s**; `just web-check` is 9.9 s with no `npm ci`. Collation verified: the glibc image sorts `apple Apple ápple banana _under Zebra` where alpine sorted `Apple Zebra _under apple banana ápple`. **Deviations from Design 2:** `verify-image.sh` uses `podman image inspect` rather than `skopeo inspect containers-storage:`, because skopeo reads the host store and on macOS the images live in the podman VM — one script that works in both places beat two kept equivalent, and `ci.yml` already documents skopeo failing on Ubuntu 24.04 for a related reason. Recorded for stage 3: the `images` job will need `podman` installed, and the AppArmor `unshare` restriction is the reason it might not work. **Also deferred to stage 3, as a decision rather than an oversight:** `api-checks.sh` still builds `eoehelp-api-test` with its own `podman build` outside the content-tag mechanism. It is always correct because it always rebuilds, so this is not a staleness risk — but `just test` gets none of the skip, and there are two answers to "where does an image come from" until stage 3 unifies them. |
| 7 | devops-reviewer | FINDINGS, then NO BLOCKING FINDINGS | **Three blocking, all demonstrated rather than deduced.** (1) **The content tag was not content-addressed.** It routed the source listing through a `$$`-named temp file, so the hash changed on every invocation — four consecutive builds produced four tags and four permanent refs, which `just prune` cannot reclaim because they are tagged rather than dangling. Worse, within one invocation `test` and `runtime` hashed identical inputs, so `runtime` found `test`'s tag present, skipped its build, and **`localhost/eoehelp-api:runtime` — the artifact `verify-promote` promotes and stage 4 publishes — was the test image**, carrying pytest, ruff, mypy and `/app/tests`. Reachable by `just build all`, `just build test runtime`, and `just rebuild`. (2) **The Postgres image change silently corrupted an existing data directory.** musl records no collation version, so PostgreSQL's own mismatch check cannot fire; the reviewer built a musl directory, started the glibc server on it, and measured an index scan and a sequential scan returning different answers to the same query, a row invisible to an index lookup, and **a duplicate primary key accepted** — on this schema, the `citext` unique index on patient email. (3) **The `node_modules` volume survived and lost its only removal path**: `compose.yaml` no longer declared it, so `down -v` could not remove it, `just prune` never touches volumes, and `web-checks.sh` still mounted it on every call. **Re-review verified the fixes by running them**, including a stub `podman` that made `build-images.sh` print tags without building: fifteen identical tags across three runs, identical tags from a clone at a different path, and a sensitivity matrix over staged edits, unstaged edits, untracked files, deletions and renames. Advisories taken in the same commit: `web-checks.sh` rebuilt only when the image was *missing*, so a lock-file change kept running the old one; `compose.yaml`'s inline defaults contradicted `infra/images.env`, giving the pin three homes and two values, now `${VAR:?}` so a missing variable fails loudly; `apps/api/README.md` is `COPY`ed and was unhashed; `web-runtime` now hashes `apps/web` wholesale because the builder does `COPY . .`; `git ls-files --error-unmatch` so a renamed input cannot silently drop out of the hash; the `cmd-a \|\| cmd-b` checksum fallback replaced by choosing the tool once, since a partial failure could have concatenated two listings; the shellcheck image pinned in `infra/images.env`; the `dev` stage labelled so `verify-image` reports on shipping artifacts only. |
