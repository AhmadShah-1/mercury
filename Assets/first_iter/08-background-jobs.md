# 8. Background jobs: the worker and the queue

## Why a worker at all?

Some work is too slow or too failure-prone to do while the browser waits: listing 2,000 Gmail
threads, calling OpenAI hundreds of times, retrying after Google rate-limits you. A web request
should finish in well under a second. So the web process writes a small **job** ("index account
X, run Y") and returns immediately. A separate **worker** process picks the job up and does the
work, and the browser watches progress by polling the `processing_runs` row.

## Why Procrastinate (a queue inside PostgreSQL)?

Many apps use Redis + Celery for this. Mercury keeps the queue **in the same PostgreSQL
database**: one less service to run and pay for, and a job can be written in the same database as
the data it refers to. Procrastinate provides retries, locks, periodic (cron-like) tasks, and
heartbeat-based detection of crashed workers.

## The pieces

| File | Role |
|---|---|
| `mercury/jobs/queue.py` | `create_queue_app()` builds a Procrastinate App on the same database (a fresh task registry per App) |
| `mercury/jobs/tasks.py` | The tasks, the retry policy, reconciliation, and the `enqueue_*` helpers routes call |
| `mercury/jobs/worker.py` | `python -m mercury.jobs.worker`: creates the Flask app and runs the worker |
| `mercury/jobs/cli.py` | Entry point for the `procrastinate` CLI (`make worker-once`) |

## The tasks

| Task | Queue | Triggered by | Does |
|---|---|---|---|
| `discover_recent_threads` | `mail` | Gmail connect, "Sync now" (real Gmail), reconciler | Bounded initial index, then AI analysis (if consented) |
| `sync_account_history` | `mail` | Pub/Sub webhook, reconciler (poll/push catch-up) | Incremental Gmail history sync |
| `apply_owned_label` | `mail` | Moving a thread when label sync is on | Adds/removes a Mercury-owned Gmail label |
| `reconcile_pending_work` | `maintenance` | **Every 5 minutes** | Re-queues pending runs and accounts that need sync, recovers stalled runs, schedules poll-mode syncs |
| `retry_stalled_jobs` | `maintenance` | **Every 2 minutes** | Re-queues jobs whose worker stopped heartbeating (crashed or killed) |
| `renew_gmail_watches` | `maintenance` | **Daily at 03:17** | Renews Gmail push watches (push mode only) |

## What a job contains (privacy)

Only internal identifiers and version numbers, for example:

```json
{"account_id": "16ba694a-…", "connection_generation": 3, "run_id": "6ad06e7a-…"}
```

Never email text, summaries, tokens, or prompts. The worker reloads everything it needs from the
database and re-checks ownership and the connection generation before touching Gmail. A test
asserts that no fixture body text ever appears in the queue table.

## Reliability rules

- **One account at a time.** Each job carries `lock="account:<id>"`, so two jobs for the same
  account never run concurrently.
- **No duplicates waiting.** Each job carries a `queueing_lock` (for example `discover:<run_id>`).
  Queuing the same work twice while one copy is still waiting is silently merged.
- **Retries with backoff (`MercuryRetry`).** Temporary failures (timeouts, HTTP 429, 5xx) retry up
  to 5 times with growing, randomized delays (capped at 15 minutes), respecting Google's
  `Retry-After`. Permanent failures (access revoked, invalid data, label write not allowed) are
  **not** retried.
- **Honest progress.** When a job won't be retried, its run becomes `failed` with a safe code such
  as `connection_needs_reauthorization`, and the progress page explains it in plain language.
- **Crash recovery.** Workers send a heartbeat. If one dies mid-job (container killed, machine
  restarted), `retry_stalled_jobs` notices within about 2 minutes and puts the job back in the
  queue. A test actually kills a worker process mid-job and verifies the job completes afterwards.
- **Stuck runs.** A run `running` for more than 15 minutes is reset to `pending` and re-queued.
  After 2 hours it's marked `failed` (`processing_stalled`) rather than retried forever.
- **The commit/enqueue gap.** If the database write succeeded but queuing the job failed, the
  durable `pending` run (or `pending_sync` flag) remains, and the 5-minute reconciler finds it.
- **Disconnect safety.** Every job re-checks `connection_generation` before calling a provider and
  before saving results, so work queued before a disconnect can't recreate deleted data.

![Run states](images/run-states.png)

## Watching jobs locally

```bash
make logs                                   # worker log lines show "Job ... ended with status: Success"
make worker-once                            # run whatever is ready, then exit
psql postgresql://mercury:mercury_local@localhost:5433/mercury \
  -c "select task_name, status, attempts from procrastinate_jobs order by id desc limit 10"
```

In the synthetic demo, connecting and "Sync now" run **synchronously** in the web request (the
fake mailbox is tiny), so the worker mainly runs its periodic tasks. With real Gmail, all
indexing goes through the worker.
