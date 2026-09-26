# Architecture

Mercury is one Flask codebase with two roles and one PostgreSQL database. The web role serves Jinja/HTMX pages, performs ownership checks, and handles bounded on-demand reads. Procrastinate runs in a separate worker using the same image. Provider SDK payloads are normalized under `mercury/integrations`; routes and templates do not import them.

Trust boundaries are browser-to-Flask, Flask/worker-to-Gmail, Flask/worker-to-OpenAI, and both roles-to-PostgreSQL. Doppler injects environment variables before startup; the app never calls the Doppler API. Production refuses fake authentication, mail, AI, debug mode, HTTP origins, manual-only sync, insecure cookies, missing TLS database verification, and missing provider configuration.

Gmail remains authoritative for messages, labels, conversation membership, and unread state. Mercury owns buckets, assignments, summaries, possible actions, and processing state. Queue payloads contain internal identifiers and versions, never bodies, prompts, tokens, or summaries.

The reader fetches a bounded provider thread, prefers plain text, converts HTML to text without external requests, discards attachments/binaries, renders through Jinja autoescaping, and sets `Cache-Control: no-store, private`.

