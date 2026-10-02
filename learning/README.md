# NGU — Design and Learning Guide

A study guide to the design of NGU (the Nidhi Masala online store), taught from
its own code. Everything educational about the project is in this one folder:

- the **high-level design** (HLD): the big boxes and how they talk,
- the **low-level design** (LLD): the classes, rules and flows inside each box,
  for the Django backend and the two React apps,
- an **interview kit**: the pitch, stories and likely questions with answers,
- **lessons**: write-ups of real problems hit while building it.

Every section links to the real file and ends with a line you can say in an
interview. Most sections open with a picture. **Look at the picture first, then
read.**

| Picture | Shows | Used in |
|---|---|---|
| ![](diagrams/hld-overview.svg) | The whole system on one page | Part 1 §3 |
| ![](diagrams/payment-three-layers.svg) | Three ways a payment is confirmed, one function | Part 1 §6.2 |

The other diagrams are written in Mermaid. They render on GitHub and in VS
Code's Markdown preview (install the "Markdown Preview Mermaid Support"
extension if a block shows as code).

> Written 2026-10-02. This folder is part of the NGU repository: since that day
> the backend, the storefront, the admin panel and the project docs are **one
> git repository**, with the three old histories merged in
> ([lesson 09](lessons/09_one_repository_from_three.md)). Links are relative,
> so they open in VS Code and on GitHub.

---

## Reading order

| # | File | What it covers | Time |
|---|---|---|---|
| 1 | [01_HLD.md](01_HLD.md) | HLD vs LLD; the boxes; one request step by step; where state lives; the three flows to know; decisions and their costs; numbers; what happens when a box fails; scaling | 30 min |
| 2 | [02_LLD_Object_Model_and_Flows.md](02_LLD_Object_Model_and_Flows.md) | The models and why each is shaped that way; checkout line by line; money rules; order state machines; payments; invoices, refunds and credit notes; restocking; the assistant loop; login; the rules that must always hold | 60 min |
| 3 | [03_LLD_Backend_Patterns.md](03_LLD_Backend_Patterns.md) | Django and DRF patterns with the OOP behind each: Model, ViewSet, Serializer, transactions and locks, idempotency, signals, caching, cookie login, services, guardrails, the agent, commands, middleware, settings, N+1, adapters | 75 min |
| 4 | [04_LLD_Frontend_Patterns.md](04_LLD_Frontend_Patterns.md) | React patterns: types as the API contract, the API layer, the fetch wrapper, Context, optimistic updates, data fetching, variants, routing, hooks, i18n, runtime config, the admin panel's axios client | 50 min |
| 5 | [05_Interview_Kit.md](05_Interview_Kit.md) | The pitch; one feature designed end to end; classic LLD questions mapped to this code; five stories; about 45 questions with answers; numbers; a cheat sheet | 45 min |
| 6 | [lessons/](lessons/00_INDEX.md) | Nine real problems, each with the cause, the fix, the general idea and interview questions | 10 min each |

**If Python, Django or object-oriented programming is new to you,** start with
Part 3. Its first three sections (§0, §0.5, §0.6) explain how a request flows
through Django and how to read a class you have never seen. Then come back to
Parts 1 and 2.

**If you have one evening before an interview:** Part 1, then Part 5 §1, §4,
§6 and §8, then lessons 05, 06 and 08.

---

## Pattern finder

| Pattern or idea | Backend | Frontend |
|---|---|---|
| Modular monolith | Ten Django apps, one process (Part 1 §7) | — |
| Active Record | Every `models.Model` (Part 3 §1) | — |
| Template Method | `ModelViewSet` hooks; `save()` overrides (Part 3 §1, §2) | — |
| Strategy | `permission_classes`, authentication classes (Part 3 §2, §8) | — |
| Adapter | `stt.transcribe` over Voxtral and whisper (Part 3 §16) | `readEnv` over runtime and build config (Part 4 §12) |
| Facade | `payments/services.py` | `lib/api/*` modules (Part 4 §2) |
| Decorator / middleware | `AbuseGuardMiddleware`, `@action` (Part 3 §13) | `authFetch`; axios interceptors (Part 4 §3, §13) |
| Observer | Django signals bust the cache (Part 3 §6) | `auth:unauthorized` DOM event (Part 4 §3) |
| Command | Management commands (Part 3 §12) | — |
| State machine | `Order.status`, `payment_status`, `Payment.status` (Part 2 §6, §7) | loading / error / success (Part 4 §6) |
| Service layer | `mark_payment_captured`, `record_refund` (Part 3 §9) | — |
| Registry | Assistant `READ_TOOLS`, `ACTION_BUILDERS` (Part 2 §10) | — |
| Idempotent operation | Payment capture, restock, refund by reference (Part 2 §7, §9) | — |
| Ledger (append-only) | `OrderRefund`, `PaymentEvent` (Part 2 §8.5) | — |
| Snapshot | `OrderItem`, `Invoice.snapshot` (Part 2 §5.4, §8.3) | — |
| Derived value, not stored | Combo price and stock (Part 2 §2.2) | — |
| Pessimistic locking | `select_for_update` on cart, variants, coupon, counter (Part 2 §4) | — |
| Fixed lock order | Order, then Payment (Part 2 §7) | — |
| Sequence generator | `InvoiceCounter` (Part 2 §8.1) | — |
| Cache-aside | `get_cached_or_set` (Part 3 §7) | TanStack Query (Part 4 §6) |
| Rate limiting | DRF throttles, abuse strikes (Part 5 §3) | Debounced search box (Part 4 §6) |
| Fail open / fail closed | Ban check vs webhook secret (Part 1 §9) | — |
| Fail fast | Boot guards in settings (Part 3 §14, lesson 04) | Provider guard `if (!ctx) throw` (Part 4 §4) |
| Single flight | — | One token refresh for many 401s (Part 4 §3) |
| Optimistic update | — | Cart quantity with rollback (Part 4 §5) |
| Dependency injection | — | React Context (Part 4 §4) |
| Tool-calling agent | `assistant/agent.py` (Part 2 §10, lesson 07) | Proposal card the customer confirms |
| Scheduler | `run_scheduler` (Part 1 §6.3) | — |

---

## How to study it

1. Read a section, then open the linked file and find the code.
2. Close the guide and explain the section to an empty chair.
3. Say the "interview line" out loud.
4. For every pattern, be ready for four questions: *what problem does it
   solve? why here? what does it cost? what would you do at 10× the size?*
5. When a class confuses you, run the six-step procedure in Part 3 §0.5 on it.

---

## Where the reference docs are

This folder teaches. These other files are the reference.

| Document | What it is |
|---|---|
| [../README.md](../README.md) | What the project is and how to run it |
| [../CLAUDE.md](../CLAUDE.md) | Rules, production facts and the decision history, one entry at a time |
| [../Backend/docs/API.md](../Backend/docs/API.md) | Every HTTP route: who may call it, which tables it touches |
| [../Backend/docs/ORDER_LIFECYCLE.md](../Backend/docs/ORDER_LIFECYCLE.md) | Order creation and pricing in full detail |
| [../Backend/docs/PAYMENTS_INTEGRATION.md](../Backend/docs/PAYMENTS_INTEGRATION.md) | The Razorpay flow |
| [../Backend/docs/AUTH.md](../Backend/docs/AUTH.md) | Login, tokens, email verification |
| [../Backend/docs/ASSISTANT.md](../Backend/docs/ASSISTANT.md) | The chat assistant |
| [../Backend/docs/AI_SEARCH_ENGINE.md](../Backend/docs/AI_SEARCH_ENGINE.md) | Search and autocomplete |
| [../Backend/docs/DATABASE_SCHEMA.md](../Backend/docs/DATABASE_SCHEMA.md) | Every model |
| [../Frontend/nidhi-brand-forge/ARCHITECTURE.md](../Frontend/nidhi-brand-forge/ARCHITECTURE.md) | Storefront structure |
| [../Admin%20Panel/e-commerce-command-center/ARCHITECTURE.md](../Admin%20Panel/e-commerce-command-center/ARCHITECTURE.md) | Admin panel structure |
| [../DEPLOYMENT.md](../DEPLOYMENT.md) | Deployment guide |

If a reference doc and the code disagree, the code is right. Fix the doc.
