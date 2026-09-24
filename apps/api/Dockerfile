# Built by buildah in CI and by podman locally (which is buildah underneath).
# No BuildKit-only syntax is used here — no RUN --mount, heredocs, or COPY --link —
# so the image is reproducible under either.
#
# The stage graph exists to make the dependency layer's cache key `pyproject.toml`
# alone. Before it, every source edit reinstalled the whole third-party closure:
# 34 s before lint, type-check or tests could start, paid on every edit.
#
#   pydeps-base ─ deps ─ builder      third-party closure, keyed on pyproject.toml
#               └ devdeps             the same closure plus [dev]
#   runtime-base ─ runtime ─ test     what ships, and what CI tests
#                └ dev                the local loop; source is mounted, never copied
#
# `test` descends from `runtime` on purpose (ADR 0005): the suite exercises the
# image that ships. `dev` branches before any source is copied, so a source edit
# rebuilds nothing.

# ---- dependency closure -----------------------------------------------------
FROM python:3.12-slim-bookworm AS pydeps-base

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update \
 && apt-get install --no-install-recommends -y build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# A stub package, so this layer depends on pyproject.toml and nothing else.
# [tool.setuptools.packages.find] where = ["src"] is satisfied by an empty
# __init__.py, so pip resolves and installs the third-party closure without the
# real source being present. `builder` then reinstalls the real package with
# --no-deps --force-reinstall, which uninstalls the stub first.
COPY pyproject.toml README.md ./
RUN mkdir -p src/eoehelp_api && touch src/eoehelp_api/__init__.py \
 && python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip setuptools wheel

FROM pydeps-base AS deps
RUN /opt/venv/bin/pip install .

FROM pydeps-base AS devdeps
RUN /opt/venv/bin/pip install ".[dev]"

FROM deps AS builder
COPY src ./src
RUN /opt/venv/bin/pip install --no-deps --force-reinstall .

# ---- runtime ----------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# WeasyPrint renders the clinical report PDF and needs Pango/Cairo at runtime,
# not just at build time. Omitting these fails only when a report is generated.
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
      libffi8 shared-mime-info fonts-dejavu-core curl \
 && rm -rf /var/lib/apt/lists/*

# Runs unprivileged: a container escape should not start from root.
RUN groupadd --system --gid 1001 app \
 && useradd --system --uid 1001 --gid app --create-home app

WORKDIR /app

FROM runtime-base AS runtime

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app src ./src

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

# --no-access-log: uvicorn's access log prints the resolved path and the
# client address, which the privacy policy says are not recorded. The structlog
# middleware in main.py logs every request with the route template instead.
CMD ["uvicorn", "eoehelp_api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log"]

# ---- test -------------------------------------------------------------------
# Built from runtime so tests exercise the image that actually ships, rather
# than a separately-assembled environment that could diverge from it.
FROM runtime AS test

# Identifies this stage whatever tag it carries: a content tag has no target
# name in it, and the failure worth catching is the test image sitting behind
# the runtime tag.
LABEL org.eoehelp.stage=test

USER root
COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[dev]"
COPY tests ./tests
USER app

# The app directory is root-owned and the container runs unprivileged, so every
# tool that wants a cache must be pointed somewhere writable.
ENV PYTHONPATH=/app/src \
    RUFF_CACHE_DIR=/tmp/ruff_cache \
    MYPY_CACHE_DIR=/tmp/mypy_cache

CMD ["pytest"]

# ---- dev --------------------------------------------------------------------
# The local loop. Source is mounted at run time and never copied, so editing a
# file rebuilds nothing at all. Same pyproject.toml and same base image as
# `test`, so the drift between them is bounded to the presence of the source.
FROM runtime-base AS dev

# Labelled like the test stage: `verify-image` reports on shipping artifacts,
# and a dev image is expected to carry ruff and mypy.
LABEL org.eoehelp.stage=dev

COPY --from=devdeps /opt/venv /opt/venv

USER app

ENV PYTHONPATH=/app/src \
    RUFF_CACHE_DIR=/tmp/ruff_cache \
    MYPY_CACHE_DIR=/tmp/mypy_cache \
    PYTEST_ADDOPTS=-p\ no:cacheprovider

EXPOSE 8000

# The same check runtime carries: without it the container reports Up whether
# or not uvicorn is serving, which is the only signal that tells those apart.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "eoehelp_api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/app/src"]
