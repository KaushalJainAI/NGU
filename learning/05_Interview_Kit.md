# Part 5 — Interview Kit

> How to talk about this project: the short pitch, one feature designed end to
> end, the classic LLD questions mapped to real code, stories, and about 45
> likely questions with answers. Back to the [index](README.md).

Level tags: 🟢 anyone may ask · 🟡 backend or full-stack round · 🔴 senior or
system-design round.

---

## 1. The pitch

Practise these until you can say them without reading.

**15 seconds.**
"NGU is the online store for an Indian spice brand. A Django REST API, a React
storefront and a React admin panel, with Razorpay payments, GST invoicing and
an AI shopping assistant. It runs in production on one small VM."

**60 seconds.**
"It's a modular monolith: ten Django apps in one process over one Postgres
database, with Redis for cache and rate limits. Two things made it interesting.
First, money: payments are confirmed by three independent paths that all call
one idempotent function, so a closed browser tab or a missed webhook can't lose
an order. Second, tax: an invoice is a stored document with a number from a
locked counter and a frozen copy of its contents, because Indian GST needs a
continuous series that never changes after it is issued. On top of that there
is a chat assistant that can read the catalogue and a customer's own orders
through tools, but can only *propose* changes, which the customer confirms."

**If they ask "what was the hardest part?"**
Pick one and go deep. Good choices, each with a section to study:

| Topic | Study | The one-sentence hook |
|---|---|---|
| Selling the last unit once | [Part 2 §4](02_LLD_Object_Model_and_Flows.md) | "Check-then-act is a race; I re-check on a locked row inside the transaction." |
| Payments that self-heal | [Part 1 §6.2](01_HLD.md), [Part 2 §7](02_LLD_Object_Model_and_Flows.md) | "Three callers, one idempotent function." |
| Invoices as documents | [Part 2 §8](02_LLD_Object_Model_and_Flows.md) | "A document that can change after issue is not a document." |
| Restocking exactly once | [Part 2 §9](02_LLD_Object_Model_and_Flows.md) | "Four paths can restock, so the function stamps a timestamp and becomes a no-op." |
| A safe AI assistant | [Part 2 §10](02_LLD_Object_Model_and_Flows.md) | "The model's output is untrusted input; tools hold the permissions." |

---

## 2. Designing a feature end to end

Interviewers often say "walk me through a feature you built". Use this order.
The example is real: **confirming cash for cash-on-delivery orders.**

### Step 1 — The problem, in the user's words

A COD order takes no money at checkout. The system never learned whether the
cash arrived. So:

- every COD order stayed "payment pending" forever,
- the owner could not see how much cash the courier was still holding,
- a COD return could not be recorded as a refund at all, because the refund
  rule demands proof that money was taken. Its tax stayed owed forever.

### Step 2 — The rules that must hold

Write these before any code.

1. Cash is confirmed by a person, not guessed by the system.
2. It is **not** set automatically when the order is delivered. The courier
   pays days later.
3. It is a fact about cash, not about tax. Tax was already due when the bill
   was issued. Confirming cash must not move any tax figure.
4. It only applies to COD orders. An online order's payment status belongs to
   the payment code and must not be set by hand.
5. A refund on a COD order is allowed only after cash is confirmed.
6. A wrong tick can be undone, unless a refund was already recorded against it.

### Step 3 — The data

Two fields on `Order`:

```python
cod_paid_at      = models.DateTimeField(blank=True, null=True, db_index=True)
cod_confirmed_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True)
```

Why a timestamp and not a true/false field: the time is needed anyway
("cash collected today"), and `NULL` already means "not yet". Why record *who*:
confirming cash is the most trusted action in the panel.

### Step 4 — The API

No new endpoint. The existing admin edit (`PATCH /api/orders/{id}/`) accepts
one more field, `cod_paid`, added to the allow-list `ADMIN_EDITABLE_FIELDS`.

### Step 5 — Where each rule is enforced

| Rule | Code |
|---|---|
| Only staff | `update()` raises `PermissionDenied` for non-staff |
| Only COD orders | `if order.payment_method != 'COD': return 400` |
| Ticking sets the time, the person, and `payment_status='paid'` | the `cod_paid` branch in `update()` |
| Un-tick refused after a refund | `if order.refunded_amount > 0: return 400` |
| Refund needs the tick | `_is_refundable_payment` |
| No race with a payment | the order row is locked first, then the payment row |

### Step 6 — What it changes elsewhere

- The dashboard gets "cash still with the courier" (count and amount) and
  "cash collected today".
- The daily roll-up counts collected cash by the **confirmation date**, like
  refunds, not by the order date.
- Refunds on COD orders become possible.

### Step 7 — What can go wrong

- *A misclick* → un-tick is allowed, and logged loudly, because un-ticking is
  also how someone could hide a real receipt.
- *An admin tries it on an online order* → refused.
- *A validation error halfway through the edit* → see the trap in
  [lessons/08](lessons/08_return_inside_a_transaction_commits.md): returning a
  400 from inside the transaction block still commits what was written before.

### Step 8 — Tests

`orders/test_shipping_gst_and_cod.py` covers the tick and what it changes;
`orders/test_refunds.py` covers who may be refunded.

**The shape to remember:** problem → rules → data → API → where each rule is
enforced → effects elsewhere → failure cases → tests.

---

## 3. Classic LLD questions, mapped to this code

When you get a textbook question, answer it with the general design and then
say "I built a version of this", and point at the real thing.

| Classic question | What this project has | Where |
|---|---|---|
| **Design a shopping cart** | One cart per user (user is the key). A line is a size or a combo. Database constraints stop duplicates and mixed lines. | [Part 2 §3](02_LLD_Object_Model_and_Flows.md) |
| **Design an inventory system / "sell the last ticket once"** | Stock on the variant. Lock the rows, re-read, then subtract, inside one transaction. A database check keeps stock ≥ 0. | [Part 2 §4](02_LLD_Object_Model_and_Flows.md) |
| **Design a rate limiter** | DRF throttle classes with a named rate per kind of action (login 5/min, chat 10/min and 100/day), counted in Redis. A separate "strike" counter per IP for abusive requests. | `spices_backend/throttles.py`, `spices_backend/abuse.py` |
| **Design a unique id / sequence generator** | A counter row per series, incremented under a row lock, with a unique constraint as the backstop | [Part 2 §8.1](02_LLD_Object_Model_and_Flows.md) |
| **Design a payment system** | A state machine changed by one idempotent function; an audit table; a table of processed webhook ids; a reconciler | [Part 2 §7](02_LLD_Object_Model_and_Flows.md) |
| **Design a cache** | Cache-aside with a key that includes every input (including language), a lifetime, and delete-by-prefix on write | [Part 3 §7](03_LLD_Backend_Patterns.md) |
| **Design a coupon system** | Percent or fixed amount, a minimum order, an expiry, a global use limit, an optional single user. The use count is incremented under a lock. | `admin_panel/models.py::Coupon` |
| **Design a notification service** | Emails sent only after the transaction commits, from a background thread, with a timeout | [Part 3 §9](03_LLD_Backend_Patterns.md) |
| **Design a job scheduler** | One process, interval and cron triggers, missed runs merged into one, no job overlapping itself, each job isolated from the others' failures | [Part 1 §6.3](01_HLD.md) |
| **Design a search / autocomplete** | Synonyms generated offline per product; at query time fuzzy matching over a cached word list; the box waits 250 ms after typing stops | `Backend/docs/AI_SEARCH_ENGINE.md` |
| **Design a soft delete / recycle bin** | An `is_deleted` flag and a time; hidden from normal lists; purged after 30 days unless protected by an invoice | `orders/models.py`, `purge_recycle_bin` |
| **Design an order state machine** | Two status fields: one for goods, one for money | [Part 2 §6](02_LLD_Object_Model_and_Flows.md) |

For each, be ready for the four follow-ups: *what problem does it solve, why
this way, what does it cost, what changes at 10× scale?*

---

## 4. Stories (STAR)

STAR means Situation, Task, Action, Result. Each story below really happened in
this project. Each has a full write-up in [lessons/](lessons/00_INDEX.md).

**Story 1 — "Free delivery" that wasn't.** ([lesson 02](lessons/02_build_time_vs_runtime_config.md))
- *Situation:* a ₹499 cart showed "free delivery" and was charged ₹69.62 at
  checkout.
- *Task:* find why two parts of one system disagreed by one rupee.
- *Action:* traced the number. The storefront image had 499 baked in at build
  time. The backend's environment said 500. The storefront container was passed
  an empty value at runtime, so it could not correct itself.
- *Result:* aligned the number in the code defaults, every env file and
  production. The lasting lesson: a value that two programs must agree on needs
  one owner.

**Story 2 — The site went down for 90 seconds.** ([lesson 03](lessons/03_the_crlf_entrypoint_outage.md))
- *Situation:* after a deploy, the storefront container kept restarting.
- *Task:* restore service, then make it impossible to repeat.
- *Action:* the start-up script had Windows line endings, so Linux could not
  find its interpreter (exit code 127). After service was back, pinned line
  endings in `.gitattributes`, made the Dockerfile strip them, and added a step
  to the deploy: start the new image in a throwaway container and check it
  stays running.
- *Result:* two independent guards plus a pre-flight check.

**Story 3 — A setting that changed meaning.** ([lesson 01](lessons/01_when_a_config_value_changes_meaning.md))
- *Situation:* delivery went from an untaxed ₹69 to ₹59 plus 18% GST. The old
  setting `SHIPPING_CHARGE=69` was in every deployed environment.
- *Task:* ship the change without overcharging or undercharging anyone during
  the rollout.
- *Action:* renamed the variable instead of reusing it. The old name is now
  ignored everywhere and a warning is printed at start-up if it is still set.
- *Result:* no order of deploy steps could produce a wrong bill.

**Story 4 — Stock that appeared from nowhere.** ([lesson 06](lessons/06_restocking_exactly_once.md))
- *Situation:* refunds were about to start returning stock. An order that was
  cancelled and then refunded would have had its stock returned twice.
- *Action:* one function for all restocking, guarded by a timestamp on the
  order. It also restores from the order's saved components, not the combo's
  current recipe.
- *Result:* restocking is safe to call from any path, any number of times.

**Story 5 — The assistant kept paging the owner.** ([lesson 07](lessons/07_an_ai_assistant_that_fails_politely.md))
- *Situation:* an audit found that every assistant failure (a timeout, an
  unreadable reply, a used-up loop) flagged the conversation for a human. With
  a revoked API key, every chat would have become a support ticket.
- *Action:* gave each result a reason. Only the customer explicitly asking
  flags a human. Provider errors return a polite fallback.
- *Result:* outages are quiet for the owner and honest for the customer.

---

## 5. Probable questions

### A. Overview

**A1 🟢 What does the project do?**
An online spice store: catalogue, cart, online and cash payments, order
tracking, tax invoices, an admin panel, and a chat assistant.

**A2 🟢 What is the stack and why?**
Django with Django REST Framework: batteries included (ORM, migrations, auth,
admin). Postgres: it needs real transactions and row locks for stock and money.
Redis: cache and counters. React with TypeScript: two separate single-page
apps. Docker Compose: one file describes the whole system.

**A3 🟢 How big is it?**
Ten backend apps, about 40 models, about 1,280 backend tests, and two
frontends with 27 and 20 pages.

**A4 🟡 Why a monolith and not microservices?**
One small server and one developer. A monolith gives one deploy and lets a
single database transaction cover an order, its stock and its coupon. With
services that would need distributed transactions. *Follow-up: what does it
cost?* Nothing stops apps importing each other, and some do. The fix would be
import rules checked in CI.

### B. HLD

**B1 🟡 Walk me through a request.**
[Part 1 §4](01_HLD.md). Caddy ends HTTPS, nginx serves the app and forwards
`/api/`, gunicorn runs Django, middleware → router → view → serializer → ORM.

**B2 🟡 Where does state live?**
Postgres is the only truth. Redis holds things that can be lost. Images are on
Cloudinary. The web containers hold nothing.

**B3 🟡 Why is the scheduler a separate container?**
gunicorn runs three worker processes. A timer inside the web server would run
three times. One dedicated process runs each job once.

**B4 🔴 What is your single point of failure?**
The VM, and the database on it. Backups exist but are on the same disk. The
first improvement is copying them off the machine; the second is a managed
database.

**B5 🔴 How would you scale this 10×?**
[Part 1 §11](01_HLD.md). Backups, more stateless web workers, a real task
queue, a managed database, a CDN. Split services last.

**B6 🟡 Why PgBouncer?**
Each gunicorn thread wants a database connection and Postgres connections are
expensive. PgBouncer lets many clients share a small pool. In transaction mode
a connection is lent for one transaction only. *Cost:* features that need the
same connection across transactions are not available.

### C. Data model

**C1 🟡 Why is stock on the variant and not the product?**
Sizes sell out separately and have different prices. The product keeps what is
true for every size: name, tax rate, HSN code.

**C2 🟡 Why does a combo have no price column?**
Its list price is the sum of its components, so it is computed. A stored copy
would go stale when a component's price changes.

**C3 🟡 Why copy the product name and price onto the order line?**
The catalogue changes. An old order must still show what was charged. It is a
snapshot.

**C4 🟡 What does `on_delete=PROTECT` do and where do you use it?**
It refuses to delete a row that others point to. Products on orders, and
orders with invoices, cannot be deleted.

**C5 🔴 Give me an example of a rule you enforce in the database, and why
there.**
"Variant stock ≥ 0" is a check constraint. Code can have bugs and someone can
run SQL by hand. The database is the last place a wrong value can be stopped.

**C6 🟡 Why two status fields on an order?**
Goods and money move independently. A COD order can be delivered and unpaid. An
online order can be paid and not shipped.

### D. Concurrency

**D1 🟡 Two people buy the last item at the same moment. What happens?**
Both pass the first stock check. Inside the transaction each locks the variant
row. The second waits. When it gets the lock it reads stock 0 and fails with a
clean error. Nothing is half-written because the whole block rolls back.

**D2 🟡 A customer double-clicks "Place order".**
The cart row is locked first. For COD the first request empties the cart, so
the second finds it empty. For online orders the second cancels the first
unpaid order and replaces it, so there is one order and one stock reservation.

**D3 🔴 What is a deadlock and how do you avoid it?**
Two transactions each hold a lock the other needs. Here, every path that needs
both locks takes Order first, then Payment. With one fixed order, a cycle
cannot form.

**D4 🔴 What is `select_for_update` and what are its limits?**
It locks the selected rows until the transaction ends. Limits: it only works
inside a transaction, it only locks rows that exist (it cannot stop an insert),
and SQLite does not support it. Two of our concurrency tests fail on SQLite and
pass on Postgres for that reason.

**D5 🔴 Why not optimistic locking?**
Optimistic locking retries when a version number changed. It suits rare
conflicts and long edits. Stock at checkout is a short, hot write where waiting
a few milliseconds is simpler than retrying.

**D6 🔴 What happens if you `return` from inside `transaction.atomic()`?**
The block ends without an exception, so it **commits**. Everything written
before the return is saved. To undo, raise. See
[lesson 08](lessons/08_return_inside_a_transaction_commits.md).

### E. Payments

**E1 🟡 How do you know an order is paid?**
Three ways: the browser calls `/verify/` with Razorpay's signature; Razorpay
calls our webhook; a job every 5 minutes asks Razorpay about orders unpaid for
15 minutes. All three call the same function.

**E2 🟡 What is idempotency and how did you get it?**
Doing something twice has the same effect as once. The capture function locks
the payment, checks whether it is already completed, and only then acts. A
unique webhook id in the database is the second guard.

**E3 🟡 How do you verify a webhook?**
Razorpay signs the exact bytes of the body with a shared secret. We compute the
same signature over the raw body and compare. We verify before parsing the
JSON, because re-writing the JSON changes the bytes.

**E4 🟡 What if the webhook secret is not set?**
Every webhook is refused. That is fail-closed. Payments still complete through
the other two paths.

**E5 🔴 A payment arrives for an order that was already cancelled.**
Record the money truthfully, mark it as an exception needing a refund, and do
not reopen the order. Its stock was already given to someone else.

**E6 🔴 Can the customer change the amount?**
No. The browser never sends an amount. The server computes it from the order
and creates the Razorpay order itself. The capture step also compares the
amount Razorpay reports with the order's total.

**E7 🟡 Why does an online order keep the cart until payment?**
If the payment fails or is abandoned the customer should not lose their cart.
The stock reserved by the abandoned order is returned after 15 minutes, or
immediately if they check out again.

### F. Tax and documents

**F1 🟡 Why can't the invoice number be the order id?**
Order ids have gaps: every abandoned or cancelled order uses one. A tax invoice
series must be continuous.

**F2 🟡 How do you generate a continuous number safely?**
A counter row per financial year. Lock the row, add one, save. A unique
constraint on (series, sequence) is the backstop.

**F3 🔴 Two workers issue an invoice for the same order at once.**
The order-to-invoice link is one-to-one, so the second insert fails. The code
catches that, keeps the first invoice and logs that a number was skipped. A
skipped number is accepted over two invoices for one sale.

**F4 🟡 What is a snapshot and why does the invoice have one?**
A copy of everything printed, saved at issue time. The PDF is drawn only from
it. Later changes to the shop's address, the customer's address or the product
cannot alter an issued bill.

**F5 🔴 Building the invoice fails during payment capture. What happens?**
The capture still succeeds. Invoice issuing catches its own errors, inside its
own savepoint so the outer transaction stays usable. A repair command fills the
gap later.

**F6 🟡 Prices include tax. How do you compute the tax?**
`tax = gross × rate / (100 + rate)`. For ₹210 at 5% that is ₹10. Delivery is
the opposite: quoted without tax, with 18% added.

### G. Caching

**G1 🟡 How does your cache work?**
Cache-aside. Look in Redis; on a miss, run the query and store the result with
a lifetime. On any product save, a signal deletes all keys with that prefix.

**G2 🟡 What goes in the cache key?**
Every input the answer depends on. The language is in the key. Without it the
first Hindi visitor would fill the cache and English visitors would get Hindi.

**G3 🔴 What is the risk of deleting by prefix?**
It throws away more than needed, and on a large Redis a pattern scan is slow.
At this size it is cheap, and a stale price on a live shop costs more than a
few extra misses.

**G4 🟡 Why do staff skip the cache?**
An owner who just edited a product must see the edit at once, or they edit it
again.

### H. Security and login

**H1 🟡 Where is the login token stored and why?**
In an HttpOnly cookie. JavaScript cannot read it, so a script injected into the
page cannot steal it. `localStorage` would be readable.

**H2 🟡 What new problem do cookies bring?**
CSRF: another site can make the browser send a request with the cookie. Two
defences: `SameSite` on the cookie, and a CSRF token the page must echo in a
header.

**H3 🟡 How does a user stay logged in with a 15-minute token?**
A 7-day refresh token gets a new access token silently. The frontend catches a
401, refreshes once, and repeats the request. If six requests fail together
they share one refresh.

**H4 🔴 How do you log someone out everywhere?**
Changing or resetting the password cancels all refresh tokens. Access tokens
already issued live out their 15 minutes.

**H5 🟡 How do you stop one user reading another's orders?**
`get_queryset` filters by the logged-in user. Every action builds on that
queryset, so another user's order cannot even be looked up.

**H6 🟡 Is validation in the browser enough?**
No. Anyone can call the API directly. Browser checks are for speed and
comfort. Server checks are the real ones.

**H7 🔴 What did you do about abuse of cash on delivery?**
A COD order reserves stock with no money. So it needs a verified email, a
value cap, and a cap on unfinished COD orders per account.

### I. Frontend

**I1 🟢 What is a single-page app?**
One HTML file. JavaScript redraws the page as the URL changes. The server must
return that file for every path.

**I2 🟡 What is an optimistic update?**
Change the screen first, then tell the server. Keep a copy of the old state. If
the server says no, put it back. If it says yes, use its answer, because it may
have changed the quantity.

**I3 🟡 Why must you not change state in place in React?**
React compares references. Changing an object in place keeps the same
reference, so React thinks nothing changed and does not redraw.

**I4 🟡 What does the dependency array of `useEffect` do?**
It says when to run again. Empty means once. Leaving it out means after every
render, which usually causes an endless loop.

**I5 🟡 Why is your API URL relative?**
The site is served on more than one domain. A relative URL calls the domain the
page came from, so cookies are sent. An absolute URL breaks login on the other
domains.

**I6 🔴 A frontend has no environment variables at runtime. How do you
configure it per deployment?**
The container writes a small `config.js` at start from its environment. The app
reads that first and falls back to the value baked in at build.

**I7 🟡 Do you have frontend tests?**
Not unit tests. There is type checking and linting, and black-box tests that
drive the running API. Component tests are a gap I would fill first for the
cart and checkout.

### J. The AI assistant

**J1 🟡 How does the assistant work?**
A loop. Send the message and a list of tools to the model. If it asks for a
tool, our code runs it and sends back the result. Repeat until it answers in
text, at most four rounds.

**J2 🔴 How do you stop it leaking another customer's data?**
The tools receive the logged-in user from the view and filter by that user. The
model cannot pass a different user. Even if it is tricked, the tool refuses.

**J3 🔴 What is prompt injection and what do you do about it?**
Text the model reads (a review, a product description) that contains
instructions. Tool results are wrapped in data markers and the prompt says to
treat them as data. More important: the model cannot do anything dangerous
anyway, because writes are only proposals.

**J4 🟡 What happens when the AI provider is down?**
A polite fallback message. No error page, and no flag for a human.

**J5 🔴 How do you control cost?**
Ten messages a minute and a hundred a day per account, one message in progress
per account, four model rounds per message, a 20-second timeout, and a token
budget for the history sent each time.

**J6 🔴 How do you test something that isn't deterministic?**
The unit tests replace the model with a scripted fake, so they test our loop,
tools and validators. That does not test the model's behaviour. For that there
is a live mode that runs the same cases against the real model. I am clear
about which is which.

**J7 🟡 Why no AI call when a customer searches?**
Speed and cost, and it keeps working if the provider is down. The model writes
synonyms once per product, offline. Search then matches text.

### K. Testing and operations

**K1 🟡 How is it tested?**
About 1,280 backend tests with pytest. A separate black-box suite calls a
running server over HTTP, including hostile inputs. Concurrency tests need
Postgres because SQLite has no row locks.

**K2 🟡 How do you deploy?**
Build three images, push them, back up the database, pull on the server, run
migrations, restart. Before switching, start the new image in a throwaway
container and check it stays up.

**K3 🟡 What is a migration?**
A versioned file describing a change to the database structure. Django
generates it from the model classes and applies them in order.

**K4 🔴 Tell me about a production incident.**
Story 2 above.

**K5 🟡 Do you run tests against production?**
No. A full run was done once and it is now forbidden. Tests run against a local
seeded server.

### L. Behavioural

**L1 🟢 What are you most proud of?**
Pick the payment design or the invoice design and explain the rule it protects.

**L2 🟢 What would you do differently?**
Honest answers: enforce import rules between apps from the start; move
background work to a task queue; back up off the machine from day one; write
frontend tests for the cart and checkout.

**L3 🟢 How did you use AI tools to build this?**
Say it plainly. Then show that you understand the design: explain a rule, where
it is enforced, and what breaks without it. That is what this guide is for.

---

## 6. Numbers to know by heart

The full table is in [Part 1 §8](01_HLD.md). The ones most worth remembering:

| | |
|---|---|
| Web capacity | 3 workers × 2 threads |
| Access / refresh token | 15 minutes / 7 days |
| Unpaid online order cancelled after | 15 minutes |
| Reconcile and roll-up | every 5 minutes |
| Assistant | 4 rounds, 20 s per call, 10/min, 100/day |
| COD | ₹5,000 per order, 3 open orders |
| Free delivery from | ₹499 |
| Delivery | ₹59 + 18% = ₹69.62 |
| GST on goods | 0% or 5%, inside the price |
| Catalogue cache | 5 minutes |
| Backend tests | about 1,280 |

---

## 7. Questions to ask the interviewer

- How do you handle money or other "must be exactly once" operations today?
- What does a deploy look like, and how long does a rollback take?
- Where does the team draw the line between a module and a service?
- How is AI-written code reviewed here?

---

## 8. One-page cheat sheet

```
HLD      Browser → Caddy (HTTPS) → nginx (static + /api proxy) → gunicorn/Django
         → PgBouncer → Postgres.  Redis: cache + counters.  Scheduler: own container.
         Outside: Razorpay, OpenRouter, Cloudinary, email.

STATE    Postgres = truth.  Redis = losable.  Containers = stateless.

CHECKOUT client sends address + method only → server reads cart + prices →
         transaction: lock cart → cancel old unpaid online order → create order
         → lock variants, re-check, subtract → lock coupon, re-check, count
         → empty cart if complete → invoice if due → emails after commit.

PAYMENT  L1 browser /verify  ·  L2 webhook  ·  L3 reconciler (5 min)
         all → mark_payment_captured(): lock Order→Payment, already done? stop.

MONEY    goods: tax = gross × r / (100 + r)   (inside the price)
         delivery: tax = net × r / 100        (added on top)
         total = subtotal − discount + shipping + shipping_tax

DOCS     Invoice = row. Number from a locked counter. Snapshot frozen. PROTECT.
         Refund = ledger row → credit note. Dated by refund date.

STOCK    lives on the variant. Returned once: stock_restored_at.

AI       loop ≤ 4 rounds. Read tools run server-side, scoped to the user.
         Action tools only propose. Provider error → polite reply, no escalation.

RULES    database constraint  >  lock + re-check  >  application code
         fail open when blocking a real user is the worse mistake
         fail closed when letting a fake through is the worse mistake
```
