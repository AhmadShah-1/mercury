# Operations

## Release

Build one image, scan it, record its digest as `RELEASE_ID`, then run application and Procrastinate migrations as a single controlled job. Deploy that digest to web and worker. Keep the previous digest. Prefer additive migrations; rolling back an image cannot undo destructive schema changes.

The release job runs `flask --app wsgi:app db upgrade && flask --app wsgi:app queue-schema`. `queue-schema` installs Procrastinate's schema only when `procrastinate_jobs` is absent, so it is safe on every release. When upgrading the pinned Procrastinate version, apply the SQL files for the intervening versions from `procrastinate schema --migrations-path` in the same controlled job before deploying the new image.

The deploy workflow passes `appHostname` (the `APP_BASE_URL` host) to Bicep because Container Apps probes must send an allowed `Host` header; Mercury rejects any other host with HTTP 400. The workflow deploys the revision and then starts the migration job and polls it; readiness includes a schema check, so a revision needing an unapplied migration never becomes ready.

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

