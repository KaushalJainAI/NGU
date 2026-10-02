# Customer Support System

The `support` app now handles a single domain: **Contact Submissions** (the
"Contact Us" form). The order-scoped `ChatSession` / `ChatMessage` system has been
**removed** — all customer conversations (AI, voice, and human-admin) now live in
the `assistant` app. See `docs/ASSISTANT.md`.

---

## Contact Submissions

Handles queries from the "Contact Us" public form.

- **Throttling:** Anonymous users are limited to 5 requests/hour (`ContactRateThrottle`).
- **Status flow:** `new` → `read` → `replied` → `closed`
- **Workflow:**
  1. User submits form → `status="new"`
  2. Admin reads it → `POST /api/contact/{id}/mark_read/` → `status="read"`
  3. Admin adds notes → `POST /api/contact/{id}/reply/` → `status="replied"`

### Endpoints

| Endpoint | Method | Who | Description |
|----------|--------|-----|-------------|
| `/api/contact/` | POST | Anyone (rate-limited) | Submit a contact form |
| `/api/contact/` | GET | Admin | List submissions |
| `/api/contact/{id}/` | GET/PATCH/DELETE | Admin | Manage a submission |
| `/api/contact/{id}/mark_read/` | POST | Admin | Mark as read |
| `/api/contact/{id}/reply/` | POST | Admin | Record admin reply notes |

---

## Removed: order-scoped Chat Support

`ChatSession` and `ChatMessage` (and the `/api/chat-sessions/` endpoints) have been
deleted, along with their data. The order↔conversation association is intentionally
gone — order context is now carried as plain text in the first message of a unified
assistant thread (the storefront "Chat Support" button on an order pre-seeds
"I need help with my order ORD-XXXXXX." into the assistant widget).

For all customer conversations — product Q&A, voice ordering, order help, and
human-admin support — see `docs/ASSISTANT.md`:

- `AssistantConversation` — the thread
- `AssistantMessage` — individual turns (roles: `user`, `assistant`, `tool`, `system`, `admin`)

Admins read and reply to any thread from the admin panel **Conversations** page.
