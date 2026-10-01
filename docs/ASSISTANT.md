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
round may carry SEVERAL calls — "haldi, jeera, dhaniya" resolves in one turn).

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
`assistant/test_eval.py` (43 scripted cases + summary: completion, median
ms/turn, false-escalation rate).

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
| **G4 — bounded loop + degrade** | Max 4 iterations; max 600 output tokens. LLM unavailable → `FALLBACK_REPLY`. |
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
| `get_policy` | No | Shipping or return policy content |
| `get_order_status` | Yes | Status of a single order (authenticated user's own) |
| `get_order_details` | Yes | Line items of one of the user's orders (for "what was in X" / reorder) |
| `list_my_orders` | Yes | The authenticated user's recent orders (number, status, date, total) |
| `get_cart` | Yes | Authenticated user's current cart |

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
   - `MAX_OUTPUT_TOKENS` (1000, AP9) and `TOOL_OBS_RESERVE_TOKENS` (8000) are reserved out
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
  never a human flag
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

The `language` field (`en`, `hi`, `hinglish`, `gu`, `mr`, `pa`) controls
the final reply language only. Tool names/args and all DB content always stay
in English.

---

## Rate Limiting

| Throttle | Limit |
|----------|-------|
| `AssistantBurstThrottle` | 10 requests/minute (AP7c) |
| `AssistantDailyThrottle` | 100 requests/day (AP7c) |

Plus one in-flight turn per account (concurrent POST → 429) and a ~12k-token
history budget (`ASSISTANT_MODEL_CONTEXT_TOKENS`, AP7c).

AP10b note on worker isolation (S5): chat currently shares the 3×2 gunicorn
pool with checkout. The shipped mitigation is bounds, not a separate pool —
20 s LLM timeout + 1 retry (AP2), one in-flight turn per account (AP7c),
10/min + 100/day throttles and the history cap. A dedicated chat worker pool
(separate service/upstream) remains future work; see DEPLOYMENT.md.

---

## LLM Configuration

```env
LLM_API_KEY=sk-or-v1-...
MODEL_PROVIDER=openrouter
LLM_MODEL=minimax/minimax-m2.5

# Optional: stronger model for the assistant
ASSISTANT_MODEL_PROVIDER=openrouter
ASSISTANT_LLM_MODEL=openai/gpt-4o-mini
```

---

## Graceful Degradation

```
LLM unavailable          → FALLBACK_REPLY, reason llm_unavailable (no crash)
Provider error/timeout   → FALLBACK_REPLY, reason llm_error, escalate=False
Unparseable turn         → FALLBACK_REPLY, reason llm_error, escalate=False
No readable reply        → nudge, then LOOP_EXHAUSTED_REPLY, reason loop_exhausted
Truncated (finish=length)→ reply + CONTINUED_SUFFIX, escalate=False
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
