# Backend Architecture

This document explains the design principles, data flow, and non-obvious implementation details.

---

## Design Principles

### 1. **Layered Architecture**
```
┌─────────────────────────────────────────────────┐
│                  API Layer                       │
│           (views.py - ViewSets)                  │
├─────────────────────────────────────────────────┤
│              Serialization Layer                 │
│    (serializers.py - Data transformation)        │
├─────────────────────────────────────────────────┤
│               Business Logic                     │
│        (models.py - Methods on models)           │
├─────────────────────────────────────────────────┤
│                Data Layer                        │
│          (Django ORM → PostgreSQL)               │
└─────────────────────────────────────────────────┘
```

### 2. **Permission-Based Access Control**
Each ViewSet declares explicit permissions. The pattern:
- **Public read, Admin write**: Products, Categories, Combos
- **Authenticated only**: Cart, Orders, User Profile
- **Admin only**: Dashboard, Coupons, Receivable Accounts

### 3. **Slug-Based Lookups**
Products and Combos use slugs instead of IDs in URLs for SEO-friendly URLs.
```python
# Instead of: /api/products/123/
# We use:     /api/products/organic-turmeric-powder/
lookup_field = 'slug'
```

### 4. **Intelligent Caching**
Redis caches are scoped with the `ngu:` prefix and invalidated on writes:
- `ngu:products:*` — product listing and detail
- `ngu:categories:*` — category listing
- `ngu:sections:*` — homepage sections
- `ngu:search:corpus:v1` — full search corpus (names + synonyms)
- `ngu:dashboard:*` — dashboard statistics

---

## Application Flow

### User Registration → Order Placement

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│Register │────▶│  Login  │────▶│Add Cart │────▶│Checkout │────▶│  Order  │
└─────────┘     └─────────┘     └─────────┘     └─────────┘     └─────────┘
     │               │               │               │               │
  users/          JWT            cart/           orders/          orders/
  views.py       tokens         views.py        views.py         models.py
```

### Order Lifecycle

```
PENDING → CONFIRMED → PROCESSING → SHIPPED → DELIVERED
    │         │            │           │          │
    └─────────┴────────────┴───────────┴──────────┘
              Status updated via admin panel
```

---

## Key Implementation Details

### 1. Cart: Product vs Combo Items

The cart supports both products and combos through **separate fields**, with a `variant` FK for product lines:
```python
class CartItem(models.Model):
    product = models.ForeignKey(Product, null=True)           # Regular product
    variant = models.ForeignKey(ProductVariant, null=True)    # The specific size/packaging
    combo = models.ForeignKey(ProductCombo, null=True)        # Combo pack
    # DB CheckConstraint: either product OR combo is set, never both
    # DB constraint: variant is always set for product lines
```

**Why?** Combos have different pricing logic (bundled discount) and different stock tracking (per-product in combo). `ProductVariant` is the actual unit of sale — it tracks the exact size and price purchased (100g vs 500g, etc.).

### 2. Order ID

Orders use a UUID primary key:
```python
order_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
```

**Why?** Prevents sequential enumeration of orders (a common BOLA vector).

### 3. Product Images: Main vs Gallery

Products have TWO image sources:
1. **Main image** (`Product.image`) — Primary display image
2. **Gallery images** (`ProductImage` model) — Additional views

```python
class Product(models.Model):
    image = models.ImageField()  # Main image

class ProductImage(models.Model):
    product = ForeignKey(Product)
    image = models.ImageField()  # Gallery images
```

All five `ImageField`s (category, product, product-gallery, combo, user profile
picture) run the same upload validator chain — see **Security Considerations §7**.

### 3b. Product on Multiple Category Shelves

A product has one primary `category` (FK) plus an optional `extra_categories`
ManyToMany so it can appear on several category shelves at once (e.g. "Chat Masala"
under both *Blended Spices* and *Chaat & Snacks*):

```python
class Product(models.Model):
    category = models.ForeignKey(Category, ...)              # primary shelf
    extra_categories = models.ManyToManyField(Category, ...)  # also list here
```

Category-listing queries union `category` and `extra_categories` so the product
surfaces on every shelf it belongs to, while `category` stays the canonical one
for breadcrumbs/SEO.

### 4. Combo Pricing

Combos store `price` (the combo price) and `discount_price` (optional discounted price).
The `total_original_price` property computes the sum of individual product prices:
```python
@property
def final_price(self):
    return self.discount_price if self.discount_price else self.price

@property
def discount_percentage(self):
    if self.discount_price and self.discount_price < self.price:
        return int(((self.price - self.discount_price) / self.price) * 100)
    return 0
```

### 5. Media Storage: Cloudinary-First

Media files (product/category/profile images, chat attachments) are stored on
**Cloudinary** when `USE_CLOUDINARY=True` (the production default). Static files
(CSS/JS) use AWS S3 when `USE_S3=True`, or the local filesystem otherwise.

```python
# Precedence for the default (media) storage backend:
#   USE_CLOUDINARY  →  Cloudinary  (preferred)
#   USE_S3          →  AWS S3
#   neither         →  local filesystem
```

Cloudinary is a **hard startup dependency** — if `CLOUDINARY_CLOUD_NAME`,
`CLOUDINARY_API_KEY`, or `CLOUDINARY_API_SECRET` are missing the backend will
crash-loop on boot.

See `Backend/docs/S3_STORAGE.md` for full storage configuration details.

### 6. Unified Chat (AI + Human Admin)

There is one conversation system for everything — AI shopping help, voice ordering,
and human-admin support all share the same thread (`AssistantConversation` /
`AssistantMessage`). The old order-scoped `support.ChatSession` system was removed.

Voice input is transcribed server-side via `POST /api/assistant/transcribe/`,
then flows through `/chat/` as text — the browser Web Speech API is no longer
used. `assistant/stt.py` dispatches to one of two backends on `STT_PROVIDER`:
Mistral Voxtral Mini Transcribe over OpenRouter (default — ~1s per utterance,
$0.003/min) or the self-hosted whisper.cpp container (`small-q5`, free but ~20s
per second of audio on the deploy box), which also serves as the fallback. See
`docs/ASSISTANT.md`.

**Why?** A single inbox for admins and a single widget for customers. Order context
is carried as text in the conversation rather than a rigid order↔thread FK, so a
customer can ask about anything in one place. See `docs/ASSISTANT.md`.

### 7. AI Shopping Assistant

The `assistant` app provides a tool-calling AI agent at `POST /api/assistant/chat/`.
The chat view is **login-only** (`IsAuthenticated`) — the whole assistant (shopping
Q&A, voice, human-admin support) is gated behind login by design. The view is the
trust boundary that supplies the authenticated user to the agent. Conversations are
persisted in `AssistantConversation` and `AssistantMessage`, scoped by user.

> The `anon_session` field and its guest-lookup branch are a **vestigial leftover**
> from an earlier anonymous-chat design; the view never admits unauthenticated
> traffic, so that path is dead. Don't "fix" the endpoint to `AllowAny`.

### 8. Behavioral Analytics + Recommendations

The `analytics` app ingests `UserEvent` rows (view, click, add-to-cart, purchase, etc.)
via `POST /api/events/`. These events feed `products/personalization.py` which returns
personalized product recommendations at `GET /api/recommendations/`.

### 9. Multilingual Content (django-modeltranslation)

Product and Category fields (`name`, `description`, `ingredients`, etc.) have
per-language database columns generated by `django-modeltranslation`. Language is
selected at request time via `?lang=` query parameter or `X-Language` header.
Supported: `en`, `hi`, `hinglish`, `gu`, `mr`, `pa`. Empty translations fall back
to English automatically.

---

## Module Responsibilities

| App | Responsibility |
|-----|----------------|
| `users` | Authentication, profiles, JWT tokens, Google OAuth |
| `products` | Catalog (products, combos, categories, images, sections, search KB) |
| `cart` | Shopping cart with stock validation, favorites |
| `orders` | Order creation, status, history, coupon redemption |
| `payments` | Payment processing (Razorpay), saved payment methods |
| `reviews` | Verified-purchase product ratings and reviews; admin `is_hidden` moderation |
| `admin_panel` | Dashboard stats, coupons, policies, receivable accounts, global admin search, bulk product ops + CSV import/export |
| `support` | Contact form submissions (order-scoped live chat was removed — all conversations are now in `assistant`) |
| `assistant` | AI shopping assistant (tool-calling agent, multilingual) + a separate read-only **admin business-data** persona (`/admin-chat/`) |
| `analytics` | Behavioral event ingest; source data for recommendations; scheduled owner email digests (daily/weekly) |

---

## Database Relationships

```
User ──┬── Cart ──── CartItem ──┬── Product ── ProductVariant ◀─┐
       │                        │                                 │
       │                        ├── ProductVariant ───────────────┘
       │                        └── ProductCombo ── ProductComboItem ── Product
       │
       ├── Order ── OrderItem ──┬── Product
       │                        ├── ProductVariant
       │                        └── ProductCombo
       │
       ├── Review ── Product
       │
       ├── AssistantConversation ── AssistantMessage
       │
       └── UserEvent ──┬── Product (optional)
                       └── ProductCombo (optional)

Category ─┬─ Product ──┬── ProductVariant (unit of sale)
          │            └── ProductImage (gallery)
          └─ (Product.extra_categories M2M — same product on extra shelves)
```

---

## Security Considerations

1. **Input Validation**: Cart quantities must be positive integers (checked in `add_item`)
2. **Stock Check**: Orders validate stock before creation
3. **Owner Check**: Users can only access their own carts, orders, profiles
4. **Admin Check**: Dashboard/coupons require `is_staff=True`
5. **Payment Verification**: Razorpay signatures verified server-side
6. **Assistant Isolation**: Conversation threads are scoped to the authenticated user (chat is login-only); the agent cannot read another user's data
7. **Image Upload Hardening** (`spices_backend/validators.py`, wired into all five `ImageField`s): every fresh upload passes
   - `validate_file_size` — reject > 500 MB;
   - `validate_image_extension` — allow-list `.jpg/.jpeg/.png/.webp/.gif`; **`.svg` is deliberately excluded** (SVG is XML and can carry inline `<script>` → stored-XSS, and can't be raster-verified);
   - `validate_image_content` — Pillow `Image.verify()` confirms the bytes are a real decodable raster image, defeating the "rename `evil.html` → `evil.png`" masquerade.

   All three run **only on fresh `UploadedFile`s**; already-stored Cloudinary/S3 `FieldFile`s (no in-name extension / remote bytes) are skipped so re-saves don't trigger needless network fetches or false rejects. The content check **fails open** if Pillow is unavailable (the extension allow-list still applies). Wired in by validator-only migrations `products/0034` and `users/0009`.

---

## Extending the Application

### Adding a New Feature

1. **Create app**: `python manage.py startapp feature_name`
2. **Define models** in `models.py`
3. **Add serializers** in `serializers.py`
4. **Create ViewSet** in `views.py`
5. **Register route** in `urls.py` via router
6. **Run migrations**: `python manage.py makemigrations && migrate`

### Adding a New API Endpoint to Existing ViewSet

Use `@action` decorator:
```python
class ProductViewSet(viewsets.ModelViewSet):
    @action(detail=False, methods=['get'])
    def featured(self, request):
        # Custom endpoint: GET /api/products/featured/
        return Response(...)
```
