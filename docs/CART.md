# Cart System

The cart spans two layers: a backend that enforces stock and persistence, and a frontend
that optimistically mirrors backend state in localStorage.

---

## Backend Cart

### Data Model

```
Cart (one per user, PK = user FK)
  └── CartItem
        ├── product   FK (nullable) ─── ProductVariant FK (nullable)
        ├── combo     FK (nullable)
        ├── item_type ('product' | 'combo')
        └── quantity  (≥ 1)
```

**DB constraints** (enforced via `CheckConstraint` and `UniqueConstraint`):
- Either `product` or `combo` is set — never both, never neither.
- For product lines: `variant` must be set (defaults to the product's default variant on
  add). The variant is the exact size/packaging being purchased.
- No duplicate `(cart, variant)` pairs or `(cart, combo)` pairs — adding the same item
  again increments quantity instead.

### Line Identity (Variant-Based Deduplication)

Two cart items for the same product but different variants are **separate lines**:

| Item | Line |
|------|------|
| Turmeric 100g (variant 7) | line A, qty 2 |
| Turmeric 500g (variant 8) | line B, qty 1 |

The deduplication key on the backend is `(cart, variant)` for products and `(cart, combo)`
for combos. On the frontend it is the composite string `"product-{id}-{variantId}"` or
`"combo-{id}-"`.

### Stock Locking

Cart operations use `select_for_update()` on the variant (or product for legacy lines)
row before reading available stock. This is pessimistic locking — concurrent add requests
for the same variant serialise and the second one sees the stock already reduced by the first.

Stock is read from:
- `variant.stock` when a variant is present
- `product.stock` for variant-less legacy lines
- for combos, the scarcest component: `min(variant.stock // qty)` over the
  components. (The cart *response* still reports `999` for a combo line's raw
  `stock` field; the authoritative check happens at checkout, per component.)

**Combo pricing in the cart.** A combo line's unit price is `discount_price` or
the DERIVED MRP — the sum of its component sizes' prices. There is no `price`
column, so `Cart.total_price` reaches it through `cart.models.combo_mrp_subquery()`
rather than an `F('combo__price')`. Its GST is likewise per component, via
`orders.pricing.combo_line_tax`, so the cart's quoted tax matches the placed
order's exactly — see ORDER_LIFECYCLE.md.

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/cart/` | Fetch full cart with computed totals |
| POST | `/api/cart/add_item/` | Add item (or increment quantity) |
| POST | `/api/cart/update_item/` | Set exact quantity for a line |
| DELETE/POST | `/api/cart/remove_item/` | Remove a line |
| POST | `/api/cart/clear/` | Empty the cart |
| POST | `/api/cart/sync/` | Replace cart with client-side snapshot |
| POST | `/api/cart/qr/` | Generate UPI QR code for current total |

### Cart Sync (Two-Phase Validation)

`POST /api/cart/sync/` replaces the server cart with a client-provided list. It runs in
two phases to prevent partial writes:

**Phase 1 — validate all items:**
- For each item: resolve product/variant, check stock
- Collect valid items and skipped items (dead products, out-of-stock)
- Do **not** touch the database in this phase

**Phase 2 — persist (only if phase 1 succeeds):**
- Delete all existing cart items
- Bulk-insert the validated items in a single transaction

If validation fails for any item, it is skipped and reported in the response; the
remaining valid items are still synced. The entire old cart is replaced atomically — there
is no partial sync state.

---

## Frontend Cart (`CartContext.tsx`)

### Persistence

Cart state lives in React context and is mirrored to `localStorage("shopping_cart")` on
every change. This enables fast initial render from local state before the backend responds.

### Login / Logout Behaviour

```
User logs in  → fetchCartFromBackend()
                backend cart replaces localStorage
                (backend is source of truth post-login)

User logs out → cart state cleared
                localStorage("shopping_cart") removed
                (prevents cart leaking between users on shared devices)
```

### Optimistic Updates

`updateQuantity` and `removeFromCart` update React state **before** the backend call, then
sync from the backend response on success. On failure, the previous state is restored:

```typescript
const previousCart = [...cart];
setCart(optimisticUpdate);          // immediate UI change
try {
  const response = await cartAPI.updateItem(...);
  setCart(mapBackendToFrontend(response.items));  // confirmed state
} catch {
  setCart(previousCart);            // revert
  toast.error(...);
}
```

`addToCart` does **not** use optimistic updates — it waits for the backend response before
updating UI, because the backend may reject the item (out of stock, invalid variant).

### Analytics Events

`addToCart` fires `trackEvent({ event_type: "add_to_cart", product_id/combo_id })` on
success. `removeFromCart` fires `trackEvent({ event_type: "remove_from_cart", ... })` on
success. Both are fire-and-forget — failures are silent.

### Cart State Shape

```typescript
interface CartItem {
  id: number;           // product or combo ID
  variantId?: number;   // null for combos and legacy lines
  variantSlug?: string;
  weight?: string;      // human-readable e.g. "100g"
  itemType: "product" | "combo";
  name: string;
  image: string;
  price: number;        // current price (may differ from order price)
  originalPrice?: number;
  quantity: number;
  stock?: number;       // for UI stock warning
  inStock?: boolean;
}
```

The cart holds display data needed to render the cart page without a second API call. The
backend is the authoritative source for prices at order creation time.

### Cart Requires Login

All cart operations (add, update, remove, clear) require the user to be logged in. The
`addToCart` function returns `{ success: false, requiresLogin: true }` for unauthenticated
calls so the UI can show a login prompt rather than silently failing.

---

## UPI QR Code for Payment

`POST /api/cart/qr/` generates a UPI deep link and QR code for the current cart total.
The backend fetches the default `ReceivableAccount` and constructs:

```
upi://pay?pa={upi_id}&pn={account_holder_name}&am={amount}&cu=INR&tn=NGU Spices Order
```

The QR code image (base64 PNG) and the raw URI are both returned. The frontend renders
the QR on the billing page so users can scan with any UPI app (Google Pay, PhonePe,
Paytm, etc.).

This is separate from Razorpay — it is a manual UPI transfer flow used when the customer
wants to pay without entering card details. Order placement still requires a separate
`POST /api/orders/` call after the payment is made out-of-band.
