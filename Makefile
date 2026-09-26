COMPOSE := docker compose -f deploy/compose.yaml
DEMO_ENV := APP_ENV=development APP_BASE_URL=http://localhost:5000 AUTH_MODE=dev MAIL_MODE=fake AI_PROVIDER=fake SYNC_MODE=manual

.PHONY: demo bootstrap dev migrate seed-demo test lint security logs down vendor

vendor:
	poetry run python scripts/fetch_vendor_assets.py

demo:
	$(DEMO_ENV) $(COMPOSE) up -d --build db
	$(DEMO_ENV) $(COMPOSE) run --rm web flask --app wsgi:app db upgrade
	$(DEMO_ENV) $(COMPOSE) run --rm web procrastinate --app=mercury.jobs.cli.app schema --apply
	$(DEMO_ENV) $(COMPOSE) run --rm web flask --app wsgi:app seed-demo
	$(DEMO_ENV) $(COMPOSE) up -d web worker

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
	$(COMPOSE) run --rm web procrastinate --app=mercury.jobs.cli.app schema --apply

seed-demo:
	$(DEMO_ENV) $(COMPOSE) run --rm web flask --app wsgi:app seed-demo

test:
	APP_ENV=testing $(COMPOSE) --profile test up -d test-db
	APP_ENV=testing APP_BASE_URL=http://localhost:5000 AUTH_MODE=dev MAIL_MODE=fake AI_PROVIDER=fake SYNC_MODE=manual DATABASE_URL=postgresql+psycopg://mercury:mercury_test@localhost:55433/mercury_test poetry run pytest

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

