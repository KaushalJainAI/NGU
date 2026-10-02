# Lessons — real problems from building NGU

Each file is one thing that went wrong, or nearly did, in this project: what
happened, why, how it was fixed, and the general idea to take away. Every one
ends with interview questions and short answers.

Back to the [learning index](../README.md).

---

## Files

| # | File | The idea | Key topics |
|---|---|---|---|
| 01 | [When a config value changes meaning](01_when_a_config_value_changes_meaning.md) | Rename a setting when its meaning changes | rollout order, additive vs breaking changes, warn vs crash |
| 02 | [Build-time vs runtime config](02_build_time_vs_runtime_config.md) | A frontend bundle has no environment | Vite `VITE_*` values, `config.js` at container start, relative API URL, one owner per value |
| 03 | [The CRLF entrypoint outage](03_the_crlf_entrypoint_outage.md) | Try the image before you switch to it | exit code 127, line endings, `.gitattributes`, defence in depth, rollback |
| 04 | [A boot guard and the whole API](04_a_boot_guard_and_the_whole_api.md) | A start-up check turns a config mistake into an outage | fail fast, safe defaults, compatibility fallbacks, planning a rollout |
| 05 | [Invoice numbers are not order ids](05_invoice_numbers_are_not_order_ids.md) | A document is issued once and stored | gap-free sequences, row locks, snapshots, credit notes, savepoints |
| 06 | [Restocking exactly once](06_restocking_exactly_once.md) | An effect with several triggers must be safe to repeat | idempotency, undo mirrors do, restoring from a snapshot |
| 07 | [An AI assistant that fails politely](07_an_ai_assistant_that_fails_politely.md) | Design the failure before the feature | timeouts, bounded loops, reason codes, honest messages, cost limits |
| 08 | [`return` inside a transaction commits](08_return_inside_a_transaction_commits.md) | Only an exception rolls back | `transaction.atomic`, validate-then-write, raising to refuse, savepoints |
| 09 | [One repository from three](09_one_repository_from_three.md) | Repository boundaries should match how code changes | monorepo vs polyrepo, merging histories, `.gitignore`, secrets before the first commit |

---

## How to use these notes

- Read the **symptom** and stop. Try to guess the cause before reading on.
- Open the file named under "Source" and find the code the lesson talks about.
- Answer the interview questions out loud, then compare.
- Each lesson has one sentence in a quote box. That is the part to remember.

---

## Topics by interview category

### Configuration and deploys
- A setting that changes meaning (01)
- Build time, container start, process start, per request: when is a value read? (02)
- Relative vs absolute API URLs and same-origin cookies (02)
- Line endings and why a script was "not found" (03)
- Smoke-testing an image; keeping a rollback tag (03)
- Fail-fast checks and what they do to a rollout (04)
- When to warn and when to refuse to start (01, 04)

### Data correctness
- Technical ids vs business numbers (05)
- Gap-free sequences under concurrency (05)
- Snapshots: freezing what a document said (05, 06)
- Idempotent effects with a timestamp guard (06)
- Undoing from the record, not from the current state (06)
- A partial refund returns the whole order's stock: a known simplification (06)

### Transactions (Django / Postgres)
- What commits and what rolls back (08)
- Validate first, write last (08)
- Raising to refuse inside a transaction (08)
- Savepoints, and "current transaction is aborted" (05, 08)

### AI features
- A model call is a slow outside service (07)
- Bounding rounds, time, tokens and requests (07)
- Reason codes: our failure vs the user needs help (07)
- Text sent with a tool call is not the answer (07)
- Scripted tests vs live model tests (07)

### Git and repository hygiene
- Monorepo vs polyrepo (09)
- Merging unrelated histories under a folder prefix (09)
- What belongs in `.gitignore` (09)
- Finding secrets before the first commit (09)
