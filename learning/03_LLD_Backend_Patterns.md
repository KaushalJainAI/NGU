# Part 3 — Backend LLD Patterns

> The recurring code patterns in the Django backend, one at a time, with the OOP
> behind each. Back to the [index](README.md). Read [Part 2](02_LLD_Object_Model_and_Flows.md)
> first if you want the classes and flows these patterns live in.

This file explains **the recurring code patterns in the Django backend**: what boilerplate we write to achieve a thing, why that boilerplate exists, and what an interviewer is really probing when they ask about it.

It assumes **you do not know Django, DRF, or object-oriented programming**. Django-specific terms and the OOP vocabulary the patterns are built on (class, object, method, inheritance, `self`, `super()`, override, decorator, context manager) are each explained *inline, the first time they appear*, in a **🧩 OOP** callout. If a pattern below uses a word you don't recognize, it was defined in a 🧩 box further up — the concepts are introduced in reading order.

---

## 0. The 60-second mental model of the stack

A web backend has one job: a request arrives (`GET /api/products/`), and a response leaves (`[{...}, {...}]` JSON). Everything below is about *how the code is organized between those two moments*.

**Django** is the framework. It gives us three big building blocks:

| Block | What it is | File it lives in |
|---|---|---|
| **Model** | A Python class that describes one database table. Django writes the SQL for you. | `models.py` |
| **View** | A Python function/class that handles one URL. Takes a request, returns a response. | `views.py` |
| **URL conf** | A routing table mapping a URL to a view. | `urls.py` |

**DRF (Django REST Framework)** sits on top of Django and adds one more block:

| Block | What it is | File |
|---|---|---|
| **Serializer** | Converts a database object ⇄ JSON, and validates incoming JSON. | `serializers.py` |

So the flow is always:

```
HTTP request → urls.py → views.py → (serializers.py for validation)
             → models.py (talks to Postgres) → serializers.py (to JSON) → HTTP response
```

The whole project is split into **apps** — self-contained folders, each with its own models/views/serializers: `products`, `cart`, `orders`, `payments`, `users`, `reviews`, `analytics`, `assistant`, `admin_panel`, `support`. An app is just "one bounded chunk of the domain." This is the **modular monolith** pattern: microservice-style separation of concerns, but one deployable process, one database, no network calls between modules.

> **Interviewer's real question:** *"Why apps instead of one big folder?"*
> **Answer:** Bounded contexts. Each app owns its tables and its rules. `orders` is allowed to import from `products` (an order contains products), but the dependency direction is deliberate and one-way where possible. It keeps the blast radius of a change small, and it's the natural seam if we ever needed to split a service out.

---

## 0.5. Skill: how to read a class you've never seen before

This is the thing to reach for when you open a file and think *"I have no idea what this class is or why it's here."* It's a procedure, not a fact — run it on any class in the codebase and it will tell you what you're looking at.

1. **Read the first line: `class Something(Parent):`.** The name after `class` is *this* thing; the name(s) in parentheses are what it **inherits** from (defined in the next section). The parent tells you what *family* the class belongs to and where most of its behaviour secretly comes from. Empty parentheses (or `(object)`) means it stands on its own.
2. **Go look at the parent.** In your editor, `Ctrl`-click (Windows) the parent name to jump to its definition. This is the single most useful move in the whole procedure: the methods you *don't* see in the file you're reading almost always live in the parent. The parents worth opening once in this repo are `models.Model`, `viewsets.ModelViewSet`, `serializers.ModelSerializer`, `BasePermission`, `AbstractUser`, and `BaseCommand`.
3. **Scan the `def` lines — those are the methods (things the object can *do*).** A method whose name *matches one the parent already has* is an **override**, and overrides are where the interesting, project-specific code always is — they're the deliberate deviations from the default. Django's overridable hook names are predictable: `save`, `get_queryset`, `get_serializer_class`, `has_permission`, `handle`. See one of those and you're looking at a customization point.
4. **Read the plain `name = value` lines at the top, before the first `def` — those are the class attributes.** For a Model they're database columns. For a ViewSet they're configuration (`serializer_class`, `permission_classes`, `lookup_field`).
5. **Ask "who uses this?" — Grep the class name across the repo.** How it's used tells you what it *is*: a Model is used through `.objects.…`; a Serializer is constructed inside a view; a Command is run by `python manage.py <name>`; a permission is named in some view's `permission_classes`.
6. **When you hit a word you don't recognize, it's almost always inherited — return to step 2.** You rarely need to understand a framework base class in full; you need to know *which* of its methods this subclass overrode and why.

Everything below is just this procedure applied to the classes that recur most.

---

## 0.6. The flow problem: Inversion of Control, and how to trace it

**The complaint this section answers:** *"An algorithm I can follow top to bottom. But with DRF a request comes in and things just happen — I can't see the flow, so I can't understand it from scratch."* That feeling is real, it has a name, and it has a fix.

### Why it feels different from an algorithm

In an algorithm **you own the control flow**: you write `main()`, you decide what's called and in what order, your finger never leaves the page. A framework **inverts** that — this is literally called **Inversion of Control**, the *Hollywood Principle: "don't call us, we'll call you."* You don't write the top-level loop; DRF does. You only write **leaf functions** (`get_queryset`, `has_permission`, `list`) that the framework calls at moments *it* picks. So when you hunt for "the flow," it isn't in your code — **it lives one layer down, in framework code you never wrote and never opened.**

The unlock: **the flow is a fixed trunk, and your overrides are leaves that hang off named spots on it.** People feel it's bottomless because they blur two different questions —

- **"What is DRF doing?"** → the *trunk*. Identical on every request in the whole framework. Learn it **once, ever.**
- **"What am I doing?"** → the *leaves*. Your overrides. The only part that changes per view.

Keep them separate and the abstraction stops shifting under you.

### The trunk, traced once (socket → response) for `GET /api/orders/`

Your real classes are marked ★. Every hook you've ever overridden is a ★ on this one skeleton:

```
1. gunicorn receives HTTP bytes → Django WSGIHandler
2. Middleware chain — each middleware's __call__() runs in order:
      AbuseGuardMiddleware ★ → LanguageQueryMiddleware ★ → auth/session/…
3. URL resolver matches "/api/orders/" → the view
      (the router mapped {'get': 'list'} onto OrderViewSet via .as_view())
4. APIView.dispatch(request)   ← THE TRUNK. ~30 lines. Read it once and you own the flow.
     a. initialize_request()          wrap Django request in a DRF Request
     b. initial(request):
          perform_authentication()  → CookieJWTAuthentication.authenticate() ★  sets request.user
          check_permissions()       → IsAdminOrReadOnly.has_permission() ★
          check_throttles()         → get_throttles() ★
     c. handler = getattr(self, 'list')     pick the method by HTTP verb
        self.list(request)                  ← YOUR action runs here
             get_queryset() ★  → filter_queryset() → paginate_queryset()
             get_serializer(page, many=True) → serializer.data
             return Response(data)
     d. finalize_response()            render to JSON
5. Response bubbles back UP through the middleware in reverse → bytes on the wire
```

`get_queryset` is not called by magic — it's called inside `list()`, which is called inside `dispatch()`. And `list()` is *five readable lines* in `rest_framework/mixins.py`:

```python
def list(self, request, *args, **kwargs):
    queryset = self.filter_queryset(self.get_queryset())   # ← your override is called RIGHT HERE
    page = self.paginate_queryset(queryset)
    serializer = self.get_serializer(page, many=True)
    return self.get_paginated_response(serializer.data)
```

That is the entire "magic." Read it once and `list` becomes a place where your `get_queryset` fires at a known moment — not a black box.

### The technique: make any hidden flow visible (cheapest first)

1. **Read the traceback as a map, not an error.** On any exception, Python prints every frame `wsgi → middleware → dispatch → initial → your view`. That stack *is the flow, printed for free.* Read it top-to-bottom once instead of skimming to your line.
2. **Print the stack with no crash:** drop `import traceback; traceback.print_stack()` in `get_queryset` to see *who called you* — the trunk above your leaf.
3. **`breakpoint()` and walk up.** Put `breakpoint()` in a hook, run the request, type `u` (up) repeatedly: each `u` climbs one frame — `get_queryset → list → dispatch → …` — so you ascend from your leaf to the root by hand.
4. **`Ctrl`-click into the framework.** `dispatch`, `initial`, `list` are plain Python in `site-packages/rest_framework/`. Read `views.py` (`dispatch`/`initial`) and `mixins.py` once. Half an afternoon buys the trunk forever.
5. **Tests are the flow made explicit** (this is what `users/tests.py` is): a test is *you re-taking control* — `client.get(url)` then `assert`. `breakpoint()` in a test and watch the trunk run under your finger. Better still, unit-test a **serializer or service function directly** (no HTTP) to see one leaf as a pure algorithm again: inputs → outputs.
6. **DRF browsable API + SQL query logging** reveal the flow's *effects*: which serializer shaped the output, which queries fired.

### The mindset

When a framework feels un-traceable, the logic didn't vanish — **you're standing on a leaf trying to see the trunk.** Go find the trunk: read the one `dispatch` function, print the stack, or step up in the debugger. Do it **once per framework** and you're de-abstracted permanently, because the trunk never changes — only your leaves do.

---

## 1. Pattern: The Model — a class *is* a table

**The boilerplate** ([products/models.py](../Backend/products/models.py)):

```python
class Product(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
```

> **🧩 OOP — read this once; it unlocks every pattern below.** This is the first real class in the file, so here is all the object-oriented vocabulary the rest of the document leans on, explained against this exact code:
> - A **class** is a *blueprint*. `class Product` doesn't hold any one product — it describes what *every* product looks like (its fields) and what it can *do* (its methods). Think cookie-cutter.
> - An **object** (also called an **instance**) is one filled-in copy stamped out of that blueprint — one actual product, e.g. "Garam Masala 100g". The class is the cutter; an object is one cookie. One `Product` class ⇄ thousands of product objects, one per row.
> - An **attribute** is a piece of data living on an object: `product.price`, `product.stock`. The `name = models.CharField(...)` lines *declare* those attributes.
> - The `(models.Model)` in the parentheses is **inheritance**: it means "a `Product` *is a kind of* `models.Model` and automatically gets everything `Model` already knows how to do" — talking to Postgres, `.save()`, `.delete()`, `.objects.filter(...)`. You wrote 6 lines and inherited hundreds. `models.Model` is the **parent** (or **base**) class; `Product` is the **child** (or **subclass**).
> - A **method** is a function that belongs to a class — a verb the object can perform. `product.save()` calls the `save` method *on that particular product*.
> - **`self`** is how a method names the specific object it was called on. Inside a method, `self` *is* that object; `self.price` is this product's price. You never pass `self` in yourself — Python supplies it automatically when you write `product.save()`.
>
> That's the whole toolkit. "Template Method", "Strategy", "Observer" later on are just *named recipes* for combining these six ideas.

**What each piece does:**

- Each class attribute becomes a **column**. `CharField` → `VARCHAR`, `IntegerField` → `INTEGER`, etc.
- `ForeignKey` is a **link to another table** ("this product belongs to one category"). `related_name='products'` creates the reverse link, so `category.products.all()` gives you every product in that category.
- `on_delete=models.CASCADE` says: if the category is deleted, delete its products too. Django *forces* you to declare this — you cannot leave the decision implicit.
- **This class is the schema.** You never write `CREATE TABLE`. You run `python manage.py makemigrations` and Django diffs your models against the last known state and generates a **migration** — a versioned, replayable Python file describing the schema change. `manage.py migrate` applies it. That's how the production database is kept in step with the code.

### The three sub-patterns you'll be asked about

**a) `DecimalField` for money — never `FloatField`.**

Floats are binary approximations: `0.1 + 0.2 == 0.30000000000000004`. For money that becomes a paisa-level accounting error that compounds. `DecimalField(max_digits=10, decimal_places=2)` maps to SQL `NUMERIC(10,2)` — exact base-10 arithmetic. In Python, all order math uses `Decimal('0.01')`, never `0.01`. You'll see `.quantize(Decimal('0.01'))` everywhere in [orders/views.py](../Backend/orders/views.py) — that's "round to exactly 2 decimal places, now," so line totals and the header total can't drift apart.

**b) `class Meta` — table-level rules the *database* enforces.**

```python
class Meta:
    ordering = ['-created_at']          # default sort
    indexes = [models.Index(fields=['slug'])]   # speed up lookups by slug
    constraints = [...]                # e.g. "stock can never be negative"
```

The distinction that impresses interviewers: **an index is a performance tool; a constraint is a correctness tool.** A constraint is enforced by Postgres itself, so even a buggy code path or a manual SQL update can't violate it. Validation in Python is a *convenience*; validation in the DB is a *guarantee*.

**c) Overriding `save()` — logic that must run on every write.**

```python
class User(AbstractUser):
    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()   # canonicalize BEFORE writing
        super().save(*args, **kwargs)
```

> **🧩 OOP — override and `super()`.** `models.Model` (the parent) already has a `save` method. Here `User` defines its *own* method also called `save` — that's an **override**: because the names collide, *your* version runs instead of the parent's. But you rarely want to *replace* the parent entirely, only to *add* to it — so `super().save(...)` means "now also run the original `save` from the parent." Override to inject your logic; call `super()` so you don't throw away the behaviour you inherited (here: the code that actually writes to the database). Forget the `super()` call and nothing gets saved.

`save()` is the method Django calls to write the row. Overriding it and then calling `super().save()` is the **template-method pattern**: hook your logic in, then let the parent do the actual work. Here it guarantees `User@X.com` and `user@x.com` can never become two accounts, because normalization happens at the single choke point every write must pass through. [products/models.py](../Backend/products/models.py) does the same to auto-generate a URL slug from the product name.

**d) `@property` — a computed field that isn't stored.**

```python
@property
def final_price(self):
    return self.discount_price or self.price
```

> **🧩 OOP — a decorator.** The `@property` line stuck on top of the method is a **decorator**: a marker starting with `@` that *changes how the thing below it behaves*. `@property` makes `final_price` readable as `product.final_price` — **no parentheses** — so from the outside it looks and feels like a stored attribute, but it actually runs the method every time you read it. You'll meet two more decorators later: `@action` (turns a method into an extra URL) and `@receiver` (subscribes a function to an event). Same idea each time: `@x` wraps the function beneath it in extra behaviour so you don't write that plumbing by hand.

Not a column. Computed on read. Rule of thumb: **store facts, compute conclusions.** Discount price and price are facts; "what the customer actually pays" is a conclusion, so storing it would just be a chance for the two to disagree.

---

## 2. Pattern: The ViewSet — CRUD without writing CRUD

A "view" for a single URL would be a function. But most REST resources need the same five operations, so DRF gives us the **ViewSet**: one class that generates all of them.

```python
class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = 'slug'
```

Those four lines produce, for free:

| HTTP | URL | Method it calls |
|---|---|---|
| GET | `/categories/` | `list()` |
| POST | `/categories/` | `create()` |
| GET | `/categories/{slug}/` | `retrieve()` |
| PATCH | `/categories/{slug}/` | `partial_update()` |
| DELETE | `/categories/{slug}/` | `destroy()` |

This is **convention over configuration** — the framework assumes the standard REST shape and you only declare the deviations. It's also a **Template Method**: DRF defines the skeleton of "handle a list request," and you override the specific hooks.

### The hooks you override, and why

**`get_queryset()` — row-level authorization.** This is the single most important pattern in the file, and the one interviewers dig into.

```python
def get_queryset(self):
    user = self.request.user
    if user.is_staff or user.is_superuser:
        return Order.objects.all()...
    return Order.objects.filter(user=user, is_deleted=False)...
```

A "queryset" is a **lazy** description of a database query — nothing has hit Postgres yet. It only executes when you iterate it. That laziness is what makes this pattern safe: **you filter the data at the source, not after fetching it.** A regular user's queryset *cannot express* another user's orders, so there is no code path — not `retrieve`, not `update`, not `delete` — that can leak one. Compare with the naive approach of fetching the order and then checking `if order.user != request.user: return 403` — that check has to be repeated in every single handler, and the one you forget is the vulnerability. `get_queryset()` is checked once and inherited by all of them.

**`get_serializer_class()` — different JSON shape per action.**

```python
def get_serializer_class(self):
    if self.action == 'create':   return OrderCreateSerializer   # what we accept
    if self.action == 'list':     return OrderListSerializer     # lightweight
    return OrderDetailSerializer                                 # full
```

The write shape and the read shape of a resource are genuinely different — an order *create* accepts only address/phone/payment method (everything else, including all money, is computed server-side and is not client-writable), while an order *read* returns 20 fields. Different serializers make that asymmetry explicit and un-bypassable.

**`@action` — an endpoint that isn't CRUD.**

```python
@action(detail=False, methods=['post'])
def validate_coupon(self, request):
    ...
```
gives you `POST /orders/validate_coupon/`. `detail=False` = operates on the collection; `detail=True` = operates on one object (`/orders/5/cancel/`). Use this when the operation is a **verb on the resource**, not one of the five nouns.

**`permission_classes` — the Strategy pattern.** A permission is a small object with one job: answer yes/no.

```python
class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:      # GET/HEAD/OPTIONS
            return True
        return bool(request.user and request.user.is_staff)
```

Anyone may read the catalog; only staff may change it. Swapping the policy on a view is a one-line change, and the policy is unit-testable in isolation. That's the whole point of Strategy: behavior as a pluggable object, not an `if` buried in a handler.

---

## 3. Pattern: The Serializer — validation and shaping at the boundary

```python
class OrderCreateSerializer(serializers.Serializer):
    shipping_address = serializers.CharField(max_length=500)
    phone_number     = serializers.CharField(max_length=15)
    payment_method   = serializers.ChoiceField(choices=['COD', 'ONLINE'])
```

Used as:

```python
serializer = OrderCreateSerializer(data=request.data)
serializer.is_valid(raise_exception=True)   # bad input → automatic 400 with field errors
```

**The principle: never trust the client.** The serializer is the wall at the boundary where untrusted JSON becomes trusted, typed Python. `raise_exception=True` means an invalid payload short-circuits into a `400 Bad Request` listing exactly which fields failed — you never write that error-formatting code.

Two flavors, and knowing the difference is a real interview question:

- **`Serializer`** — you declare every field by hand. Used above because "create an order" doesn't map 1:1 to the Order table (the client sends 3 fields; the server derives 20).
- **`ModelSerializer`** — reads the model and generates the fields automatically. Used for reads:

```python
class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemListSerializer(many=True, read_only=True)   # nested
    total = serializers.DecimalField(..., source='total_amount') # rename for the API
    order_number = serializers.SerializerMethodField()           # computed

    class Meta:
        model = Order
        fields = ["id", "order_number", "status", "items", "total", ...]

    def get_order_number(self, obj):
        return f"ORD-{obj.id:06d}"
```

Three techniques worth naming out loud:
- **`many=True` nesting** — one serializer embeds another, so an order's items come back inline instead of requiring a second request.
- **`source=`** — decouples the API's public vocabulary from the DB column name. The column is `total_amount`; the API says `total`. Renaming the column later doesn't break the frontend.
- **`SerializerMethodField`** — a read-only field computed in Python. `ORD-000123` is a presentation concern, so it lives in the presentation layer, not the database.

> **Interviewer:** *"Isn't the serializer just duplicating the model?"*
> **Answer:** No — it's an anti-corruption layer. The model is shaped for storage; the serializer is shaped for the API contract. Keeping them separate is what lets us refactor the schema without breaking clients, and lets us expose different subsets to different audiences.

---

## 4. Pattern: Atomic transactions + row locks — the concurrency core

This is where senior interviews live. The scenario: **two requests for the last item in stock arrive at the same millisecond.**

Naive code:
```python
if product.stock >= qty:      # both requests read stock = 1 → both pass
    product.stock -= qty      # both write stock = 0
    order.save()              # we just sold 2 units of 1 item
```
This is a **race condition** (specifically a check-then-act / TOCTOU bug), and it will absolutely happen in production.

The fix, from [orders/views.py](../Backend/orders/views.py):

```python
with transaction.atomic():
    locked_cart = Cart.objects.select_for_update().get(pk=cart.pk)
    if not locked_cart.items.exists():
        raise ValueError('Cart is empty')
    # ... validate stock, create Order + OrderItems, decrement stock ...
```

> **🧩 OOP — a context manager (the `with` block).** `with something:` is Python's way of saying "run setup when I enter this indented block, and *guaranteed* cleanup when I leave it — whether I leave normally or by crashing." The object after `with` (here `transaction.atomic()`) defines what "entering" and "leaving" do. On entry it opens a database transaction; on exit it commits if the block finished cleanly, or rolls back if any line raised. You *cannot forget* the cleanup, because leaving the block **is** the cleanup — there's no `commit()` line to omit. (Tying a resource's lifetime to a scope like this is the pattern named **RAII**.)

**`transaction.atomic()`** — everything inside the block is all-or-nothing. If any line raises, Postgres rolls the whole thing back: no half-created order, no stock decremented without an order to match. As a context manager (`with`), the commit/rollback is automatic and cannot be forgotten — that's **RAII**, and it's why you never see a manual `commit()` in this codebase.

**`select_for_update()`** — issues `SELECT ... FOR UPDATE`, which takes a **row-level write lock** in Postgres. The second concurrent request *blocks at that line* until the first one commits. It doesn't read stale data; it waits, then reads the truth. The two requests are now **serialized** instead of interleaved.

Note what's being locked in that snippet: the **Cart** row, before anything else. That's the double-submit guard — a user double-clicking "Place Order" fires two identical requests. Whoever gets the lock creates the order and empties the cart; the loser then acquires the lock, finds an empty cart, and gets a clean `400 Cart is empty` instead of a duplicate order and a double stock decrement.

**Lock ordering matters.** Every code path that locks a cart and its products does so in the same order. If path A locks cart→product and path B locks product→cart, they can deadlock. Consistent lock ordering is the standard prevention, and mentioning it unprompted is a strong signal.

**The deliberate exception, documented at the top of the file:** the cart is cleared *outside* the transaction. Reasoning: if cart deletion fails, we do **not** want to roll back a successfully placed, successfully paid order. A stale cart is a cosmetic annoyance; a lost paid order is a disaster. That's a conscious trade-off of consistency for availability on a non-critical write — exactly the kind of judgment call interviewers want to hear articulated.

**Batching writes:** `restore_order_stock()` accumulates every stock change into a dict first, then issues **one** `bulk_update()` per table instead of one UPDATE per item. N+1 queries are the classic Django performance failure; this is the classic fix.

---

## 5. Pattern: Idempotency — "the same event, processed twice, changes nothing"

Payment gateways (Razorpay) will send you the same webhook **more than once**. That's not a bug in their system, it's a guarantee in ours: they promise *at-least-once* delivery, so we must make our handling *exactly-once* in effect. If a duplicate `payment.captured` webhook marks an order paid twice, we could double-fulfil or double-refund.

The pattern, in [payments/services.py](../Backend/payments/services.py) / [payments/views.py](../Backend/payments/views.py):

1. **Verify the signature over the raw body** before parsing anything:
   ```python
   raw_body = request.body   # raw bytes — must NOT be re-serialised
   client.utility.verify_webhook_signature(raw_body.decode('utf-8'), signature, secret)
   ```
   Razorpay signs the exact bytes it sent. If you parse the JSON and re-serialize it, the bytes change and the HMAC comparison fails. This is the #1 webhook bug in the wild.

2. **Fail closed.** If `RAZORPAY_WEBHOOK_SECRET` is unset, *every* webhook is rejected. An unauthenticated "mark this order paid" endpoint is the worst bug you can ship — so when the security control is missing, the feature is off, not open.

3. **Lock, then check current state, then act:**
   ```python
   if payment.status == 'paid':
       log(...); return   # already captured — this is a replay, do nothing
   ```
   The write is guarded by "is the transition I'm about to make still valid?" A second delivery finds the payment already `paid` and no-ops. The handler is a **state machine**: it only permits legal transitions, so replaying an event is harmless by construction.

4. **Two independent sources of truth (L1/L2).** L1 is the browser calling `/verify/` after checkout; L2 is the webhook. The browser can close mid-payment, so L1 alone loses money. The webhook can be delayed, so L2 alone is slow. Both funnel into the *same idempotent capture function*, so whichever arrives first wins and the second is a no-op. This is **defence in depth for state, not just for security.**

5. **The reconciler.** A `scheduler` container runs `manage.py reconcile_payments` every few minutes: any ONLINE order still unpaid past `PAYMENT_STUCK_TTL_MINUTES` is auto-cancelled and restocked. This is the **self-healing / eventual-consistency** backstop — even if *both* L1 and L2 fail, the system converges to a correct state on its own instead of leaking inventory forever.

> **Interviewer:** *"How do you make an endpoint idempotent?"*
> **Answer:** Give the operation a stable identity (the Razorpay order id / event id), lock the record, and make the state transition conditional on the current state. Then the second execution is a no-op rather than a second effect.

---

## 6. Pattern: Signals — decoupled reactions to model events

```python
@receiver(post_save, sender=Product)
def auto_update_product_on_save(sender, instance, created, **kwargs):
    if instance.is_active and instance.stock > 0:
        run_in_background(search_engine.a_ensure_search_kb, instance)
    invalidate_product_cache()
    invalidate_search_cache()
```

**What it is:** the **Observer pattern** (a.k.a. pub/sub). `post_save` is an event Django fires *after any Product is saved*. `@receiver` subscribes this function to it. The code that saved the product knows nothing about caches or search — it just saved a product.

**Why it's the right call here:** a product can be saved from the admin panel, from the API, from a management command, from a data migration. If cache invalidation were called explicitly, you'd have to remember it in all four places, and the one you forget serves stale prices to customers. The signal makes it structurally impossible to save a product without busting its cache.

**Be ready for the counter-argument, because a good interviewer will make it:** signals are "spooky action at a distance." Reading `product.save()` gives you no hint that an LLM call and five cache purges are about to fire. The discipline that makes them safe: **keep receivers small, side-effect-only, and never let one throw** — a failing cache purge must not fail the save. Heavy work (the LLM call that regenerates search synonyms) is pushed off the request via `run_in_background`, so the admin's save request returns immediately.

---

## 7. Pattern: Cache-aside with prefix invalidation

The catalog is read constantly and written rarely — a textbook cache target.

**Read path** ([products/cache.py](../Backend/products/cache.py)):
```python
def get_cached_or_set(cache_key, callback, timeout=None):
    data = cache.get(cache_key)
    if data is not None:
        return data              # HIT
    data = callback()            # MISS → compute
    cache.set(cache_key, data, timeout or TTL_MEDIUM)
    return data
```
This is **cache-aside** (lazy loading): the application, not the cache, owns the fill. `callback` is passed as a function rather than a value so the expensive query is *only* executed on a miss — passing `callback()` instead of `callback` would defeat the entire cache. That's a favourite gotcha question.

**Key design:**
```python
cache_key = make_cache_key(CACHE_PREFIX_CATEGORIES, 'list', lang=get_language())
```
`categories:list:lang:hi`. The active language is **part of the key** — otherwise the first Hindi visitor would poison the cache and every English visitor would get Hindi category names. **A cache key must include every input the output depends on.** Long keys get MD5-hashed to stay bounded.

**Invalidation** — famously one of the two hard problems:
```python
cache.delete_pattern('products:*')    # Redis: wildcard delete
```
Namespacing keys by prefix is what makes wholesale invalidation possible. We deliberately choose **precision over efficiency**: any product write nukes *all* product keys. It's slightly wasteful (we drop keys that were still valid) but it's correct and it's simple, and a stale price on a live store is far more expensive than a few extra cache misses.

**TTL as a safety net.** Every entry also has an expiry (`TTL_SHORT`/`MEDIUM`/`LONG`). Even if an invalidation is missed entirely, staleness is bounded to minutes rather than forever. Belt and suspenders.

**Layer-skipping:** staff bypass the cache entirely (`if request.user.is_staff: return super().list(...)`) — an admin who just edited a product must see their edit immediately, or they'll edit it again.

---

## 8. Pattern: Cookie-based JWT auth

A **JWT** is a signed token that says "this is user 42," and because it's signed, the server can trust it without a database lookup.

The classic tutorial stores it in `localStorage`. **We don't** — any XSS on the page can read `localStorage` and exfiltrate the token. Instead:

```python
response.set_cookie(
    'access_token', token,
    httponly=True,                          # JavaScript CANNOT read this cookie
    secure=settings.AUTH_COOKIE_SECURE,     # HTTPS only
    samesite=settings.AUTH_COOKIE_SAMESITE, # blocks cross-site sends → CSRF defence
)
```

`httponly=True` is the whole point: the browser attaches the cookie to every request automatically, but no script can read its value. Stolen-token XSS is off the table.

The cost of cookies is **CSRF** — a malicious site can make *your* browser send a request with your cookies attached. Two mitigations, both present: `samesite` (the browser refuses to attach the cookie on cross-site requests) and Django's CSRF token (the frontend echoes the `csrftoken` cookie back in an `X-CSRFToken` header; an attacker's site can't read that cookie to forge the header).

The glue is a custom authentication class, `CookieJWTAuthentication` — DRF normally reads the token from the `Authorization` header, so we subclass and override it to read from the cookie instead. Same **Strategy** shape as permissions: auth is a pluggable object.

**Short access token + long refresh token:** the access token expires quickly (minutes), so a leaked one is nearly worthless; the refresh token, sent only to the refresh endpoint, mints new ones silently. Security and UX both satisfied.

---

## 9. Pattern: Fat service functions, thin views

Money logic does **not** live in views. [payments/services.py](../Backend/payments/services.py) holds `mark_payment_captured()`, `mark_payment_failed()`, `mark_payment_refunded()`, and the view is a thin shell that authenticates, parses, and delegates.

Why this matters: `mark_payment_captured` is called from **three** places — the browser's `/verify/` call, the Razorpay webhook, and the reconciler cron. If the capture logic lived in the view, the webhook and the cron would each need their own copy, and they would drift apart. Three copies of "mark an order paid" is three chances to get it wrong.

**Rule: a view's job is HTTP. A service's job is the domain.** The service knows nothing about requests or responses, which also makes it trivially unit-testable — no HTTP client needed.

Related: `transaction.on_commit(...)`. Confirmation emails are fired *after* the transaction commits, not inside it. Send inside, and a subsequent rollback leaves the customer holding an email for an order that doesn't exist. You can't un-send an email, so **never take an irreversible external action inside a transaction that can still roll back.**

---

## 10. Pattern: Guardrails — limits, throttles, fail-closed

Centralized constants (`spices_backend/limits.py`) rather than magic numbers scattered around: `MAX_ITEM_QUANTITY`, `MAX_ORDER_TOTAL`, `SHIPPING_CHARGE_NET`, `FREE_SHIPPING_THRESHOLD`, `COD_MAX_VALUE`. (Why the shipping variable was renamed is its own lesson: [lessons/01](lessons/01_when_a_config_value_changes_meaning.md).)

**Throttling** is per-action, chosen at runtime:
```python
def get_throttles(self):
    if self.action == 'create':
        return [OrderRateThrottle(), OrderDailyThrottle()]
    return super().get_throttles()
```
Browsing is cheap; placing orders touches money and inventory, so it gets a tighter per-minute and per-day budget. Rate limits should be proportional to the cost and blast radius of the operation, not uniform across the API.

**Validate the same thing at every layer.** Quantity is clamped in the React cart, again in the cart API, and again at order creation. The frontend check is UX (instant feedback, no round trip); the backend checks are *security* — a client can be bypassed with `curl` in ten seconds. **Client-side validation is never a security control.** Say this sentence in the interview.

---

## 11. Bonus: the tool-calling agent (`assistant`)

The AI shopping assistant is a **tool-calling agent loop**, and it's worth understanding because it's the most modern pattern in the codebase.

The LLM is not given database access. It's given a **catalog of tools** — plain Python functions with a name, a description, and a JSON schema for their arguments (`tool_search_products`, `tool_get_order_status`, `tool_get_cart`, …). The loop is: send the user's message + the tool list → the model replies "call `tool_get_order_status(order_id=5)`" → **our code** executes that function, applying our own permission checks → feed the result back → repeat until the model produces prose.

Two things make it safe, and they're the interesting part:
- **The tools enforce authorization, not the model.** `tool_get_order_status(user, args)` takes the authenticated user and scopes the query to *their* orders. Even if the user prompt-injects the model into asking for order #999, the tool refuses. **The LLM is untrusted input, so it sits on the same side of the wall as the browser.**
- **Read tools execute; write tools only *propose*.** `tool_search_products` runs server-side, but `build_add_to_cart` merely *builds* an action the frontend then confirms with the user. The model can never silently spend money.

---

## 12. Pattern: Management commands — the Command pattern

You keep seeing `python manage.py reconcile_payments` / `rollup_analytics` / `run_scheduler`. Each of those is a **class** in `<app>/management/commands/<name>.py`:

```python
class Command(BaseCommand):
    help = "Auto-cancel + restock ONLINE orders unpaid past the TTL."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        ...   # the actual work
```

> **🧩 OOP — this is inheritance + override again, nothing new.** `Command` inherits from `BaseCommand` (Django's parent for CLI commands). Django already knows how to parse the command line, show `--help`, and handle errors — all inherited. The *one* method you override is `handle()`, which is the hook Django calls to run your logic. The filename becomes the command name. That's the entire contract.

This is the **Command pattern**: an operation packaged as an object so it can be invoked from anywhere — a human at a shell, a cron entry, the `scheduler` container, or a test — without a web request. It's the counterpart to "fat services": a command is a *thin CLI shell* around a service function, exactly as a view is a *thin HTTP shell* around the same function. `reconcile_payments` the command and the `/verify/` endpoint both call into the same payment-capture service (§5, §9). One brain, many mouths.

---

## 13. Pattern: Middleware — a callable object wrapping every request

Middleware is code that runs on *every* request, before it reaches any view. `spices_backend/middleware.py`:

```python
class AbuseGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response       # runs ONCE at startup

    def __call__(self, request):               # runs on EVERY request
        if is_blocked(get_client_ip(request)):
            return JsonResponse({"error": "Access denied."}, status=403)
        return self.get_response(request)      # hand off to the next layer
```

> **🧩 OOP — `__init__` and `__call__`, the two "dunder" methods.** Names wrapped in double underscores are **special methods** Python calls for you at defined moments. `__init__` is the **constructor** — it runs once when the object is *created*, to set it up (here, storing the next layer to call). `__call__` is what runs when you *use the object like a function* — `middleware(request)`. So this class turns an object into something callable: Django builds it once at boot (`__init__`), then invokes it per request (`__call__`). It's a function that gets to keep state between the setup and the calls.

The interesting design point is the contrast with §5. This middleware **fails *open***: the real class wraps the block in `try/except: pass` so that if the block-check errors (a Redis hiccup), the request proceeds. The webhook (§5) **fails *closed***: a missing secret rejects everything. **Same engineering instinct, opposite default, because the stakes are mirror images** — wrongly *blocking* a real shopper over a cache blip loses a sale, while wrongly *allowing* a webhook forges a payment. You choose the failure direction by asking "which mistake is cheaper?"

---

## 14. Pattern: Config as code — the settings resolver, 12-factor, fail-fast

Nothing environment-specific is hard-coded. Secrets and toggles come from **environment variables**, read in `settings.py` via `python-decouple`:

```python
RAZORPAY_TEST_MODE = config('RAZORPAY_TEST_MODE', default=True, cast=bool)
if RAZORPAY_TEST_MODE:
    RAZORPAY_KEY_ID = config('RAZORPAY_TEST_KEY_ID')
else:
    RAZORPAY_KEY_ID = config('RAZORPAY_LIVE_KEY_ID')
# ... then a guard:
if RAZORPAY_TEST_MODE and RAZORPAY_KEY_ID.startswith('rzp_live_'):
    raise ImproperlyConfigured("test mode is on but a LIVE key is configured")
```

Two patterns stacked:

- **12-factor config.** The *same image* runs in dev and prod; only the injected env vars differ. Code never contains a key. `RAZORPAY_TEST_MODE` is a single switch that resolves *which* pair of keys the rest of the code reads — every other module only ever touches the resolved `RAZORPAY_KEY_ID`, never the raw test/live names. That's the **resolver / indirection** idea: callers depend on one stable name; the decision of what it points to is made in exactly one place.
- **Fail-fast boot guards.** `raise ImproperlyConfigured(...)` runs at *import time* — the instant Django starts, before a single request is served. A dangerous misconfiguration (test flag on, live key loaded) **crashes the process immediately** rather than quietly taking real payments in test mode. Loud failure at startup beats silent wrongness in production. (This is also the trap the CLAUDE.md warns about: the guard is doing its job — it's *supposed* to refuse to boot.)

**Rule: push every environment difference to config, and make an invalid config unbootable, not merely wrong.**

---

## 15. Pattern: Killing the N+1 on reads — `select_related` / `prefetch_related`

§4 mentioned N+1 on *writes* (`bulk_update`). The far more common version is on *reads*, and it's the single most likely performance question you'll get.

The trap:

```python
for order in Order.objects.all():      # 1 query for the orders
    print(order.user.email)            # + 1 query PER order to fetch its user
```

100 orders → **101 queries**. That's N+1: one query, then one more for each row's related object. The fixes, both used in this codebase's list views:

```python
Order.objects.select_related('user')            # SQL JOIN — for ForeignKey (one related row)
Order.objects.prefetch_related('items')         # 2nd query + Python join — for reverse/many
```

- **`select_related`** follows a *forward* ForeignKey with a SQL `JOIN`, pulling the related row in the *same* query. Use it for "each order has *one* user."
- **`prefetch_related`** runs *one extra* query for all the related rows and stitches them together in Python. Use it for "each order has *many* items" (a JOIN there would multiply rows).

101 queries collapse to 2. Pair this with **pagination** (DRF's `PageNumberPagination` returns 20 rows at a time, not the whole table) and a list endpoint stays fast no matter how big the table grows. **Whenever a serializer reaches across a relation, the queryset must pre-fetch it** — that's the rule the two names encode.

---

## 16. Pattern: Swappable backends — the provider/adapter pattern

The assistant and AI-search don't hard-depend on one LLM vendor. `MODEL_PROVIDER` / `ASSISTANT_MODEL_PROVIDER` select an implementation at runtime, and the calling code talks to a *uniform interface* — "given messages, return a completion" — regardless of which vendor answers. Same shape for voice: `assistant/stt.py` has one `transcribe()` function, and `STT_PROVIDER` picks which client answers it — the hosted Voxtral model (`voxtral_client.py`, the default) or the self-hosted whisper container (`whisper_client.py`). If Voxtral fails and `STT_FALLBACK_TO_WHISPER` is on, the same call is retried on whisper.

This is the **Adapter / Strategy pattern at the integration boundary** (the same shape as permissions in §2 and cookie-auth in §8, just applied to an external service instead of a policy). Each provider is wrapped so its quirky, vendor-specific API is presented through *our* consistent method signature. A real quirk the adapters hide: whisper needs the literal word `auto` to detect the language, while the hosted API rejects `auto` and detects only when the field is left out. `stt.resolve_language()` produces one answer and each client translates it. The payoff: swapping one chat model for another, or self-hosted whisper for a cloud STT, is a config change plus one new adapter — **no caller changes**. Isolating a third party behind an interface you own is how you avoid a vendor rewriting themselves into every file of your codebase.

---

## Quickfire recap

| Pattern | Where | The one-line answer |
|---|---|---|
| Modular monolith (apps) | project root | Bounded contexts, one deploy |
| Active Record (Model) | `models.py` | Class = table; migrations version the schema |
| `Decimal` for money | everywhere | Floats lose paisa |
| Template Method (ViewSet) | `views.py` | Framework owns the skeleton; you override hooks |
| Row-level auth (`get_queryset`) | `views.py` | Filter at the source; leaking becomes inexpressible |
| Strategy (permissions/auth) | `permission_classes` | Policy as a pluggable object |
| Boundary validation (Serializer) | `serializers.py` | Untrusted JSON → trusted Python |
| Atomic + `select_for_update` | `orders`, `cart`, `payments` | Serialize concurrent writes; kill the race |
| Idempotent handlers | `payments/services.py` | Same event twice = same state once |
| Observer (signals) | `signals.py` | Save a product → cache busts itself |
| Cache-aside + prefix bust | `products/cache.py` | Lazy fill; key includes every input |
| HttpOnly cookie JWT | `users/` | XSS can't read the token |
| Service layer | `payments/services.py` | Views do HTTP; services do domain |
| Fail-closed | webhook secret | Missing control ⇒ feature off, not open |
| `on_commit` for emails | `payments/services.py` | Never do irreversible things inside a transaction |
| Tool-calling agent | `assistant/` | LLM output is untrusted input; tools hold the authz |
| Command pattern | `management/commands/` | Package an operation so cron/CLI/tests can run it without HTTP |
| Middleware (callable object) | `spices_backend/middleware.py` | Runs per request; `__init__` once, `__call__` each time |
| Fail-open vs fail-closed | middleware vs webhook | Pick the failure direction by which mistake is cheaper |
| 12-factor config + boot guards | `settings.py` | Env-driven; an invalid config refuses to boot, doesn't run wrong |
| `select_related`/`prefetch_related` | list views | Kill N+1 reads: JOIN for one, prefetch for many |
| Adapter (swappable providers) | `assistant/`, STT | Wrap a vendor behind your own interface; swapping is a config change |

---

## A note on how to keep learning this

You will not absorb this by reading it. The move that makes it stick: **pick one section, open the real file it links to, and run the §0.5 procedure on the class there** — read the `class X(Parent):` line, jump to the parent, find the overridden method, and confirm with your own eyes that the pattern the doc describes is the code in front of you. Do that for `Product`, then `OrderViewSet`, then `AbuseGuardMiddleware`, and the vocabulary stops being words and becomes something you can see.
