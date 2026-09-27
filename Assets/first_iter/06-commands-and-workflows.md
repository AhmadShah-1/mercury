# 6. Commands and workflows

All commands are `make` targets defined in the [`Makefile`](../Makefile). `make` is a classic tool
that gives short names to longer shell commands. `make demo` simply runs the lines listed under
`demo:`. You can always see exactly what a target will run, without running it, using
`make -n <target>`.

Two shorthands appear inside the Makefile:

- `COMPOSE` = `docker compose -f deploy/compose.yaml`
- `DEMO_ENV` = `APP_ENV=development APP_BASE_URL=http://localhost:5000 AUTH_MODE=dev MAIL_MODE=fake AI_PROVIDER=fake SYNC_MODE=manual DEBUG=false`
  (forces synthetic, offline settings)

## Prerequisites

| Tool | Needed for | Check |
|---|---|---|
| Docker + Compose v2 | Everything | `docker compose version` |
| Poetry 2.4 + Python 3.12 | Tests, lint, host-Python workflow | `poetry --version` |
| Doppler CLI | `make dev` with real credentials | `doppler --version` |
| Playwright Chromium | `make browser-test` only | `poetry run playwright install --with-deps chromium` |

## The targets

### `make demo`: the zero-credential product demo
```text
compose build web                        # build image mercury:local from deploy/Dockerfile
compose up -d --wait db                  # start PostgreSQL, wait until healthy
compose run --rm web flask db upgrade    # apply Alembic migrations (creates/updates tables)
compose run --rm web flask queue-schema  # install Procrastinate's queue tables if missing
compose run --rm web flask seed-demo     # create demo user + fake mailbox + demo buckets
compose up -d --wait web worker          # start web and worker, wait until web is healthy
```
Then open <http://localhost:5000> → "Open the synthetic demo". `compose run --rm` starts a
temporary container for one command and deletes it afterwards. Safe to re-run: migrations and
`queue-schema` are idempotent, and seeding skips existing data.

### `make demo-smoke`: check the running demo without a browser
Calls `/health/live` and `/health/ready`, checks that the real HTMX file is served (not a
placeholder), and checks that db, web, and worker are all running.

### `make browser-test`: real browser walk-through (Playwright)
Runs `tests/browser/` against `http://localhost:5000` (override with
`make browser-test BROWSER_BASE_URL=http://localhost:5001`). It clicks through connect → reader →
move → handled → keyboard shortcuts → bulk move → settings → phone-width view. It disconnects and
reconnects the synthetic mailbox as part of the flow. It refuses non-loopback URLs.

### `make worker-once`: drain the queue once
Starts a throwaway worker container that runs every job currently ready, then exits. Useful for
seeing queued work happen step by step.

### `make dev`: local stack with your Doppler `dev` secrets
```text
doppler run --project mercury --config dev -- docker compose -f deploy/compose.yaml up --build web worker db
```
What happens:
1. `doppler run` logs in with your personal Doppler CLI session, downloads the `mercury/dev`
   config, and sets those values as environment variables **for this one command only** (nothing is
   written to disk).
2. `docker compose up --build` rebuilds the image and starts db, web, and worker **in the
   foreground**, streaming logs to your terminal. Ctrl+C stops them.
3. Compose passes the Doppler values into the containers through the `${VAR:-default}` entries in
   `compose.yaml`. For example, if Doppler sets `AUTH_MODE=google` and `MAIL_MODE=gmail`, you get
   real Google sign-in against a real (test) mailbox.
4. `DATABASE_URL` stays pointed at the local `db` container. Dev never touches production data.

Note: `make dev` doesn't run migrations. Run `make migrate` once first (and after pulling new
migrations). For real Gmail, the Doppler config must provide non-demo `SECRET_KEY` and
`TOKEN_ENCRYPTION_KEYS`, plus `GOOGLE_CLIENT_ID`/`SECRET`. Config validation refuses to start
otherwise.

### `make bootstrap`: first-time host setup
Checks Poetry and Docker exist, `poetry install --sync` (all dependencies, including dev tools,
into a local virtualenv), fetches vendor assets, starts db, migrates, seeds the demo.

### `make migrate`
`flask db upgrade` + `flask queue-schema` inside a temporary web container.

### `make seed-demo`
Creates the demo user and synthetic mailbox. It **refuses** in production or with real Gmail.

### `make test`
Starts the in-memory `test-db` (port 55433), migrates it, installs the queue schema, and runs
`pytest`. Tests block all non-local network access (pytest-socket), so a test can never
accidentally call Google or OpenAI. The test configuration refuses to run against any database
except the disposable one on port 55433.

### `make lint`
`ruff check .` (bugs, import order, security patterns) and `ruff format --check .` (formatting).
Fix formatting with `poetry run ruff format .`.

### `make security`
`bandit` (security lint of `mercury/`) and `pip-audit` (known CVEs in dependencies).

### `make logs` / `make down` / `make reset-local`
Follow web + worker logs; stop containers but keep data; delete the database volume after typing
`reset`.

### `make vendor`
Re-downloads Bootstrap/HTMX and verifies their hashes (you rarely need this; the files are checked in).

## Useful `flask` commands (run inside a container or with host Poetry)

| Command | What it does |
|---|---|
| `flask --app wsgi:app db upgrade` | Apply migrations |
| `flask --app wsgi:app db migrate -m "msg"` | Generate a migration from model changes (always review it) |
| `flask --app wsgi:app db check` | Fail if models and migrations differ |
| `flask --app wsgi:app queue-schema` | Install the queue tables once |
| `flask --app wsgi:app seed-demo` | Synthetic data (dev only) |
| `flask --app wsgi:app promote-admin <email>` | Make an existing user an admin |
| `flask --app wsgi:app rotate-token-encryption` | Re-encrypt stored tokens with the newest key |
| `flask --app wsgi:app export-deletions --since <ISO time>` | Export deletion events (backup-restore procedure) |
| `flask --app wsgi:app replay-deletions <file>` | Re-apply deletions after a restore |
| `flask --app wsgi:app retention-cleanup` | Remove expired OAuth attempts and old audit events |
| `flask --app wsgi:app routes` | List every URL |

## How do we "build"?

"Building" Mercury means building **the Docker image**; there's no separate compile or frontend step.

| Where | Command | Result |
|---|---|---|
| Your laptop | `make demo` or `docker compose -f deploy/compose.yaml build web` | Local image `mercury:local` |
| CI (every push) | `docker build -f deploy/Dockerfile .` then Trivy scan | Proves the image builds and has no known critical/high CVEs |
| Deployment | `az acr build ...` in `deploy.yml` | Image stored in Azure Container Registry, deployed by digest |

Python dependencies are "built" into the image by `poetry install` from the lock file. To add a
dependency: `poetry add <package>` (or `poetry add --group dev <package>` for tools), commit
`pyproject.toml` + `poetry.lock`, rebuild.

## Day-to-day workflows

**Try the product:** `make demo` → browse → `make down` when finished.

**Change backend code and verify:**
1. Edit code.
2. `make test` (or faster, a single file: `poetry run pytest -q tests/integration/test_worker.py`
   with the env vars from the Makefile's `test` target).
3. `make lint` and `make security`.
4. `make demo` to see it in the real containers.

**Host-Python workflow (fastest UI iteration, no rebuilds):** with `db` running from Compose:
```bash
export APP_ENV=development AUTH_MODE=dev MAIL_MODE=fake AI_PROVIDER=fake SYNC_MODE=manual \
       APP_BASE_URL=http://localhost:5001 \
       DATABASE_URL=postgresql+psycopg://mercury:mercury_local@localhost:5433/mercury
poetry run flask --app wsgi:app run --port 5001 --debug   # auto-reloads on file changes
```
Templates and CSS changes then show on refresh. (Stop the Compose `web` container first if you
want to avoid confusion, or just use port 5001 as above.)

**Change the database schema:** edit a model → `flask db migrate -m "..."` → review the generated
file in `migrations/versions/` → `make migrate` → `make test` → commit the migration with the code.

**Before pushing:** `make lint && make security && make test` (CI runs the same checks, plus a
secret scan and a container scan).
