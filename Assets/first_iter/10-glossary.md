# 10. Glossary

| Term | Meaning |
|---|---|
| **Alembic / migration** | Versioned scripts that change the database schema step by step (`migrations/versions/`) |
| **Application factory** | `create_app()`, a function that builds a configured Flask app. Lets tests create isolated instances |
| **Blueprint** | A Flask group of related routes (e.g. `inbox`, `buckets`) |
| **Bucket** | A Mercury category. Thread in no bucket = **Unsorted** |
| **Connection generation** | A counter on the Gmail account. Jobs carry it and abort if it changed (disconnect safety) |
| **Container / image / volume** | See chapter 5 |
| **Content version** | A fingerprint of a thread's messages. Changes on new mail, not on label changes. Decides when AI must re-run |
| **CSP (Content-Security-Policy)** | A header telling the browser which scripts and styles may run. Mercury allows only its own files |
| **CSRF** | Cross-site request forgery: another site tricking your browser into submitting a form. Blocked by per-form tokens |
| **Digest (image) / commit SHA (action)** | An exact fingerprint. Pinning to it prevents silent upstream changes |
| **Doppler** | Hosted secrets manager that injects environment variables at start-up |
| **Embedding** | A list of 512 numbers representing a text's meaning; similar texts have similar vectors |
| **Fernet** | An authenticated symmetric encryption format from the `cryptography` library |
| **Gunicorn** | Production Python web server that runs Flask |
| **HDBSCAN / PCA** | Clustering algorithm that can leave outliers unassigned / dimensionality reduction before clustering |
| **Heartbeat** | Periodic "I'm alive" signal from a worker; missing heartbeats mean a crashed worker |
| **History ID** | Gmail's change counter; Mercury stores it as a checkpoint for incremental sync |
| **HTMX** | Small library that fetches HTML fragments and swaps them into the page via HTML attributes |
| **Idempotent** | Safe to run again with the same result (e.g. `flask queue-schema`) |
| **Jinja** | Flask's template language; auto-escapes values |
| **Lock / queueing lock** | Procrastinate features: don't *run* two jobs with the same lock at once / don't *queue* a duplicate while one is waiting |
| **OAuth / OIDC / PKCE / nonce / state** | Google sign-in protocols and their anti-forgery values |
| **ORM (SQLAlchemy)** | Maps Python classes to database tables |
| **pgvector** | PostgreSQL extension that stores and compares vectors |
| **Poetry / lock file** | Python dependency manager / exact versions everyone installs |
| **Procrastinate** | PostgreSQL-backed job queue library |
| **ProcessingRun** | The progress record the UI shows for an indexing/sync operation |
| **Pub/Sub** | Google's messaging service; Gmail uses it to push "mailbox changed" notifications |
| **Reconciler** | The 5-minute periodic task that finds and re-queues pending work |
| **Scope** | A permission granted by Google (e.g. `gmail.readonly`) |
| **Tenant isolation** | Guaranteeing one user can never reach another user's data |
| **Trusted hosts** | The hostnames Mercury will answer to; others get HTTP 400 |
| **Worker** | The separate process that runs background jobs from the same image as the web app |
