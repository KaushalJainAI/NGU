# Database Schema Documentation

Core models organized by app. Field lists focus on non-obvious or important fields;
standard `created_at`/`updated_at` timestamps are omitted unless notable.

---

## 1. Users App

| Model | Purpose | Key Fields |
|-------|---------|------------|
| **User** | Custom user extending `AbstractUser` | `email` (login field, unique), `name`, `phone`, `address`, `city`, `state`, `pincode`, `profile_picture` |
| **PasswordResetOTP** | OTP tokens for password reset flow | `user` (FK), `otp_code`, `reset_token`, `expires_at`, `is_used`, `failed_attempts` |

`email` is the `USERNAME_FIELD` — users log in with email, not username.

---

## 2. Products App

| Model | Purpose | Key Fields |
|-------|---------|------------|
| **Category** | Organizational folder for spices | `name`, `slug`, `image`, `is_active` |
| **Product** | Individual spice item | `category` (FK, primary shelf), `extra_categories` (M2M — also list under these shelves), `spice_form`, `price`, `discount_price`, `stock`, `low_stock_threshold` (default 5 — warns admin dashboard + daily digest), `weight`, `unit`, `origin_country`, `organic`, `shelf_life`, `ingredients`, `image`, `thumbnail`, `is_active`, `is_featured`, `badge`, `sections` (M2M via `ProductSectionPlacement`) |
| **ProductVariant** | A specific packaging/size of a Product (e.g. 100g, 500g, 1kg) | `product` (FK), `weight`, `unit`, `price`, `discount_price`, `stock`, `sku`, `slug`, `is_default`, `is_active`, `display_order` |
| **ProductImage** | Gallery images for a product | `product` (FK), `image`, `alt_text` |
| **ProductCombo** | Bundle of multiple products | `name`, `slug`, `title`, `subtitle`, `price`, `discount_price`, `image`, `thumbnail`, `is_active`, `is_featured`, `badge`, `weight`, `unit`, `sections` (M2M) |
| **ProductComboItem** | Junction table for combo contents | `combo` (FK), `product` (FK), `quantity` |
| **ProductSection** | Homepage display group (Trending, New, etc.) | `name`, `slug`, `section_type`, `description`, `icon`, `display_order`, `max_products`, `is_active` |
| **ProductSectionPlacement** | Through model for Product ↔ ProductSection with per-section ordering | `product` (FK), `section` (FK), `position` (lower = first within that section) |
| **ProductSearchKB** | LLM-generated search synonyms for a product | `product` (OneToOne), `synonyms` (JSONField list), `last_updated` |
| **ProductComboSearchKB** | LLM-generated search synonyms for a combo | `combo` (OneToOne), `synonyms` (JSONField list), `last_updated` |

### Product sizing note
`ProductVariant` is the unit of sale. Each product can have multiple variants (sizes).
The legacy `price`/`stock`/`weight`/`unit` fields on `Product` are kept for
backward compatibility; every product has a backfilled `is_default=True` variant
mirroring those values. Cart and order items reference the variant, not just the product.

### ProductSection ordering
`ProductSection.display_order` controls the order of sections on the homepage.
`ProductSectionPlacement.position` controls the order of products *within* a section.
Both are admin-draggable via `django-admin-sortable2`.

---

## 3. Cart App

| Model | Purpose | Key Fields |
|-------|---------|------------|
| **Cart** | One cart per user | `user` (OneToOne PK), `total_price` (property), `total_items` (property) |
| **CartItem** | A line in the cart | `cart` (FK), `product` (FK, nullable), `variant` (FK to `ProductVariant`, nullable), `combo` (FK, nullable), `item_type` (product/combo), `quantity` |
| **Favorite** | User wishlist | `user` (FK), `product` (FK) |

`CartItem` uses DB constraints to enforce: either product or combo is set (never both),
variant is always set for product lines (defaults to product's default variant),
quantity ≥ 1, and no duplicate (cart, variant) or (cart, combo) pairs.

---

## 4. Payments App

| Model | Purpose | Key Fields |
|-------|---------|------------|
| **Payment** | Gateway transaction record for an online order | `order` (OneToOne FK), `payment_id` (unique, gateway-assigned), `payment_gateway` (razorpay/cod/stripe), `amount`, `status` (pending/completed/failed/refunded), `transaction_details` (JSONField — full gateway response) |
| **PaymentMethod** | Saved payment reference for a user | `user` (FK), `payment_type` (UPI/CARD/NETBANKING/WALLET), `is_default`, `is_active`, `upi_id`, `card_last_four`, `card_brand`, `card_expiry_month/year`, `gateway_token`, `bank_name`, `wallet_provider` |

`Payment.order` is OneToOne — each order has at most one gateway payment record.  
`PaymentMethod` never stores raw card numbers; only the last 4 digits and the gateway's opaque token are kept. `is_default` is enforced via `save()` — setting one default clears all others for the same user in a transaction. Soft delete: destroy sets `is_active=False`.

## 5. Orders App

| Model | Purpose | Key Fields |
|-------|---------|------------|
| **Order** | Full invoice | `order_id` (UUIDField, auto-generated), `user` (FK), `status` (pending/confirmed/processing/shipped/delivered/cancelled/delivering), `payment_method` (COD/ONLINE/razorpay), `payment_status`, `subtotal`, `discount_amount`, `shipping_charge`, `tax`, `total_amount`, `coupon` (FK, nullable), `delivery_bill` (FileField, **private storage** — admin-only courier receipt, never a public CDN URL), `delivery_bill_uploaded_at` |
| **OrderItem** | Line item in an order | `order` (FK), `product` (FK, PROTECT, nullable), `variant` (FK to `ProductVariant`, PROTECT, nullable), `combo` (FK, PROTECT, nullable), `item_type`, `product_name`, `product_weight` (snapshot), `quantity`, `price`, `discounted_price`, `discount_amount`, `tax_amount`, `final_price` |

`Order.order_id` is a full UUID (`uuid.uuid4()`), stored as a `UUIDField`.
`OrderItem` snapshots `product_name` and `product_weight` at order time so historical
orders remain accurate even if the product is later renamed or repriced.

---

## 6. Analytics App

| Model | Purpose | Key Fields |
|-------|---------|------------|
| **UserEvent** | Single behavioral interaction | `user` (FK), `event_type` (view/click/add_to_cart/remove_from_cart/favorite/search/purchase), `product` (FK, nullable), `combo` (FK, nullable), `category` (FK, nullable), `created_at` |

Events are ingested via `POST /api/events/` and aggregated by `products/personalization.py`
to power `GET /api/recommendations/`.

---

## 7. Assistant App

| Model | Purpose | Key Fields |
|-------|---------|------------|
| **AssistantConversation** | A chat thread (AI + admin) | `conversation_id` (UUID), `user` (FK, nullable in schema but always set — chat is login-only), `anon_session` (vestigial, unused), `title`, `status` (active/resolved/archived), `needs_human`, `assigned_to` (FK to User, nullable) |
| **AssistantMessage** | One turn in a conversation | `conversation` (FK), `role` (user/assistant/tool/system/admin), `content`, `sender_name`, `meta` (JSON audit), `created_at` |

Conversations are scoped to the authenticated user (chat is login-only) — the agent cannot read another user's thread. Human admins participate directly via the `admin` role. This is the single conversation system (the old `support.ChatSession` chat was removed).

---

## 8. Support App

| Model | Purpose | Key Fields |
|-------|---------|------------|
| **ContactSubmission** | Contact form entry | `name`, `email`, `phone`, `subject`, `message`, `status` (new/read/replied/closed), `user` (FK, nullable), `admin_notes`, `replied_at` |

The order-scoped `ChatSession` / `ChatMessage` models have been removed — all
conversations now live in the `assistant` app (see section 7).

---

## 9. Reviews App

| Model | Purpose | Key Fields |
|-------|---------|------------|
| **Review** | Verified-purchase rating for a product or combo | `item_type` (product/combo), `product` (FK, nullable), `combo` (FK, nullable), `user` (FK), `rating` (1–5), `title`, `comment`, `is_verified_purchase`, `is_hidden` (admin moderation — hidden reviews are excluded from public listings), `created_at` |

One review per `(user, product)` and per `(user, combo)`, enforced by partial
`UniqueConstraint`s. `is_verified_purchase` is set when the reviewer has a delivered
order containing the item; `is_hidden` is toggled by admins via `POST
/api/reviews/{id}/set-hidden/`.

---

## 10. Admin Panel App

| Model | Purpose | Key Fields |
|-------|---------|------------|
| **Coupon** | Discount codes | `code` (unique), `discount_percent` (1–100), `is_active`, `valid_until`, `max_usage` (nullable), `usage_count`, `minimum_order_amount` |
| **ReceivableAccount** | Payment collection accounts | `account_holder_name`, `upi_id` (unique), `bank_name`, `bank_account_number`, `ifsc_code`, `branch_name`, `contact_email`, `contact_phone`, `is_active`, `is_default` |
| **Policy** | Editable policy content | `type` (shipping/return, unique), `content` |

`Coupon.discount_percent` is always a percentage (1–100). There is no fixed-amount discount type.
`ReceivableAccount.is_default` enforces at most one default via a `save()` override that clears other defaults.

---

## Architectural Principles

1. **Order ID is a UUID** — `Order.order_id` is a full `uuid.uuid4()` UUID, not a sequential integer or formatted string. This prevents enumeration attacks.
2. **Price snapshots in OrderItem** — `product_name`, `product_weight`, `price`, and `final_price` are snapshotted at order time. Historical orders never change when products are updated.
3. **Variant-aware cart and orders** — `CartItem` and `OrderItem` carry a `variant` FK so the exact packaging/size purchased is recorded.
4. **DB-level constraints** — models use `CheckConstraint` and `UniqueConstraint` for positive quantities, exclusive item-type references, unique favorites, and single-default variants.
5. **Soft protection on deletion** — `Product`/`ProductVariant`/`ProductCombo` use `on_delete=PROTECT` on `OrderItem` to preserve historical order data.
6. **Soft delete for catalog items** — `Product` and `Category` destroy endpoints set `is_active=False` rather than hard-deleting. Only active items are shown to non-staff. This preserves historical review and order data.
7. **Variant slug fallback** — product detail lookup by slug checks `Product.slug` first, then `ProductVariant.slug`. If a variant slug matches, the parent product is returned with a `selected_variant_id` hint so the frontend can pre-select the right size.
8. **Multilingual columns** — `django-modeltranslation` adds per-language columns for `Product` and `Category` translatable fields. Empty translations fall back to English automatically.
9. **Validated `ImageField`s** — every image column (category, product, product-gallery, combo, user profile picture) shares one validator chain from `spices_backend/validators.py`: size cap, extension allow-list (no `.svg`), and a Pillow content-verify on fresh uploads. See `docs/ARCHITECTURE.md` §Security. Wired in by validator-only migrations `products/0034` and `users/0009`.
10. **Product on multiple shelves** — `Product.category` is the canonical shelf; `Product.extra_categories` (M2M to `Category`) lists the same product under additional shelves without duplicating the row.
