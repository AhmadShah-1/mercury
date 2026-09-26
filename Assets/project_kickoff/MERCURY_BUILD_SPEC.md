# Mercury
## Product vision, architecture, security, and implementation brief

**Audience:** An LLM coding agent working with Ahmad, a developer familiar with Flask, Python, PostgreSQL, Docker, Doppler, Azure, and WSL.  
**Specification version:** 1.0 - September 24, 2026.  
**Primary deliverable:** A small, secure, maintainable application, not a demonstration with placeholder integrations.

## 01. Instructions to the coding agent

Build **Mercury**, a Gmail organization workspace. Read this entire specification before implementing. Treat its security boundaries, scope limits, and acceptance criteria as requirements. The feature set should remain deliberately small; the implementation must be reliable enough to handle private email data.

Inspect an existing repository before changing it. Reuse working conventions, dependencies, and migrations where compatible. If starting from an empty repository, use the structure below. Write a short implementation plan, then deliver vertical slices that run and have tests. Do not create an enormous speculative scaffold or dozens of empty abstractions. Do not substitute a screenshot-only interface, fake OAuth success, in-memory production persistence, or unimplemented buttons for working features.

Use **Flask**, an application factory, feature-oriented blueprints, PostgreSQL, and a background worker. Prefer **Jinja + HTMX + locally served Bootstrap** over a separate React application for V1. This is a deliberate simplification: one origin, one application deployment, one authentication system, and reusable server-rendered components. Preserve service boundaries so a richer frontend can be added later without moving business logic into routes.

Use hosted AI APIs initially. Use Doppler for injected configuration. Local development must work in WSL without paid cloud resources, a public webhook tunnel, real Gmail data, or live AI credentials. Production must never silently fall back to development authentication, synthetic data, or weakened security.

When credentials are unavailable, finish the offline implementation and document the exact setup step needed for a real integration test. Explicitly distinguish **implemented**, **tested offline**, **tested against the provider**, and **requires production verification**. Do not claim Google approval or security certification because automated tests pass.

### Definition of engineering success

A human should be able to answer these questions by looking at the repository: Where is Gmail synchronization? Where are buckets created? Where is email content rendered? Where are secrets loaded? What happens when a worker crashes? How are another user's records kept inaccessible? How do I run this locally and deploy the same image?

Prefer ordinary functions, SQLAlchemy models, small service modules, and established libraries. Introduce an interface where an external dependency could change, not for every database query. A readable implementation with fewer moving parts is better than a theoretically perfect framework with a large maintenance burden.

## 02. Vision and product philosophy

**Mercury turns a noisy Gmail account into a calm, personalized workspace without replacing Gmail.** The name evokes communication, messages, speed, and information. Use that association as a restrained design theme, not a reason for elaborate mythological illustrations.

The primary user journey is: connect Gmail, preview useful categories, correct a few suggestions, read an AI summary, open the actual message inside Mercury, and move to Gmail only when replying or handling an attachment. The user should not need to understand embeddings, vectors, or clustering.

Mercury owns the organization layer: buckets, user corrections, summaries, possible actions, and processing state. Gmail remains authoritative for the messages themselves, conversation membership, Gmail labels, and Gmail unread state. Mercury must not imply that a model suggestion is a fact or that a local interaction performed an action in Gmail.

**User control beats automation volume.** An uncertain email belongs in Unsorted. A user-created category name is never silently replaced. A manually assigned thread is not moved by the next clustering run. Suggestions may improve; user choices remain authoritative.

**Privacy claims must match implementation.** Mercury retains selected message metadata and derived information, including summaries and embeddings. It temporarily processes message bodies. It is not end-to-end encrypted, zero-knowledge, or a product that stores no email-derived data. A suitable description is: "Mercury keeps the information needed to organize your inbox. Full message bodies are fetched when needed rather than retained in Mercury's database. AI processing and provider retention are explained before connection."

**Reliability beats breadth.** Stable synchronization, safe rendering, reversible organization, token security, and trustworthy error states matter more than an animated dashboard or a long list of AI features.

## 03. V1 scope and explicit exclusions

### Required for the first complete release

- Google sign-in; explicit Gmail connection; one connected Gmail account per Mercury user; disconnect and account deletion.
- Bounded initial indexing: up to 2,000 recently active threads from a six-month window. Show the selected window before processing, not a surprise full-mailbox scan.
- Suggested flat buckets, an Unsorted view, rename/create/archive, moving one or several threads, merging buckets, and a simple exact-sender rule. Preserve manual overrides.
- One concise AI summary per eligible thread and conservative possible-action indicators. Provide "Mark handled in Mercury" and "Not an action" controls.
- An on-demand, read-only email viewer. Show readable text inside Mercury and an **Open in Gmail** button. No reply composer or attachment viewer.
- Durable background processing with visible progress, retries, reconnect states, and bounded resource use.
- Optional, explicit synchronization of Mercury-owned labels to Gmail. It must work technically, but remain disabled unless both the operator and the user enable it and the user grants the appropriate scope.
- A small settings page and a restricted administrative operations panel. Administrators must not receive a mailbox-reading interface.
- A repeatable local workflow, automated tests, deployment configuration, privacy/security documentation, and Google review preparation materials.

### Excluded from V1

Do not implement sending, drafting, replying, attachment retrieval/viewing, automatic archiving or deletion of Gmail messages, a browser extension, a Workspace add-on, Outlook, shared mailboxes, billing, chat over the inbox, calendar integration, email tracking, a mobile app, public sharing, team taxonomies, an elaborate role-permissions engine, nested bucket trees, or autonomous actions. Defer drag-and-drop if an accessible Move menu achieves the same result with less code. Do not provision a GPU or a dedicated vector database.

A manual "split" can be accomplished by creating a bucket and moving selected threads. Automated hierarchical clustering and a visual split editor are not required.

## 04. Visual direction and interaction design

### Theme: quiet speed, not inbox overload

Use a clean, light workspace with generous spacing, silver-gray surfaces, dark ink typography, and one restrained blue accent. Suggested design tokens are `--ink: #172033`, `--muted: #526078`, `--surface: #FFFFFF`, `--canvas: #F5F7FA`, `--border: #DCE2EA`, and `--accent: #3659D9`. These are starting tokens; validate contrast for actual text/background combinations. Use color plus text/icon, never color alone, for status.

Use a system font stack, familiar form controls, visible keyboard focus, modest corner radii, and subtle transitions that honor reduced-motion preferences. No external font service, tracking scripts, session replay, or decorative third-party assets on authenticated pages. Keep branding to a Mercury wordmark and a simple locally stored mark. An elaborate logo is not a prerequisite.

### Main workspace

Desktop has three functional regions: a narrow navigation sidebar, a thread list, and a reader panel. Navigation contains Overview, Needs attention, All indexed threads, Unsorted, user buckets, and Settings. A synchronization status is visible but not intrusive. On smaller screens, the reader becomes a separate view with a clear Back control rather than squeezing three columns together.

Each thread row shows sender, original subject, short AI summary or an honest pending state, bucket, last-message time, and a possible-action badge. The original subject must remain visible. Do not replace it with an invented AI title. Distinguish an unread Gmail conversation from a thread that has not yet been opened in Mercury.

The reader shows original sender/recipient information, timestamps, the summary clearly labeled "AI summary," and message content below a visual separator. Show the newest message first, with earlier messages expandable. **Open in Gmail** stays easy to find. An attachment indicator may say "Attachments are available in Gmail," but there is no attachment preview or download route.

### Essential states

Design empty, loading, partial-results, no-category-yet, AI-disabled, AI-budget-paused, Gmail-disconnected, provider-rate-limited, message-deleted, stale-summary, invalid-permission, and failed-label-sync states. Do not leave a spinner indefinitely. A user may browse already indexed metadata while a background task is failing, provided the connection and deletion policies allow retaining that metadata.

Processing is not an exact countdown. Show stages and measured counts: "Finding conversations," "Indexed 180 conversations," "Preparing category suggestions." Do not claim a fixed number of seconds until completion.

## 05. Chosen stack and minimal external accounts

| Responsibility | V1 choice | Reason and boundary |
| --- | --- | --- |
| Web application | Flask + Jinja + HTMX | Server-rendered pages and partial updates; no separate frontend authentication or API gateway. |
| Styling | Bootstrap, locally served, with one Mercury stylesheet | Familiar accessible components; no large custom design framework. |
| Authentication | Authlib for Google OIDC/OAuth; Flask-Login for Mercury sessions | Reuse protocol implementations; no password/reset system. |
| Forms and CSRF | Flask-WTF / WTForms | Global CSRF enforcement for browser-originated mutations. |
| Database | PostgreSQL + pgvector; Flask-SQLAlchemy; Flask-Migrate | One persistent store for domain data, vectors, and the queue's tables. |
| Jobs | Procrastinate, behind a small queue adapter | PostgreSQL-backed jobs with existing retry/locking features instead of a homegrown queue or Redis service. |
| AI | Official OpenAI SDK, inside one provider adapter | Embeddings and structured summaries through one paid AI provider. |
| Clustering | NumPy + scikit-learn HDBSCAN/PCA | CPU work in the worker; no GPU service. |
| Email integration | google-auth + Google API Python client | Gmail requests and Pub/Sub token verification through maintained provider libraries. |
| Content extraction | Python email utilities + Beautiful Soup | MIME/header handling and HTML-to-text conversion without rendering untrusted HTML. |
| Cryptography | cryptography library | Encrypt stored OAuth tokens; do not implement cryptography. |
| Administration | Flask-Admin | Restricted operational views, not unrestricted CRUD over every table. |
| Packaging and server | Poetry, Docker, Gunicorn | Familiar development workflow and repeatable deployment. |
| Secrets and deployment | Doppler; Azure Container Apps; managed Azure PostgreSQL | Few services, with portable application code. |

The external account list is intentionally small: **Google Cloud, OpenAI, Doppler, Azure, and the existing GitHub account**. Domain registration is an operational purchase, not another application SDK. No Auth0, Clerk, Pinecone, Redis Cloud, Stripe, email-delivery service, analytics provider, or separate frontend host is required.

Flask's factory pattern and extension initialization support this structure. HTMX supplies HTML-driven partial updates. Procrastinate documents PostgreSQL-backed tasks, retries, locks, and periodic work; use its supported API rather than manipulating its tables directly. Recheck library maintenance, supported versions, and compatibility when creating the lockfile. [S01] [S02] [S03]

## 06. Runtime architecture and trust boundaries

```text
Browser
  | HTTPS, same-origin session cookie, CSRF token
  v
Flask / Gunicorn ------------------------> Gmail API
  | pages, forms, scoped reads              | live reader only
  | enqueue durable work                   | user OAuth tokens
  v                                        |
PostgreSQL + pgvector <---------------------+
  ^ domain records, tokens, vectors, jobs
  |
Worker (same Docker image, different command)
  | bounded Gmail reads, AI requests, clustering
  +------------------> Gmail API
  +------------------> OpenAI API

Gmail -> Google Pub/Sub -> authenticated HTTPS webhook
                              |
                              +-> durable sync request -> worker

Doppler -> environment injection -> web / worker / migration job
```

Run web and worker as separate processes. Never start a worker, scheduler, inbox scan, or model call as a side effect of importing a module or handling an ordinary list-page request. A Gunicorn process can restart or multiply; it is not the place for periodic jobs.

The web process is responsible for authentication, authorization, validation, rendering, and short operations. The worker performs indexing, semantic processing, label application, reconciliation, and retention cleanup. The one exception to background Gmail reading is the on-demand reader: a bounded provider fetch on a user request, with a timeout and a useful error state.

Application state lives in PostgreSQL, not the container filesystem. Do not rely on sticky sessions, a local SQLite database, or an in-process queue. Container restarts must not lose the user's organization choices or a synchronization checkpoint.

Keep outward network calls within integration modules. Services receive normalized data structures instead of Google SDK response dictionaries. UI templates never import provider clients. Neither the browser nor a model receives OAuth refresh tokens.

## 07. Human-readable repository structure

Create files as their feature is implemented; this is a map of responsibilities, not a request to generate empty files.

```text
mercury/
  __init__.py                 # create_app()
  config.py                   # grouped settings and validation
  extensions.py               # unbound Flask extensions
  commands.py                 # administrative CLI entry points
  accounts/
    models.py                 # users, Gmail connection, consent
    routes.py                 # login, connect, settings, delete
    service.py                # account lifecycle and access checks
  inbox/
    models.py                 # threads, message references, analysis
    routes.py                 # list, reader, progress, action controls
    service.py                # scoped queries and thread state
    reader.py                 # ephemeral MIME-to-text presentation
  buckets/
    models.py                 # buckets, assignments, sender rules
    routes.py                 # create, rename, move, merge, archive
    service.py                # user changes and stable membership
    clustering.py             # initial discovery; pure computations
    classification.py         # incoming-thread assignment
  intelligence/
    service.py                # input selection and AI orchestration
    schemas.py                # validated structured AI output
    prompts.py                # versioned summarization/naming prompts
  integrations/
    google/
      oauth.py                # Google authorization setup
      gmail.py                # narrow Gmail API wrapper
      notifications.py        # Pub/Sub authentication and decoding
      links.py                # Open in Gmail link construction
    ai/
      base.py                 # minimal provider contracts
      openai.py               # real summaries and embeddings
      fake.py                 # deterministic offline implementation
    fake_gmail.py             # synthetic local mailbox
  jobs/
    queue.py                  # Procrastinate adapter and registration
    tasks.py                  # short task wrappers around services
    worker.py                 # worker process with Flask app context
  security/
    authorization.py          # ownership / admin checks
    crypto.py                 # token encryption and key rotation
    headers.py                # CSP, cache rules, security headers
  admin/
    views.py                  # restricted Flask-Admin operations
  templates/
    base.html
    accounts/                 # auth, connect, settings
    inbox/                    # workspace, list, reader, partials
    buckets/                  # forms and category-review screens
    components/               # reusable alerts, pagination, badges
  static/
    css/mercury.css
    js/mercury.js
    vendor/                   # pinned local HTMX / Bootstrap assets
migrations/                   # reviewed Alembic revisions
tests/                       # automated test suites
  unit/
  integration/
  security/
  acceptance/
  fixtures/                   # synthetic messages only
docs/                        # short operational documentation
  architecture.md
  security.md
  google-review.md
  operations.md
deploy/                      # container and cloud deployment
  Dockerfile
  compose.yaml
  entrypoint.sh
  gunicorn.conf.py
  azure/main.bicep
.github/workflows/            # CI and deployment workflows
pyproject.toml
poetry.lock
Makefile
.env.example                  # names/examples, never real secrets
README.md
AGENTS.md                     # short repository guardrails
```

Routes parse input, check access, call services, and return a response. Services contain application decisions and transaction boundaries. Models describe persistence, constraints, and simple relationships. Integration modules translate provider data and exceptions. Jobs call the same services as the web app where appropriate.

Do not add a generic repository layer over every SQLAlchemy model, an event bus, CQRS, microservices, a plugin registry, a dependency-injection framework, or a large `utils.py`. If a helper is specific to Gmail links, put it in `integrations/google/links.py`. If a feature is currently only 30 lines, one cohesive file is better than five tiny files.

## 08. Application factory, extension setup, and request conventions

`create_app(config_overrides=None)` loads and validates configuration, creates Flask, initializes extensions with `init_app`, registers blueprints and CLI commands, installs safe error handling and response headers, and returns the app. Unit tests may pass overrides without changing process-global state. Load environment values when the factory runs, not as import-time class attributes.

`extensions.py` defines unbound `SQLAlchemy`, `Migrate`, `LoginManager`, `CSRFProtect`, and the Authlib integration. Keep initialized provider clients in a documented `app.extensions` entry or an equally small application-owned container. It must be possible to create two app instances with different test providers in one test process.

Use SQLAlchemy 2-style queries and explicit transaction boundaries. Do not call `db.create_all()` during production startup. Run Alembic migrations as a separate deployment step. Database extension creation and queue schema migrations are also explicit operational steps.

Use one error vocabulary: forbidden/not found, invalid form, connection needs reauthorization, provider temporarily unavailable, processing pending, and budget paused. Return ownership-related not-found responses consistently so raw identifiers do not become an enumeration interface. Attach a non-sensitive request ID to operational errors without showing a traceback or provider response body.

Provide `/health/live` without a database dependency, and `/health/ready` with a quick database check and schema compatibility check. Neither endpoint exposes configuration, token status, mailbox identity, or environment dumps. Liveness and readiness must not call Gmail or OpenAI.

## 09. Domain model and data ownership

Use UUID primary keys for Mercury records, UTC-aware timestamps, explicit foreign keys, and indexes on the query paths below. A Gmail identifier is an external identifier, never the authorization boundary. Every mailbox-derived row carries `user_id` and, where applicable, `gmail_account_id`.

### Core records

| Record | Essential fields and invariants |
| --- | --- |
| User | UUID; immutable Google OIDC subject; verified account email; display name; role `user/admin`; active flag; random session-generation identifier; created/deletion timestamps. Google subject, not a mutable email address, identifies the account. |
| GmailAccount | Owner; provider subject; mailbox address; encrypted token bundle; granted scopes; connection state; connection generation; last completed history ID; pending sync flag; watch expiry; last successful sync; per-user AI and label-write consent. Unique owner in V1. |
| EmailThread | Owner/account; Gmail thread ID; subject; participants needed for display; latest message time; Gmail-unread state; message-version fingerprint; processing state; last indexed/last opened in Mercury. Unique `(gmail_account_id, gmail_thread_id)`. |
| MessageReference | Owner/account/thread; Gmail message ID; Internet Message-ID when available; sender; timestamp; relevant Gmail labels; attachment-present flag. Store metadata, not a body or raw MIME blob. |
| ThreadAnalysis | One current analysis per thread; summary; possible action; action type; optional due date; source message ID; model/prompt version; analyzed content version; user handled/dismissed status; stale flag. |
| ThreadEmbedding | Thread; embedding vector; provider/model/dimension; input-pipeline version; analyzed content version. Keep the current embedding only in V1. |
| Bucket | Owner/account; name; short purpose; active/archive state; origin `suggested/user`; user-confirmed flag; creation/update times. A name is presentation, not identity. |
| BucketAssignment | Thread; bucket or no bucket; origin `model/rule/user`; score; locked-by-user flag; version. One primary bucket per thread in V1. |
| SenderRule | Owner/account; normalized exact sender address; destination bucket; enabled flag; rule priority. Rules are explicit user instructions, not security/trust judgments. |
| GmailLabelMapping | Owner/account/bucket; Mercury-created Gmail label ID; desired display name; sync status. Never assume an existing label is Mercury-owned merely because of its name. |
| ProcessingRun | Owner/account; kind; stages/counts; last safe error code; start/end; requested limits. This is the user's progress view, not a duplicate queue implementation. |
| UsageBucket | Owner and time window; reserved/spent AI tokens or estimated cost; counts for expensive operations. Atomic updates enforce budgets and abuse limits. |
| SecurityAuditEvent | Minimal event type, internal actor/resource IDs, time, outcome. No bodies, summaries, prompts, tokens, or raw provider errors. |

Use the queue library's tables for queue mechanics. Do not add a second homegrown jobs engine. MessageReference records permit deterministic content-version checks and correct source-message links; they are not an invitation to copy every Gmail field.

Prevent cross-tenant joins as well as cross-tenant lookups. For example, moving a thread must verify that both the thread and target bucket belong to the current user/account. Use composite uniqueness and foreign-key constraints where practical to reinforce these relationships. Test ownership for reads, writes, bulk actions, progress polling, rules, label mapping, and admin routes.

Start with exact similarity comparisons within one user's small dataset. An HNSW index is not required for 2,000 vectors per account. Never perform a global nearest-neighbor query and filter to the owner afterward. If approximate indexes are introduced later, validate tenant filtering and recall. pgvector supports both exact and approximate search; choose the simpler option until measurements justify an index. [S04]

Do not confuse three states: `gmail_unread`, `last_viewed_in_mercury`, and `action_status`. Opening a reader does not mark Gmail as read; marking an action handled does not send a response.

## 10. Google sign-in, Gmail consent, and token lifecycle

### Separate identity from mailbox authorization

Use Google OIDC for Mercury sign-in with `openid email profile`. Ask for Gmail access only when the user selects **Connect Gmail**, after the in-product processing disclosure. Use the authorization-code flow through a maintained client library, validate state and nonce, and use PKCE S256 where supported by the selected integration. Never hand-build token validation or trust claims decoded without signature verification.

In V1, the Gmail account must be the same Google subject as the signed-in Mercury account. Reject a callback that selects a different account instead of silently attaching it. Supporting an independently connected second account is a future feature.

The read-only product requests `gmail.readonly`. Optional Gmail label application requires incremental authorization for `gmail.modify`; `gmail.labels` alone does not authorize assigning labels to messages/threads. `gmail.modify` grants broader provider capabilities, including sending, even though Mercury must not implement those operations. Disclose that distinction honestly. Do not request `https://mail.google.com/`, separate sending scopes, Drive, Calendar, or Contacts. [S05] [S06]

### Callback and session behavior

Use exact registered callback URIs derived from configured `APP_BASE_URL`, not a request Host header. Keep the OAuth flow purpose and random state associated with the initiating browser/session, enforce expiry, and reject replay. Validate issuer, audience, nonce, subject, and verified email through the library. Check the scopes actually granted and handle partial consent. Do not repeatedly force the consent screen on ordinary sign-in.

Use offline access for background Gmail synchronization. Store refresh tokens encrypted in PostgreSQL. Preserve an existing refresh token when a later token response omits one. Serialize updates to an account's token bundle so concurrent refreshes cannot overwrite good credentials. Treat `invalid_grant` as reconnect-required, not a reason for an infinite retry loop. Google's external OAuth Testing status can produce seven-day refresh tokens for these scopes; make that expected development behavior explicit. [S07] [S08]

Flask's signed session cookie is not encrypted. It may contain only minimal session identifiers, OAuth state/nonce material as needed, and CSRF-related state. It must never contain Gmail tokens, email bodies, summaries, or provider API keys. Validate user active status and session generation on each request. Rotate the Mercury session after login and invalidate it after disconnect-related security changes, account disablement, or deletion.

An administrator is assigned by an explicit local/operations CLI command against an existing user, not by the first sign-up, an email suffix, or a query parameter. Use fresh Google authentication for sensitive administrative actions and secure the operator's Google account with MFA. Do not falsely claim that the app verifies an MFA method Google does not attest to it.

### Connection generations

Increment `connection_generation` on reconnect, disconnect, or replacement. Every job records the generation it was created for and checks it again before reading tokens, calling a provider, and committing results. Old work must not repopulate data after a user disconnects or deletes the account.

## 11. Gmail API connection contract

Only the integration adapter may call Gmail. Use `userId='me'` with the token belonging to the verified account. Never accept a caller-supplied Gmail account identity or arbitrary provider URL.

| API operation | Mercury purpose | Guardrail |
| --- | --- | --- |
| `users.getProfile` | Establish mailbox identity/current history marker | Verify the connected mailbox matches the authorized account. |
| `users.threads.list` or `users.messages.list` | Discover bounded recent conversations | Page results; deduplicate thread IDs; exclude Spam, Trash, and drafts; stop at the declared cap. |
| `users.threads.get` / `users.messages.get` | Index selected content or display an opened thread | Restrict fields, input sizes, and selected messages; never persist the raw response. |
| `users.history.list` | Retrieve changes after the durable checkpoint | Process all pages and persist work before advancing the checkpoint. |
| `users.watch` / `users.stop` | Establish or stop mailbox notifications | Same Google project as the Pub/Sub topic; renew before expiry. |
| `users.labels.list/create/update` | Manage labels created by Mercury | Operate only on recorded Mercury-owned IDs. |
| `users.threads.modify` | Add/remove Mercury-owned labels | Global flag, per-user consent, granted scope, and account ownership must all pass. |

Do not expose Gmail's send, draft, delete, trash, attachment-download, or settings APIs. The absence of a UI button is not sufficient; these operations should not exist in the production adapter's public interface.

A full Gmail message response may include inline MIME data. Therefore, "no attachment support" means Mercury does not deliberately retrieve separate attachments, render them, store them, or send them to AI. Skip attachment-designated MIME parts and discard any inline binary content received in the message response. Do not promise that Google can never include such bytes in a fetched response. [S09]

### Initial indexing without a synchronization gap

1. Validate connection/consent and create a ProcessingRun. Record a starting history marker before listing the historical window. Enable or renew the watch in production when configured.
2. Discover recent thread IDs using a bounded date query and pagination. Fetch metadata in small batches, create durable thread/message references, and mark records needing analysis. Do not make 2,000 synchronous calls in the onboarding HTTP request.
3. Process selected threads with bounded concurrency. Normalize text, embed, and summarize eligible recent/unread threads. Old history need not receive rich summaries immediately.
4. Discover suggested buckets from available embeddings. Return partial progress rather than waiting for every optional summary to finish.
5. Replay Gmail history from the starting marker to pick up changes that arrived during indexing. Publish a completion state only after the durable catch-up checkpoint is saved.

Use an epoch-seconds cutoff for date-sensitive Gmail API queries rather than assuming date-string timezone behavior matches the user. [S36]

The six-month window chooses recently active threads; a selected conversation can contain older messages. Bound the actual text selected from the thread separately. Exclude draft messages from AI input, even when a thread also contains sent or received messages.

### Incremental synchronization and reconciliation

Pub/Sub notifications contain a mailbox identifier and history marker, not the new email content. Treat a notification as a hint that the account needs synchronization. Deduplicate/coalesce notifications and serialize sync for each account. Out-of-order or duplicate notifications must not roll the checkpoint backward. History IDs are non-contiguous and can exceed ordinary 32-bit integer ranges; preserve them as strings or a suitably large numeric type. [S10]

Read history starting from the last completed checkpoint, page through changes, update metadata, and durably mark the changed threads for downstream work. Advance the checkpoint only after that transaction commits. If queue publication happens separately and fails, a periodic reconciler must find the durable pending records and enqueue them again. Avoid losing data in the gap between a database commit and a queue call.

An expired history checkpoint may return HTTP 404. Perform a bounded resynchronization and establish a fresh marker; do not retry an expired checkpoint forever. Periodic reconciliation is required even when push is enabled because push alone is not the complete consistency mechanism. [S11]

Distinguish changes to message content/membership from changes only to labels or unread state. Mercury's own label writes must not trigger another embedding/summary cycle. Compare a content version built from selected message IDs/timestamps and normalization version. When a new message arrives in an existing conversation, refresh its derived data and reapply its Mercury label if needed. Gmail thread labeling applies to existing messages; later messages do not automatically inherit the label. [S12]

## 12. Authenticated Pub/Sub webhook

Use one Google Cloud project per environment, one production topic, and one authenticated push subscription. Grant Gmail's publisher identity permission to publish to the topic. The push subscription uses a dedicated service account identity, but Mercury does not need to download a service-account private key to validate the incoming token.

`POST /webhooks/google/pubsub` is the only browser-CSRF exemption. It must instead verify the Google-signed OIDC token using `google-auth`: signature, issuer, expiry, exact audience, expected service-account email, and verified-email claim. Validate the subscription name, envelope size, base64 payload, mailbox identity, and history marker. Do not copy sample code that logs bearer tokens or raw message envelopes. [S13]

After validation, durably mark the account as needing sync and enqueue/coalesce work. Return a 2xx response only when this durable acceptance has succeeded. An authenticated delivery for an already deleted account can be acknowledged without processing. A database outage should return a retryable error rather than acknowledge and lose the notification.

Store watch expiry and renew watches daily, leaving time before the documented maximum renewal interval. Have a periodic catch-up sync for missed notifications and a status indicator for stale sync. Do not create a webhook tunnel as a dependency of ordinary local development; polling/manual sync covers dev. [S10]

## 13. On-demand reader and safe content presentation

The list and summary are served from Mercury's retained metadata. Opening a thread fetches its selected original messages from Gmail and displays them inside Mercury. V1 displays **escaped readable text**, not arbitrary email HTML. HTML-only emails are converted to text with a parser that does not fetch external resources. Preserve paragraphs and recognizable links as text; never execute a sender's styles, scripts, forms, event attributes, SVG, embedded frames, or HTMX attributes.

Use a normalized ephemeral `ThreadView`/`MessageView` structure. Decode base64url and MIME headers with existing libraries. Prefer a `text/plain` body when present; otherwise extract text from `text/html`. Skip attachment parts, nested attachments, binaries, and content beyond depth/size limits. A standalone text-body part that cannot be obtained without an unsupported attachment endpoint should show an honest fallback to Gmail.

Separate analysis text from reader text. For analysis, remove repeated quote history and boilerplate conservatively and cap tokens. For the reader, preserve the available original text; do not display the trimmed analysis input as though it were the full message. If the reader truncates a large thread, state that clearly and offer the original in Gmail.

The fetch path has finite timeouts and at most a small transient retry. A disconnected account shows reconnect guidance; a deleted message shows unavailable; a provider outage leaves the existing summary visible but does not present it as original content. Fetching content must not call AI or consume AI budget.

Set `Cache-Control: no-store, private` on authenticated HTML, reader responses, and sensitive API responses. Do not cache bodies in PostgreSQL, Redis, temporary files, browser storage, a service worker, an error tracker, or job payloads. Disable HTMX history snapshots on authenticated pages. Clearing references after a request is data minimization, not a guarantee that Python securely zeroes memory. [S02]

### Open in Gmail

Centralize URL construction in `links.py`. Do not trust an email-provided URL as the original-message link. Gmail API thread identifiers do not come with a documented universal web permalink in the resource. Treat a constructed Gmail thread URL as a tested integration detail, not a stable API contract. Account selection and Gmail web routing must be tested with multiple Google accounts signed in.

Provide a fallback Gmail search using the stored Internet Message-ID and Gmail's `rfc822msgid:` query when available. URL-encode all values, allow only the intended Gmail origin, and use `rel='noopener noreferrer'` when opening a new tab. Never put OAuth tokens in a URL. Test original-thread opening in the actual browser before calling this feature complete. [S31] [S34]

## 14. Embeddings, bucket discovery, and stable assignment

### Normalize once; keep provenance

Construct a short, versioned analysis input from the subject, sender/domain, useful participants, and bounded meaningful text from selected recent messages. A sender domain is context, not a universal category: the same person can send invoices, project updates, and personal messages. Do not embed only a vague subject such as "Following up."

Keep message selection deterministic and include a small amount of conversation context. Filter out drafts, repeated quoted history, common footers, hidden HTML noise, and binary data. Do not strip so aggressively that a request, amount, negation, or deadline disappears. Document normalization assumptions and test them against synthetic fixtures.

Use `text-embedding-3-small` initially with **512 dimensions**, explicitly requested through its dimensions parameter. Store model, dimension, input-pipeline version, and content version with each vector. Validate length, finite numeric values, and nonzero norm. The provider supports reduced dimensions; 512 is Mercury's initial engineering choice, not a claim that it is optimal for every mailbox. [S14]

Do not mix fake and real vectors, different model versions, or different normalization pipelines in one comparison. Changing an embedding model/dimension requires a re-embedding and prototype-rebuild plan, not just editing an environment variable. Preserve user assignments during that migration.

### Initial discovery

For a sufficiently populated mailbox, L2-normalize vectors and evaluate PCA to a small dimension such as `min(32, sample_count - 1, vector_dimensions)` before HDBSCAN. Use deterministic PCA settings. Run HDBSCAN in the worker with bounded memory and one clustering task at a time initially. Starting parameters such as `min_cluster_size=8` and `min_samples=3` are tunable prototype defaults, not calibrated product constants. HDBSCAN supports identifying noise rather than forcing every sample into a cluster. [S15]

For a small or sparse mailbox, avoid fabricating categories from unstable clusters. Suggest exact-sender groupings where useful and let the user create buckets. Keep uncertain threads in Unsorted. Evaluate semantic quality with labeled fixtures and small, consented pilot datasets; do not assume HDBSCAN automatically produces human-meaningful groups.

Choose representative threads deterministically: several near the cluster center plus a small diversity check, excluding obvious duplicates. Use at most five short representative descriptions to request a two-to-four-word name and a one-sentence purpose. Do not submit all raw bodies solely to name a bucket. Store the suggested name; once edited by the user, never rename it automatically.

Proposed buckets are reviewable. Aim for a manageable initial set rather than dozens of tiny categories. Tiny or overlapping suggestions may remain Unsorted or be offered for a user-confirmed merge. Do not silently reorganize an already approved taxonomy.

### Incoming threads

Apply this precedence: manual assignment lock, explicit sender rule, sufficiently strong semantic match, then Unsorted. Compare new vectors against a few representative vectors per bucket, not only a single centroid. This matters when a user merges related but semantically broad groups. Compute prototypes from existing member vectors; do not keep another permanent copy of the text for that purpose.

Use both an absolute similarity threshold and a margin above the next-best bucket. Thresholds are measured on test data, not advertised as probabilities. A cosine score of 0.91 is not "91% sure." Display "Suggested" or "Needs review" instead of a fabricated confidence percentage.

Never recluster the entire mailbox on each new email. Recompute only affected prototypes, and discover possible new groups from Unsorted periodically or on an explicit user request. User moves become locked positive examples; the previous bucket becomes a negative example for that particular thread. Do not infer a permanent sender rule from one move.

### Bucket operations

Rename preserves bucket ID. Archive removes a bucket from active navigation without deleting Gmail messages. Move updates assignment transactionally and schedules label reconciliation when enabled. Merge moves members, rules, and label mappings through a reviewed service operation, preserving manual locks and a sensible primary name. Bulk operations show the affected count and a confirmation when they change many assignments.

For V1, support reversing the most recent bulk move/merge with a small operation record or an explicit preview/cancel flow before committing; do not promise arbitrary historical undo unless it is implemented and tested. Do not delete an existing Gmail label as an incidental result of archiving a Mercury bucket.

## 15. Summaries and possible-action extraction

Keep topic organization and action detection separate. A thread can belong to Finance and have no action; a personal message can require a reply. Cluster membership must not be used as proof that money is due or a response is required.

Use one short model call to produce validated structured output. Initial supported example model: `gpt-4.1-mini`, with a pinned snapshot when the chosen project supports it. The configuration must expose the model name. This is a verified, documented example, not a commitment to a permanently cheapest model. Do not bake a model from an earlier conversational estimate into the architecture without checking current provider support. [S16]

```json
{
  "summary": "The sender asks you to review the revised forecast.",
  "action_required": true,
  "action_type": "review",
  "action_text": "Review the revised forecast and respond.",
  "due_date": null,
  "source_message_id": "an-id-from-the-provided-message-list",
  "uncertain": false
}
```

Validate output using Pydantic or a comparably small schema layer already available through the SDK. Use bounded strings, enumerated action types, optional ISO dates, and a source-message ID drawn only from supplied input. Reject extra fields. A refusal, malformed output, truncation, timeout, or schema failure is an analysis failure/unknown state, not an empty success.

Suggested action types are `none`, `reply`, `review`, `pay`, `schedule`, `read`, and `unknown`. The model may suggest an action; it may not send, pay, browse links, download content, change permissions, or invoke Gmail tools. No tool-calling or web-browsing capability is enabled for summary generation.

Treat all email content as untrusted data, including sentences claiming to be system instructions. Delimit data clearly, instruct the model to ignore embedded instructions, and validate outputs. These precautions reduce risk; the main containment is that the model has no tools, secrets, or cross-account context. Always escape AI-generated strings when rendering.

Do not infer a date from an ambiguous relative phrase without identifying the source timestamp and timezone. Use `null` and uncertainty when unclear. Prefer a short, faithful summary to a confident invented deadline. Payment suggestions should be labeled as claims in the message, not verified obligations.

Include relevant recent outgoing messages so the app can notice that the user may already have replied in Gmail. A model should not reopen a manually handled action solely because an old request remains in the conversation. Tie analysis and handled state to message/content versions; a genuinely new request can be flagged as new.

Initially summarize recent/unread eligible threads and newly active conversations. Other indexed threads can show subject/snippet and receive analysis on an explicit, budgeted request. Opening the original reader never requires a summary to be ready.

Set `store=False` for stateless API requests and do not use persistent conversations, hosted file stores, provider vector stores, fine-tuning, or training-data opt-in. Provider retention still needs disclosure: OpenAI distinguishes application state from abuse-monitoring retention, and disabling response storage is not equivalent to approved zero-data retention. Select and document a provider configuration compatible with Google's applicable data-use restrictions before a public launch. [S17]

## 16. Queue, concurrency, retries, and fault recovery

Use Procrastinate through a small `enqueue_*` adapter. Jobs contain internal IDs, connection generation, content version, and small parameters - not email text, summaries, token bundles, or prompts. Refetch ephemeral text inside the worker when needed. Keep tasks small enough that a retry does not restart an entire account import.

Useful job types are `discover_recent_threads`, `sync_account`, `analyze_thread`, `discover_buckets`, `sync_bucket_labels`, `renew_watches`, and `reconcile_pending_work`. These are task wrappers, not separate microservices. Application services remain callable directly by unit tests.

Use account-scoped locks for synchronization and thread/content-version deduplication for analysis. Use bounded global concurrency and fair scheduling so one large onboarding cannot monopolize the worker. Separate CPU-heavy discovery from parallel I/O logically; do not multiply BLAS threads and exhaust a small container.

Retries use exponential backoff with jitter, provider `Retry-After` where applicable, and a maximum attempt count. Retry timeouts, rate limits, and temporary service errors. Do not retry invalid authorization, a missing user, invalid schema indefinitely, or a permanent validation failure. Expose a safe error code and a retry/reconnect action.

Do not promise exactly-once provider calls. A worker can crash after a provider responds but before a result is saved. Prevent avoidable duplicates with content-version keys, but account for bounded repeat cost in budgets. Commit results only if the connection and content versions still match.

If using the queue library's periodic-task support, run it only in the worker role. Ensure periodic jobs are not duplicated across every web process. Use heartbeat/lease and stalled-job recovery features supported by the pinned queue version; test terminating a worker mid-job. If a library capability differs from an example, adapt the wrapper and document the exact supported behavior rather than silently dropping recovery.

## 17. Web endpoints and interaction contracts

Keep endpoints same-origin and session-authenticated unless explicitly public. HTMX may request HTML partials, but it is never an authorization mechanism. A forged `HX-Request` header grants nothing. Use normal form POSTs with progressive enhancement for essential operations.

| Endpoint family | Purpose | Required controls |
| --- | --- | --- |
| `GET /`, `/privacy`, `/terms`, `/help` | Public product and disclosure pages | No private state; accurate descriptions of processing and retention. |
| `POST /auth/google/start` | Start sign-in | CSRF, finite state lifetime, safe return path. |
| `GET /auth/google/callback` | Complete sign-in | OAuth state/nonce/code validation, no sensitive URL logging. |
| `POST /auth/gmail/start` and its callback | Connect or upgrade Gmail permissions | Logged-in user, CSRF on initiation, bound account identity, explicit purpose. |
| `POST /auth/logout` | End session | CSRF; invalidate relevant session state. |
| `GET /app` and `/app/buckets/<uuid>` | Workspace and scoped thread list | Login, owner filtering, pagination, no-store. |
| `GET /app/threads/<uuid>` and `/body` | Reader shell and original content | Ownership before fetch, finite timeout, escaped text, no-store. |
| `POST /app/threads/<uuid>/move` | Change bucket | CSRF; same-owner source and destination; record manual lock. |
| `POST /app/threads/<uuid>/action` | Mark handled/dismiss/reopen | CSRF; validated enum; affects Mercury only. |
| `POST /app/buckets/...` | Create, rename, archive, merge | CSRF; name/size bounds; preview for bulk changes. |
| `POST /app/rules/...` | Manage exact-sender rules | CSRF; normalized address; owner validation. |
| `POST /app/sync` | Request reconciliation | CSRF; deduplication; account cooldown and operation budget. |
| `GET /app/runs/<uuid>` | Processing progress | Owner-filtered; expose counts and safe codes only. |
| `POST /settings/label-sync` | Enable/disable native labels | CSRF; granted scope; confirmation; operator flag. |
| `POST /settings/disconnect` or `/delete` | Stop processing / remove account | CSRF; fresh auth for deletion; cancel stale jobs; retention policy. |
| `POST /webhooks/google/pubsub` | Provider notification | No browser session; verified provider JWT and durable acceptance. |
| `/admin/...` | Minimal operations | Explicit admin check on every view; fresh auth for changes; no mailbox viewer. |
| `/health/live`, `/health/ready` | Infrastructure probes | Minimal responses; no sensitive debug data. |

A separate public REST API is not a V1 requirement. Add small JSON responses only where useful, such as progress polling; avoid maintaining duplicate HTML and JSON service implementations. Use cursor/keyset pagination or another bounded query strategy. No endpoint returns the entire mailbox.

## 18. Security requirements and threat model

This section defines Mercury's engineering baseline. It is not a claim that these controls alone satisfy every version of Google's assessment framework.

### Authentication, sessions, and CSRF

Enforce CSRF globally with Flask-WTF for state-changing browser requests, including HTMX, JSON, settings, logout, and administrative actions. Send the token in a hidden field or `X-CSRFToken` header. Do not rely only on SameSite cookies. OAuth callbacks use their protocol state protections; do not create a broad CSRF exemption for the auth or API blueprint. Flask-WTF documents the header-based pattern. [S18]

Use Secure, HttpOnly, SameSite=Lax session cookies in production, a host-only cookie with no Domain attribute, finite session lifetime, and no permanent "remember me" token in V1. A production `__Host-` cookie name requires Secure, Path=/, and no Domain. Local HTTP development uses a separate ordinary name and does not disable CSRF.

Set explicit trusted hosts. Trust forwarded headers only for the known ingress topology; configuring `ProxyFix` is not a substitute for understanding how many trusted proxies exist. Reject unsafe return URLs and Host values. Disable Flask debug and the interactive debugger in any network-exposed deployment. Configure request/form size limits. [S19]

### Tenant isolation and authorization

Check ownership before database reads, content fetches, moves, merges, label writes, progress requests, or any expensive provider call. Never authorize based on a UUID being hard to guess. A supplied bucket ID must be checked independently of the source thread. Jobs must load owner/account relationships, not assume trusted queue arguments make them correct.

Administrator access is not permission to browse customer emails. No impersonation, raw token field, SQL console, arbitrary model editor, or mailbox export in V1. Flask-Admin does not supply a complete authorization system by itself; explicitly protect the index and every registered view. [S20]

Use read-only operational views by default. Route state-changing admin controls through the same CSRF-protected FlaskForm/service path as normal application actions. Do not exempt Flask-Admin wholesale to resolve a form incompatibility. If generated ModelView edit forms are introduced, integrate their CSRF mechanism and test it with the selected Flask-WTF configuration. Support a narrowly scoped CSP nonce for library assets when needed rather than allowing arbitrary inline scripts site-wide. [S21]

### XSS, unsafe content, and browser privacy

Never apply Jinja `safe`/Markup to email content, subjects, sender names, AI output, rule text, or bucket names. Render email text through autoescaping. Use a restrictive CSP, no framing, `X-Content-Type-Options: nosniff`, an appropriate Referrer-Policy, and production HSTS after HTTPS is working. Serve scripts/styles locally. Do not fetch remote email images or send read receipts.

Set HTMX `allowEval=false`, `allowScriptTags=false`, `historyCacheSize=0`, and `selfRequestsOnly=true`. Avoid `hx-on`, JavaScript-valued attributes, and unsafe server-returned scripts. Implement the few needed interactions in a local JS file. Disable injected indicator styles when the CSP requires it and define those styles in Mercury's stylesheet. [S02]

### Tokens, secrets, and cryptography

Encrypt stored Google access/refresh tokens with `cryptography` using a documented authenticated-encryption scheme such as Fernet/MultiFernet. Keep keys in Doppler, not in the database, container image, repository, or browser. Store a key version or use a documented key-ring rotation process. Keep old decryption keys until all relevant records and retained backups have been handled. Never invent encryption primitives.

Doppler environment injection makes configuration manageable; it does not prevent a compromised running application from reading its secrets. Database at-rest encryption does not replace token encryption. Do not claim client-side or zero-knowledge encryption. Restrict cloud and Doppler access, rotate credentials, and record procedures for token/key compromise.

### Input boundaries, SSRF, and abuse

Gmail identifiers, form values, and model output are validated against size/type constraints. Use parameterized SQLAlchemy queries. Never execute shell commands derived from message text. Never fetch a URL supplied by an email or ask the model to do so. Provider base URLs are fixed/operator-controlled, not editable user settings.

Enforce atomic per-account limits on expensive operations and AI budget reservations in PostgreSQL. A small `UsageBucket` upsert is sufficient; do not build a general rate-limiting framework. Login/OAuth abuse also needs bounded initiation rates and infrastructure/request-size protections. An in-memory per-process limiter may supplement development or one replica, but is not a correct global production limit across multiple workers. Document what is enforced where.

### Logging and operational access

Log event type, request ID, safe internal IDs, latency, counts, provider status class, and retry number. Never log bodies, subjects, prompts, summaries, tokens, cookies, authorization codes, full callback query strings, or raw exceptions containing provider payloads. Turn off verbose HTTP/client logging. Use sanitized exception classes and restricted log access.

Treat embeddings, snippets, summaries, sender information, and action items as protected Gmail-derived data. Google's policy expressly extends restrictions to derived data; not storing full bodies does not remove these obligations. Limit processing to the disclosed user-facing purpose and do not train a shared/general model on users' mail. [S22]

## 19. Configuration design and dev/prod separation

The companion `config_reference.py` is a concrete, annotated starting point. Its full text is included in Appendix A so this specification can be supplied to an agent on its own. Adapt it into `mercury/config.py`; do not maintain two runtime configurations. It uses standard-library parsing and makes no network requests.

Keep the supported settings understandable. Environment variables are for credentials, environment identity, endpoints, budgets, and a few operational switches. Stable defaults such as the initial vector dimension, cookie policies, MIME bounds, and batch size belong together in code. Do not expose 100 feature switches or allow a production environment variable to turn off tenant checks.

| Group | Required settings / source |
| --- | --- |
| Identity and host | `APP_ENV`, `APP_BASE_URL`, `RELEASE_ID`, `SUPPORT_EMAIL`; chosen by the operator and deployment workflow. |
| Application secrets | `SECRET_KEY`, `TOKEN_ENCRYPTION_KEYS`; generated locally with secure library commands, then stored in Doppler. |
| Database | `DATABASE_URL`; local Compose or the managed PostgreSQL connection details. Use TLS certificate verification in production. |
| Google OAuth | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`; Google Cloud's OAuth Web application client. Callback URLs are derived centrally. |
| Development modes | `AUTH_MODE`, `MAIL_MODE`, `AI_PROVIDER`; explicit real or synthetic implementations. |
| Gmail behavior | `GMAIL_LABEL_WRITES_ENABLED`, `SYNC_MODE`, `SYNC_INTERVAL_SECONDS`; safe defaults, with user consent stored separately. |
| Push notifications | `GOOGLE_PROJECT_ID`, `PUBSUB_TOPIC`, `PUBSUB_SUBSCRIPTION`, `PUBSUB_PUSH_SERVICE_ACCOUNT`, `PUBSUB_AUDIENCE`; only needed for push mode. |
| AI | `OPENAI_API_KEY`, `SUMMARY_MODEL`, `EMBEDDING_MODEL`, `AI_PROCESSING_ENABLED`; one AI account. |
| Cost controls | Per-account/global AI budgets, daily incoming-thread limit, initial indexing cap, lookback window, worker concurrency. |
| Runtime | `LOG_LEVEL`, `PROVIDER_TIMEOUT_SECONDS`, `PROXY_HOPS`, optional exact additional trusted hosts. |
| Deployment bootstrap | `DOPPLER_TOKEN` exists only as a container/bootstrap secret, not as a Flask setting exposed to the application UI. |

### Profiles

**Offline development:** explicit `APP_ENV=development`; synthetic login/mailbox/AI; local PostgreSQL; manual sync; Gmail writes disabled. Development fixture keys are clearly non-secret and allowed only for synthetic data. Bind the dev server and published Compose port to loopback; checking the Host header alone is not adequate protection for a public demo-login route.

**Real-account development:** a separate Doppler development config; Google sign-in; a separate Google test project/client; explicit private developer consent for any AI transfer; non-demo session and encryption keys. Start with label writes disabled and a much smaller import. Use manual or polling sync without a public tunnel. Never connect this environment to the production database.

**Production:** real Google/Gmail/AI adapters, HTTPS, non-demo keys, secure cookies, CSRF, validated hosts, TLS PostgreSQL, and background poll/push synchronization. Missing required values cause startup failure with setting names only. Production must reject dev authentication, fake providers, debugging, and manual-only synchronization. Missing optional push settings should not block a deliberately configured polling deployment.

**Tests:** synthetic providers and disposable PostgreSQL. Keep CSRF enabled in security/integration tests. Tests that deliberately bypass it for a narrow unit concern must not become the default application configuration. Real-provider smoke tests are a separate, opt-in workflow, not part of ordinary CI.

Doppler should inject values before application startup using `doppler run -- <command>`. Use a read-only, config-scoped production service token, not a personal/CLI token. The source of truth is Doppler; application modules never contact its API themselves. Local Docker Compose must explicitly pass needed environment values into each container - invoking Compose under Doppler does not automatically make every parent variable available inside a container. [S23] [S24]

In the simplest production deployment, store the scoped `DOPPLER_TOKEN` as an Azure Container Apps secret and inject it into the entrypoint. Fail closed when production secrets cannot be obtained; do not silently use local fallback files. Disable any persistent fallback mechanism unless its storage, encryption, and recovery behavior are intentionally reviewed. A later Doppler-to-Key-Vault sync is an optional infrastructure improvement, not another custom secrets client to build now. [S33]

The reference config validates static settings only. The coding agent must still implement runtime permission checks, budgets, session rotation, consent enforcement, encryption, and secure headers. No configuration object can enforce those by itself.

## 20. Local development in WSL

Use the Linux filesystem, for example `~/projects/mercury`, instead of making the working repository depend on Windows drive paths. Use LF line endings in scripts, Linux container images, and POSIX commands. Document Docker Desktop's WSL integration or an equivalent working Docker Engine setup; do not mix incompatible Docker daemons.

Use Python 3.12, Poetry, and a checked-in lockfile. Do not introduce a second Python package manager alongside Poetry. Pin a tested PostgreSQL major version supported locally and by the selected Azure plan, plus a compatible pgvector extension. Never use SQLite as a substitute for PostgreSQL tests that cover vectors, constraints, or queue behavior.

The default Compose stack contains `db`, `web`, and `worker`. Web and worker use the same Docker image and codebase with different commands. Mount code for development, but not production. Bind the development web port to `127.0.0.1:5000`; use a non-conflicting local PostgreSQL host port such as 5433. Use the Compose service hostname `db` inside containers, not `localhost`.

### Required developer commands

The coding agent must implement and document these Make targets. They are a requested interface, not commands that already exist in the supplied pack.

```bash
# Zero-cloud synthetic product demo; Docker is the only runtime prerequisite.
make demo

# Doppler-backed development after installing the official CLI (source S35).
doppler login
doppler setup --project mercury --config dev
make bootstrap
make dev

# Normal development operations.
make migrate
make seed-demo
make test
make lint
make security
make logs
make down
```

`make bootstrap` checks tool availability, installs locked dependencies as needed, starts PostgreSQL, applies domain and queue migrations, and creates synthetic fixtures only in a synthetic environment. It does not create a Google project, spend money, or mutate a real mailbox.

`make dev` wraps the local stack in `doppler run` with the documented project/config. `make demo` supplies only explicit synthetic settings without Doppler. Both profiles use the same services, models, migrations, and routes. Do not implement a separate fake frontend that bypasses the real application.

`make test` must run against an isolated test database and refuse a production-looking database target. `make seed-demo` must refuse real Gmail mode and production. `make down` should preserve the local database by default; a destructive reset is a separately named command with confirmation.

Use the official Debian/Ubuntu Doppler installation instructions for WSL and verify `doppler --version` before setup. [S35]

A host-Python workflow may be documented as a secondary convenience, using the same PostgreSQL container and application factory. Do not require developers to maintain two divergent workflows. Unit tests can call application services directly; realistic integration tests run the queue and PostgreSQL path.

### Synthetic fixtures

Provide a small mailbox with shopping, work, banking, newsletters, mixed-topic senders, vague subjects, a conversation with an outgoing reply, a new request after a handled action, and unclassifiable messages. Include malicious HTML, prompt-injection text, malformed MIME, quoted replies, very large content, an expired token, and a deleted thread. All names and content must be invented.

Fake AI returns deterministic structured output and deterministic embeddings with the same dimension contract, clearly marked as fixture outputs. It demonstrates workflow, not real clustering accuracy. Real semantic-quality evaluation is a separate opt-in activity.

## 21. Azure deployment, portability, and maintenance

### Initial production topology

Deploy a single same-origin Flask web app to Azure Container Apps, a separate worker using the same image, and managed PostgreSQL with pgvector. Serve the small frontend's assets from Flask/Gunicorn in V1; a separate static-web hosting service is unnecessary. Use Azure Container Registry for the image and GitHub Actions for CI/CD.

Enable pgvector on the selected managed PostgreSQL server and verify the actual available extension version. Pin a compatible local version. Azure documents extension enablement and vector usage; availability alone is not proof that every extension version or operator behaves identically across providers. [S27]

Start with a web allocation suitable for the measured Flask workload and a worker with enough memory for clustering. Small starting candidates are 0.25 vCPU/0.5 GiB for web and 0.5 vCPU/1 GiB for worker, subject to load testing. Do not set untested memory values as a product guarantee. Keep worker concurrency low and record actual peak memory during onboarding.

For the first reliable deployment, run one worker replica continuously. The web app may scale to zero if the measured cold-start experience is acceptable. **A PostgreSQL queue does not automatically wake a zero-replica worker.** Scale-to-zero workers require a supported event scaler or a separately scheduled finite job; implement and test that trigger before setting the worker minimum to zero. [S25] [S26]

Managed PostgreSQL, registry storage, logs, worker uptime, and network configuration create a baseline bill even when the web app is quiet. Do not repeat a near-zero compute estimate as though it included all these resources.

Use private database connectivity in the production design where supported by the chosen Azure topology. Do not open PostgreSQL to all IPs. If a restricted public endpoint is selected for an early private pilot, document and test the exact egress/firewall model and TLS validation rather than assuming serverless outbound IPs are fixed. The public release needs a reviewed network configuration.

### Docker and release mechanics

Build one non-root runtime image from a pinned Python base, with locked dependencies and local static assets. Do not copy `.env`, keys, database dumps, or a developer's home directory. Use a small entrypoint that obtains injected configuration and `exec`s either Gunicorn or the worker. Do not run `flask run` in production.

Do not build a separate Docker image per environment with secrets embedded. Development mounts source; production uses the immutable built image. Record the Git commit as `RELEASE_ID`.

CI runs formatting/linting, unit/integration/security tests, dependency audit, secret scanning, and a container scan. Build once and deploy the same digest. Use GitHub-to-Azure OIDC with narrowly scoped deployment permissions rather than a long-lived Azure client secret where available.

Run database and queue migrations once as a controlled release job, not on every web replica startup. Prefer additive migrations that allow the old and new code to coexist during rollout. Keep a previous image digest and a documented rollback procedure. A destructive schema migration cannot be safely undone merely by switching back to the prior image.

### Operating responsibilities

Document backups, a restore drill, deletion replay after restore, key rotation, expired Google authorization, worker failure, queue backlog, failed watch renewal, exhausted AI budget, and security incident response. Have alerts for stale sync, repeated authorization failures, database saturation, worker death, and rising error/latency rates. Use existing Azure monitoring; do not add another monitoring account for V1.

### Moving later

A later move to another host reuses the container image, PostgreSQL schema, and provider adapters, but still requires operational work: network/TLS setup, secrets, queue compatibility, extension availability, backups, migration, OAuth redirect URLs, and rollout testing. Do not promise a cloud migration is a one-line change.

Do not build AWS and DigitalOcean infrastructure templates now. Preserve portability by using ordinary containers, PostgreSQL, and environment configuration; implement one deployment well.

## 22. Privacy, retention, disconnect, and deletion

Before connecting Gmail, display a concise description of what Mercury reads, what it stores, which AI provider receives selected text, and how to stop/delete processing. Hosted embeddings are also an AI-provider data transfer, not a privacy-free operation. Record the disclosure version and affirmative consent. If the user declines AI transfer, do not send mail text to an embedding endpoint; offer basic/manual organization or explain the limitation.

Do not claim zero retention by every processor just because Mercury does not retain full bodies. Document selected metadata, summaries, vectors, tokens, operational logs, managed backups, and the provider's actual retention settings. Google's Workspace policy and provider contract must both be reviewed for the chosen data flow. [S17] [S22]

| Data | Mercury retention policy to implement |
| --- | --- |
| Full bodies, raw HTML/MIME, binary content | Ephemeral processing only; excluded from DB, queue, filesystem, browser snapshots, and logs. |
| Selected metadata, summaries, vectors, rules | Retained while connected and needed for the user-facing feature; removed by disconnect/delete policy. |
| OAuth tokens | Encrypted while connected; removed when disconnected/deleted. |
| General operational logs | Short configured retention, initially seven days; content and credentials prohibited. |
| Security/deletion audit | Minimal restricted records with a documented retention, initially 30 days; no email contents. |
| Managed database backups | Configure and disclose a bounded retention, initially seven days if supported by the chosen plan; no claim of instant erasure from backups. |

For V1, make **Disconnect Gmail** stop processing and remove that account's derived mailbox data, not leave a confusing dormant copy. Explain this consequence in the confirmation. Account deletion also removes the Mercury user profile and invalidates sessions. A future reconnect is a new authorization/indexing operation.

Mark the connection disabled/deleting first and increment its generation. Cancel or invalidate pending jobs. Best-effort stop the Gmail watch and revoke the OAuth token, then remove token material and mailbox-derived records. If provider revocation fails, report that the user can also revoke access in Google account settings; do not retain the token indefinitely to keep retrying. The local processing ban is immediate even if an external provider call fails.

Deletion must be idempotent. Workers must not repopulate removed records. Keep only the minimal deletion audit needed for operations. After restoring a backup, replay deletions from a separately retained restricted deletion audit before enabling processing or user traffic. Test this procedure; an old backup must not silently resurrect a deleted mailbox.

Do not silently delete Gmail messages or the user's existing labels during disconnect. Leave Mercury-created labels in Gmail by default and explain that choice. Removing them would be a separate, explicitly confirmed Gmail operation and is not necessary for V1.

## 23. Google verification and assessment readiness

This product processes restricted Gmail data on a server. Plan for OAuth verification and the applicable security assessment before a broad public launch, subject to Google's current applicability rules. Private testing is not an excuse to weaken data handling or an assurance that a commercial unverified app can grow indefinitely. [S05] [S28]

Current official assessment materials describe **AL1/AL2 assurance levels** and annual revalidation. Older documentation and discussions may still use tier terminology. The assigned assessment path comes from Google/the framework user, not from a developer selecting the cheapest label. Do not hard-code an assumed "Tier 2" requirement into launch planning. [S29]

Google's FAQ says Google does not charge an assessment fee; independent assessor pricing is agreed with the developer. Do not represent a previously discussed $500-$1,500 range as an official or dependable quote. Obtain written quotes for Mercury's actual assigned scope and infrastructure, and budget remediation time as well as the assessment. [S30]

### Build the evidence while building the app

Maintain a small `docs/google-review.md` containing the product description, requested-scope justification, data-flow/trust-boundary description, provider/processor list, data inventory, retention/deletion behavior, user-consent screens, token/key management, deployment inventory, and a mapping from applicable assessment requirements to implementation and evidence.

Prepare a demo using a dedicated synthetic/test mailbox that shows sign-in, Gmail consent, organization, original-message viewing, optional label writes, disconnect, and deletion. Have public product/help/privacy pages, domain ownership verification, accurate OAuth branding, and working support contact details. Never place real customer mail in screenshots, test fixtures, or an assessor demo recording.

Maintain dependency/container scan results, authorization/CSRF/XSS test evidence, backup/restore evidence, and remediation tracking. Automated scans support review; they do not replace an assessor's evaluation or prove that Google has approved a use case.

Do not allow a coding agent to check a "Google compliant" checkbox. Completion means the implementation and evidence are ready for the actual review process; approval is a separate external outcome.

## 24. Cost and resource controls

Use provider usage measurements, not message counts alone. Record input/output token totals, embedding tokens, model version, task category, and an internal account identifier without retaining prompt text. Reserve budget atomically before expensive work and reconcile actual usage afterward. Stop new paid analysis when the account or global cap is reached, while leaving already available organization and original-message reading usable.

Separate one-time onboarding limits from ongoing daily-thread limits. A 100-new-threads/day quota should not accidentally make the initial 2,000-thread embedding import take 20 days. Bound onboarding independently, summarize at most a selected recent subset initially, and include it in the same monetary budget.

A pricing example, not a bill guarantee: the documented `gpt-4.1-mini` rates are $0.40 per million input tokens and $1.60 per million output tokens; `text-embedding-3-small` is $0.02 per million input tokens. At 1,000 summary-input tokens, 120 output tokens, and 400 embedding tokens, one fully analyzed thread is approximately **$0.0006**, or **$0.60 per 1,000 threads**. Long conversations, repeated analyses, naming requests, retries, and provider changes alter the result. Recheck rates before launch. [S16] [S32]

Treat roughly **$50-$100/month of initial infrastructure headroom** as a planning target to validate in the Azure calculator, not a quote. AI usage, domain, Doppler plan needs, and assessment costs are separate. If the selected database/network/worker configuration exceeds that target, show the actual estimate before provisioning rather than silently adding more services.

Clustering is CPU work with a real memory/runtime cost. It may fit the existing worker at small scale, but it is not literally free or unlimited. Measure a 2,000-thread discovery run, cap concurrency, and bound database pools across web and worker processes. Avoid a global vector index, background jobs on every request, and repeated embeddings for label-only changes.

## 25. Testing and measurable acceptance criteria

Use pytest for Python tests and a small browser suite such as Playwright for complete flows. Run integration tests against PostgreSQL with pgvector, not SQLite. Ordinary CI uses synthetic providers and blocks unexpected external network calls.

### Required test groups

**Configuration:** missing production keys fail safely; malformed booleans fail rather than turning truthy; demo keys cannot access real Gmail; production rejects fake providers/debug/HTTP/insecure cookies; each optional integration validates only when enabled; overrides cannot disable production CSRF; secrets never appear in error messages.

**Authentication and authorization:** mismatched/replayed/expired OAuth state; wrong audience/subject; partial scope grants; denied consent; missing refresh token preservation; expired/revoked credentials; session invalidation; wrong-account connection; admin denial; cross-user reads, moves, merges, rules, progress, and label-write attempts.

**CSRF and web safety:** missing/invalid tokens fail every mutation path; authenticated webhook is narrowly exempt and still rejects invalid JWTs; external return URLs fail; hostile Host/forwarded headers fail under the documented topology; email/AI/bucket HTML remains escaped; remote images do not load; no browser history/localStorage snapshot contains email content.

**Sync and jobs:** pagination; initial sync racing new mail; duplicate/out-of-order push; transient 429/5xx; expired history marker; label-only updates; multiple messages in a thread; draft exclusion; old connection-generation jobs; crash/restart; failed enqueue after durable DB commit; pending-work reconciliation; no checkpoint advancement before durable acceptance.

**Reader:** text-only/HTML-only/multipart/malformed content; quoted text; large message limits; no attachment endpoint; no Gmail read-state modification; source fidelity; deleted message; timeout; cache headers; Open in Gmail links under multiple signed-in Google accounts.

**AI and buckets:** deterministic input selection; schema rejection; no cross-user context; prompt-injection containment; unknown action fallback; dates not fabricated; version changes mark summaries stale; manual move/name locks survive reclustering; explicit rule priority; merged buckets use representative examples; mixed embedding versions are rejected.

**Privacy and operations:** database and queue contain no full-body fixture markers; logs do not contain seeded secret strings; delete/disconnect during active jobs; encrypted token storage; rotation with old records; backup restoration with deletion replay; exhausted budget pauses AI; admin has no mailbox-content view.

### Product acceptance

From a fresh clone, `make demo` produces the real workspace with synthetic data, not an unrelated mockup. A test user can review buckets, move/rename/merge them, read original text, see a summary, handle an action locally, and open the original Gmail flow when using the real provider. The UI is keyboard-usable and handles small screens.

A list page does not wait for Gmail or AI. Its queries are bounded and indexed. Large indexing requests return a processing reference instead of keeping the browser request open. Set latency targets after measuring the first representative environment; do not invent guaranteed provider latency. No task failure leaves the interface permanently claiming work is progressing.

## 26. Implementation order and exit gates

### Phase 1 - foundation and offline slice

Create the Flask factory, config, extensions, PostgreSQL migrations, synthetic providers, basic user/account model, workspace layout, and safe reader. Add CI and the first authorization/CSRF tests immediately. Exit when a fresh clone can run the core UI without a cloud credential.

### Phase 2 - real Google identity and read-only Gmail

Implement OAuth, encrypted token storage, reconnect handling, ownership enforcement, bounded initial discovery, and on-demand original content. Keep write scopes disabled. Exit when a dedicated test mailbox works and no full body appears in the database or logs.

### Phase 3 - durable processing and AI organization

Implement the queue adapter, worker, progress, normalized inputs, structured AI output, embeddings, initial bucket discovery, manual moves/rules, and budget accounting. Exit when crash/retry and manual-override tests pass and the user can organize mail without knowing the algorithms.

### Phase 4 - continuous sync and optional label writes

Add history synchronization, reconciliation, authenticated push, watch renewal, incremental consent, and the narrow managed-label writer. Exit when label-only changes do not re-trigger AI and missed/out-of-order notifications are recoverable.

### Phase 5 - production and review readiness

Provision the single Azure topology, deploy the same container image, rehearse migrations/rollback/restore/deletion, run security tests/scans, complete documentation, and prepare Google review evidence. Public availability remains gated on the real provider approvals and assessed data-flow requirements.

At each phase, summarize changed files, explain the main design choices in ordinary language, list commands actually run and their results, and identify untested live integrations. Do not claim all phases are finished after generating a skeleton. Do not seek additional products/services unless a concrete requirement cannot reasonably be met with the agreed stack.

## 27. Final handoff and non-negotiables

The coding agent's repository handoff must include a readable README, annotated config, names-only `.env.example`, locked dependencies, migrations, one Docker image, Compose, Make targets, a limited Azure deployment template, synthetic fixtures, tests, and short security/operations/Google-review guides. Include the exact API setup pages needed to obtain keys and the exact registered callback URLs for each environment.

**Do not ship** public demo login, a debugger, plaintext tokens, unrestricted admin CRUD, an unauthenticated webhook, implicit Gmail writes, permissive CORS, arbitrary email HTML rendering, unbounded imports, a fake production AI fallback, user content in logs, or a deletion flow that leaves workers able to recreate the account's data.

**Keep Mercury small:** one Flask application, one worker role, one PostgreSQL database, one AI provider, one Google integration, and one secrets workflow. Add complexity only when a measured problem or required security control justifies it.


## Appendix A. Annotated configuration reference

The following is the same source as the companion `config_reference.py`. Read the preceding requirements before using it: this module validates settings, not runtime authorization or provider behavior.

```python
"""Mercury configuration reference: adapt into mercury/config.py.

Load once inside create_app(), after Doppler injects environment variables.
No SDK calls, secret downloads, or environment reads happen at import time.
Only this module reads deployment environment variables.

Accounts needed: Google Cloud, OpenAI, Doppler, Azure, and GitHub.
The app never needs a Google service-account private key for ordinary Gmail
OAuth or for verifying an authenticated Pub/Sub push.

This is a configuration scaffold, not an implementation of the security
middleware, token encryption, provider adapters, or worker described in the spec.
"""
from __future__ import annotations

import base64
import os
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit


class ConfigError(ValueError):
    """Safe to show at startup: messages name settings, never secret values."""


DEV_SECRET = "mercury-local-fixtures-only-not-a-production-secret"
DEV_TOKEN_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()


def load_config(
    overrides: Mapping[str, Any] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a fresh config for each Flask app instance, then validate it."""
    env = dict(os.environ if environ is None else environ)

    def text(name: str, default: str = "") -> str:
        return env.get(name, default).strip()

    def flag(name: str, default: bool) -> bool:
        value = text(name, "true" if default else "false").lower()
        if value not in {"true", "false", "1", "0", "yes", "no"}:
            raise ConfigError(f"{name} must be true or false")
        return value in {"true", "1", "yes"}

    def integer(name: str, default: int, low: int, high: int) -> int:
        try:
            value = int(text(name, str(default)))
        except ValueError as exc:
            raise ConfigError(f"{name} must be an integer") from exc
        if not low <= value <= high:
            raise ConfigError(f"{name} is outside its allowed range")
        return value

    def money(name: str, default: str) -> Decimal:
        try:
            value = Decimal(text(name, default))
        except InvalidOperation as exc:
            raise ConfigError(f"{name} must be a decimal amount") from exc
        if not value.is_finite() or value < 0:
            raise ConfigError(f"{name} must be finite and non-negative")
        return value

    # CORE: Set APP_ENV explicitly in Doppler; never infer production from DEBUG.
    # Local app: http://localhost:5000. Production: your actual HTTPS domain.
    app_env = text("APP_ENV")
    if app_env not in {"development", "testing", "production"}:
        raise ConfigError("APP_ENV must be development, testing, or production")
    production = app_env == "production"
    base_url = text("APP_BASE_URL", "" if production else "http://localhost:5000")
    base_url = base_url.rstrip("/")
    host = urlsplit(base_url).hostname
    extra_hosts = [v.strip() for v in text("ADDITIONAL_TRUSTED_HOSTS").split(",") if v.strip()]

    # SECRETS: Generate locally and save directly in Doppler's selected config.
    # SECRET_KEY: python -c "import secrets; print(secrets.token_hex(32))"
    # TOKEN_ENCRYPTION_KEYS: poetry run python -c \
    #   "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # For rotation, list newest first, then old keys, separated by commas.
    # Do not use the demo defaults with real Gmail data, even in development.
    secret = text("SECRET_KEY", "" if production else DEV_SECRET)
    token_keys = tuple(v.strip() for v in text(
        "TOKEN_ENCRYPTION_KEYS", "" if production else DEV_TOKEN_KEY
    ).split(",") if v.strip())

    # DATABASE: Local Compose injects its own container hostname URL.
    # Azure: portal.azure.com -> PostgreSQL flexible server -> connection details.
    # Production example (replace values, URL-encode password):
    # postgresql+psycopg://USER:PASSWORD@HOST:5432/mercury?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt
    # The queue DSN is derived centrally from this URL, not a second DB service.
    database_url = text("DATABASE_URL", "" if production else
        "postgresql+psycopg://mercury:mercury_local@localhost:5433/mercury")

    # GOOGLE: console.cloud.google.com -> Google Auth Platform -> Clients.
    # Create a Web application OAuth client in a separate dev/prod project.
    # Register BOTH derived callback URLs below exactly. Enable Gmail API.
    # No client secret may be sent to the browser.
    auth_mode = text("AUTH_MODE", "google" if production else "dev")
    mail_mode = text("MAIL_MODE", "gmail" if production else "fake")
    project = text("GOOGLE_PROJECT_ID")

    # AI: platform.openai.com -> project -> API keys and usage/billing controls.
    # Keep one provider initially. Fake mode needs no key and no network.
    # Model changes require evaluation; embedding changes require re-indexing.
    ai_provider = text("AI_PROVIDER", "openai" if production else "fake")

    # PUB/SUB: same Google project -> Pub/Sub -> topic + authenticated push
    # subscription. Use a dedicated push identity, not a downloaded JSON key.
    # Audience must exactly match what the subscription puts in its OIDC JWT.
    # Local manual/poll mode needs none of these Pub/Sub settings.
    sync_mode = text("SYNC_MODE", "push" if production else "manual")

    config: dict[str, Any] = {
        "APP_ENV": app_env,
        "APP_BASE_URL": base_url,
        "RELEASE_ID": text("RELEASE_ID", "development"),
        "SUPPORT_EMAIL": text("SUPPORT_EMAIL"),
        "DEBUG": flag("DEBUG", False),
        "TESTING": app_env == "testing",
        "SECRET_KEY": secret,
        "TOKEN_ENCRYPTION_KEYS": token_keys,
        "SQLALCHEMY_DATABASE_URI": database_url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "pool_pre_ping": True, "pool_size": 2, "max_overflow": 1,
            "pool_timeout": 10, "pool_recycle": 300,
            "connect_args": {"connect_timeout": 5},
        },
        "AUTH_MODE": auth_mode,
        "MAIL_MODE": mail_mode,
        "GOOGLE_CLIENT_ID": text("GOOGLE_CLIENT_ID"),
        "GOOGLE_CLIENT_SECRET": text("GOOGLE_CLIENT_SECRET"),
        "GOOGLE_LOGIN_REDIRECT_URI": base_url + "/auth/google/callback",
        "GOOGLE_GMAIL_REDIRECT_URI": base_url + "/auth/gmail/callback",
        "GOOGLE_PROJECT_ID": project,
        "GMAIL_LABEL_WRITES_ENABLED": flag("GMAIL_LABEL_WRITES_ENABLED", False),
        "GMAIL_LABEL_PREFIX": "Mercury",
        "SYNC_MODE": sync_mode,
        "SYNC_INTERVAL_SECONDS": integer("SYNC_INTERVAL_SECONDS", 300, 60, 3600),
        "PUBSUB_TOPIC": text("PUBSUB_TOPIC", f"projects/{project}/topics/mercury-mailbox-events" if project else ""),
        "PUBSUB_SUBSCRIPTION": text("PUBSUB_SUBSCRIPTION"),
        "PUBSUB_PUSH_SERVICE_ACCOUNT": text("PUBSUB_PUSH_SERVICE_ACCOUNT"),
        "PUBSUB_AUDIENCE": text("PUBSUB_AUDIENCE", base_url + "/webhooks/google/pubsub"),
        "AI_PROVIDER": ai_provider,
        "AI_PROCESSING_ENABLED": flag("AI_PROCESSING_ENABLED", True),
        "OPENAI_API_KEY": text("OPENAI_API_KEY"),
        "SUMMARY_MODEL": text("SUMMARY_MODEL", "gpt-4.1-mini"),
        "EMBEDDING_MODEL": text("EMBEDDING_MODEL", "text-embedding-3-small"),
        "EMBEDDING_DIMENSIONS": 512,  # Schema/pipeline contract, not a casual env toggle.
        "AI_GLOBAL_MONTHLY_BUDGET_USD": money("AI_GLOBAL_MONTHLY_BUDGET_USD", "50"),
        "AI_ACCOUNT_MONTHLY_BUDGET_USD": money("AI_ACCOUNT_MONTHLY_BUDGET_USD", "3"),
        "AI_ACCOUNT_DAILY_THREAD_LIMIT": integer("AI_ACCOUNT_DAILY_THREAD_LIMIT", 100, 1, 1000),
        "INDEX_MAX_THREADS": integer("INDEX_MAX_THREADS", 2000, 1, 5000),
        "INDEX_LOOKBACK_DAYS": integer("INDEX_LOOKBACK_DAYS", 180, 1, 365),
        "SUMMARY_LOOKBACK_DAYS": 30,
        "SUMMARY_MAX_INPUT_TOKENS": 3000,
        "SUMMARY_MAX_OUTPUT_TOKENS": 220,
        "EMBEDDING_MAX_INPUT_TOKENS": 800,
        "INDEX_BATCH_SIZE": 25,
        "MAX_THREAD_MESSAGES": 20,
        "MAX_READER_BYTES": 2 * 1024 * 1024,
        "MAX_MIME_DEPTH": 12,
        "PROVIDER_TIMEOUT_SECONDS": integer("PROVIDER_TIMEOUT_SECONDS", 20, 5, 60),
        "WORKER_CONCURRENCY": integer("WORKER_CONCURRENCY", 2, 1, 4),
        "LOG_LEVEL": text("LOG_LEVEL", "INFO"),
        # PROXY_HOPS: set only after verifying the actual Azure ingress chain.
        "PROXY_HOPS": integer("PROXY_HOPS", 0, 0, 2),
        "TRUSTED_HOSTS": list(dict.fromkeys(([host] if host else []) + extra_hosts)),
        # Security defaults are code-level invariants, not production off-switches.
        "SESSION_COOKIE_NAME": "__Host-mercury" if production else "mercury-dev",
        "SESSION_COOKIE_SECURE": production,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_DOMAIN": None,
        "SESSION_COOKIE_PATH": "/",
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=8),
        "SESSION_REFRESH_EACH_REQUEST": False,
        "WTF_CSRF_ENABLED": True,
        "WTF_CSRF_TIME_LIMIT": timedelta(hours=1),
        "MAX_CONTENT_LENGTH": 256 * 1024,
        "MAX_FORM_MEMORY_SIZE": 64 * 1024,
        "MAX_FORM_PARTS": 100,
    }
    if overrides:
        config.update(overrides)
    validate_config(config)
    return config


def validate_config(config: Mapping[str, Any]) -> None:
    """Fail early on unsafe combinations without printing credentials."""
    def require(*names: str) -> None:
        for name in names:
            if not config.get(name):
                raise ConfigError(f"{name} is required for the selected mode")

    env = config["APP_ENV"]
    if env not in {"development", "testing", "production"}:
        raise ConfigError("APP_ENV is invalid")
    if config["AUTH_MODE"] not in {"dev", "google"}:
        raise ConfigError("AUTH_MODE is invalid")
    if config["MAIL_MODE"] not in {"fake", "gmail"}:
        raise ConfigError("MAIL_MODE is invalid")
    if config["AI_PROVIDER"] not in {"fake", "openai"}:
        raise ConfigError("AI_PROVIDER is invalid")
    if config["SYNC_MODE"] not in {"manual", "poll", "push"}:
        raise ConfigError("SYNC_MODE is invalid")
    require("SECRET_KEY", "SQLALCHEMY_DATABASE_URI", "TOKEN_ENCRYPTION_KEYS")
    if len(config["SECRET_KEY"]) < 32:
        raise ConfigError("SECRET_KEY must contain at least 32 characters")
    try:
        keys = config["TOKEN_ENCRYPTION_KEYS"]
        if isinstance(keys, str) or not all(
            len(base64.b64decode(k.encode(), altchars=b"-_", validate=True)) == 32
            for k in keys
        ):
            raise ValueError
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ConfigError("TOKEN_ENCRYPTION_KEYS must contain valid Fernet keys") from exc

    origin = urlsplit(config["APP_BASE_URL"])
    if (origin.scheme not in {"http", "https"} or not origin.hostname
            or origin.username or origin.password or origin.query
            or origin.fragment or origin.path):
        raise ConfigError("APP_BASE_URL must be a plain HTTP(S) origin")
    if any("*" in host or "/" in host for host in config["TRUSTED_HOSTS"]):
        raise ConfigError("TRUSTED_HOSTS must contain explicit hostnames")
    if origin.hostname not in config["TRUSTED_HOSTS"]:
        raise ConfigError("TRUSTED_HOSTS must include the configured application host")
    for callback in ("GOOGLE_LOGIN_REDIRECT_URI", "GOOGLE_GMAIL_REDIRECT_URI"):
        target = urlsplit(config[callback])
        if (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
            raise ConfigError(f"{callback} must use APP_BASE_URL")
    db_url = urlsplit(config["SQLALCHEMY_DATABASE_URI"])
    if db_url.scheme != "postgresql+psycopg" or not db_url.hostname:
        raise ConfigError("DATABASE_URL must use postgresql+psycopg")

    if config["AUTH_MODE"] == "google" or config["MAIL_MODE"] == "gmail":
        require("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
    if config["MAIL_MODE"] == "gmail":
        if config["AUTH_MODE"] != "google":
            raise ConfigError("Real Gmail requires Google authentication")
        if config["SECRET_KEY"] == DEV_SECRET or DEV_TOKEN_KEY in config["TOKEN_ENCRYPTION_KEYS"]:
            raise ConfigError("Real Gmail requires non-demo session and encryption keys")
    if config["AI_PROVIDER"] == "openai" and config["AI_PROCESSING_ENABLED"]:
        require("OPENAI_API_KEY", "SUMMARY_MODEL", "EMBEDDING_MODEL")
    if config["SYNC_MODE"] == "push":
        if config["MAIL_MODE"] != "gmail":
            raise ConfigError("Push mode requires real Gmail")
        require("GOOGLE_PROJECT_ID", "PUBSUB_TOPIC", "PUBSUB_SUBSCRIPTION",
                "PUBSUB_PUSH_SERVICE_ACCOUNT", "PUBSUB_AUDIENCE")
        prefix = f"projects/{config['GOOGLE_PROJECT_ID']}/"
        if not config["PUBSUB_TOPIC"].startswith(prefix + "topics/"):
            raise ConfigError("PUBSUB_TOPIC must belong to GOOGLE_PROJECT_ID")
        if not config["PUBSUB_SUBSCRIPTION"].startswith(prefix + "subscriptions/"):
            raise ConfigError("PUBSUB_SUBSCRIPTION must belong to GOOGLE_PROJECT_ID")
    if env == "testing" and (config["MAIL_MODE"] != "fake" or config["AI_PROVIDER"] != "fake"):
        raise ConfigError("Default test mode forbids live Gmail and AI providers")
    if config["AUTH_MODE"] == "dev" and origin.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ConfigError("Development login requires a loopback application origin")
    if env == "production":
        if config["DEBUG"] or config["TESTING"]:
            raise ConfigError("Production forbids DEBUG and TESTING")
        if (config["AUTH_MODE"], config["MAIL_MODE"], config["AI_PROVIDER"]) != ("google", "gmail", "openai"):
            raise ConfigError("Production forbids development providers")
        if origin.scheme != "https" or origin.hostname in {"localhost", "127.0.0.1", "::1"}:
            raise ConfigError("Production requires a non-loopback HTTPS origin")
        if config["SYNC_MODE"] == "manual":
            raise ConfigError("Production requires poll or push synchronization")
        if parse_qs(db_url.query).get("sslmode") != ["verify-full"]:
            raise ConfigError("Production DATABASE_URL requires sslmode=verify-full")
        require("SUPPORT_EMAIL")
        if (not config["SESSION_COOKIE_SECURE"] or not config["SESSION_COOKIE_HTTPONLY"]
                or not config["WTF_CSRF_ENABLED"]
                or config["SESSION_COOKIE_DOMAIN"] is not None
                or config["SESSION_COOKIE_PATH"] != "/"
                or config["SESSION_COOKIE_NAME"] != "__Host-mercury"
                or config["SESSION_COOKIE_SAMESITE"] != "Lax"):
            raise ConfigError("Production session/CSRF settings cannot be weakened")

# DOPPLER_TOKEN is intentionally absent from Flask config. It bootstraps
# `doppler run -- <process>` in production and belongs in an Azure secret.
# Never log it or use a personal Doppler token in a production container.

```

## Appendix B. Official documentation and verification notes

Sources were checked for this specification on September 24, 2026. Provider features, model availability, prices, and review requirements may change. Requirements stated as Mercury design choices are proposed implementation decisions, not vendor guarantees. Follow current official guidance when deploying.

**S01.** [Flask application factories](https://flask.palletsprojects.com/en/stable/patterns/appfactories/).

**S02.** [HTMX documentation and security configuration](https://htmx.org/docs/).

**S03.** [Procrastinate PostgreSQL task queue](https://procrastinate.readthedocs.io/en/stable/index.html).

**S04.** [pgvector project documentation](https://github.com/pgvector/pgvector).

**S05.** [Gmail API scopes and classifications](https://developers.google.com/workspace/gmail/api/auth/scopes).

**S06.** [Gmail threads.modify authorization and behavior](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.threads/modify).

**S07.** [Google OAuth for web-server applications](https://developers.google.com/identity/protocols/oauth2/web-server).

**S08.** [Google OAuth token expiration and testing behavior](https://developers.google.com/identity/protocols/oauth2).

**S09.** [Gmail messages.get and message formats](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get).

**S10.** [Gmail push notifications and watch renewal](https://developers.google.com/workspace/gmail/api/guides/push).

**S11.** [Gmail synchronization and expired history markers](https://developers.google.com/workspace/gmail/api/guides/sync).

**S12.** [Gmail labels and thread/message behavior](https://developers.google.com/workspace/gmail/api/guides/labels).

**S13.** [Google Pub/Sub authenticated push subscriptions](https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions).

**S14.** [OpenAI embeddings and dimensions](https://developers.openai.com/api/docs/guides/embeddings).

**S15.** [scikit-learn HDBSCAN reference](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.HDBSCAN.html).

**S16.** [OpenAI GPT-4.1 mini model, capabilities, and pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

**S17.** [OpenAI API data controls and retention](https://developers.openai.com/api/docs/guides/your-data).

**S18.** [Flask-WTF CSRF protection](https://flask-wtf.readthedocs.io/en/1.2.x/csrf/).

**S19.** [Flask security considerations](https://flask.palletsprojects.com/en/stable/web-security/).

**S20.** [Flask-Admin introduction and authorization](https://flask-admin.readthedocs.io/en/stable/introduction/).

**S21.** [Flask-Admin CSRF and CSP integration](https://flask-admin.readthedocs.io/en/stable/advanced/).

**S22.** [Google Workspace user data and developer policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy).

**S23.** [Doppler service tokens](https://docs.doppler.com/docs/service-tokens).

**S24.** [Doppler with Docker Compose](https://docs.doppler.com/docs/docker-compose).

**S25.** [Azure Container Apps scaling](https://learn.microsoft.com/en-us/azure/container-apps/scale-app).

**S26.** [Azure Container Apps jobs](https://learn.microsoft.com/en-us/azure/container-apps/jobs).

**S27.** [Azure PostgreSQL pgvector support](https://learn.microsoft.com/en-us/azure/postgresql/extensions/how-to-use-pgvector).

**S28.** [Google restricted-scope security assessment](https://support.google.com/cloud/answer/13465431?hl=en).

**S29.** [App Defense Alliance CASA assurance levels](https://appdefensealliance.dev/casa/casa-tiering).

**S30.** [Google verification FAQ and assessment fees](https://support.google.com/cloud/answer/13463817?hl=en).

**S31.** [Gmail thread resource reference](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.threads).

**S32.** [OpenAI text-embedding-3-small pricing](https://developers.openai.com/api/docs/models/text-embedding-3-small).

**S33.** [Optional Doppler to Azure Key Vault synchronization](https://docs.doppler.com/docs/azure-key-vault).

**S34.** [Gmail search-query syntax including rfc822msgid](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.settings.filters).

**S35.** [Doppler CLI installation and local setup](https://docs.doppler.com/docs/install-cli).

**S36.** [Gmail API search filtering and date interpretation](https://developers.google.com/workspace/gmail/api/guides/filtering).

[S01]: https://flask.palletsprojects.com/en/stable/patterns/appfactories/
[S02]: https://htmx.org/docs/
[S03]: https://procrastinate.readthedocs.io/en/stable/index.html
[S04]: https://github.com/pgvector/pgvector
[S05]: https://developers.google.com/workspace/gmail/api/auth/scopes
[S06]: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.threads/modify
[S07]: https://developers.google.com/identity/protocols/oauth2/web-server
[S08]: https://developers.google.com/identity/protocols/oauth2
[S09]: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get
[S10]: https://developers.google.com/workspace/gmail/api/guides/push
[S11]: https://developers.google.com/workspace/gmail/api/guides/sync
[S12]: https://developers.google.com/workspace/gmail/api/guides/labels
[S13]: https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions
[S14]: https://developers.openai.com/api/docs/guides/embeddings
[S15]: https://scikit-learn.org/stable/modules/generated/sklearn.cluster.HDBSCAN.html
[S16]: https://developers.openai.com/api/docs/models/gpt-4.1-mini
[S17]: https://developers.openai.com/api/docs/guides/your-data
[S18]: https://flask-wtf.readthedocs.io/en/1.2.x/csrf/
[S19]: https://flask.palletsprojects.com/en/stable/web-security/
[S20]: https://flask-admin.readthedocs.io/en/stable/introduction/
[S21]: https://flask-admin.readthedocs.io/en/stable/advanced/
[S22]: https://developers.google.com/workspace/workspace-api-user-data-developer-policy
[S23]: https://docs.doppler.com/docs/service-tokens
[S24]: https://docs.doppler.com/docs/docker-compose
[S25]: https://learn.microsoft.com/en-us/azure/container-apps/scale-app
[S26]: https://learn.microsoft.com/en-us/azure/container-apps/jobs
[S27]: https://learn.microsoft.com/en-us/azure/postgresql/extensions/how-to-use-pgvector
[S28]: https://support.google.com/cloud/answer/13465431?hl=en
[S29]: https://appdefensealliance.dev/casa/casa-tiering
[S30]: https://support.google.com/cloud/answer/13463817?hl=en
[S31]: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.threads
[S32]: https://developers.openai.com/api/docs/models/text-embedding-3-small
[S33]: https://docs.doppler.com/docs/azure-key-vault
[S34]: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.settings.filters
[S35]: https://docs.doppler.com/docs/install-cli
[S36]: https://developers.google.com/workspace/gmail/api/guides/filtering
