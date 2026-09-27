# Mercury implementation handoff

Last updated: 2026-09-26 (America/New_York)

This is a coordination log, not a replacement for
`Assets/project_kickoff/MERCURY_BUILD_SPEC.md`. Every agent must read the full specification
before changing code and preserve the user's scope exclusions.

## Coordination protocol

1. Read this file, `git status --short`, `git diff --check`, `AGENTS.md`, and the full build spec.
2. Before editing, add a row to **Active work claims** naming the task and intended files. Avoid
   files claimed by another active agent. Prefer disjoint worktrees/tasks when parallel work is
   available.
3. Never reset, discard, overwrite, or commit another agent's changes. The worktree is intentionally
   dirty. Re-read a file immediately before patching it.
4. After each verified slice, update the claim, changed-file summary, commands/results, decisions,
   unverified integrations, and next work. Record failures as well as passes.
5. Keep secrets, tokens, mailbox bodies, raw MIME, and provider payloads out of this file and logs.

## Active work claims

| Agent | Task | Intended files | Status / timestamp |
|---|---|---|---|
| Lead (Claude, session 2) | Worker/demo/deploy validation, mocked tests, pins, gates | see slice A | **Complete** 2026-09-26 — released |
| UI agent (Claude subagent) | Quicksilver UI/UX rework + Playwright flow | see slice B | **Complete** 2026-09-26 — released |
| Next agent | Live-provider smoke tests (needs credentials) or remaining items under "Highest-priority remaining work" | Claim before editing | Unclaimed |

## Current outcome

Mercury is now a substantial five-phase implementation rather than an empty scaffold. The offline
vertical slice and its PostgreSQL security gates work. It includes:

- Flask 3.1 factory, feature blueprints, Jinja/HTMX, local pinned frontend assets during image build.
- PostgreSQL 17/pgvector migrations and Procrastinate 3.9 queue schema/worker roles.
- Synthetic login/mail/AI, bounded indexing, workspace, safe ephemeral text reader, buckets/rules,
  actions, merge preview, disconnect, deletion, and deletion-event replay.
- Google OIDC/Gmail OAuth attempts with PKCE/state/nonce, encrypted refresh tokens, generation
  checks, bounded Gmail adapter, history sync, watch renewal, authenticated Pub/Sub, and optional
  Mercury-owned label writes behind all operator/user/scope/ownership gates.
- OpenAI Responses structured output with `store=False`, no tools, pinned summary snapshot,
  512-dimensional embeddings, operator-supplied production rates, atomic reservations/ledger,
  deterministic clustering helpers, and conservative assignment thresholds.
- Composite tenant constraints, CSRF, trusted hosts, session-generation invalidation, headers/CSP,
  no-store authenticated responses, restricted read-only Flask-Admin metrics, health probes.
- One non-root Dockerfile, Compose, Doppler fail-closed entrypoint, CI scans, Azure Bicep and a
  manual GitHub OIDC deployment workflow.

Explicitly absent as required: sending, drafts, attachments/downloads, Gmail deletion/trashing or
archiving, billing, browser extension, chat, permissive production fakes, hard-coded AI pricing,
and claims of Google approval.

## Session 2 slice A — worker, demo, deployment validation (lead, verified 2026-09-26)

Bugs found by actually running `make demo` and a worker, and fixed:

1. **Every queued job was unrunnable in worker processes.** `create_app()` builds an enqueue App
   and the worker builds a second App; `add_tasks_from` mutates the shared Blueprint, renaming
   tasks to `mercury:mercury:*` → `TaskNotFound`. Fix: `mercury/jobs/tasks.py::build_blueprint()`
   creates a fresh Blueprint per App; task bodies are plain functions. Regression test added.
2. Periodic tasks crashed (`unexpected keyword argument 'timestamp'`). Fixed.
3. `procrastinate schema --apply` is not idempotent → `make demo`, `make migrate`, and the Azure
   migration job failed on any existing DB. New `flask queue-schema` (install-once) is used in
   Makefile, CI, and Bicep.
4. Runtime image served 85-byte vendor placeholders (runtime stage copied source, not builder
   output). Dockerfile now copies the verified vendor dir from the builder.
5. `make demo` never rebuilt (`compose run` reuses an existing image). It now builds first and
   waits on health. Compose web+worker both use `image: mercury:local` (verified same image ID).
6. `SYNC_INTERVAL_SECONDS`/poll mode did nothing; reconciler now schedules catch-up syncs in
   poll/push mode.
7. Integer `retry=5` meant immediate retries on every error and runs could stay `running` forever.
   Now: `MercuryRetry` (capped exponential backoff + jitter, Retry-After, no retry on
   permanent errors), `track_run` marks runs `failed` with safe codes, `queueing_lock`/`lock`,
   heartbeat-based `retry_stalled_jobs`, bounded stall recovery. Watch renewal no longer moves
   the history checkpoint (it could skip changes) and isolates per-account failures.
8. Gmail adapter: no finite HTTP timeout; only some calls refreshed tokens; refresh triggered only
   on `expired` (not missing token); retryable refresh errors were treated as revoked; real
   Gmail 404 surfaced as `HttpError` (so the reader's deleted-message state never appeared).
   Now typed `ReauthorizationRequired`/`ProviderUnavailable` in `integrations/types.py`,
   `_execute` translation, lock-serialized refresh for every call. UI agent was asked to catch
   these in `thread_body`.
9. `main.bicep` did not compile (BCP237). Also fixed: worker `command` bypassed the Doppler
   entrypoint; probes would 400 on Host (new `appHostname` param → probe Host header); ACR Basic
   retention policy (Premium-only) removed; workload-profiles env for the delegated subnet;
   serialized Postgres server operations.
10. CI: test DB port mismatch (conftest requires 55433), missing queue schema, and
    `aquasecurity/trivy-action@0.33.1` referenced a nonexistent tag. All actions pinned to commit
    SHAs; Docker/Compose/CI images pinned to digests (resolved from official registries/repos
    2026-09-26; **a human should review the pinned trivy-action commit before first use**).

Files changed (lead): `mercury/jobs/{tasks,queue}.py`, `mercury/integrations/types.py`,
`mercury/integrations/google/gmail.py`, `mercury/commands.py`, `tests/conftest.py`
(`MERCURY_TEST_DATABASE_URL` override restricted to port 55433; also truncates `procrastinate_*`),
new `tests/integration/{test_worker,test_commands,test_recovery_and_admin}.py`,
`tests/unit/test_gmail_adapter.py`, `Makefile` (demo, demo-smoke, worker-once, reset-local),
`deploy/{Dockerfile,compose.yaml}`, `deploy/azure/{main,bootstrap}.bicep`,
`.github/workflows/{ci,deploy}.yml`, `docs/operations.md`, `README.md`.

Commands actually run and results:

- `make demo` → first failed (`type "procrastinate_job_status" already exists`), then **exit 0**
  after fixes; web healthy. `make demo-smoke` → passed. curl walk: dev login 302, connect 302 →
  `/app`, workspace 200, reader 200, body 200 with `Cache-Control: no-store, private` + CSP,
  CSRF-less move 400.
- Real job through the long-running Compose worker and through `make worker-once`:
  `mercury:discover_recent_threads` → `succeeded`; run `succeeded/complete`. Worker: 0 restarts,
  0 errors in logs over ~30 min; new periodic jobs succeed.
- Official Bicep CLI 0.47.16 (standalone binary in session scratchpad; no Azure login):
  `bicep build` + `bicep lint` on both templates → exit 0 after fixes.
- Pytest (network blocked): **69 passed** (includes UI agent's in-progress tests at that moment);
  worker file alone 12 passed, including a real SIGKILL-mid-job recovery.
- `ruff check` clean; `bandit -q -r mercury` clean; `flask db check` → no new operations;
  `git diff --check` clean; pip-audit → only the unpublished local package skipped.

## Session 2 slice B — Quicksilver UI/UX (UI subagent, reviewed and merged by lead)

Note: the user committed a checkpoint mid-session (`6f06691 second`) that includes part of this
work (base template, components, vendor assets, pyproject/lock). Everything since is uncommitted.

- Design: spec tokens plus a small scale, silver gradient family, semantic tones, dark theme
  (`prefers-color-scheme` and a toggle that stores only "light"/"dark"), local SVG planet/orbit
  mark, system fonts, AA contrast checked, reduced-motion honored, no horizontal scroll at 390px.
- All templates rewritten; new `templates/components/{icons,brand,ui,toasts}.html` and
  `inbox/{_thread_row,_reader,_reader_panel,_progress}.html`; `static/css/mercury.css`,
  `static/js/{mercury,theme}.js`, `static/img/mercury-mark.svg`. Real SHA-384-verified vendor
  assets are now checked in (resolves the old placeholder caveat). Bootstrap JS is vendored but
  no longer loaded (native `<dialog>`/`<details>`).
- Interactions: HTMX reader panel (≥1100px; plain links/Back otherwise), keyboard shortcuts with
  `?` help, bulk move with count confirmation (JS only; single Move works without JS),
  client-side filter of the rendered page, in-place Handled/Not an action/Move (plain CSRF POSTs
  without JS), staged progress polling that stops on completion/failure/30 min, and the spec's
  essential states. No `|safe`, inline script/style, `hx-on`, or innerHTML; storage holds only the
  theme and a `moved:N` notice.
- Route changes (presentation only; `HX-Request` selects templates, never authorizes):
  `/app?view=` allowlist, owner-scoped nav counts/latest run, reader partial, provider error
  mapping in `thread_body` (404 deleted / 409 reconnect / 503 unavailable or rate-limited with
  Retry-After), settings label-sync counts, and a fixed crash when the delete-confirmation
  re-render lacked `label_form`.
- **New data write:** `thread_reader` sets `EmailThread.last_opened_at` on first open
  (owner-scoped, Mercury-local, never touches Gmail unread state).
- Lead follow-ups: explicit `user_id` conditions on every workspace outer join and the action
  route's analysis lookup (defense in depth over composite FKs); safe 409/503 error handlers plus
  a regression test; `make browser-test`.
- Tests: `tests/acceptance/test_ui_partials.py`, `tests/browser/` (opt-in via
  `MERCURY_BROWSER_BASE_URL`, loopback only, disconnects/reconnects the synthetic mailbox).
  Dev dependency `pytest-playwright`. Browser setup: `poetry run playwright install --with-deps
  chromium` (on this WSL host the libraries were extracted into the session scratchpad without
  root and supplied via `LD_LIBRARY_PATH`).

## Session 2 final gates (merged tree, 2026-09-26)

- `make demo` → exit 0, web healthy; `make demo-smoke` → passed; web and worker share image
  `mercury:local` (same image ID).
- `make browser-test` against the Compose demo → **1 passed**.
- `pytest -q` (network blocked) → **82 passed, 1 skipped** (the opt-in browser test).
- `ruff check .` clean; `ruff format --check .` → 72 files already formatted.
- `bandit -q -r mercury` → clean. `pip-audit` → No known vulnerabilities found.
- `flask db check` → No new upgrade operations detected. `poetry check --lock` → only the
  authors deprecation warning.
- Bicep CLI 0.47.16 `lint` + `build`: both templates OK. `docker compose config` OK.
  `git diff --check` clean.
- Disposable test DB `mercury_test_ui` is kept on the test server for concurrent agent runs;
  `mercury_ui_preview` was dropped.

## Live integrations still not verified

Google OIDC/Gmail OAuth, the Gmail API adapter against real Google, Pub/Sub push signature
verification against Google, OpenAI, Doppler production injection, Azure deployment (templates
compile/lint only; nothing provisioned), GitHub OIDC deploy workflow, Open-in-Gmail with multiple
signed-in Google accounts. No Google approval or assessment is implied.

## Last verified results (session 1)

- `poetry run ruff check .`: passed.
- `poetry run ruff format .`: applied; the last full check was clean before the final tiny changes.
- PostgreSQL/pgvector suite with unexpected network blocked: **41 passed in 17.18s** after upgrading
  to fixed dependency versions; an earlier full run was **41 passed in 12.23s**.
- `poetry run pip-audit`: **No known vulnerabilities found** after upgrading `cryptography` to
  50.0.1 and pytest to 9.1.1 in the lockfile. The local package is correctly skipped as unpublished.
- `poetry run bandit -q -r mercury`: passed with no output after removing two low findings.
- `flask db check`: `No new upgrade operations detected.` Procrastinate tables are deliberately
  excluded from Alembic comparison.
- Rehearsed downgrade `3ca94f7cb56f -> c981d9eb4d2d` and upgrade back successfully.
- Built web and worker Docker targets successfully. Build fetched and verified Bootstrap 5.3.8 and
  HTMX 2.0.11, installed the lock, and produced non-root runtime images. The build finished after
  the output stream detached; manifests were exported successfully.

Use these environment prefixes for host Poetry commands in this session if the existing temporary
virtualenv is still present:

```bash
POETRY_CACHE_DIR=/tmp/mercury-poetry-cache \
POETRY_VIRTUALENVS_PATH=/tmp/mercury-poetry-venvs
```

The disposable test database has been running from `deploy/compose.yaml` on
`127.0.0.1:55433`; verify with `docker compose -f deploy/compose.yaml ps` rather than assuming.

## Important recent changes

- Initial migration: `migrations/versions/c981d9eb4d2d_initial_schema.py` creates `vector` and the
  application schema.
- Tenant/accounting migration:
  `migrations/versions/3ca94f7cb56f_tenant_constraints_and_usage_accounting.py` adds composite
  ownership constraints and AI token/rate/reservation fields.
- Continuous history synchronization lives in `mercury/inbox/sync.py`.
- Label-write runtime enforcement lives in `mercury/integrations/google/labels.py`.
- Atomic AI budget logic lives in `mercury/intelligence/budget.py`.
- Durable tasks, periodic reconciliation, stalled-run recovery, watch renewal, sync and label jobs
  live in `mercury/jobs/tasks.py`.
- `mercury/jobs/cli.py` now binds the Flask app so CLI-started Procrastinate workers can execute
  tasks; this was fixed immediately before handoff and still needs a real one-shot worker test.
- `deploy/azure/main.bicep`, `bootstrap.bicep`, and `.github/workflows/deploy.yml` were added but
  have not been validated by Azure tooling or a deployment.
- Dependency audit required and received upgrades: `cryptography ^50.0.0`, `pytest ^9.0.3`; lockfile
  resolves 50.0.1 and 9.1.1.

## Commands actually run in the latest work

- `poetry lock`; `poetry install --sync` (successful).
- `flask db migrate`, manual migration review/repair, `flask db upgrade`, `flask db check`.
- `procrastinate --app=mercury.jobs.cli.app schema --apply` (successful).
- Repeated `ruff format`, `ruff check`, and PostgreSQL `pytest -q` runs.
- `pip-audit` first found 9 advisory rows in cryptography/pytest; dependencies were upgraded; the
  repeat found none.
- `bandit -q -r mercury` first reported two low findings; both were removed; the repeat passed.
- `docker compose -f deploy/compose.yaml build web worker` (successful).

## Highest-priority remaining work

Items 1–8 from session 1 are done (slice A/B). Remaining:

1. With a dedicated Google test project and test mailbox: register both callbacks, run the
   real-account dev profile (`make dev` via Doppler), and smoke-test sign-in, Gmail consent,
   bounded indexing through the worker, reader, reconnect after revoking access, disconnect and
   deletion. Record results as "tested against the provider".
2. OpenAI smoke test with a small budget and operator-supplied rates; confirm `store=False` and
   the 512-dimension embedding contract live.
3. Azure: `az deployment group what-if` with real parameters (requires authorization), then
   the first deploy; verify probe Host header, migration job polling, pgvector version, and
   private DB connectivity. Add Log Analytics retention configuration if desired.
4. Review the pinned `aquasecurity/trivy-action` commit before first CI use; decide whether to
   add `make browser-test` to CI (needs `playwright install --with-deps chromium`).
5. **Wire automatic bucket discovery.** `buckets/clustering.py` (PCA + HDBSCAN,
   `conservative_choice`) is unit-tested but no task calls it; real Gmail users start with
   everything Unsorted. Add a `discover_buckets` worker task (bounded, one at a time) that
   creates `origin="suggested"` buckets and model assignments without touching locked ones.
6. **Revoke the Google OAuth token on disconnect/delete** (best effort, spec §22); currently only
   the watch is stopped and the encrypted token is deleted locally.
7. Consider a manual-sync cooldown for `POST /app/sync` in real Gmail mode (currently a full
   bounded re-index, coalesced per run) and an undo for bulk moves (currently count confirmation
   only).

## Known caveats / review points

- Verified vendor assets are now checked in; the Docker build still re-fetches and verifies them.
- Compose currently has a local PostgreSQL volume and a separate tmpfs test database. Preserve the
  local volume by default.
- Azure, Google OAuth/Gmail, Pub/Sub signature verification against Google, OpenAI, and production
  Doppler injection remain **implemented but not live-provider verified** because no credentials or
  deployment authorization were provided.
- Do not claim Google approval, production readiness, an assessment result, or verified provider
  pricing.
- The worktree contains intentional uncommitted changes. Do not run destructive Git commands.
