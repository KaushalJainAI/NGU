# 11 — A Conversation Is a Budget

> Source: `Backend/assistant/agent.py` (`estimate_tokens`, `Agent.run`),
> `Backend/assistant/compaction.py`, `Backend/assistant/views.py` (`load_history`)
> Built: 2026-10-03 · Tests: `Backend/assistant/tests.py` (sections chat_limits, compaction)

---

## The problem

The chat assistant "remembers" a conversation by sending it to the model again on
every message. The model has no memory of its own. So a long chat means a long prompt,
and a long prompt costs money and time on every single call (a message can make up to
four calls).

The first design was a **budget**: send the newest messages that fit in about 6,000
estimated tokens and drop the rest. That is cheap and safe, but it forgets. A customer
who said "no chilli, it is for a toddler" in message 2 is asked again in message 30.

---

## Four ideas

### 1. Count in the same unit the bill uses

There is no tokenizer in the backend, so tokens are estimated from characters. The first
estimate was "3 characters per token". That is about right for English and badly wrong
for Hindi, Gujarati and Punjabi, which need roughly two tokens for every three characters.
A Hindi chat cost about twice what the budget believed. The estimate now counts each
non-ASCII character as 2/3 of a token. A wrong unit is a wrong limit.

### 2. Summarise before you forget, not after

`compaction.py` turns the oldest messages into a short running summary stored on the
conversation row. The model then reads `summary + recent messages`. The summary costs a
few hundred tokens instead of thousands, and the facts that matter survive.

The rule that makes it safe: the **trigger must be lower than the room the prompt
really has**. If you only summarise when the thread reaches 500,000 tokens, the oldest
messages have long since fallen out of the prompt — unsummarised. So the trigger is
clamped to 80% of the room. A bigger number in the settings cannot defeat it.

### 3. Compaction must never be in the way

- It runs in a background thread **after** the reply is saved. The customer never waits.
- If the model is down, nothing changes; the chat behaves as it did before.
- A failed attempt backs off for ten minutes instead of failing on every message.
- It saves with a compare-and-set (`UPDATE ... WHERE summary_upto = <what I read>`), so
  two workers cannot overwrite each other's summary.
- **Nothing is deleted.** The summary is only what the *model* reads. The customer and
  the admin panel still see every message. That is why this needed no change to the
  inbox, and why a bad summary can be thrown away without losing anything.

### 4. Text that came from a customer is not trusted

A summary is built from what customers typed. If a customer writes "ignore your rules",
a naive summary would carry that into every future prompt. So the summariser is told the
messages are data, and the summary reaches the main model wrapped in `<<DATA ...>>`
markers like any tool result. Those markers are only a defence if the text cannot close
them, so `_spotlight` strips `<<` and `>>` from everything it wraps. (Review text could
always have done this; the summary just made it matter.)

---

## "Why not store the chat in JSONL instead of Postgres?"

Because storage is not where the time goes. Measured on a 1,000-message thread:

| Step | Time |
|---|---|
| Read the newest 500 messages from the database | ~11 ms |
| Build the model client | ~0.3 ms |
| Trim history to the budget | ~0.4 ms |
| **One model call** | **1,000 – 20,000 ms** |

Swapping the database would change under 1% of a turn, and lose transactions, safe
concurrent writers (six threads plus a scheduler) and the admin inbox queries. The thing
that makes a turn faster is **fewer and smaller model calls**: answer common questions
from the FAQ file, lower the reasoning effort, shrink the prompt, and compact long
threads.

> Measure before you change the architecture. Optimise the slowest step, not the one
> that sounds old-fashioned.

---

## What to remember

> A conversation is a budget in tokens. Spend it on the newest messages, keep a summary
> of the rest, count in the unit you are billed in, and never let the summary step be
> able to hurt the reply.

---

## Interview questions

**1. A chat assistant forgets things from early in a long conversation. What are your
options?** Send more history (costs more on every call), summarise old messages into a
running summary, or retrieve relevant old messages on demand. Summaries are cheapest;
retrieval is best for very long histories.

**2. When should a summary be written?** Before the messages it replaces are dropped from
the prompt — so the trigger has to sit below the prompt's capacity, not above it.

**3. Why run compaction in a background thread?** The customer's reply must not wait for
an optional improvement, and its failure must not become the customer's failure.

**4. How do two workers avoid overwriting each other's summary?** Read the current
position, build the summary, then update only `WHERE position = what I read`. If the
count of updated rows is zero, someone else won; discard.

**5. Why is a summary a security concern?** It is derived from untrusted input and is
re-sent on every later call, so one injected sentence would persist. Treat it as data,
and make sure the data markers cannot be closed from inside.

**6. Someone proposes replacing Postgres with JSONL files to speed things up. What do you
do?** Profile first. If the database is ~11 ms of a multi-second turn, the change cannot
matter, and it gives up concurrency, transactions and queries.
