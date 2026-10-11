# Chat assistant — fix plan (2026-10-03)

**Status:** Steps 1–7 implemented 2026-10-03 in the working tree (record in §7).
Step 0 (read prod logs) was NOT done — it needs the owner's go-ahead. Nothing is
committed or deployed, and **prod's env still has `ASSISTANT_REASONING_EFFORT=high`**
(§7 lists the prod actions).
**Written for:** whoever implements this.
**Covers:** the owner's five complaints — (1) the chat limit is wrong, (2) a failed reply
is always in English, (3) sometimes there is no reply at all, (4) answer common questions
from a stored set and spend fewer tokens, (5) the assistant should sell like a good
salesperson.

---

## 1. Read this before changing anything

1. **Never run anything against production.** Step 0 reads prod logs; that is read-only
   and still needs the owner's go-ahead.
2. Run backend tests from `Backend/`: `venv/Scripts/python.exe -m pytest assistant -q`.
   Two failures in `assistant/tests.py` are known and come from the local
   `.env` (`ASSISTANT_MODEL_CONTEXT_TOKENS=200000`). Any other failure is yours.
3. The 43-case eval in `assistant/eval/` is **scripted** — it tests tools and validators,
   not the model. Steps 5 and 6 change the prompt, so they also need a live run:
   `ASSISTANT_EVAL_LIVE=1` with a working key.
4. Every new customer-facing string goes into all six storefront locale files
   (`en, hi, hinglish, gu, mr, pa`).
5. Chat stays login-only. Escalation to a human stays "only when the customer asks".
6. Keep `Backend/docs/ASSISTANT.md` and `learning/` true in the same change. No route
   changes are planned, so `Backend/docs/API.md` only changes if a response field does.
7. Leave changes uncommitted and undeployed unless the owner says otherwise.

---

## 2. The FAQ file (built first, 2026-10-03)

| File | What it is |
|---|---|
| `Backend/assistant/faq_data.json` | 17 questions, answers in all six languages |
| `Backend/assistant/faq.py` | Loads the file and finds the matching entry. No LLM, no network |
| `Backend/assistant/tools.py`, `prompts.py` | Read tool `search_faq` |
| `Backend/assistant/management/commands/faq_search.py` | `faq_search "question"` and `faq_search --check` |
| `Backend/assistant/management/commands/faq_gaps.py` | Questions customers asked that the file cannot answer |
| `Backend/assistant/tests.py` | FAQ tests |

An entry with a `review` note is never served word for word. **One is still open:**
`payment-methods` — the storefront FAQ page says only "We accept UPI payments"; the file
says "online at checkout, such as UPI, or Cash on Delivery up to ₹5,000". The owner must
list the Razorpay methods that are switched on (D6). The cancellation entry was resolved
with the D5 default (see §7).

---

## 3. What is wrong today

| # | Problem | Cause | Where |
|---|---|---|---|
| P1 | A failed reply is in English whatever language was chosen | The four failure messages are fixed English strings | `assistant/prompts.py` (`FALLBACK_REPLY`, `LOOP_EXHAUSTED_REPLY`, `HONEST_HANDOFF_REPLY`, `CONTINUED_SUFFIX`) |
| P2 | Sometimes no reply | A turn may take 4 rounds × 20 s × 2 attempts = 160 s; the storefront nginx gives up on `/api/` after 60 s. The customer sees "Sorry, something went wrong" and the saved thread has a question with no answer | `agent.py` (`MAX_ITERATIONS`, `LLM_REQUEST_TIMEOUT`, `LLM_MAX_RETRIES`), `Frontend/nidhi-brand-forge/nginx.conf` (`proxy_read_timeout 60s`) |
| P3 | Timeouts are likely on prod | Prod runs `openai/gpt-6-luna` with `ASSISTANT_REASONING_EFFORT=high`. Thinking time counts against the 20 s timeout, and thinking tokens count against the 2,500 output limit, so a reply can come back empty | prod `~/NGU/.env.backend` |
| P4 | Long replies end mid-sentence | `_clean_reply` cuts at 1,500 characters with no notice, although prod allows 2,500 output tokens | `agent.py` `_clean_reply` |
| P5 | Every error looks the same | The widget shows one message for a daily cap (429), a busy turn (429), a timeout (504) and a server error | `AssistantWidget.tsx` `onError` |
| P6 | Staff share the customer cap | The admin assistant uses the same 10/min + 100/day throttle scopes | `views.py` `AdminAssistantChatView` |
| P7 | The tool list is sent twice | Once as text (`TOOL_CATALOGUE`) inside the ~2,100-token system prompt and once as function schemas, on every one of up to 4 calls per turn | `prompts.py`, `tools.py` |
| P8 | The assistant only answers | The prompt describes a helper. Nothing tells it to ask, recommend, or mention free delivery, and it has no tool for either | `prompts.py` `SYSTEM_PROMPT` |

P2 and P3 are read from the code. Step 0 confirms them against real data.

---

## 4. Decisions the owner has to make

Each has a default. The plan uses the default unless told otherwise.

| # | Question | Default |
|---|---|---|
| D1 | Daily messages per customer (100 today) | Keep 100, but make it an env setting (`THROTTLE_ASSISTANT_DAY`) |
| D2 | Reasoning effort on prod (`high` today, set on 2026-10-02) | `low`. It is the main cause of slow and empty replies and the largest token cost |
| D3 | May word-for-word FAQ answers skip the AI? | Yes, for English, Hindi and Hinglish. Gujarati, Marathi and Punjabi keep going to the AI until those answers are written |
| D4 | May the assistant mention a coupon without being asked? | No. Only when the customer asks about offers |
| D5 | Cancelling: "24 hours" or "before shipping"? | "Before shipping" (the policy page). Fix the FAQ page to match |
| D6 | Which payment methods to name | Owner to list what is switched on in Razorpay |

---

## 5. Steps

Order matters: Steps 1–3 are bug fixes and can ship alone. Steps 4–6 build on them.

### Step 0 — Measure (read-only, needs the owner's go-ahead)

On the VM, count why turns ended over the last 14 days. Every assistant message
already stores `meta.reason`:

```bash
docker compose exec -T backend python manage.py shell -c "
from collections import Counter
from django.utils import timezone
from datetime import timedelta
from assistant.models import AssistantMessage as M
qs = M.objects.filter(role='assistant', created_at__gte=timezone.now()-timedelta(days=14))
print(Counter(m.meta.get('reason','?') for m in qs))" < /dev/null
docker logs ngu-backend --since 336h 2>&1 | grep -c "Assistant LLM call failed"
```

Also count customer messages with no assistant message after them — those are the
turns nginx cut off. Read the `edge-caddy` timeouts in `~/edge/Caddyfile`. Write the
numbers at the top of this file; they are the "before" for Steps 2 and 5.

### Step 1 — Failure replies in the customer's language (P1)

1. `prompts.py`: turn the four strings into a dict per language (`en, hi, hinglish, gu,
   mr, pa`) and add `failure_reply(kind, language, message)`.
2. For `language='auto'`, pick by the script of the customer's message: Devanagari →
   `hi`, Gujarati → `gu`, Gurmukhi → `pa`, otherwise `en`.
3. `agent.py`: every place that returns one of the four strings calls `failure_reply`.
   Keep the English constants as the `en` values so existing imports still work.

**Tests** (`assistant/tests.py`): for each language, a provider error, an unparseable
turn, loop exhaustion and a cut-off reply each come back in that language.

### Step 2 — Always a reply, inside the proxy timeout (P2, P3)

1. `agent.py`: add `TURN_BUDGET_SECONDS` (env `ASSISTANT_TURN_BUDGET_SECONDS`, default
   45). Before each round, if the time already spent plus one LLM timeout would pass the
   budget, stop and return the loop-exhausted reply. A turn then always finishes — and
   is always saved — before nginx's 60 s.
2. `LLM_MAX_RETRIES` 1 → 0. A retry of a 20 s timeout is another 20 s the customer waits.
3. An empty reply with `finish == 'length'` means the output limit was spent on
   thinking. Return the failure reply at once instead of nudging the model again.
4. `views.py`: `INFLIGHT_TTL_SECONDS` 180 → budget + 30.
5. Prod env (D2): `ASSISTANT_REASONING_EFFORT=low`.
6. Do **not** raise nginx's timeout. The rule to keep: turn budget < proxy timeout.

**Tests**: a completion that sleeps past the budget returns the failure reply with
reason `loop_exhausted` and saves an assistant message; empty + `length` does not loop.

### Step 3 — Limits (P4, P5, P6, D1)

1. `_clean_reply`: raise the cut to 4,000 characters, cut at the last sentence end, and
   append the (translated) "continued" line when it cuts.
2. `settings.py`: `assistant_day` reads `THROTTLE_ASSISTANT_DAY` (default `100/day`),
   `assistant` reads `THROTTLE_ASSISTANT` (default `10/min`).
3. Admin assistant: its own scopes `admin_assistant` / `admin_assistant_day`.
4. Storefront: `onError` reads the status. Daily cap → "You've reached today's chat
   limit, it resets tomorrow"; per-minute cap and busy turn → "One moment — still
   answering"; anything else → the current message. Six locale files.

**Tests**: a 5,000-character reply is cut at a sentence with the suffix; the admin view
is not throttled by a customer-scope counter.

### Step 4 — Word-for-word FAQ answers with no AI call (D3)

1. `views.py`, both chat views, after the customer message is saved and the thread is
   known not to be handled by a human: call `faq.direct_answer(message, language)`. If
   it returns an answer, skip `Agent` and finalise the turn with
   `reason='faq'`, `llm_used=False`, `sources=[{'tool': 'faq', 'args': {'id': ...}}]`.
2. Language: `auto` uses the script rule from Step 1. For `gu`, `mr`, `pa` skip the
   direct path while those answers are missing.
3. The thread title still gets set on a first turn (`_make_title` logic, moved so it
   does not need an `Agent`).
4. Storefront: four suggested-question chips under the greeting ("Delivery charge?",
   "Cash on Delivery?", "Return policy?", "How long does delivery take?"). Their text
   must match a question in `faq_data.json` exactly, so a tap is a certain hit. A test
   reads the locale files and asserts each chip gets a direct answer.
5. `faq_gaps` management command: list customer questions from the last N days where
   `search_faq` was called and matched nothing. That is the owner's list of answers
   still to write.
6. Write the Gujarati, Marathi and Punjabi answers, then drop the skip in point 2.

**Tests**: a direct hit makes no LLM call (the completion stub is never invoked) and
saves an assistant message; a follow-up like "aur COD par?" goes to the model; a paused
thread never gets an FAQ answer.

### Step 5 — Fewer tokens per turn (P7)

1. Remove `TOOL_CATALOGUE` from `SYSTEM_PROMPT`. Move the guidance the schemas lack
   (ask for the pack size, call several lookups in one step, prefer `cart_proposal`)
   into the schema descriptions in `tools.py` or two short prompt lines.
2. Print the estimated prompt size before and after (`_estimate_tokens`) and record it
   here. The freed tokens become thread memory automatically (`budget` in `Agent.run`).
3. Check what `search_products` and `browse_products` return per hit and drop fields
   the model never uses; cap `browse_products` at 8 rows unless asked for more.
4. Keep the system prompt identical for every customer and every turn (the language
   line stays last). The provider caches a repeated prompt prefix, so anything
   per-customer placed before it would undo that.
5. Run the scripted eval and one live eval. Compare against Step 0's numbers.

### Step 6 — Salesperson behaviour (P8, D4)

1. Two tool changes:
   - `get_cart` also returns `subtotal` and `free_delivery_gap` (how much more reaches
     free delivery, from `limits.FREE_SHIPPING_THRESHOLD`; 0 when already free).
   - new read tool `get_recommendations(slug)`: goes-with items for a product, or
     bestsellers with no slug. Reuse `products/recommendations.py`. Public fields and
     boolean `in_stock` only, as in the other catalogue tools.
2. New prompt section, replacing the passive wording:
   - Ask one question when the need is vague ("what are you cooking?").
   - Recommend one specific product and pack size, with the price, and say why.
   - After an item is confirmed, suggest **one** thing that goes with it.
   - When the cart is below free delivery, say how much more is needed, once.
   - Offer checkout when the customer sounds finished.
   - Never: invent a claim, a rating or a stock shortage; repeat a suggestion the
     customer declined; mention a coupon unless asked (D4).
3. Greeting text in the six locale files, written as a shop assistant, not a help desk.
4. Add eval cases to `assistant/eval/cases.py` (vague need → a question; item confirmed
   → one cross-sell; cart ₹420 → mentions ₹79 to free delivery; "no thanks" → no repeat)
   and run them live.

### Step 7 — Docs and deploy

1. `Backend/docs/ASSISTANT.md` (limits, failure replies, FAQ direct path, sales
   section), `learning/` wherever it quotes these numbers, `CLAUDE.md`, `.env.example`.
2. Prod env: `ASSISTANT_REASONING_EFFORT`, `ASSISTANT_TURN_BUDGET_SECONDS`. Back the
   file up first.
3. Rebuild the backend image (Steps 1–6) and the storefront image (Steps 3, 4, 6).
   No migration is needed by Steps 1–7 themselves; the later context-management work
   (§7) adds `assistant/0005`.
4. After deploy, repeat Step 0's counts a week later.

---

## 6. Not in this plan

- Real streaming (the SSE endpoint chunks a finished reply; the storefront does not use it).
- An FAQ editor in the admin panel. The file is the store for now; if the owner wants
  to edit answers without a deploy, move the entries to a table and keep `faq.py`'s
  matching unchanged.
- Changing the model.

---

## 7. Implementation record (2026-10-03)

Decisions D1–D6 were taken at their defaults (the owner said "implement everything").

| Step | Done | Where |
|---|---|---|
| 0 Measure | **Not done** — reads prod; needs the owner's go-ahead | — |
| 1 Failure replies in the customer's language | ✅ six languages × five kinds; `lang.py` detects the language for `auto` | `prompts.py`, `lang.py`, `agent.py` |
| 2 Always a reply, inside the proxy timeout | ✅ `ASSISTANT_TURN_BUDGET_SECONDS=45`, retries 0, new `slow` reply, empty+`length` answers at once, in-flight TTL = budget + 30 | `agent.py`, `views.py` |
| 3 Limits | ✅ cut at 4,000 chars at a sentence end; caps are env (`THROTTLE_ASSISTANT[_DAY]`); staff chat has its own scopes; 429s are named; widget shows daily vs busy messages | `agent.py`, `views.py`, `throttles.py`, `settings.py`, `AssistantWidget.tsx`, six locale files |
| 4 FAQ with no model call | ✅ `views._faq_result` before the agent in both chat views; four suggested-question chips; `faq_gaps`; Gujarati/Marathi/Punjabi answers written, plus typed phrasings for each entry | `views.py`, `faq*.py`, `AssistantWidget.tsx` |
| 5 Fewer tokens | ✅ tool list removed from the prompt; image URLs dropped from search hits; prompt trimmed | `prompts.py`, `tools.py` |
| 6 Selling | ✅ SELLING section; `get_cart.free_delivery_gap`; `get_recommendations`; greeting rewritten; 7 eval cases | `prompts.py`, `tools.py`, `eval/cases.py`, locales |
| 7 Docs | ✅ `ASSISTANT.md`, `API.md`, `CLAUDE.md`, `.env.example`, `learning/` (HLD, kit, lesson 10) | — |

**Measured (estimated tokens, same estimator the agent uses), customer prompt + tool
schemas per model call:** 4,122 → 3,543 (−14%, ≈1,700 over a three-round message). The
first attempt saved only 21 tokens because the richer schema text and the two new tools
cancelled the removed catalogue — the descriptions were trimmed until the saving was real.
History room grew from ≈4,900 to ≈5,900 tokens (≈30–35 messages).

**Tests:** assistant suite 358 passed, 2 failed — the same two `.env`-caused failures as
before (`assistant/tests.py`, the chat-limits section: local `.env` pins `ASSISTANT_MODEL_CONTEXT_TOKENS=200000`).
Scripted eval 50/50 (43 old + 7 new), no false escalations. Storefront type-checks.
Full backend suite: 1,790 passed, 8 skipped, 4 failed — exactly the known four (the two
`.env` ones above and `orders/test_concurrency.py` G4/G5, SQLite cannot do row locking).
Not run: a browser check of the widget, a live-model eval.

### Decisions taken at their default — change these if the owner disagrees

- **D5:** cancelling is "any time before shipping". The storefront FAQ page text was edited
  in all six locales to say so (it said "within 24 hours"). Revert that and the
  `cancel-order` entry together if the owner wants 24 hours.
- **D3:** word-for-word FAQ answers are on for all six languages.
- **D1:** daily cap stays 100, now an env setting.
- **D4:** the assistant mentions coupons only when asked.

### Still to do — needs the owner, not code

1. **Prod env** (`~/NGU/.env.backend`, back it up first): `ASSISTANT_REASONING_EFFORT=low`
   (D2), add `ASSISTANT_TURN_BUDGET_SECONDS=45`. Recreate `backend` + `scheduler`.
2. **Rebuild and deploy** the backend and storefront images. ⚠ The later context-management
   work adds migration `assistant/0005` (summary columns + a message index; additive) — run
   `migrate` as in the CLAUDE.md deploy recipe, after `./pg_backup.sh`.
3. **D6:** name the payment methods switched on in Razorpay, then delete the `review` line
   from the `payment-methods` entry.
4. **Step 0:** with the owner's go-ahead, count `meta.reason` over 14 days on the VM
   (command in Step 0) and write the before/after here.
5. **Live eval:** `ASSISTANT_EVAL_LIVE=1 pytest assistant/tests.py -k "sell or faq"` with
   a working `LLM_API_KEY` — the only way to see whether the model actually sells well.
6. Have a native speaker read the Gujarati, Marathi and Punjabi FAQ answers and failure
   replies (written by the assistant, not reviewed by a person).
