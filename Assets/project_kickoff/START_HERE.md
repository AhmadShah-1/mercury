# Mercury coding-agent handoff

The primary document is **MERCURY_BUILD_SPEC.md**. It is a self-contained product and engineering specification, including a full annotated configuration example and official source references. The companion Python files are reference scaffolding, not the Mercury application.

## Give your coding agent these files

Supply `MERCURY_BUILD_SPEC.md` and `config_reference.py`. The configuration is also embedded in the master document, so the Markdown document can stand alone. Keep the test file beside the configuration reference to run its checks. `.env.example` lists example inputs without real credentials.

Use this kickoff prompt:

```text
Build Mercury according to MERCURY_BUILD_SPEC.md. Read the entire specification
before changing code. Inspect the current repository and preserve compatible
working conventions. Use Flask, feature-oriented blueprints, Jinja/HTMX,
PostgreSQL/pgvector, Doppler, Docker, and a separate background worker.

Start by giving me a short implementation plan and the folder structure.
Then implement Phase 1 as a working vertical slice with tests, not a large
empty scaffold. Continue in the documented phase order. Keep the code small,
readable, and secure. Do not introduce extra hosted services unless an actual
requirement cannot reasonably be met with the agreed stack.

Use the annotated config reference as a starting point, not as proof that
runtime security is implemented. Keep CSRF and ownership checks active in
normal development. Synthetic providers must make local development usable
without cloud keys; production must fail closed rather than use those fakes.

Do not implement sending, attachments, automatic Gmail deletion/archiving,
billing, an extension, or a chat interface. Do not hard-code unverified provider
prices or claim Google approval. Report the commands you actually ran, test
results, live integrations not yet verified, and the next implementation step.
```

## Reference configuration checks

Run from this folder:

```bash
python -m unittest test_config_reference.py -v
```

The supplied reference passed 26 offline tests covering configuration parsing,
production guards, required credentials, development keys, origin validation,
TLS mode, selected provider modes, and independent app configurations. Those
checks do not constitute application testing, a security audit, or provider
verification. Mercury itself still needs to be built and tested.

## Document roles

`MERCURY_BUILD_SPEC.md` is the authoritative prompt. `config_reference.py` is a
readable configuration starting point. `test_config_reference.py` demonstrates
checks for that starting point. `.env.example` is a reference, not a place to
save real keys. The Word edition is a reading copy of the specification.

No real credentials or private mailbox data are included.
