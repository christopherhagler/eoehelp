# ADR 0005 — Podman as the container runtime; everything containerized

**Status:** Accepted · 2026-09-15

## Context

The project needs a single way to run the stack locally, in CI, and in
production. Divergence between those — a developer running Postgres on the host
while CI runs it in a container — is where "works on my machine" comes from, and
in a system whose security properties depend on database roles and grants, that
divergence is not cosmetic.

## Decision

**Everything runs in containers, and the container engine is Podman.**

Local development is `make up`: Postgres, Redis, the API, the Angular dev server,
and Mailhog. No language runtime, database, or toolchain needs to be installed on
the host. Tests, linting, type checking, and the Angular scaffold all run in
containers too.

Podman specifically:

- **Rootless by default.** Containers run as an unprivileged user, so a container
  escape does not begin with host root.
- **No long-running privileged daemon.** Podman is fork/exec; there is no
  root-owned socket whose access is equivalent to root on the host.
- **OCI-standard.** The Dockerfiles and `compose.yaml` are engine-neutral. Nothing
  in this repository is Podman-specific, so ECS in production and Podman locally
  run the same artefacts.

`podman compose` delegates to a Compose provider while the containers themselves
run on Podman — no Docker daemon is involved.

Images run unprivileged internally as well: the API as a dedicated `app` user, the
web image as nginx's `nginx` user on port 8080. CI asserts this rather than
trusting it, since a base-image bump can silently revert it.

## AWS compatibility, and why Docker is not needed

AWS consumes what Podman produces. ECR stores Docker- and OCI-format images and
OCI artifacts; ECS and Fargate pull and run them identically. There is no
"Docker image" that AWS runs better — the deploy target sees a registry manifest
and a filesystem, not the tool that built them.

Two real caveats, both handled:

**Manifest format.** Podman can emit OCI-format manifests, and ECS has
historically failed on those. Builds pin `--format docker`, and CI asserts the
resulting manifest type. Podman already defaults to Docker v2 in this setup, so
the pin exists to stop a future default change from silently breaking deploys.

**Architecture, which is the thing that actually bites.** Podman on Apple Silicon
produces `linux/arm64` images, and an arm64 image will not run on x86 Fargate.
Rather than cross-build under emulation, the architecture is **arm64 end to
end**: Apple Silicon locally, `ubuntu-24.04-arm` runners in CI, and Fargate with
`cpuArchitecture: ARM64` (Graviton) in production. Graviton Fargate is also
about 20% cheaper than x86 for the same vCPU and memory, so the consistent
choice is the cheaper one.

Where Docker genuinely leads is its tooling, not AWS: `buildx` has a mature
GitHub Actions layer cache and easier multi-architecture builds. Building a
single native architecture removes the multi-arch need entirely, and registry-
backed `--cache-from`/`--cache-to` covers caching if CI build time becomes a
problem. Some AWS tooling does shell out to `docker` — CDK asset bundling and
SAM's container builds — but this project deploys with Terraform against an image
in ECR and does not use them. CDK honours `CDK_DOCKER=podman` if that changes.

**Superseded in part by [ADR 0006](0006-buildah-and-skopeo.md).** The paragraph
above compares Docker's wrapper against Podman's and skips the tools underneath.
CI now builds with `buildah` and publishes with `skopeo` — the engine Podman
already uses and the registry client it already embeds — which also supplies the
mechanism for the `--format docker` assertion described above.

## Consequences

- Onboarding is `podman` plus `make up`.
- The test image is built **from** the runtime image rather than assembled
  separately, so tests exercise the artefact that actually ships.
- Container-internal caches (ruff, mypy, pytest) must be pointed at `/tmp`,
  because the application directory is not writable by the unprivileged user.
- Rootless containers cannot bind ports below 1024 without extra configuration.
  Nothing here needs to: the published ports are 4200, 5432, 6379, 8000, 8025.
- On macOS, Podman runs a VM (`podman machine`), so first start has a cost and
  bind-mount performance is lower than native.

## Alternatives rejected

**Docker Desktop.** Requires a paid licence for larger organisations and runs a
privileged daemon. Nothing here needs either.

**Host-installed Postgres for local development.** Faster, but it drifts from
production and quietly hides role and grant problems — the `app_runtime` role
owning no tables is exactly the kind of detail that would be "fine locally" and
broken in CI.
