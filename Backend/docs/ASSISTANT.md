# Unified Chat & AI Assistant System

The `assistant` app is the single source of truth for all customer conversations —
AI-driven shopping help, voice ordering, and human admin support all live in the
same thread. The old `support.ChatSession` order-scoped chat system has been
removed entirely; there is no separate support chat anymore.

## Architecture

```
Frontend widget (text or voice input)
      │
      │  POST /api/assistant/chat/
      │  { message, conversation_id, language }
      ▼
AssistantChatView          ← trust boundary: injects authenticated user
      │
      ├── _get_or_create_conversation()
      │     loads existing thread (G1 isolation) or creates a new one
      │
      ├── _load_history()
      │     recent turns that fit the token budget — roles: user | assistant | admin
      │     (admin messages are included so the LLM knows a human has joined)
      │
      ▼
Agent.run(message, history, language)
      │
      ├── _complete(messages)   ← LLM call with bound functions (native tool
      │         │                   calling; several calls per round allowed)
      │    turn { content?, tool_calls[], finish }
      │         │
      ├── each call in READ_TOOLS?
      │     yes → run_read_tool(name, user, args) (user injected by view, G1)
      │            └─ result wrapped in <<DATA>> spotlighting
      │            └─ appended to messages, loop continues (max 4 iterations)
      │
      ├── each call in ACTION_BUILDERS?
      │     yes → build_action(name, user, args) → validated proposal recorded
      │            (first valid wins); escalate_to_human sets escalate
      │
      └── plain-text content reached → return { reply, proposed_action, sources,
                                         escalate, title, reason }
                                         │
                              title: server-side from the opening message, first
                              turn only, auto-saves to conversation.title
                              escalate: ONLY on explicit escalate_to_human
                              (reason customer_asked) → needs_human = True +
                              immediate owner email. Failures/exhaustion never
                              escalate (reasons llm_error / loop_exhausted).
```

The loop is bounded to **MAX_ITERATIONS = 4** tool rounds per turn (AP9: one
round may carry SEVERAL calls — "haldi, jeera, dhaniya" resolves in one turn)
**and by a time budget** (`ASSISTANT_TURN_BUDGET_SECONDS`, default 45 — see
"Turn budget" below).

**Before the agent runs at all**, the view tries the FAQ file
(`views._faq_result` → `faq.direct_answer`): a near-exact match on a common shop
question is answered word for word with NO model call (`reason 'faq'`,
`llm_used False`). Anything doubtful goes on to the agent as usual.

---

## Data Model

### `AssistantConversation`

One thread per customer session. A customer can have many threads and switch between them.

| Field | Type | Notes |
|-------|------|-------|
| `conversation_id` | UUID | Public identifier sent to clients |
| `user` | FK (nullable) | Nullable in schema, but always set — chat is login-only |
| `anon_session` | CharField | **Vestigial** — leftover from a removed anonymous-chat design; unused |
| `title` | CharField(80) | Auto-set server-side from the opening message on first turn (AP9; no LLM round); editable |
| `status` | CharField | `active` / `resolved` / `archived` |
| `needs_human` | BooleanField | True when AI escalates or admin flags it |
| `assigned_to` | FK → User (nullable) | Admin who owns this thread |
| `summary` | TextField | Rolling summary of the thread's OLD part, written by `compaction.py`; what the model reads in place of messages that no longer fit (never shown as a message) |
| `summary_upto` | BigInteger (nullable) | Id of the newest message folded into `summary`; the prompt carries the summary plus only messages after this id |
| `summary_updated_at` | DateTimeField (nullable) | When the summary last changed |
| `created_at` | DateTimeField | |
| `updated_at` | DateTimeField | |

### `AssistantMessage`

One row per turn. Roles: `user` / `assistant` / `tool` / `system` / `admin`.

| Field | Type | Notes |
|-------|------|-------|
| `conversation` | FK | Parent thread |
| `role` | CharField | `user` \| `assistant` \| `tool` \| `system` \| `admin` |
| `content` | TextField | Message body |
| `sender_name` | CharField(100) | Display name — set for `admin` role (e.g. "Kaushal"), blank otherwise |
| `meta` | JSONField | Audit trail: sources, proposed_action, escalate flag, llm_used |
| `created_at` | DateTimeField | |

---

## API Endpoints

### Customer-facing

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| `POST` | `/api/assistant/chat/` | **Required** (login-only) | Send a message; AI responds |
| `POST` | `/api/assistant/chat/stream/` | **Required** (login-only) | Same turn, SSE-delivered (`meta` → `reply` chunks → `done`) — AP10b |
| `GET` | `/api/assistant/conversations/` | Required | List the authenticated user's threads |
| `POST` | `/api/assistant/conversations/` | Required | Create a new empty thread |
| `GET` | `/api/assistant/conversations/{id}/messages/` | Required | Full message history for one thread (assistant messages carry their saved `proposed_action` — AP10b) |

### Admin-facing (`IsAdminUser`)

| Method | URL | Description |
|--------|-----|-------------|
| `GET` | `/api/assistant/conversations/admin/` | All threads; filter by `needs_human`, `status`, `user`, date |
| `POST` | `/api/assistant/conversations/{id}/admin-reply/` | Insert an admin message; clears `needs_human` |
| `PATCH` | `/api/assistant/conversations/{id}/` | Update `status`, `assigned_to` |
| `POST` | `/api/assistant/admin-chat/` | **Admin business-data assistant** — a separate store-manager persona (see below) |

#### Admin business assistant (`POST /api/assistant/admin-chat/`)

A distinct assistant persona for the store owner/admin, separate from the customer
chat. It is **stateless by design**: the admin panel keeps the short conversation in
the browser and posts the recent history each turn, so these chats are never persisted
as `AssistantConversation`s. `Agent(request.user, persona='admin')` runs with a
**read-only** reporting toolset (`assistant/admin_tools.py → ADMIN_READ_TOOLS`) that
aggregates across all customers and orders — it has no action/cart tools. Gated by
`IsAdminUser` **and** the persona.

| Admin tool | Reports |
|------------|---------|
| `sales_summary` | Revenue / orders / units / AOV for a period |
| `count_orders` | Order counts by status/period |
| `list_recent_orders` | Latest orders with customer + status |
| `low_stock_products` | Products at/under their `low_stock_threshold` |
| `top_products` | Best sellers by revenue for a period |
| `product_stock` | Stock level for a named product |
| `find_customer` | Look up a customer (orders, total spent) — contact masked unless `include_contact` (AP8/S11) |
| `search_report` | Top search terms + zero-result ("not found") searches |

Customer tools added in AP10: size-aware `search_products` (per-variant rows) and
`add_to_cart` (`variant_id`); multi-line `cart_proposal`; `edit_cart`;
`get_offers`, `get_delivery_info` (live limits), `get_tracking` (own orders);
`get_policy` answered from `assistant/policies.py` (static-page source, AP10 —
no longer the retired Policy table). Behaviour contract is locked by
the last section of `assistant/tests.py` (50 scripted cases + summary: completion,
median ms/turn, false-escalation rate).

#### `POST /api/assistant/chat/` Request / Response

```json
// Request
{
  "message": "Do you have haldi?",
  "conversation_id": "uuid-or-omit-for-new",
  "language": "hi"
}

// Response
{
  "reply": "हाँ! हमारे पास Nidhi Haldi Powder है…",
  "conversation_id": "abc123...",
  "proposed_action": null,
  "sources": [{ "tool": "search_products", "args": { "query": "haldi" } }]
}
```

#### `GET /api/assistant/conversations/` Response

```json
[
  {
    "conversation_id": "abc123...",
    "title": "Haldi powder order query",
    "status": "active",
    "needs_human": false,
    "last_message": "Anything else you'd like?",
    "updated_at": "2026-06-21T10:32:00Z"
  }
]
```

#### `POST /api/assistant/conversations/{id}/admin-reply/` Request

```json
{ "message": "Let me check that order for you right away." }
```

---

## Security Guardrails

| Guard | What it does |
|-------|-------------|
| **G1 — user isolation** | No tool accepts a `user_id`/email argument. Every user-scoped read is hard-filtered by the authenticated user from the view. Admin endpoints verified via `IsAdminUser`. |
| **G2 — public fields only** | Tool serializers expose a whitelisted subset of fields. No cost prices, margins, supplier data, or internal flags. |
| **G3 — closed registry + spotlighting** | Only names in `ALL_TOOL_NAMES` can be called. Retrieved data wrapped in `<<DATA source=…>>…<</DATA>>` markers. |
| **G4 — bounded loop + degrade** | Max 4 iterations inside a 45 s turn budget; `ASSISTANT_MAX_OUTPUT_TOKENS` output tokens; no retry. LLM unavailable → the canned `fallback` reply, in the customer's language. |
| **G5 — quantity clamp** | Add-to-cart proposals clamped to 10 units max. |
| **G6 — navigation allowlist** | `navigate` only returns routes from a hardcoded static set or verified slugs. No open redirect. |

---

## Tool Registry

### READ_TOOLS — executed server-side, result fed back to LLM

| Tool | Auth | Description |
|------|------|-------------|
| `search_products` | No | Fuzzy text search products and combos |
| `browse_products` | No | Structured catalogue browse/filter (category, price range, spice_form, on_offer, in_stock, sort, limit) over products + combos |
| `get_product_details` | No | Full detail for one product/combo by slug |
| `get_product_reviews` | No | Rating summary + recent public reviews for one product/combo (public review fields only) |
| `list_categories` | No | All active categories |
| `get_policy` | No | Shipping or return policy content (long; `search_faq` first) |
| `get_recommendations` | No | What to suggest next: with a product slug, items bought in the same orders (cancelled/unpaid orders excluded), topped up from the same shelf; without one, bestsellers. In-stock products only, public fields, each with pack sizes. Used for the "suggest ONE matching item" sales rule |
| `search_faq` | No | Short ready answers to common shop questions, from `assistant/faq_data.json` (see "FAQ file" below) |
| `get_order_status` | Yes | Status of a single order (authenticated user's own) |
| `get_order_details` | Yes | Line items of one of the user's orders (for "what was in X" / reorder) |
| `list_my_orders` | Yes | The authenticated user's recent orders (number, status, date, total) |
| `get_cart` | Yes | Authenticated user's current cart: items, `total`, `free_above` and `free_delivery_gap` (rupees still needed for free delivery, 0 = free; read live from `limits.FREE_SHIPPING_THRESHOLD`) |

All user-scoped tools (`get_order_*`, `list_my_orders`, `get_cart`) are hard-filtered
by the authenticated user from the view (G1). No tool accepts a user identifier, so
the model has no way to request another customer's orders, cart, or reviews. Catalogue
and review tools expose only public, whitelisted fields (G2) — no cost prices, margins,
stock counts, supplier data, or reviewer emails.

### ACTION_BUILDERS — return `proposed_action`; UI confirms before acting

| Action | Auth | Description |
|--------|------|-------------|
| `add_to_cart` | Yes | Propose adding a product/variant (one item per turn) |
| `checkout` | Yes | Propose navigating to checkout |
| `navigate` | No | Return a verified in-app route |
| `escalate_to_human` | No | Set `needs_human=True`; admin sees thread highlighted |

### FAQ file (`assistant/faq_data.json` + `assistant/faq.py`)

The questions a shop hears every day (delivery time, COD, returns, bills) have fixed
answers. They live in a plain JSON file, and `faq.py` finds the entry that matches the
customer's wording. Matching is fuzzy string comparison (rapidfuzz) — **no LLM call, no
network, no tokens.**

- **One entry** = `id`, `questions` (every way of asking it, in any of the six
  languages), `answer` (`en` / `hi` / `hinglish` / `gu` / `mr` / `pa`), `route`
  (an allowlisted page or `null`), `direct`, and an optional `review` note.
  The `search_faq` tool falls back to the English answer for a language an entry
  lacks (the model then translates); the word-for-word path does not — it answers
  only in a language the entry has.
- **Numbers are placeholders, never typed in.** `{free_above}`, `{delivery_fee}`,
  `{fee_net}`, `{tax_rate}`, `{cod_max}`, `{cod_open}`, `{phone}`, `{email}` are filled
  from `spices_backend/limits.py` and settings when the file loads, so the FAQ cannot
  disagree with checkout. A test fails if `499`, `69.62` or `5000` is typed into an answer.
- **Scoring**: both sides are lower-cased, stripped of punctuation and filler words
  ("what is", "kya hai"), then compared; the score (0–100) is the average of rapidfuzz
  `token_set_ratio` and `token_sort_ratio`, taking the best of the entry's questions.
- **`faq.search(query)`** — used by the `search_faq` tool. Returns up to 3 entries
  scoring ≥ 62. The model reads them as DATA and decides whether one fits.
- **`faq.direct_answer(query, language)`** — an answer that may be given word for word
  with no model call. Needs score ≥ 88, a lead of ≥ 8 over the next entry, at least two
  meaningful words, `direct: true`, no `review` note, and an answer in the customer's
  language. **Called by both chat views before the agent** (`views._run_turn`).
  A tap on a storefront suggested-question chip is an exact match by design: the
  four chips (`assistant.chipDelivery`, `chipDeliveryTime`, `chipCod`, `chipReturns`
  in every locale file) are worded like questions in the file, and
  `assistant/tests.py::TestStorefrontChips` fails if one stops matching.
  What it does NOT answer: anything order-specific (`track-order` is `direct: false`),
  single words ("delivery"), a follow-up that needs the thread, "I want a human".
- **Finding what to write next**: `python manage.py faq_gaps [--days N]` lists
  the `search_faq` queries of the last N days that still match nothing, most frequent
  first.
- The file is read once per process, so **an edit needs a backend restart**. A broken
  file is logged and the FAQ switches itself off; the assistant keeps working.
- After editing: `python manage.py faq_search --check` (every question must find its
  own entry) and `python manage.py faq_search "your question"`.

---

## Selling (the system prompt's SELLING section)

The assistant is written as a counter salesperson, helpful first and never pushy.
The rules live in `prompts.SYSTEM_PROMPT`; the two facts they need come from tools,
never from the model's memory:

| Rule | Tool it reads |
|------|---------------|
| A vague need → ask ONE question, or recommend one product with size, price, reason | `search_products`, `browse_products` |
| After an item is confirmed → suggest ONE matching item, not a list | `get_recommendations(slug)` |
| Cart under the free-delivery line → say once how much more, name one item that covers it; at 0, say it is free | `get_cart` → `free_delivery_gap` |
| Customer sounds done → offer checkout | `checkout` proposal |
| Coupon codes → only when the customer asks about offers | `get_offers` |

Never: invented claims, ratings, discounts, stock shortages or urgency; suggesting
an out-of-stock item; repeating a suggestion the customer declined. ⚠ The scripted
eval (`assistant/eval/cases.py`, `sell-*` cases) only checks the tool wiring. Whether
the MODEL follows these rules is checked by running it live:
`ASSISTANT_EVAL_LIVE=1 pytest assistant/tests.py -k sell` with a working key.

---

## Voice Ordering

Voice input is transcribed server-side, not by the browser. The old Web Speech API
was unreliable — Chrome/Edge-only, and weak on Hindi/Hinglish and regional
languages, which is exactly our customer base.

**Flow:**

```
Mic -> MediaRecorder (browser) -> 16 kHz mono WAV
    -> POST /api/assistant/transcribe/  (multipart: audio, language)
    -> assistant/stt.py  -> dispatches on STT_PROVIDER
         voxtral  -> OpenRouter /v1/audio/transcriptions (default)
         whisper  -> local whisper.cpp container (fallback)
    -> { transcript, language }
    -> POST /api/assistant/chat/  (identical to typed text)
```

### Two backends

| | `voxtral` (default) | `whisper` (fallback) |
|---|---|---|
| Model | `mistralai/voxtral-mini-transcribe` via OpenRouter | whisper.cpp `small-q5`, self-hosted |
| Latency | **~1.1s** for a ~5s utterance | **~20s per second of audio** on the 2 vCPU box |
| Cost | $0.003/min of audio, prorated to the second (~Rs 0.026 per utterance) | free |
| Audio leaves our infra | yes (OpenRouter -> Mistral) | no |
| RAM | none | 1 GB container limit |

`STT_PROVIDER` picks the primary. When it is `voxtral` and
`STT_FALLBACK_TO_WHISPER` is on (default), an unavailable Voxtral — OpenRouter
outage, exhausted credit limit, missing key — retries on the local container, so
voice degrades to slow-but-working rather than failing. Set it to `False` where
the whisper container is not deployed; the fallback would only add latency before
the same 503.

Voxtral reuses the assistant's `LLM_API_KEY` unless `OPENROUTER_API_KEY` is set
separately. **Prefer a separate key in production** so transcription and chat do
not share a failure domain or a credit limit.

- **Frontend:** `useVoiceInput` records with `MediaRecorder` (works in all browsers,
  incl. Firefox/Safari), converts to 16 kHz mono WAV client-side (`lib/audio.ts`),
  and uploads it. Nothing here is backend-specific — OpenRouter accepts WAV, and
  keeping the conversion means the whisper fallback stays usable (it needs no
  ffmpeg build). No frontend change was needed to switch backends.
- **Backend:** `AssistantTranscribeView` (login-only, tighter `assistant_stt`
  throttle, 8 MB cap) calls `stt.transcribe`. It never touches the LLM and
  persists nothing — it just returns text. The per-request cost OpenRouter reports
  is logged at DEBUG and deliberately **not** returned: that is our billing data,
  and this response goes straight to the browser.
- **whisper.cpp container:** `whisper/Dockerfile` builds the server with the `small`
  model quantized to q5_1 (~180 MB disk, ~400 MB resident). Runs internal-only on
  `ngu-network`, 1 GB limit.

### Accuracy notes

1. **Forced language** — the UI language selector is passed through (`hinglish`->`hi`).
   Forcing the language beats autodetect, especially on the small whisper model.
   WARNING: the two backends disagree on how to say "detect it". whisper.cpp needs
   the literal `'auto'` (omitting the field makes it assume English), while
   OpenRouter **422s on `'auto'`** and autodetects only when the field is *absent*.
   `stt.py` resolves to `'auto'` and each client translates from there — see
   `test_voxtral_omits_language_when_unknown`.
2. **Domain prompt** — `stt.DOMAIN_PROMPT` primes the decoder with catalogue
   vocabulary (haldi, jeera, garam masala, "add to cart", ...). WARNING: **this
   works on whisper.cpp but appears to be a no-op on Voxtral.** OpenRouter documents
   `prompt` as "accepted but ignored on most providers", and a side-by-side probe
   returned byte-identical text with and without it — including transcribing
   "kasuri methi" as "kajari methi" either way. We still send it (free, harmless,
   may start being honoured), but Voxtral's accuracy advantage comes from the model
   itself, not from biasing. Near-miss spice names are absorbed downstream by the
   search tool's fuzzy/synonym matching rather than fixed at transcription time.

**Config / degradation:** `USE_SELF_HOSTED_STT` gates the endpoint as a whole (503
when off, so the frontend simply behaves as if voice is unavailable — the name
predates there being a hosted option). If every configured backend is unreachable
the endpoint returns 503 and the frontend drops the recording silently.

The system prompt enforces a structured ordering arc for voice sessions:
1. Search for the item → confirm name + price in the reply
2. Propose `add_to_cart` for one item at a time (never silently)
3. Ask "Anything else?" after each addition
4. Propose checkout when the customer is done

---

## Three-Party Conversation

Every thread can have three participant types:

| Role | Who | Rendered as |
|------|-----|-------------|
| `user` | Customer (typed or voice) | Right-aligned bubble |
| `assistant` | Nidhi AI | Left-aligned, bot icon |
| `admin` | Admin team member | Left-aligned, distinct color, name shown |

When the LLM encounters `admin` messages in history, it acknowledges the handoff
and defers cart actions to the admin.

Admins post into any thread via `POST …/admin-reply/`. The message is stored as
`AssistantMessage(role='admin', sender_name=<admin display name>)` and becomes
part of the thread history the customer sees and the LLM reads.

---

## Authentication (login-only)

The chat endpoint is **login-only** — `ChatView.permission_classes = [IsAuthenticated]`.
The entire assistant (shopping Q&A, voice, human-admin support) is gated behind login
by design; there is no anonymous chat.

> **Vestigial `anon_session`.** `AssistantConversation.user` is nullable and an
> `anon_session` CharField plus a guest-lookup branch still exist in the code — a
> leftover from an earlier anonymous-chat design. Because the view never admits
> unauthenticated requests, `user` is always set and that guest path is dead. Don't
> "fix" the endpoint to `AllowAny`; the login gate is intentional. (Cart/order tools
> also carry their own per-tool auth guard as defence-in-depth, but it never fires
> for anonymous callers since none reach the agent.)

## Human Escalation (`needs_human`)

`needs_human=True` is set on the conversation ONLY when the model calls the
`escalate_to_human` function — i.e. the customer explicitly asked for a human
(AP9/A4; `reason == 'customer_asked'`). Provider failures, unparseable output
and loop exhaustion return friendly fallbacks with `escalate=False` and never
flag the thread. On escalation the owner is emailed at once
(`ADMIN_ALERT_EMAIL`, thread id + last message) — the flag no longer waits for
the morning digest. The customer sees an honest line ("flagged for our team —
they usually reply within a day"), and a reply cut off by the output limit
gets a "…(continued — ask me to continue)" suffix instead of an escalation.

It is **cleared automatically** when an admin posts a reply to the thread
(`POST …/admin-reply/`), signalling that a human is now engaged.

In the admin panel, threads with `needs_human=True` appear highlighted and can be filtered
with `?needs_human=true`. A sidebar badge shows the count of threads needing attention.

## Message Role Visibility

| Role | Visible to customer | Visible to admin | Sent to LLM |
|------|--------------------|--------------------|-------------|
| `user` | Yes | Yes | Yes |
| `assistant` | Yes | Yes | Yes |
| `admin` | Yes | Yes | Yes |
| `tool` | No | Yes | Yes (as observation) |
| `system` | No | No | Yes (as system prompt) |

`tool` and `system` messages are filtered out of customer-facing responses. The LLM
receives the full history including tool observations.

## Conversation Persistence & Thread Management

- All messages are persisted immediately on every turn (user + AI + admin + tool)
- A customer can have unlimited threads; the frontend lists them sorted by `updated_at`
- **Token-budgeted history**: the thread is remembered as far back as fits under a
  token budget rather than a fixed message count. History is trimmed newest-first
  until the estimated prompt size reaches the ceiling, then older turns are dropped.
  - Tokens are estimated from characters (`CHARS_PER_TOKEN = 3`, deliberately
    over-counting English so the estimate stays under the real limit).
   - `MODEL_CONTEXT_TOKENS` (env `ASSISTANT_MODEL_CONTEXT_TOKENS`, default `12000`,
     AP7c) is the hard ceiling — a turn's prompt can never exceed it.
   - `MAX_OUTPUT_TOKENS` (1000, AP9) and `TOOL_OBS_RESERVE_TOKENS` (4000) are reserved out
     of the ceiling so appended `<<DATA>>` tool observations across the loop can't
     overflow the window mid-turn.
  - The view loads at most `MAX_HISTORY_MESSAGES = 500` rows from the DB before the
    agent token-trims them, bounding the queryset on a runaway thread.
  - Older turns beyond the budget stay in the DB for the full audit trail / UI
    history; they are just not sent to the LLM.
  - **The drop is reported, not silent.** When any turn is trimmed, `Agent.run`
    returns `history_truncated: True` and both chat views echo it as
    `history_truncated` in the JSON response. The storefront widget then shows a
    persistent amber notice + a one-click "Start a new chat" button
    (`assistant.contextFull` / `assistant.contextFullCta`, all six locales).
    Rationale: past that point the assistant answers without the earliest part of
    the thread, so the customer must know its memory of this chat is now partial.
    The flag is per-thread — it clears on switching threads or starting a new one.
- **Human handoff (AI pause)**: the moment an admin replies into a thread, the AI
  stops answering it. This is enforced state, not a prompt instruction — the chat
  view short-circuits *before* the LLM call, so a handed-off thread also costs
  zero tokens.
  - `AssistantConversation.ai_paused_at` / `ai_paused_by` are stamped by
    `AdminConversationReplyView`. Every admin reply restarts the clock.
  - `is_ai_paused` is a **computed property**, never a stored bool, so the
    auto-release takes effect on read without a scheduler tick.
  - Auto-release: `ASSISTANT_HANDOFF_IDLE_HOURS` (default `12`). Without it an
    admin who replies at 11pm and goes to bed leaves *nobody* answering — worse
    than the AI talking over a human. Set `0` to disable (sticky forever).
  - Manual release: admin PATCHes `{"ai_paused": false}` ("Hand back to AI" in the
    panel), or resolves/archives the thread, which releases it implicitly.
  - While paused, a customer message is **still persisted** and re-raises
    `needs_human` — silence must never mean a lost message. The chat response is
    `{reply: '', ai_paused: true, handled_by: '<admin name>'}` and the storefront
    shows a "team member is helping you" banner plus an 8s poll of the open thread
    (the AI produces no turns during a handoff, so without the poll the chat
    would look dead until the widget was reopened).
  - `needs_human` is cleared on an admin reply (they just answered) and re-set by
    the customer's next message.
- `MAX_ITERATIONS = 4` — the agent loop runs at most 4 tool rounds per turn;
  exhaustion returns a friendly "try fewer items" reply (`reason loop_exhausted`),
  never a human flag. Running out of TIME returns the `slow` reply, same reason.
- Thread title is derived server-side from the opening message on the first turn
  and stored on `AssistantConversation.title`
- `status` lifecycle: `active` → `resolved` (admin action) → `archived`
- `needs_human=True` highlights the thread in the admin dashboard

---

## Admin Dashboard Integration

The admin panel polls `GET /api/assistant/conversations/admin/` every 5 seconds
when a thread is open. Filters available: `needs_human=true`, `status`, `user_id`,
date range. Unread/needs-attention count shown as a badge in the sidebar.

---

## Multilingual Replies

The `language` field (`en`, `hi`, `hinglish`, `gu`, `mr`, `pa`, or `auto`) controls
the final reply language only. Tool names/args and all DB content always stay
in English.

**Replies no model wrote are translated too.** The failure replies (`fallback`,
`loop`, `slow`, `handoff`, and the `continued` line) live in
`prompts.FAILURE_REPLIES` for all six languages, picked by `prompts.failure_reply`.
For `auto` the language is detected from the message's script (`assistant/lang.py`):
Devanagari → Hindi, Gujarati script → Gujarati, Gurmukhi → Punjabi, Roman text with
two or more common Hindi words → Hinglish, otherwise English. Devanagari cannot
separate Hindi from Marathi, so a Marathi customer must have picked Marathi (the
storefront sends the site language with the suggested-question chips for this
reason). The same detection chooses the language of FAQ answers.

---

## Context management

What the model reads on every turn, in order:

```
system prompt (~1,100 tokens, identical for every customer)  +  language line
summary of the thread's older part          (only once the thread is long; DATA)
messages after the summary, newest that fit (token-budgeted)
the new message
```

plus the tool schemas (~2,400 tokens) that the provider receives separately and the
budget below does NOT count: the real prompt is the ceiling plus the schemas.

**Token estimate** (`agent.estimate_tokens`, no tokenizer): Latin text is 3 characters
per token (over-counts English on purpose); every non-ASCII character counts 2/3 of a
token, because Hindi/Gujarati/Punjabi tokenize at roughly 1-2 characters per token. At a
flat 3 per character a Hindi thread cost about twice what the budget thought.

**Budget** (`Agent.run`): `ASSISTANT_MODEL_CONTEXT_TOKENS` - `ASSISTANT_MAX_OUTPUT_TOKENS`
- `ASSISTANT_TOOL_OBS_RESERVE_TOKENS`, less the system prompt, the new message and the
summary. Messages are added newest-first until it is spent. About 5,900 tokens of history
at the defaults (and on prod: 13,500 - 2,500 - 4,000). The ceiling is a COST guard, not the
model's window. `history_truncated` (and the storefront's "start a new chat" notice)
now means only: messages that were NOT covered by the summary were dropped.

### Auto-compaction (`assistant/compaction.py`)

Before: a long thread silently lost its oldest messages. A customer who said "no chilli,
it is for a toddler" at the start was asked again 30 messages later.

Now, after each turn is saved, a background thread checks the thread:

1. Count the estimated tokens of the messages after `summary_upto`. If they exceed the
   trigger (`ASSISTANT_COMPACT_AFTER_TOKENS`, default 4,500, **clamped to 80% of the
   prompt's real room for history**), go on.
2. Keep the newest `ASSISTANT_COMPACT_KEEP_TOKENS` (2,000) word for word - never fewer than
   the latest exchange - and fold everything older (at most ~12,000 tokens per call; the
   rest waits for the next run) into the summary with one small model call: temperature 0,
   reasoning effort `ASSISTANT_SUMMARY_REASONING_EFFORT` (`low`), the old summary as input,
   cut to `ASSISTANT_SUMMARY_MAX_TOKENS` (700).
3. Save with a compare-and-set on `summary_upto`, so two workers cannot overwrite each other.

Properties worth knowing:

- **No message is deleted or hidden.** The customer and the admin panel still see the whole
  thread. The summary is only what the model reads.
- **It never slows or breaks a reply.** The reply is saved first; the check, and the model
  call, run in a daemon thread. If the model is down or slow, nothing changes (the thread
  behaves as it did before) and it backs off for 10 minutes. One summariser per thread
  (cache lock).
- **The summary is untrusted text.** It is built from customer messages, so it reaches the
  model wrapped as DATA like a tool result, the summariser is told the messages are data, and
  `_spotlight` strips `<<` / `>>` so nothing can close the block early.
- **Cost:** one extra small call per compaction, at most once every ~15 customer messages,
  against the 4,500 tokens it stops being re-sent on every later call.
- Off switch: `ASSISTANT_COMPACT_ENABLED=0`.
- Not covered: the staff chat (`persona='admin'`) is stateless and never summarised.

**Why the trigger is not 500,000 tokens.** The model is only ever shown ~6,000 tokens of
history, so a trigger of 500,000 would never be reached in practice: a thread of that size is
about 1,500 full-length messages, the loader reads only the newest 500, and long before then the
oldest messages would have fallen out of the prompt UNSUMMARISED. The trigger has to sit below
what the prompt can hold, which is why it is clamped. Sending 500,000 tokens per call instead
would cost ~80x more per call (up to 4 calls per message) and take far longer than the 45 s
turn budget allows - the opposite of faster.

**Why the thread is not stored as JSONL instead of Postgres.** Storage is not where the time
goes. Measured on a 1,000-message thread: reading the newest 500 messages takes ~11 ms, building
the model client ~0.3 ms, trimming history ~0.4 ms; a model call takes 1,000-20,000 ms. Replacing
the database would change under 1% of a turn. It would also lose transactions, concurrent
writers (3 gunicorn workers x 2 threads, plus a scheduler container), the admin inbox queries
and ownership checks, for nothing. What does speed a turn up is fewer and smaller model calls:
the FAQ path (no call), reasoning effort `low`, the smaller prompt, this compaction (a long
thread stops dragging thousands of tokens through every call) and the turn budget.

---

## Rate Limiting

| Throttle | Limit | Env override |
|----------|-------|--------------|
| `AssistantBurstThrottle` | 10 requests/minute | `THROTTLE_ASSISTANT` |
| `AssistantDailyThrottle` | 100 requests/day | `THROTTLE_ASSISTANT_DAY` |
| `AdminAssistantBurstThrottle` | 20 requests/minute (store-manager chat) | `THROTTLE_ADMIN_ASSISTANT` |
| `AdminAssistantDailyThrottle` | 500 requests/day (store-manager chat) | `THROTTLE_ADMIN_ASSISTANT_DAY` |

The staff chat has its own counters so the owner and a shopper on the same
account never spend each other's allowance. A refused request says which limit it
was (`NamedThrottleMixin`): the error text starts `Daily chat limit reached.`,
`Too many messages. Please wait a moment.`, or — for a second message while one
is still being answered — `A reply is already in progress.` The storefront shows a
different message for the daily cap ("resets tomorrow") than for the other two
("one moment"), matching on the word "daily".

Plus one in-flight turn per account (concurrent POST → 429, taken BEFORE the
message is saved so a refused turn leaves nothing in the thread; dead-man TTL =
turn budget + 30 s) and a ~12k-token prompt ceiling (`ASSISTANT_MODEL_CONTEXT_TOKENS`, AP7c).
Of that ceiling, what is left for HISTORY is 12000 − 1000 (reply) − 4000 (tool
reserve) − ~1,100 (system prompt) ≈ 5,900 estimated tokens, roughly 30–35
ordinary messages. (The reserve was 8000, which left ~800 — about five
exchanges; the system prompt was ~2,100 until the tool list stopped being
written out twice.) ⚠ These are env-overridable: a deployed env that still pins
`ASSISTANT_MODEL_CONTEXT_TOKENS=200000` / `ASSISTANT_TOOL_OBS_RESERVE_TOKENS=8000`
/ `ASSISTANT_MAX_OUTPUT_TOKENS=600` silently overrides all three defaults.

A turn that carries text AND a lookup ("Let me check…" + `search_products`) is
not treated as the answer — the loop goes round again so the reply is written
with the results. Only on the last round is such text returned as-is.

AP10b note on worker isolation (S5): chat currently shares the 3×2 gunicorn
pool with checkout. The shipped mitigation is bounds, not a separate pool —
20 s LLM timeout and NO retry, a 45 s turn budget, one in-flight turn per
account (AP7c), 10/min + 100/day throttles and the history cap. A dedicated chat
worker pool (separate service/upstream) remains future work; see DEPLOYMENT.md.

### Turn budget

The storefront nginx gives up on `/api/` after 60 s (`proxy_read_timeout`). A turn
used to be allowed 4 rounds × 20 s × 2 attempts = 160 s: past 60 s the customer saw
a generic error while the answer was still computed, saved and billed. Now:

- `LLM_MAX_RETRIES = 0` — a retry of a 20 s timeout is another 20 s of waiting.
- `ASSISTANT_TURN_BUDGET_SECONDS` (default **45**): a round starts only if
  `elapsed + ASSISTANT_LLM_TIMEOUT` still fits; otherwise the turn ends with the
  `slow` reply, which is saved like any other. The first round always runs.
  Worst case ≈ 40 s plus tool time.
- A reply that is empty with `finish_reason == 'length'` (a reasoning model spent
  its whole output allowance thinking) gets the `fallback` reply at once instead
  of a second, equally doomed call.
- **Invariant to keep: `ASSISTANT_LLM_TIMEOUT` < `ASSISTANT_TURN_BUDGET_SECONDS` <
  the proxy timeout.** Do not raise the nginx timeout to make a slow model fit.

### Reply length

A reply is cut at 4,000 characters (`MAX_REPLY_CHARS`), at the last sentence end in
its final quarter (`।` counts), and the translated "continued" line is added.
Before 2026-10-03 the cut was 1,500 characters with no notice, below what the
output-token allowance can produce.

---

## LLM Configuration

```env
LLM_API_KEY=sk-or-v1-...
MODEL_PROVIDER=openrouter
LLM_MODEL=minimax/minimax-m2.5

# Optional: stronger model for the assistant
ASSISTANT_MODEL_PROVIDER=openrouter
ASSISTANT_LLM_MODEL=anthropic/claude-haiku-5.5
ASSISTANT_REASONING_EFFORT=low
ASSISTANT_MODEL_CONTEXT_TOKENS=100000

# Optional: how hard a reasoning model thinks (sent to OpenRouter as
# reasoning.effort). Unset = provider default. Thinking tokens are billed as
# output and count against ASSISTANT_MAX_OUTPUT_TOKENS and ASSISTANT_LLM_TIMEOUT,
# so raise those two with it or replies truncate / time out. `high` was the likely
# cause of slow and empty replies on prod; `low` is the recommended setting for a
# shop assistant (it mostly looks things up and writes two sentences).
ASSISTANT_REASONING_EFFORT=low

# The whole turn must end before the proxy gives up (60 s). Keep
# ASSISTANT_LLM_TIMEOUT < ASSISTANT_TURN_BUDGET_SECONDS < 60.
ASSISTANT_LLM_TIMEOUT=20
ASSISTANT_TURN_BUDGET_SECONDS=45
```

---

## Graceful Degradation

Every canned reply below is in the customer's language (see "Multilingual Replies").

```
LLM unavailable          → 'fallback', reason llm_unavailable (no crash)
Provider error/timeout   → 'fallback', reason llm_error, escalate=False
Unparseable turn         → 'fallback', reason llm_error, escalate=False
Empty + finish=length    → 'fallback', reason llm_error (no second call)
No readable reply        → nudge, then 'loop', reason loop_exhausted
Out of turn budget       → 'slow', reason loop_exhausted
Truncated (finish=length)→ reply + 'continued' line, escalate=False
Common question matched  → FAQ answer, reason faq, llm_used False (no model call)
Unknown tool/action name → error fed back to LLM (not executed)
Tool raises exception    → {'error': 'tool_error'} returned as observation
Customer asked for human → escalate_to_human → needs_human + owner email now
```

---

## Removed: support.ChatSession Escalation

An earlier design had `AssistantConversation.escalated_session` point to a
`support.ChatSession` record. That FK, the `ChatSession`/`ChatMessage` models, and
the `/api/chat-sessions/` endpoints have all been **removed** (migrations
`assistant.0003_remove_escalated_session` and `support.0004_delete_chat_models`).
Human-admin participation now happens directly inside `AssistantMessage` via the
`admin` role.
