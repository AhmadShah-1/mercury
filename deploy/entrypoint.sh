#!/bin/sh
set -eu

if [ "${APP_ENV:-}" = "production" ] && [ "${MERCURY_DOPPLER_INJECTED:-}" != "1" ]; then
  if [ -z "${DOPPLER_TOKEN:-}" ]; then
    echo "DOPPLER_TOKEN is required in production" >&2
    exit 1
  fi
  export MERCURY_DOPPLER_INJECTED=1
  exec doppler run --no-fallback -- "$0" "$@"
fi

exec "$@"

