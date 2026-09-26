# Mercury repository guardrails

- Preserve the phase order and scope limits in `Assets/project_kickoff/MERCURY_BUILD_SPEC.md`.
- Never persist message bodies, raw MIME, OAuth plaintext, prompts, or provider payloads.
- Every mailbox query and mutation must establish ownership before provider work.
- Keep CSRF enabled in normal development and integration/security tests.
- Production must fail closed when real providers or secrets are unavailable.
- Do not add sending, attachments, Gmail deletion/archiving, billing, chat, or extra hosted services.

