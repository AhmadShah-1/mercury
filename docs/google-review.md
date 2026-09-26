# Google review evidence checklist

This document prepares evidence; it does not claim Google approval or compliance certification.

## Product and scopes

Mercury organizes one Gmail account belonging to the signed-in Google subject. Sign-in requests `openid email profile`. Read-only connection requests `gmail.readonly`. Optional label application separately requests `gmail.modify`, is operator-disabled by default, and is described honestly as a broader scope even though Mercury implements no sending or deletion.

## Data flow and processors

Document the browser, Flask web role, worker, PostgreSQL/pgvector, Gmail API, OpenAI API, Doppler, and Azure boundaries using `docs/architecture.md`. Record exact Azure resources, regions, production model/project settings, and subprocessors before review.

## Evidence to capture

- Public product, help, privacy, terms, support contact, domain ownership, and OAuth branding.
- Consent screens and scope justification for sign-in, read-only mail, AI transfer, and optional labels.
- Token encryption/rotation, CSRF, ownership, XSS, webhook, deletion, backup/restore, dependency, secret, and container scan results.
- A dedicated synthetic/test-mailbox demo covering connect, organization, reader, Open in Gmail, optional label writes, disconnect, and deletion.
- Current provider retention controls and applicable Google assessment assignment.

Never include customer mail in fixtures, screenshots, logs, or review recordings.

