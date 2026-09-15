# ADR 0006 — Build with buildah, publish with skopeo, promote by digest

**Status:** Accepted · 2026-09-15
**Extends:** [ADR 0005](0005-podman-container-runtime.md) (Podman as the container runtime)

## Context

ADR 0005 settled Podman as the container engine and noted that `buildx` was the one
place Docker's tooling genuinely led, on CI layer caching. That framing was
incomplete: it compared Docker's wrapper against Podman's wrapper and skipped the
tools underneath.

`podman build` is `buildah`. `podman push` is most of `skopeo`. Using the
lower-level tools directly is not a change of engine — it is dropping a
convenience layer in the one place where the convenience costs something.

## Decision

**Local development uses Podman. CI builds with buildah. Publishing and promotion
use skopeo.**

Local is deliberately unchanged. `podman compose` stays, because `podman build`
already calls buildah, and buildah is Linux-native — using it directly on macOS
means shelling into the Podman VM for no benefit. Consistency of *engine* is what
matters, and that already holds.

### Build once, promote by digest

This is the decision that actually changes the architecture, not just the commands.

The deploy pipeline builds one image, tests that exact image, pushes it to the
staging registry, and then copies **the identical digest** to production:

```bash
skopeo copy --all \
  docker://<staging-ecr>/eoehelp-api@sha256:<digest> \
  docker://<prod-ecr>/eoehelp-api:released
```

`--all` copies the manifest verbatim, which is what preserves the digest; without
it skopeo may re-encode and the digest changes. The source is referenced by digest
rather than tag, so what gets promoted is pinned rather than whatever the tag
points at when the copy runs.

The alternative — rebuilding for production — produces a different digest. That
means the artifact serving patients was never the artifact that passed the tests.
For a medical-adjacent product that is a real audit weakness and the first thing
a reviewer asks about, and it is avoidable for the cost of one command.

ECS task definitions therefore reference images by `@sha256:…`, not by tag, and
ECR repositories are created with tag immutability and scan-on-push enabled. What
runs is provably what was built.

### Why these tools specifically

- **No container runtime in CI.** buildah builds, skopeo inspects and publishes.
  Neither needs a daemon, a socket, or a running engine. For a repository heading
  into SOC 2 scope, a build job with no container daemon is less to attest to.
- **Registry work without pulling.** skopeo copies between registries server-side
  and reads remote manifests without downloading them, so promotion never
  transfers layers through the runner.
- **Manifest format becomes asserted, not assumed.** `buildah --format docker`
  plus `skopeo inspect --raw` makes ECS compatibility something CI proves, rather
  than something that happens to be the current default (ADR 0005 flagged this
  risk; this is the mechanism that closes it).

### Proving it before AWS exists

`scripts/verify-promote.sh` stands up two throwaway `registry:2` containers,
pushes a built image to the first, promotes it to the second by digest, and
asserts that both the digest and the manifest media type survived. It runs in CI
and on a laptop, needs no AWS account, and is the regression test for the publish
pipeline before the publish pipeline exists.

## Consequences

- skopeo becomes a local dependency for `make verify-promote` (`brew install
  skopeo`). The build and test paths do not need it.
- Registry-backed `--cache-from`/`--cache-to` replaces buildx's GitHub Actions
  cache. `buildah --layers` is enabled now so that caching can be switched on
  without another change.
- Publish and promote workflows are not written yet — they need ECR to target.
  Writing them now would leave unrunnable YAML in the repository.
- The CI assertions had to be rewritten rather than ported: `podman image inspect
  --format '{{.ManifestType}}'` has no buildah equivalent, and `buildah inspect`
  returns a different JSON shape. Manifest and architecture checks now go through
  `skopeo inspect` against `containers-storage:`, and the non-root check through
  `buildah inspect --format '{{.OCIv1.Config.User}}'`.
- The `# syntax=docker/dockerfile:1.7` directives were removed from both
  Dockerfiles. buildah ignores them, and neither file uses a BuildKit-only
  feature, so the line implied a builder that is not in use.

## Alternatives rejected

**Docker with buildx for CI.** The mature GitHub Actions layer cache and easy
multi-architecture builds are real advantages. Both are answers to problems this
project does not have: building a single native architecture (arm64 end to end,
per ADR 0005) removes the multi-arch need, and registry-backed caching covers the
rest. Adopting Docker in CI while running Podman locally would also reintroduce
the divergence ADR 0005 exists to prevent.

**Staying on `podman build` in CI.** Works today. But it requires a runtime for a
job that only builds, keeps the manifest format a matter of defaults, and offers
nothing toward promotion by digest — which is the part that matters once there is
a production account to promote into.
