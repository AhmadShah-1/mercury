# Architecture

Mercury is one Flask codebase with two roles and one PostgreSQL database. The web role serves Jinja/HTMX pages, performs ownership checks, and handles bounded on-demand reads. Procrastinate runs in a separate worker using the same image. Provider SDK payloads are normalized under `mercury/integrations`; routes and templates do not import them.

Trust boundaries are browser-to-Flask, Flask/worker-to-Gmail, Flask/worker-to-OpenAI, and both roles-to-PostgreSQL. Doppler injects environment variables before startup; the app never calls the Doppler API. Production refuses fake authentication, mail, AI, debug mode, HTTP origins, manual-only sync, insecure cookies, missing TLS database verification, and missing provider configuration.

Gmail remains authoritative for messages, labels, conversation membership, and unread state. Mercury owns buckets, assignments, summaries, possible actions, and processing state. Queue payloads contain internal identifiers and versions, never bodies, prompts, tokens, or summaries.

The reader fetches a bounded provider thread, prefers plain text, converts HTML to text without external requests, discards attachments/binaries, renders through Jinja autoescaping, and sets `Cache-Control: no-store, private`.

## Automatic organization

After each analysis step the worker runs one organization pass per account, under the account lock ([`mercury/buckets/organize.py`](../mercury/buckets/organize.py)). It reuses stored embeddings, so the only AI calls are bucket naming, which is budgeted.

1. **Prune.** A thread Mercury placed goes back to Unsorted when its similarity to its bucket's nearest other members falls below `BUCKET_KEEP_MIN`. A bucket where more than half the members miss is left alone, since that points to a miscalibrated threshold.
2. **Split.** A bucket that has grown since its last check is re-clustered. A clearly separate topic (group centroids below `BUCKET_SPLIT_MAX_SIMILARITY`) becomes a new bucket recorded with `split_from_id`. The part holding the user's own placements keeps the original bucket. A topic split off a bucket the user put in a crate joins that crate. Buckets from the retired destructive merge (`merged_at` set) are never split. This is automatic by product decision, which goes beyond the spec's reviewable-suggestion default.
3. **Classify.** Unplaced threads join the one bucket whose nearest members they match above `BUCKET_MATCH_MIN` and by at least `BUCKET_MATCH_MARGIN` over the runner-up. Otherwise they stay in Unsorted.
4. **Discover.** Remaining unplaced threads are clustered into new suggestions. Only members that clear the match bar join; loose ones stay in Unsorted.
5. **Name.** Each bucket has a user-facing `name`/`purpose` and Mercury's own `ai_name`/`ai_purpose`, which only the program writes. They are refreshed after a split or substantial growth. The display name follows `ai_name` until the user renames the bucket.

6. **Crate.** Mercury files its own suggested buckets with fewer than 15 conversations (`MISC_MAX_MEMBERS`) into the account's Misc crate, and takes one back out once it reaches 15. Each bucket is judged once (`crate_origin = 'auto'`), so a bucket that shrinks again is not refiled. A bucket the user created or placed (`crate_origin = 'user'`) is never moved; the SQL guard makes a concurrent user placement win.

Manual moves and sender rules always take precedence: every write is guarded in SQL by `origin = 'model' AND NOT locked_by_user`, so a concurrent user move wins. Everything is keyed by bucket ID, so renames never break placements, crates, or rules.

## Crates

A crate ([`mercury/buckets/crates.py`](../mercury/buckets/crates.py)) is a user-arranged group of buckets, one level deep. It replaced the destructive bucket merge. A crate never owns conversations: every thread keeps exactly one bucket, so grouping, regrouping, and ungrouping never change a placement, a sender rule, a Gmail label, or the examples Mercury classifies against. The crate view lists all of its active buckets' conversations as one list and can narrow to one member. Every account has one Misc crate (a partial unique index enforces it); Misc can be renamed or emptied but not deleted. A user crate is deleted when its last bucket leaves. `buckets.crate_id` is a composite foreign key to `(crates.id, user_id, gmail_account_id)`, so a bucket can only sit in a crate of the same owner and mailbox.

Favorites are independent flags on buckets and crates; favoriting a crate never favorites its buckets. Each sidebar section (Crates above Buckets) shows its favorites, or its three largest items until something of that kind is favorited. The Organize view (`/app/organize`) shows only crates and buckets, with drag-and-drop, and every drag action also has a plain form for keyboard and no-JS use.

