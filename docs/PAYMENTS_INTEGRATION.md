# Payments Integration

Payment in NGU Spices has three distinct paths: Cash on Delivery, UPI QR (manual
transfer), and Razorpay (card/UPI via gateway). All paths converge at the `Order` model
whose `payment_method` and `payment_status` fields track the outcome.

---

## Payment Paths

### 1. Cash on Delivery (COD)

- `Order.payment_method = 'COD'`
- `Order.payment_status` starts as `pending`, updated to `paid` when admin confirms
  receipt
- No gateway involved; no server-side verification step

### 2. UPI QR (Manual Transfer)

A direct bank transfer flow — no gateway:

1. Checkout page calls `POST /api/cart/qr/`
2. Backend fetches the default `ReceivableAccount` (admin-configured) and builds a
   UPI deep link:
   ```
   upi://pay?pa={upi_id}&pn={account_holder_name}&am={total}&cu=INR&tn=NGU Spices Order
   ```
3. A QR code image (base64 PNG) and the URI are returned to the frontend
4. Customer scans the QR with any UPI app (Google Pay, PhonePe, Paytm, etc.)
5. Customer places the order (`POST /api/orders/`) after completing the transfer —
   the backend has no webhook for manual UPI; the admin marks `payment_status=paid`
   manually after seeing the transfer

### 3. Razorpay (Online Payments)

1. Order created with `payment_method='razorpay'`
2. Backend creates a Razorpay Order ID via the Razorpay API
3. Frontend receives the `razorpay_order_id` and opens the Razorpay JS modal
4. Customer completes payment in modal
5. Razorpay calls the backend webhook with payment details
6. Backend verifies the Razorpay signature server-side (HMAC-SHA256 using
   `RAZORPAY_KEY_SECRET`)
7. On valid signature: `Order.payment_status` → `completed`; `Payment` record created

**Configuration:**

Both key pairs sit in the environment at once; `RAZORPAY_TEST_MODE` selects which
one is live. Switching modes is a one-flag change plus a backend restart — no code
or image rebuild.

```env
RAZORPAY_TEST_MODE=True          # True = test keys, False = live keys

RAZORPAY_TEST_KEY_ID=rzp_test_...
RAZORPAY_TEST_KEY_SECRET=...
RAZORPAY_TEST_WEBHOOK_SECRET=...

RAZORPAY_LIVE_KEY_ID=rzp_live_...
RAZORPAY_LIVE_KEY_SECRET=...
RAZORPAY_LIVE_WEBHOOK_SECRET=...
```

`settings.py` resolves the selected pair into `RAZORPAY_KEY_ID` /
`RAZORPAY_KEY_SECRET` / `RAZORPAY_WEBHOOK_SECRET`, which is all the rest of the
codebase reads. The flat names still work as a fallback for un-migrated
environments.

**The webhook secret switches with the mode.** Test and live webhooks are separate
dashboard entries with different signing secrets. Because the handler is
fail-closed, a mode flip that left the wrong secret in place would silently reject
every delivery — pairing them here prevents that.

**Boot guards** (all raise `ImproperlyConfigured` at startup, never at checkout):

| Condition | Why it's blocked |
|---|---|
| `TEST_MODE=True` + `rzp_live_` key | Real cards charged by a build that thinks it's in test mode |
| `TEST_MODE=False` + non-live key | Live checkout silently running on test credentials |
| `TEST_MODE=False` + `DEBUG=True` | Live keys on a development server |

Note the prefix check validates the *shape* of the key, not that the credential is
real — a well-formed but wrong `rzp_live_` key still boots.

---

## Pricing Rules (applied during order creation)

⚠ **The authoritative formula lives in `ORDER_LIFECYCLE.md` § "Pricing calculation".**
It is deliberately NOT repeated here — this section used to carry its own copy and
drifted into teaching the *opposite* GST convention after the 2026-08-04 change.
The two facts a payments reader needs:

- **Goods prices are GST-INCLUSIVE (MRP).** `tax` is *extracted* from the subtotal
  for disclosure and is **not** a term in `total_amount`. Charging it on top
  double-bills the customer.
- **Delivery is the exception**: quoted net (`SHIPPING_CHARGE`, default ₹59) and
  taxed **on top** at `SHIPPING_TAX_RATE` (18%, SAC 9968), so `shipping_tax` *is* a
  term in `total_amount`. The customer pays ₹69.62 when delivery applies.

The amount handed to Razorpay is `Order.total_amount`; the output-tax figure every
report must read is `Order.total_tax` (= `tax + shipping_tax`), never `tax` alone.

All amounts stored as `Decimal(max_digits=10, decimal_places=2)` to avoid floating-point
errors. See `ORDER_LIFECYCLE.md` for the full order creation flow.

---

## Receivable Accounts

`ReceivableAccount` (in `admin_panel` app) holds the bank/UPI details the business
collects money into.

| Field | Notes |
|-------|-------|
| `upi_id` | Unique; used for QR generation |
| `bank_account_number`, `ifsc_code`, `branch_name` | For NEFT/RTGS display |
| `is_active` | Inactive accounts are never shown |
| `is_default` | At most one default; enforced via `save()` that clears others |

`GET /api/payment-account/` returns the default active account (or first active if none
is default). This is the endpoint the billing page calls to show payment details and
generate QR codes.

---

## Payment Model (`payments.Payment`)

Tracks the gateway transaction for online orders:

| Field | Notes |
|-------|-------|
| `order` | OneToOne FK to Order |
| `payment_id` | Gateway-assigned ID (unique) |
| `payment_gateway` | `razorpay` \| `cod` \| `stripe` |
| `amount` | Decimal |
| `status` | `pending` \| `completed` \| `failed` \| `refunded` |
| `transaction_details` | JSONField — full gateway response for audit |

---

## Saved Payment Methods (`payments.PaymentMethod`)

Users can save payment references for faster checkout. **Raw card numbers are never
stored** — only the last 4 digits and the gateway's opaque token.

### Supported types

| Type | Fields stored |
|------|--------------|
| `UPI` | `upi_id` (validated against `[\w.\-]+@[\w]+` regex) |
| `CARD` | `card_last_four`, `card_brand`, `card_expiry_month/year`, `gateway_token` |
| `NETBANKING` | `bank_name` |
| `WALLET` | `wallet_provider` |

### Display

The `masked_display` property returns a safe string for UI rendering:

| Type | Example output |
|------|---------------|
| UPI | `user@paytm` |
| Card | `Visa ending in 4242` |
| Net Banking | `HDFC Bank` |
| Wallet | `Paytm Wallet` |

### Default enforcement

`PaymentMethod.save()` runs in a transaction: if `is_default=True`, all other methods for
the same user are set to `is_default=False`. Exactly one default per user at all times.

### Soft delete

`DELETE /api/payment-methods/{id}/` sets `is_active=False` rather than hard-deleting.
Historical order references to the method are preserved.

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/payment-methods/` | List active saved methods |
| POST | `/api/payment-methods/` | Save a new method |
| DELETE | `/api/payment-methods/{id}/` | Soft-delete (deactivate) |
| GET | `/api/payment-account/` | Get default receivable account for checkout |

---

## Coupons

Coupons are managed by the `admin_panel` app (`Coupon` model) and validated at order time.

| Field | Notes |
|-------|-------|
| `code` | Unique, case-insensitive match (`__iexact`) |
| `discount_percent` | Integer 1–100; percentage only (no fixed-amount type) |
| `is_active` | Must be True |
| `valid_until` | Optional expiry date |
| `max_usage` | Optional cap; `null` = unlimited |
| `usage_count` | Incremented with `F()` expression to prevent race conditions |
| `minimum_order_amount` | Optional; checked against pre-discount subtotal |

**Pre-validation endpoint:** `POST /api/auth/validate-coupon/` lets the checkout UI
show exact savings before committing the order. It runs the full validation and returns
the complete price breakdown.
