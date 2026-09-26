# syntax=docker/dockerfile:1.7
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS builder
ENV POETRY_VERSION=2.4.1 POETRY_VIRTUALENVS_IN_PROJECT=true POETRY_NO_INTERACTION=1
WORKDIR /app
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"
COPY pyproject.toml poetry.lock* README.md ./
RUN poetry install --only main --no-root --sync
COPY mercury ./mercury
COPY scripts ./scripts
RUN poetry run python scripts/fetch_vendor_assets.py
RUN poetry install --only main --sync

FROM dopplerhq/cli:3@sha256:e974c93a74b0fd8795e48eb24b43eea273bf7773294f14c8c9184baf66e658cc AS doppler

FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS runtime
ENV PATH="/app/.venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system mercury && adduser --system --ingroup mercury --home /nonexistent mercury
COPY --from=doppler /bin/doppler /usr/local/bin/doppler
COPY --from=builder /app/.venv /app/.venv
COPY --chown=mercury:mercury mercury ./mercury
# Always ship the SHA-384-verified vendor assets fetched in the builder, never source placeholders.
COPY --from=builder --chown=mercury:mercury /app/mercury/static/vendor ./mercury/static/vendor
COPY --chown=mercury:mercury migrations ./migrations
COPY --chown=mercury:mercury deploy/entrypoint.sh deploy/gunicorn.conf.py ./deploy/
COPY --chown=mercury:mercury wsgi.py pyproject.toml README.md ./
RUN chmod 0755 /app/deploy/entrypoint.sh
USER mercury
EXPOSE 8000
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["gunicorn", "--config", "deploy/gunicorn.conf.py", "wsgi:app"]
