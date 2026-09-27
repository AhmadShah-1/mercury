# syntax=docker/dockerfile:1.7
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS builder
ENV POETRY_VERSION=2.4.1 POETRY_VIRTUALENVS_IN_PROJECT=true POETRY_NO_INTERACTION=1
WORKDIR /app
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"
COPY pyproject.toml poetry.lock* README.md ./
RUN poetry install --only main --no-root --sync
COPY mercury ./mercury
COPY scripts ./scripts
RUN poetry run python scripts/fetch_vendor_assets.py
RUN poetry install --only main --sync
# The runtime never installs packages; drop pip and its vendored libraries from the shipped venv.
RUN rm -rf /app/.venv/lib/python3.12/site-packages/pip /app/.venv/lib/python3.12/site-packages/pip-* /app/.venv/bin/pip*

FROM dopplerhq/cli:3@sha256:e974c93a74b0fd8795e48eb24b43eea273bf7773294f14c8c9184baf66e658cc AS doppler

FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS runtime
ENV PATH="/app/.venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system mercury && adduser --system --ingroup mercury --home /nonexistent mercury \
    && python -m pip uninstall --yes --quiet pip
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
