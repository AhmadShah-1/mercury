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
| Lead (Claude, session 2) | `make demo`/worker one-shot validation, Compose shared image, Bicep validation, remaining mocked tests, digest pinning, quality gates | `Makefile`, `deploy/*`, `.github/workflows/*`, `mercury/jobs/*`, `mercury/integrations/google/{oauth,gmail}.py`, `mercury/inbox/sync.py`, `mercury/admin/views.py`, `tests/conftest.py`, new `tests/{unit,integration,security}/test_*` files, `handoff.md` | Active 2026-09-26 |
| UI agent (Claude subagent) | Quicksilver UI/UX rework + Playwright browser flow | `mercury/templates/**`, `mercury/static/**` (css/js/img; vendor via `make vendor`), presentation-only edits in `mercury/{inbox,buckets,accounts,public}/routes.py`, `tests/browser/**`, markup assertions in existing tests, `pyproject.toml`/`poetry.lock` (dev dep for Playwright only). Uses test DB `mercury_test_ui` via `MERCURY_TEST_DATABASE_URL`. | Active 2026-09-26 |

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

## Last verified results

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

1. Run `make demo` from a clean-ish Compose state, verify migrations, queue schema, seed command,
   web readiness, login/connect/workspace/body flow, and worker stability. Do not delete persistent
   user volumes unless explicitly authorized.
2. Exercise one real Procrastinate job end-to-end with `worker --one-shot`, including a retry/failure
   case and periodic reconciliation. The queue payload privacy test already passes, but consumption
   after the latest CLI binding change is not yet verified.
3. Add `image: mercury:local` to both Compose web and worker services if needed so Compose visibly
   runs the exact same locally built image rather than separately named equivalent targets. Rebuild
   and inspect user/entrypoint/health behavior.
4. Validate `deploy/azure/*.bicep` with official Azure/Bicep tooling. Review Container Apps Job API
   property names, subnet delegations, ACR pull identity, pgvector allow-list configuration, and the
   deploy workflow's `az containerapp job start --wait` support. No Azure deployment is authorized.
5. Implement/run the documented Playwright browser flow if browser tooling is available. Current
   acceptance coverage uses Flask's real templates/routes, not a browser engine.
6. Add mocked tests for serialized Google credential refresh/`invalid_grant`, admin success/no-content
   exposure, expired Gmail history 404 recovery, enqueue-failure reconciliation, and a worker crash
   retry. Existing tests already cover stale generations, pagination, label-only changes, OAuth
   replay/partial scope/wrong subject, token preservation, webhook JWT claims, budgets, deletion,
   CSRF, XSS, ownership, MIME safety, and no body persistence.
7. Pin Docker base images and third-party GitHub Actions to reviewed immutable digests once the final
   compatibility scan is complete. The current Docker tags resolve successfully but source files do
   not yet pin every digest.
8. Re-run `ruff format --check`, `ruff check`, all 41+ tests, Bandit, pip-audit, migration check,
   Docker build, and `git diff --check` after fixes. Update this file with exact results.

## Known caveats / review points

- Source-tree vendor files are tiny placeholders; the Docker build and `make vendor` fetch verified
  pinned assets. Decide whether final handoff should check the fetched assets into the repository.
- Compose currently has a local PostgreSQL volume and a separate tmpfs test database. Preserve the
  local volume by default.
- Azure, Google OAuth/Gmail, Pub/Sub signature verification against Google, OpenAI, and production
  Doppler injection remain **implemented but not live-provider verified** because no credentials or
  deployment authorization were provided.
- Do not claim Google approval, production readiness, an assessment result, or verified provider
  pricing.
- The worktree contains intentional uncommitted changes. Do not run destructive Git commands.
