# Security baseline

- Flask-WTF CSRF applies to every browser mutation. Only the Pub/Sub push endpoint is exempt, and it authenticates a Google-signed OIDC token plus audience, identity, subscription, and payload.
- Sessions contain only identity/generation and OAuth flow references. Tokens are MultiFernet-encrypted in PostgreSQL; the newest key encrypts and older keys remain for controlled rotation.
- Every mailbox lookup scopes by `user_id`; source and destination resources are checked independently. Unknown and foreign UUIDs both return 404.
- Production uses Secure, HttpOnly, SameSite=Lax, host-only `__Host-mercury` cookies, explicit trusted hosts, bounded requests, a restrictive CSP, no framing, `nosniff`, no referrer, and HSTS.
- No template marks email, AI, sender, rule, or bucket strings safe. HTMX evaluation, script tags, cross-origin requests, and history snapshots are disabled.
- Logs may contain event types, request IDs, internal IDs, counts, latency, status class, and retry number. They must not contain subjects, bodies, snippets, prompts, summaries, cookies, tokens, authorization codes, or raw provider payloads.
- The Gmail production adapter exposes no send, draft, delete, trash, attachment-download, or settings methods.

Security tests are evidence, not a certification. Review Google Workspace policy and the AI processor's data controls (OpenAI, or Azure OpenAI's abuse-monitoring retention and deployment data zone) for the actual production account before public use.

