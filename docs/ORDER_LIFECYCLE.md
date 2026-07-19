# Order Lifecycle

Everything that happens from "Place Order" to delivery, including pricing rules, stock
management, and cancellation.

---

## Status Workflow

```
PENDING ──▶ CONFIRMED ──▶ PROCESSING ──▶ SHIPPED ──▶ DELIVERED
   │              │              │              │
   └──────────────┴──────────────┴──────────────┴──▶ CANCELLED
```

`DELIVERING` is an intermediate state used by some delivery integrations, sitting between
`SHIPPED` and `DELIVERED`. Orders in `delivered`, `cancelled`, or `delivering` cannot be
cancelled.

Status transitions are driven by admin updates (`PATCH /api/orders/{id}/`). There is no
automatic status progression — the admin panel's order detail view provides the dropdown.

---

## Order Creation Flow (`POST /api/orders/`)

`OrderViewSet.create` in `orders/views.py`. The entire flow is atomic with one deliberate
exception noted below.

### 1. Pre-transaction validation

```
Validate cart exists and has items
  └── If no cart or empty cart → 400

Validate coupon (if provided)
  └── Check is_active, valid_until, max_usage, minimum_order_amount
  └── If invalid → 400
```

Coupon validation happens **before** the transaction to fail fast without locking any rows.

### 2. Build order items (pre-transaction)

Cart items are read and validated outside the transaction. For each cart item:

| Item type | Price source | Weight source | Stock source |
|-----------|-------------|---------------|-------------|
| Product with variant | `variant.final_price` | `variant.formatted_weight` | `variant.stock` |
| Product without variant (legacy) | `product.final_price` | `product.formatted_weight` | `product.stock` |
| Combo | `combo.final_price` | `f"{combo.weight}{combo.unit}"` | `combo.stock` (default 999) |

If any item's available stock is less than the requested quantity, the entire request is
rejected with a `400` before the transaction opens.

### 3. Pricing calculation

Applied to the collected `subtotal`:

```
subtotal            = Σ (item_price × quantity)
total_discount      = subtotal × (coupon.discount_percent / 100)
discounted_subtotal = subtotal − total_discount
shipping_charge     = ₹0   if discounted_subtotal ≥ FREE_SHIPPING_THRESHOLD
                    = SHIPPING_CHARGE  otherwise
tax                 = discounted_subtotal × DEFAULT_TAX_RATE% (or per-line tax_rate if set)
total_amount        = discounted_subtotal + shipping_charge + tax
```

**Key points:**
- Free shipping threshold is checked against the **post-discount** subtotal.
- `SHIPPING_CHARGE` (default ₹69), `FREE_SHIPPING_THRESHOLD` (default ₹500), and
  `DEFAULT_TAX_RATE` (default 5%) are env-configurable — see `spices_backend/limits.py`.
- Tax is on the **post-discount** subtotal; shipping is not taxed.
- No tax on shipping.

### 4. Atomic transaction

Everything inside `with transaction.atomic()`:

#### 4a. Create Order row

```python
Order.objects.create(
    user=request.user,
    subtotal=subtotal,
    discount_amount=total_discount,
    shipping_charge=shipping_charge,
    tax=tax,
    total_amount=total_amount,
    coupon=coupon,
    status='pending',
    ...address fields from serializer...
)
```

#### 4b. Create OrderItems with proportional discounts

The total discount is distributed to line items proportionally to their share of the
subtotal, so the numbers always add up:

```python
item_discount = (item_total / subtotal) × total_discount
discounted_item_price = item_price − (item_discount / quantity)
item_tax = discounted_item_price × quantity × 5%
```

Each `OrderItem` stores a **snapshot** of `product_name` and `product_weight` at the time
of order. Historical orders remain accurate even if the product is later renamed, repriced,
or deleted.

#### 4c. Stock decrement (variant-first, with product mirror)

Stock lives on `ProductVariant`. `Product.stock` is a legacy mirror kept in sync for
product listing pages.

```
For each product line item:
  if variant:
    variant_updates[variant.pk] += quantity
    if variant.is_default:
      product_updates[variant.product_id] += quantity   ← mirror
  else (legacy, no variant):
    product_updates[product.pk] += quantity

Batch reduce variant stock (select_for_update to prevent race conditions)
Batch reduce product stock (clamp at 0, never go negative)
```

Combos have no `stock` field — their availability is controlled only by `is_active`.
There is nothing to decrement for combo lines.

The `select_for_update()` lock on variants and products prevents two concurrent orders
from both seeing sufficient stock and both succeeding.

#### 4d. Coupon usage count

```python
coupon.usage_count = F('usage_count') + 1
coupon.save(update_fields=['usage_count'])
```

`F()` expression avoids a race condition where two orders applying the same coupon
simultaneously both read `usage_count=1`, write `2`, and report `2` when the correct
answer is `3`.

#### 4e. Cart clearing

The cart is cleared when the order is **complete**, not merely created:

```python
if order.payment_method == 'COD' or order.payment_status == 'paid':
    cart.items.all().delete()
```

- **COD** and **zero-total** (fully-couponed, `payment_status='paid'`) orders are complete at
  placement, so the cart is cleared **inside** the transaction. If the transaction rolls back
  (e.g. stock ran out mid-flight), the cart is preserved — the customer's items are not lost.
- A **pending ONLINE** order deliberately **keeps** the cart until its payment is captured
  (`payments.services.mark_payment_captured` clears it then). This means an abandoned or failed
  payment never strands the customer with an empty cart — "Proceed to checkout" still works.

To stop reserved stock leaking across retries, a fresh checkout first **supersedes** any earlier
pending ONLINE order from the same user: it cancels that order (`payment_status='rejected'`) and
restocks it under the cart lock before reserving stock for the new order. This guarantees exactly
one open ONLINE order per user and subsumes the old double-submit guard (which previously relied on
the cart being emptied at creation).

### 5. Post-transaction (best-effort)

After the transaction commits:

```python
record_purchase_events(order)   # analytics — never blocks or fails the order
```

Analytics outages do not prevent order creation.

### 6. Response

```json
{
  "message": "Order created successfully",
  "order_id": 42,
  "order_number": "ORD-000042",
  "total_amount": 540.75,
  "order": { ...OrderDetailSerializer... }
}
```

**Order number format:** `ORD-` prefix + zero-padded 6-digit primary key. This is
generated after the transaction and is returned in the response only — it is not stored
in the database (the PK is the canonical identifier).

---

## Order Cancellation (`POST /api/orders/{id}/cancel/`)

Cancellation is fully atomic. The same select-for-update locking pattern as creation:

```
Lock order row (select_for_update)
Check status: delivered / cancelled / delivering → reject

Restore stock:
  variants: stock += quantity (+ product mirror for default variants)
  products: stock += quantity  (legacy lines)
  combos:   stock += quantity  (if combo model has stock field)

order.status = 'cancelled'
order.cancelled_at = now()
```

**Who can cancel:** the order owner or any `is_staff` user.

---

## Invoice Generation (`GET /api/orders/{id}/invoice/`)

Returns a PDF tax invoice generated by `reportlab` (`orders/invoice.py`). The PDF is
generated dynamically from the stored order data — it reflects the prices and names at
the time of ordering (not current product prices). Requires `reportlab` to be installed;
returns `503` if the library is missing.

File name: `invoice-ORD-{order_id:06d}.pdf`.

---

## Coupon Rules

| Check | Detail |
|-------|--------|
| `is_active` | Coupon must be active |
| `valid_until` | Must be before expiry date |
| `max_usage` | If set, `usage_count < max_usage` |
| `minimum_order_amount` | Subtotal (pre-discount) must meet minimum |
| Discount type | Percentage only (`discount_percent` 1–100) |

Coupons are case-insensitive (`code__iexact`). Pre-validation via
`POST /api/auth/validate-coupon/` returns the full breakdown before order creation so the
checkout UI can show exact savings without committing an order.

---

## Stock Management — Source of Truth

```
ProductVariant.stock  ←── source of truth for all new products
       │
       └── is_default=True variant mirrors to Product.stock
                                      │
                                      └── used by listing pages & legacy cart lines
```

**Why the mirror?** Product listing pages and the old cart API read `Product.stock` for
display. Keeping them in sync avoids a full migration of all list queries. The mirror is
best-effort on the `Product.stock` side — it is clamped at 0 if it would go negative
(drift can accumulate from direct SQL edits; the canonical count is always on the variant).

**Combos never have stock decremented** — availability is `is_active` only. Attempting to
call `.stock` on a combo inside a batch update raises `FieldDoesNotExist`, which is why
combo lines are explicitly excluded from the decrement loop.
