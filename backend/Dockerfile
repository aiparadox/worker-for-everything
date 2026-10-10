# Backend image (FEAT-20261010-1202). One image, many commands: api, worker, relay,
# maintenance and migrate all run from this image with a different command.
# Build context: backend/.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Packages first, so this layer is cached until the lock file changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS run
RUN useradd --system --uid 10001 --no-create-home qfe
WORKDIR /app
COPY --from=build --chown=qfe:qfe /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
USER qfe
