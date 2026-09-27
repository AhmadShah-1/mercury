# Operations

## Release

Build one image, scan it, record its digest as `RELEASE_ID`, then run application and Procrastinate migrations as a single controlled job. Deploy that digest to web and worker. Keep the previous digest. Prefer additive migrations; rolling back an image cannot undo destructive schema changes.

The release job runs `flask --app wsgi:app db upgrade && flask --app wsgi:app queue-schema`. `queue-schema` installs Procrastinate's schema only when `procrastinate_jobs` is absent, so it is safe on every release. When upgrading the pinned Procrastinate version, apply the SQL files for the intervening versions from `procrastinate schema --migrations-path` in the same controlled job before deploying the new image.

The deploy workflow passes `appHostname` (the `APP_BASE_URL` host) to Bicep because Container Apps probes must send an allowed `Host` header; Mercury rejects any other host with HTTP 400. The workflow deploys the revision and then starts the migration job and polls it; readiness includes a schema check, so a revision needing an unapplied migration never becomes ready. It records the Git commit as `RELEASE_ID`, so do not also set `RELEASE_ID` in Doppler (Doppler's value would override it).

## Environments

`staging` and `production` are deployment names, not application modes. Both run `APP_ENV=production`, so every fail-closed check, secure cookie, and header applies to anyone with real Gmail tokens, including Google test users. Each has its own:

| | staging | production |
|---|---|---|
| GitHub environment (secrets `DOPPLER_TOKEN`, `POSTGRES_ADMIN_PASSWORD`) | `staging` | `production` |
| Doppler config | `mercury` / `stg` | `mercury` / `prd` |
| Azure resource names (tagged `environment=<name>`) | `mercury-<role>-staging` | `mercury-<role>-production` |
| PostgreSQL host in `DATABASE_URL` | `mercury-postgres-staging.postgres.database.azure.com` | `mercury-postgres-production.postgres.database.azure.com` |

Both environments share the operator-created `Mercury` resource group and one container registry (registry names allow only letters and digits, so it has no suffix). Each GitHub environment needs its own federated credential with subject `repo:OWNER/REPO:environment:<name>`. Never point one environment's Doppler config at another's database.

## Custom domain

Bind the custom domain once by hand after the first deploy, with `<env>` as `staging` or `production`:

1. Read `properties.configuration.ingress.fqdn` and `properties.customDomainVerificationId` from `az containerapp show -g <rg> -n mercury-web-<env>`.
2. At the DNS provider, create `CNAME <host> -> <fqdn>` and `TXT asuid.<host> -> <verification id>`.
3. `az containerapp hostname add -g <rg> -n mercury-web-<env> --hostname <host>`, then `az containerapp hostname bind -g <rg> -n mercury-web-<env> --hostname <host> --environment mercury-environment-<env> --validation-method CNAME`. This issues a free managed certificate, which Azure renews.

Later deploys look up that managed certificate and pass it to Bicep as `customDomainCertificateId`; without it, the redeployed ingress would drop the binding.

## Worker recovery model

- Transient provider failures (timeouts, 429, 5xx) retry with capped exponential backoff and jitter, honoring `Retry-After`; reauthorization, validation, and denied label writes are never retried.
- When a job will not be retried, its `ProcessingRun` becomes `failed` with a safe code (for example `connection_needs_reauthorization`, `provider_rate_limited`, `processing_stalled`), so the interface never shows endless progress.
- Jobs for one account share a Procrastinate `lock`; duplicate waiting jobs are coalesced with a `queueing_lock`.
- `retry_stalled_jobs` (every 2 minutes) re-queues jobs whose worker stopped heartbeating for 60 seconds, for example after a killed container. `tests/integration/test_worker.py` kills a real worker mid-job to verify this.
- `reconcile_pending_work` (every 5 minutes) re-enqueues durable pending runs (covering a failed enqueue after commit), resets runs stuck `running` for 15 minutes, fails runs older than 2 hours, and, in `poll`/`push` mode, schedules catch-up syncs for accounts not synced within `SYNC_INTERVAL_SECONDS` (effective granularity: 5 minutes).
- Locally, `make worker-once` drains runnable jobs in a throwaway container; `make reset-local` deletes the local database volume only after typing `reset`.

## Backups and deletion replay

Configure managed PostgreSQL backup retention to seven days. Retain sanitized deletion audit events in restricted Azure logs for 30 days. Before restoring, export deletion events newer than the backup timestamp. Restore into an isolated environment, run the deletion-replay command/data procedure, verify deleted user/account IDs are absent, then enable workers and traffic. Perform this drill before launch and after material schema changes.

## Incidents

- Authorization failures: stop retries, show reconnect, and inspect only safe status codes.
- Worker death/backlog: keep web browsing available, restart the worker, then run pending-work reconciliation.
- Watch failure: renew the watch and run a bounded history catch-up; polling remains the consistency fallback.
- AI budget exhaustion: pause new paid work while retaining indexed navigation and the reader.
- Token/key compromise: disable processing, rotate Google credentials and Doppler secrets, prepend a new Fernet key, run token rotation, retain old keys through backup expiry, and review access logs.
- Database restore: follow deletion replay before any network-facing role starts.

Alerts should cover worker absence, queue age, repeated auth failures, stale sync, database saturation, and error/latency increases using Azure's existing monitoring.

