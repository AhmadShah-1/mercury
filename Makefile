COMPOSE := docker compose -f deploy/compose.yaml
DEMO_ENV := APP_ENV=development APP_BASE_URL=http://localhost:5000 AUTH_MODE=dev MAIL_MODE=fake AI_PROVIDER=fake SYNC_MODE=manual DEBUG=false

.PHONY: demo demo-smoke browser-test worker-once bootstrap dev migrate seed-demo test lint security logs down reset-local vendor

vendor:
	poetry run python scripts/fetch_vendor_assets.py

# `compose run` never rebuilds an existing image, so build explicitly before migrating.
demo:
	$(DEMO_ENV) $(COMPOSE) build web
	$(DEMO_ENV) $(COMPOSE) up -d --wait db
	$(DEMO_ENV) $(COMPOSE) run --rm web flask --app wsgi:app db upgrade
	$(DEMO_ENV) $(COMPOSE) run --rm web flask --app wsgi:app queue-schema
	$(DEMO_ENV) $(COMPOSE) run --rm web flask --app wsgi:app seed-demo
	$(DEMO_ENV) $(COMPOSE) up -d --wait web worker
	@echo "Mercury synthetic demo: http://localhost:5000"

# Probe the running demo without a browser: health, static assets, and worker liveness.
demo-smoke:
	curl -fsS http://localhost:5000/health/live >/dev/null
	curl -fsS http://localhost:5000/health/ready >/dev/null
	test "$$(curl -fsS http://localhost:5000/static/vendor/htmx.min.js | wc -c)" -gt 10000
	test "$$($(COMPOSE) ps --status running --format '{{.Service}}' | grep -c -x -E 'web|worker|db')" -eq 3
	@echo "demo smoke checks passed"

# Playwright flow against a running synthetic server (default: `make demo`). It disconnects and
# reconnects the synthetic mailbox. One-time setup: poetry run playwright install --with-deps chromium
BROWSER_BASE_URL ?= http://localhost:5000
browser-test:
	MERCURY_BROWSER_BASE_URL=$(BROWSER_BASE_URL) poetry run pytest -q tests/browser -p no:cacheprovider

# Drain currently runnable jobs once in a throwaway worker container, then exit.
worker-once:
	$(DEMO_ENV) $(COMPOSE) run --rm worker procrastinate --app=mercury.jobs.cli.app worker --one-shot

bootstrap:
	@command -v poetry >/dev/null || (echo "Poetry is required" && exit 1)
	@command -v docker >/dev/null || (echo "Docker is required" && exit 1)
	poetry install --sync
	$(MAKE) vendor
	$(COMPOSE) up -d db
	$(MAKE) migrate
	$(MAKE) seed-demo

dev:
	doppler run --project mercury --config dev -- $(COMPOSE) up --build web worker db

migrate:
	$(COMPOSE) run --rm web flask --app wsgi:app db upgrade
	$(COMPOSE) run --rm web flask --app wsgi:app queue-schema

seed-demo:
	$(DEMO_ENV) $(COMPOSE) run --rm web flask --app wsgi:app seed-demo

test:
	APP_ENV=testing $(COMPOSE) --profile test up -d --wait test-db
	APP_ENV=testing APP_BASE_URL=http://localhost:5000 AUTH_MODE=dev MAIL_MODE=fake AI_PROVIDER=fake SYNC_MODE=manual DEBUG=false DATABASE_URL=postgresql+psycopg://mercury:mercury_test@localhost:55433/mercury_test poetry run flask --app wsgi:app db upgrade
	APP_ENV=testing APP_BASE_URL=http://localhost:5000 AUTH_MODE=dev MAIL_MODE=fake AI_PROVIDER=fake SYNC_MODE=manual DEBUG=false DATABASE_URL=postgresql+psycopg://mercury:mercury_test@localhost:55433/mercury_test poetry run flask --app wsgi:app queue-schema
	APP_ENV=testing APP_BASE_URL=http://localhost:5000 AUTH_MODE=dev MAIL_MODE=fake AI_PROVIDER=fake SYNC_MODE=manual DEBUG=false DATABASE_URL=postgresql+psycopg://mercury:mercury_test@localhost:55433/mercury_test poetry run pytest

lint:
	poetry run ruff check .
	poetry run ruff format --check .

security:
	poetry run bandit -q -r mercury
	poetry run pip-audit

logs:
	$(COMPOSE) logs -f --tail=200 web worker

down:
	$(COMPOSE) down

# Destructive: deletes the local synthetic database volume after an explicit confirmation.
reset-local:
	@printf "This deletes the local Mercury database volume. Type 'reset' to continue: "; \
	read answer; [ "$$answer" = "reset" ] || (echo "aborted"; exit 1)
	$(COMPOSE) down --volumes
