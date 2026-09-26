# Mercury

Mercury is a small Flask workspace that organizes a bounded part of a Gmail mailbox without replacing Gmail. It stores metadata and derived organization, fetches original message text on demand, and deliberately has no sending, attachment, deletion, archiving, billing, extension, or chat features.

## Local synthetic demo

Requirements: Docker with Compose. The demo binds only to `127.0.0.1:5000` and uses invented mailbox data.

```bash
make demo
```

Open <http://localhost:5000>, choose **Open synthetic demo**, then connect the synthetic mailbox. CSRF, ownership checks, PostgreSQL, migrations, the real templates, and the same service layer used by live providers remain active.

## Doppler-backed development

Install Python 3.12, Poetry 2.4, Docker, and the official Doppler CLI, then:

```bash
doppler login
doppler setup --project mercury --config dev
make bootstrap
make dev
```

Copy setting names from `.env.example` into Doppler; do not put credentials in the repository. Register these exact callbacks for the configured `APP_BASE_URL`:

- `<APP_BASE_URL>/auth/google/callback`
- `<APP_BASE_URL>/auth/gmail/callback`

Development Google testing projects may issue short-lived refresh tokens. Use a dedicated test mailbox and leave Gmail label writes disabled initially.

## Commands

```bash
make migrate     # application and Procrastinate schemas
make seed-demo   # guarded: fake mail and non-production only
make test        # disposable PostgreSQL/pgvector test database
make lint
make security
make logs
make down        # preserves the local database volume
```

## Runtime roles

The same image runs either Gunicorn or `python -m mercury.jobs.worker`. Web requests authenticate, authorize, validate, render, and enqueue bounded work. The worker owns imports, analysis, reconciliation, clustering, and synchronization. PostgreSQL stores application and Procrastinate records; message bodies never belong in either schema.

## Live integration status

Google OAuth/Gmail, Pub/Sub, OpenAI, Doppler production injection, and Azure deployment require separately scoped credentials and must be smoke-tested before release. Passing offline tests does not mean Google has approved the application or that a security assessment is complete.

See `docs/architecture.md`, `docs/security.md`, `docs/operations.md`, and `docs/google-review.md` before deploying.

