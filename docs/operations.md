# Operations

## Release

Build one image, scan it, record its digest as `RELEASE_ID`, then run application and Procrastinate migrations as a single controlled job. Deploy that digest to web and worker. Keep the previous digest. Prefer additive migrations; rolling back an image cannot undo destructive schema changes.

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

