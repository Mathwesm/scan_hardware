# Reproducible environment: the same image on Windows, macOS and Linux.
# Multi-stage keeps the runtime image free of Poetry and the build toolchain.
FROM python:3.12-slim-bookworm AS builder

ENV POETRY_VERSION=2.4.1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

WORKDIR /app
# Copy the manifests alone first: this layer is cached until the dependencies
# actually change, so day-to-day code edits rebuild in seconds.
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root

COPY README.md ./
COPY src/ ./src/
RUN poetry install --only main


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PATH="/app/.venv/bin:$PATH"

# Never run as root: a container escape should not land on a privileged shell.
RUN apt-get update && apt-get install --no-install-recommends -y libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv
COPY --from=builder --chown=appuser:appuser /app/src ./src
RUN mkdir -p /app/data /app/logs && chown -R appuser:appuser /app/data /app/logs

USER appuser

CMD ["python", "-m", "scan_hardware"]
