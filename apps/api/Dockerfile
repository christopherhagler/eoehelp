# Built by buildah in CI and by podman locally (which is buildah underneath).
# No BuildKit-only syntax is used here — no RUN --mount, heredocs, or COPY --link —
# so the image is reproducible under either.

# ---- builder ----------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update \
 && apt-get install --no-install-recommends -y build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
 && /opt/venv/bin/pip install .

# ---- runtime ----------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

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

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app src ./src

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "eoehelp_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- test -------------------------------------------------------------------
# Built from runtime so tests exercise the image that actually ships, rather
# than a separately-assembled environment that could diverge from it.
FROM runtime AS test

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
