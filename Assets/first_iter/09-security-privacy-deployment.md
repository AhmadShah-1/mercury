# 9. Security, privacy, secrets, CI, and deployment

## Security controls and where they live

| Threat | Control | Where |
|---|---|---|
| Another user reads or changes your data | Every query filters by `user_id`; composite foreign keys; not-found responses for others' IDs | `*/service.py`, models, `tests/security/test_ownership.py` |
| A malicious site submits forms as you (CSRF) | Global Flask-WTF CSRF on every POST, including HTMX; only the signed Pub/Sub webhook is exempt | `extensions.py`, `mercury.js`, tests |
| Script injection via email/AI content (XSS) | Jinja auto-escaping; reader shows plain text only; strict CSP (`script-src 'self'; style-src 'self'`) | `templates/`, `inbox/reader.py`, `security/headers.py` |
| Stolen database leaks Google access | Tokens encrypted with Fernet; keys live in Doppler, not the DB | `security/crypto.py` |
| Stale sessions after disconnect or deletion | `session_generation` checked on every request | `__init__.py` |
| Forged OAuth callbacks | Single-use `oauth_attempts` with state, nonce, PKCE, expiry; same-Google-account check; scope check | `integrations/google/oauth.py` |
| Forged Gmail notifications | Google-signed JWT verification (issuer, audience, service account, subscription) | `integrations/google/notifications.py` |
| Host-header tricks | `TRUSTED_HOSTS` from `APP_BASE_URL`; untrusted hosts get 400 | `config.py` |
| Admin snooping | Admin page shows counts and run statuses only; every view checks the role; others get 404 | `admin/views.py` |
| Cached private pages | `Cache-Control: no-store, private` on `/app`, `/settings`, `/admin` | `security/headers.py` |
| Runaway AI costs | Atomic budget reservation per account, global monthly cap, daily thread limit; prices supplied by the operator | `intelligence/budget.py` |
| Unsafe production config | Startup validation: production refuses fake providers, debug, HTTP, demo keys, weak cookies, non-TLS DB | `config.py` |

## Privacy promises (and how they're kept)

- **Bodies are never stored.** They're fetched on demand for the reader or for AI analysis, then
  discarded. No body in PostgreSQL, the queue, logs, files, or browser storage. Tests check this
  with a secret marker string.
- **AI is optional and explicit.** Without AI consent, no text goes to OpenAI (not even for
  embeddings). When it's on, calls use `store=False`, no tools, and structured output.
- **Gmail stays authoritative.** Reading in Mercury doesn't mark mail as read in Gmail. "Handled"
  is Mercury-only. Label writes are off unless the operator enables them *and* the user opts in
  *and* grants the broader `gmail.modify` scope.
- **Disconnect removes derived data.** Threads, summaries, embeddings, buckets, and rules are all
  deleted (cascade), tokens are cleared, and old jobs become no-ops. Account deletion also removes
  the user. (Gap: Google token revocation isn't called yet; see README.)
- **No overclaiming.** Mercury isn't end-to-end encrypted, isn't "zero-knowledge", and has no
  Google approval or security certification yet.

## Secrets with Doppler

**Doppler** is a hosted secrets manager. You store values like `SECRET_KEY`, `GOOGLE_CLIENT_SECRET`,
and `OPENAI_API_KEY` in a Doppler **project** (`mercury`) with separate **configs** (`dev`, `prd`).

- **Locally:** `doppler login` once, then `make dev` runs `doppler run -- docker compose ...`, which
  injects the `dev` values as environment variables.
- **In production:** the container gets only a read-only **service token** (`DOPPLER_TOKEN`, stored
  as an Azure secret). `entrypoint.sh` runs `doppler run --no-fallback -- <app>`. If Doppler is
  unreachable or the token is missing, the container exits. There's no silent fallback.
- **The app never talks to Doppler itself.** It only reads environment variables in `config.py`.
  `.env.example` lists the variable **names** only, never real values.

## Continuous integration (`.github/workflows/ci.yml`, every push and PR)

| Job | Steps |
|---|---|
| `secrets` | gitleaks scans the Git history for committed secrets |
| `test` | Starts pgvector PostgreSQL, installs with Poetry, migrates, installs the queue schema, then ruff check + format, pytest with coverage, bandit, pip-audit |
| `container` | Builds the Docker image and scans it with Trivy (fails on fixable critical/high CVEs) |

All GitHub Actions and base images are pinned to exact commit SHAs or digests so they can't change
underneath you.

## Deployment (`.github/workflows/deploy.yml`, manual, **never run yet**)

1. Log in to Azure with GitHub OIDC (no long-lived Azure password).
2. Create the resource group and the container registry (`deploy/azure/bootstrap.bicep`).
3. `az acr build`: build the image once in Azure; resolve its digest; Trivy scan.
4. Deploy `deploy/azure/main.bicep` with that digest:
   - VNet with subnets for Container Apps and PostgreSQL (the database has no public access)
   - PostgreSQL 17 Flexible Server (Burstable B1ms, 7-day backups, pgvector allow-listed)
   - Container Apps environment + `mercury-web` (0.25 vCPU / 0.5 GiB, scales 0–3, probes send the
     real hostname) + `mercury-worker` (0.5 vCPU / 1 GiB, always 1 replica)
   - `mercury-migrate` job (`flask db upgrade && flask queue-schema`)
   - a managed identity with only the AcrPull role to pull the image
5. Start the migration job and poll until it succeeds.

Status: the templates **compile and lint cleanly** with the official Bicep CLI, but nothing has
been provisioned. The next Azure step is a `what-if` preview with real parameters.
