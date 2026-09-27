# 5. Docker, explained from zero

## The problem Docker solves

Running Mercury needs Python 3.12, about 60 exact package versions, PostgreSQL 17 with the
pgvector extension, the Doppler CLI, and a particular way of starting each process. Installing all
of that by hand on every laptop and server is slow and error-prone: "it works on my machine" but
not on yours, or not in Azure.

Docker packages an application **together with everything it needs to run** into one portable
unit, so it runs the same everywhere Docker is installed.

## The five words you need

| Term | Plain meaning | Analogy |
|---|---|---|
| **Image** | A read-only package: a minimal Linux filesystem + Python + your dependencies + your code + a default start command | A recipe plus all ingredients, sealed in a box |
| **Container** | A running instance of an image, an isolated process with its own filesystem and network | A dish cooked from the recipe; you can cook several from one box |
| **Dockerfile** | The text file of instructions to build an image | The recipe card |
| **Volume** | Storage that lives outside the container, so data survives when the container is deleted | A fridge the dish can be stored in |
| **Registry** | A server that stores images (Docker Hub, Azure Container Registry) | A warehouse of sealed boxes |

Key facts:

- Containers are **disposable**. Deleting and recreating one is normal. Anything written inside a
  container that isn't in a volume disappears. That's why Mercury keeps all state in PostgreSQL,
  and PostgreSQL keeps its files in a volume.
- An image is **built once and run anywhere**. The exact image you test is the one you deploy.
- Containers are **isolated**: each has its own network address. Compose gives them names (`db`,
  `web`, `worker`) so they can find each other.

## How Docker is typically used

1. Write a **Dockerfile** describing how to build the app image.
2. `docker build` turns it into an **image**.
3. `docker run` starts a **container** from the image.
4. Because real apps have several pieces (app + database + worker), a **Compose file**
   (`compose.yaml`) describes them all, and `docker compose up` starts them together with the
   right settings, ports, and startup order.
5. For production, the image is pushed to a **registry**, and the hosting platform (Azure
   Container Apps here) pulls and runs it.

## How Mercury uses Docker

![Docker build and compose](images/docker.png)

### The Dockerfile (`deploy/Dockerfile`): one image, built in three stages

A **multi-stage build** uses throwaway intermediate images so the final image stays small and has
no build tools in it.

**Stage 1: `builder`**
- Starts from `python:3.12.12-slim-bookworm`, pinned to an exact **digest** (a SHA-256
  fingerprint), so the base can't silently change.
- Installs Poetry, then `poetry install --only main`: the production dependencies from
  `poetry.lock` into `/app/.venv`. Dev tools such as pytest are excluded.
- Copies the code and runs `scripts/fetch_vendor_assets.py`, which downloads Bootstrap and HTMX
  and **checks their SHA-384 hashes**, failing the build if they were tampered with.

**Stage 2: `doppler`**
- Just a source for the official Doppler CLI binary (also digest-pinned).

**Stage 3: `runtime`** (the final image)
- A fresh slim Python image. It copies in only the finished `.venv`, the Doppler binary, the app
  code, the verified vendor assets, the migrations, and the deploy scripts.
- Creates and switches to a **non-root user** `mercury`, so a compromise inside the container has
  fewer privileges.
- `ENTRYPOINT ["/app/deploy/entrypoint.sh"]` is always run first.
- `CMD ["gunicorn", "--config", "deploy/gunicorn.conf.py", "wsgi:app"]` is the default command
  (the web role).

**`deploy/entrypoint.sh`** (the fail-closed secrets gate):

```sh
if APP_ENV is production and we haven't injected Doppler yet:
    if DOPPLER_TOKEN is missing: print an error and EXIT (refuse to start)
    otherwise: re-run this same command under `doppler run --no-fallback -- ...`
run the command
```

Locally (`APP_ENV=development`) it just runs the command. In production, the app can't start
without secrets from Doppler; there's no fallback to local files.

**One image, two roles.** The same image runs:
- **web:** default CMD → Gunicorn serving Flask on port 8000.
- **worker:** CMD overridden to `python -m mercury.jobs.worker` → the Procrastinate worker.

The web code and the worker code can therefore never drift apart: they're literally the same bytes.

### The Compose file (`deploy/compose.yaml`): the local stack

| Service | Image | What it is | Port on your machine |
|---|---|---|---|
| `db` | `pgvector/pgvector:0.8.2-pg17-bookworm` (digest-pinned) | PostgreSQL 17 with pgvector. Data in volume `mercury_pgdata` | `127.0.0.1:5433` → container `5432` |
| `web` | `mercury:local` (built from the Dockerfile) | Gunicorn + Flask. Health check calls `/health/ready` every 5s | `127.0.0.1:5000` → container `8000` |
| `worker` | `mercury:local` (same image, `pull_policy: never`) | The job worker | none (it doesn't serve HTTP) |
| `test-db` | pgvector (same pinned image), **profile `test`** | Throwaway test database stored in memory (`tmpfs`), wiped when stopped | `127.0.0.1:55433` |

Details worth understanding:

- **Ports like `127.0.0.1:5000:8000`** mean "port 5000 on *this computer only* (loopback) forwards
  to port 8000 inside the container". Binding to `127.0.0.1` keeps the demo login unreachable from
  other machines on your network.
- **Inside Compose, containers reach the database at host `db`, port `5432`**, not `localhost`. In a
  container, `localhost` means *that container itself*. That's why `DATABASE_URL` inside Compose is
  `postgresql+psycopg://mercury:mercury_local@db:5432/mercury`, while from your laptop (tests,
  `psql`) it's `localhost:5433`.
- **Environment variables** are passed explicitly in the `environment:` block with defaults, e.g.
  `AUTH_MODE: ${AUTH_MODE:-dev}` means "use the `AUTH_MODE` from my shell if set, else `dev`". This
  is also how Doppler's values reach the containers during `make dev`.
- **`depends_on: condition: service_healthy`** makes web/worker wait until PostgreSQL answers.
- **Volumes:** `mercury_pgdata` survives `docker compose down` (`make down`). Only
  `down --volumes` (`make reset-local`, which asks for confirmation) deletes it.
- **Profiles:** `test-db` only starts when asked for (`--profile test`), so `make demo` doesn't
  start it.

### Why the frontend isn't built by Docker

There's no Node.js or `npm run build` step. The browser files (CSS, JS, Bootstrap, HTMX) are plain
static files inside the Python package and are copied into the image as-is. See
[07-frontend-explained.md](07-frontend-explained.md).

## Commands you'll actually use

| You want to… | Command |
|---|---|
| Build and start the whole demo | `make demo` |
| See what's running | `docker compose -f deploy/compose.yaml ps` |
| Follow web + worker logs | `make logs` (Ctrl+C stops following, not the app) |
| Stop everything, keep data | `make down` |
| Open a shell inside the web container | `docker compose -f deploy/compose.yaml exec web sh` |
| Run a one-off Flask command in a fresh container | `docker compose -f deploy/compose.yaml run --rm web flask --app wsgi:app <command>` |
| Connect to the local database from your laptop | `psql postgresql://mercury:mercury_local@localhost:5433/mercury` |
| List images | `docker images` (look for `mercury  local`) |
| Delete the local database (destructive) | `make reset-local` |
| Free disk space from old builds | `docker image prune` / `docker builder prune` |

**Rebuild rule:** the image contains a copy of the code. After changing Python, templates, or CSS,
you must rebuild (`make demo` does this) before the containers show the change. For fast UI
iteration, run Flask directly on your machine instead (chapter 6, "Host-Python workflow").

## Docker in production

1. GitHub Actions runs `az acr build`, which builds the same Dockerfile **inside Azure Container
   Registry** and tags it with the Git commit.
2. It looks up the image's **digest** (`mercury@sha256:...`) and scans it with Trivy.
3. Bicep deploys **that exact digest** to three Azure Container Apps resources: `mercury-web`
   (default CMD), `mercury-worker` (args `python -m mercury.jobs.worker`), and the `mercury-migrate`
   job (runs migrations once per release).
4. Each container starts through `entrypoint.sh`, which fetches secrets via Doppler.
