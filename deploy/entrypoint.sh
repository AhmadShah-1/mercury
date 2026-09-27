#!/bin/sh
set -eu

if [ "${APP_ENV:-}" = "production" ] && [ "${MERCURY_DOPPLER_INJECTED:-}" != "1" ]; then
  if [ -z "${DOPPLER_TOKEN:-}" ]; then
    echo "DOPPLER_TOKEN is required in production" >&2
    exit 1
  fi
  export MERCURY_DOPPLER_INJECTED=1
  # The runtime user has no home directory, so the CLI's config lives in the container's /tmp.
  exec doppler run --config-dir /tmp/doppler --no-check-version --no-fallback -- "$@"
fi

exec "$@"
