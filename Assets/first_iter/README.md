# Mercury — first iteration info session

This folder explains how Mercury is built as of **26 September 2026**. It assumes you know
Python and Flask. It does **not** assume you know Docker, background job queues, or how the
frontend is served; those parts start from the basics.

## Reading order

| # | File | What you'll learn |
|---|---|---|
| 1 | [01-what-mercury-is-and-the-stack.md](01-what-mercury-is-and-the-stack.md) | What the app does, every technology in the stack and why it was chosen, the runtime architecture |
| 2 | [02-how-the-code-is-organized.md](02-how-the-code-is-organized.md) | The folder layout, the "route → service → model/integration" pattern, where to find things |
| 3 | [03-database-tables.md](03-database-tables.md) | Every table, why it exists, and what each field tracks |
| 4 | [04-diagrams.md](04-diagrams.md) | User diagram, ER diagram, class diagram, and four sequence diagrams, each explained |
| 5 | [05-docker-explained.md](05-docker-explained.md) | Docker from zero: images, containers, volumes, Compose, and exactly how Mercury uses them |
| 6 | [06-commands-and-workflows.md](06-commands-and-workflows.md) | Every `make` command, what it really runs, and day-to-day workflows |
| 7 | [07-frontend-explained.md](07-frontend-explained.md) | How pages are produced, why there is no frontend build step, how to change the UI |
| 8 | [08-background-jobs.md](08-background-jobs.md) | The worker, the queue, retries, crash recovery, and progress tracking |
| 9 | [09-security-privacy-deployment.md](09-security-privacy-deployment.md) | Security rules, privacy guarantees, secrets (Doppler), CI, and Azure |
| 10 | [10-glossary.md](10-glossary.md) | Short definitions of every term used here |

Diagram sources live in [`diagrams/`](diagrams/) as Mermaid (`.mmd`) text; rendered images live
in [`images/`](images/). To change a diagram, edit the `.mmd` file and re-render it (see the end of
[04-diagrams.md](04-diagrams.md)).

## Mercury in five minutes

- **What it is:** a web app that connects to one Gmail account, groups recent conversations into
  categories ("buckets") you control, writes a short AI summary per conversation, and flags
  possible actions. Gmail stays the source of truth: Mercury never sends, deletes, or archives mail.
- **How it runs:** one Docker image started in two roles: a **web** process (Flask + Gunicorn) that
  serves pages, and a **worker** process (Procrastinate) that does slow work like indexing and AI
  calls. Both share one **PostgreSQL** database, which also holds the job queue and the AI vectors
  (pgvector).
- **How the UI works:** the server renders HTML with Jinja templates. HTMX swaps small HTML
  fragments into the page, and one small JavaScript file adds keyboard shortcuts and dialogs.
  There is no React and no `npm build`.
- **How to try it:** `make demo`, then open <http://localhost:5000>. Everything uses invented
  data, a fake Gmail, and a fake AI, so no accounts or keys are needed.
- **What's real vs. untested:** the whole offline product works and has 82 passing automated tests
  plus a browser test. Real Google sign-in/Gmail, OpenAI, Doppler in production, and Azure are
  implemented but **have never been run against the real services**.

![Runtime architecture](images/architecture.png)

## Known gaps found while writing this

These are true of the code today and are recorded in `handoff.md`:

1. **Automatic bucket suggestions aren't wired up.** The clustering helpers
   (`mercury/buckets/clustering.py`: PCA + HDBSCAN) exist and are unit-tested, but no job calls
   them. The demo gets its buckets from a fixed mapping (`seed_demo_buckets`). A real Gmail user
   starts with everything in **Unsorted** and creates buckets by hand. A `discover_buckets` worker
   task is the missing piece.
2. **Disconnect doesn't revoke the Google OAuth token.** It stops the Gmail watch, deletes the
   encrypted token and all mailbox data, and bumps the connection generation, but it never calls
   Google's token revocation endpoint. The spec asks for a best-effort revoke.
