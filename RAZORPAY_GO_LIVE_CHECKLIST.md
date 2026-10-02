# Razorpay Go-Live Checklist — NGU / Nidhi Masala

The Razorpay integration is **fully built and tested** in code. Nothing here is a
code change — everything below is **configuration and operational setup** needed to
switch from test mode to accepting real money in production.

Endpoints already live (see `Backend/payments/`):

| Endpoint | Purpose |
|----------|---------|
| `POST /api/payments/create-order/` | Mint (or reuse) a Razorpay order for a placed Order |
| `POST /api/payments/verify/` | L1 browser-callback signature verification |
| `POST /api/payments/webhook/` | L2 source of truth (signature-gated) |
| `GET  /api/payments/status/` | Honest, non-alarming payment state for polling |

---

## 1. Razorpay account (one-time)

- [ ] Complete **KYC / business verification** in the Razorpay dashboard. Live keys
      are not issued until this is approved.
- [ ] Confirm the settlement bank account is added and verified.
- [ ] Decide currency = **INR** (the code hardcodes INR).

## 2. Generate LIVE keys

- [ ] In the dashboard, switch from **Test Mode → Live Mode**.
- [ ] Settings → API Keys → **Generate Live Key**. You get `rzp_live_…` (Key ID)
      and a **live Key Secret shown only once** — store it immediately.
- [ ] ⚠️ The test keys currently in use (`rzp_test_TFLIpbzfJAoapZ` / …) were shared
      in chat and must **not** go to production. Use fresh live keys.

## 3. Register the webhook (CRITICAL — fail-closed)

The webhook is the L2 **source of truth**. The code **fail-closes**: if
`RAZORPAY_WEBHOOK_SECRET` is blank in prod, **every webhook is rejected** and orders
won't auto-confirm from the reliable path — you'd be leaning on the browser callback
alone.

- [ ] Dashboard → Settings → **Webhooks** → Add New Webhook.
- [ ] URL: **`https://nidhimasala.com/api/payments/webhook/`** (trailing slash matters).
- [ ] Set an **active secret** on the webhook — copy it verbatim.
- [ ] Subscribe to exactly these events (the code handles these; others are ACKed and ignored):
  - [ ] `payment.captured`
  - [ ] `order.paid`
  - [ ] `payment.failed`
  - [ ] ~~`refund.processed`~~ — **not handled since 2026-08-01** (manual-only
        refunds; the branch is commented out in `payments/views.py`). Subscribing
        it is harmless but has no effect.
- [ ] (Optional) Add a second webhook for `https://nidhigrahudyog.com/api/payments/webhook/`
      if orders are placed on that domain too — same events, same secret handling.

## 4. Set production environment variables

On the **deploy EC2** (`13.235.238.99`), in the prod `.env` used by `docker-compose.prod.yml`:

```env
RAZORPAY_KEY_ID=rzp_live_xxxxxxxxxxxxxx
RAZORPAY_KEY_SECRET=<live secret from step 2>
RAZORPAY_WEBHOOK_SECRET=<webhook secret from step 3>
PAYMENT_STUCK_TTL_MINUTES=15
```

- [ ] Live Key ID set (`rzp_live_…`, **not** `rzp_test_…`).
- [ ] Live Key Secret set — never committed, never sent to the frontend.
- [ ] Webhook secret set (non-blank — see step 3 warning).
- [ ] **Frontend needs no Razorpay env var** — the browser receives `razorpay_key_id`
      from the `create-order` response, so no rebuild is required for a key swap. Just
      restart the backend.

Apply on the server:

```bash
docker-compose -f docker-compose.prod.yml up -d --force-recreate backend scheduler
```

## 5. Verify the scheduler (self-healing) is running

Stuck/abandoned online orders are auto-cancelled + restocked, and payments are
reconciled, by the `scheduler` container (`manage.py run_scheduler`).

- [ ] `docker-compose -f docker-compose.prod.yml ps` shows `scheduler` up.
      (Per deploy notes it may report "unhealthy" cosmetically — check logs, not just status.)
- [ ] `RECONCILE_INTERVAL_MINUTES` and `ROLLUP_INTERVAL_MINUTES` are set (default 5).
- [ ] Manual fallback if ever needed:
      `docker-compose -f docker-compose.prod.yml exec backend python manage.py reconcile_payments`

## 6. End-to-end live smoke test (small real amount)

- [ ] Place a real order for a **small amount** (e.g. ₹1–₹5) using a real UPI/card.
- [ ] Confirm the modal opens, payment succeeds, and you land on `/order-success`.
- [ ] In the DB / admin: Order `status = confirmed`, `payment_status = paid`;
      Payment `status = completed` with a `razorpay_payment_id`.
- [ ] In the Razorpay dashboard: the webhook shows a **200** delivery for
      `payment.captured` / `order.paid`.
- [ ] Confirmation email received (customer + admin alert).
- [ ] **Refund** that test order from the dashboard → the webhook is now IGNORED
      (manual-only mode). Confirm the order still reads `paid`, then mark it
      `refunded` in the admin panel and check the GST reversal lands.

## 7. Edge cases to spot-check (already coded — just confirm behaviour)

- [ ] **Modal dismissed** → order stays pending, retryable from **My Orders** (cart not re-added).
- [ ] **Abandoned online order** past `PAYMENT_STUCK_TTL_MINUTES` → auto-cancelled + restocked.
- [ ] **Amount cap**: online payment blocked above ₹1,00,000 (gateway + client guard).
- [ ] **Capture-after-cancel**: if a payment lands on a cancelled order, money is
      recorded and an admin refund alert fires — the order is **not** reopened.

## 8. Rollback / safety

- [ ] Keep the test keys handy to revert to test mode instantly if the live smoke test misbehaves.
- [ ] Rotate the **test** credentials shared in this session (dashboard → regenerate) — low risk, but hygiene.
- [ ] Confirm `.env` is gitignored on the server (it is in-repo) and secrets are not in any image layer.

---

### Quick sanity: what does NOT need to change

- No code changes. No migrations. No frontend rebuild for the key swap.
- `create-order` / `verify` / `webhook` / `status` are already wired in
  `Backend/spices_backend/urls.py` under `api/payments/`.
- Idempotency, lock ordering, out-of-order safety, and amount integrity are all
  handled in `Backend/payments/services.py` and covered by tests.
