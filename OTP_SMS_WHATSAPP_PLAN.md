# OTP via SMS & WhatsApp — Implementation Plan

**Status:** Proposal (no code changes made yet)  
**Date:** 2026-07-21 (expanded)  
**Owner:** kaushaljain7000@gmail.com

## Goal

Today every OTP and notification in NGU is delivered by **email only**. This plan
adds **SMS** and **WhatsApp** as delivery channels for:

1. **Password-reset OTP** (existing flow, multi-channel).
2. **Phone verification** (required before phone is trusted).
3. **Mobile-number OTP login** (passwordless auth — first-class, not optional).
4. **Order lifecycle SMS** (confirmation + status/tracking updates).

It also specifies **layered rate limits and anti-abuse controls** so SMS/WhatsApp
cannot be exploited for toll fraud, account enumeration, or spam.

---

## 1. Current state

| Area | Today |
|------|--------|
| OTP | Email-only password reset in `users/views.py` (`PasswordResetRequestView` / `Verify` / `Confirm`) |
| OTP storage | `PasswordResetOTP` — hashed code, 10‑min expiry, 5 failed-attempt lockout (`users/models.py`) |
| Auth | Email/password JWT cookies + Google OAuth (`POST /api/auth/login/`, `/api/auth/google/`) |
| Notifications | Order confirmation, status/tracking, admin new-order alert — all email (`orders/emails.py`) |
| Phone on User | `User.phone` — `CharField(max_length=15, blank=True)`, **unverified, not unique** |
| Phone on Order | `Order.phone_number` — required at checkout, **not linked to verified identity** |
| SMS/WhatsApp | None — no provider config, no DLT templates |
| Throttles | Login 5/min/IP, register 3/min/IP, password-reset 10/day/IP; abuse strikes via `spices_backend/abuse.py` |

Order status workflow (from `ORDER_LIFECYCLE.md`):

```
PENDING → CONFIRMED → PROCESSING → SHIPPED → DELIVERING → DELIVERED
                ↘ CANCELLED (from most pre-delivery states)
```

Status emails fire from admin `PATCH /api/orders/{id}/` via `send_order_status_email`.

---

## 2. Design principles

1. **Channel-agnostic delivery** — business code never hard-codes SMS/WhatsApp/email.
2. **Fail-soft** — notification failures never break order placement, status updates, or auth HTTP responses (same daemon-thread pattern as `orders/emails.py`).
3. **Phone must be verified before trust** — unverified numbers cannot receive password-reset OTP or become a login identifier.
4. **No phone enumeration** — OTP request responses are identical whether the number is registered or not (mirror email password-reset).
5. **Cost-aware rate limits** — SMS/WhatsApp are pay-per-message; throttle by **IP + phone + user**, not IP alone.
6. **Reuse existing security** — hashed OTPs, expiry, failed-attempt lockout, HttpOnly JWT cookies, `flag_suspicious` / ban tooling.
7. **India-first compliance** — DLT templates (SMS) and Meta-approved templates (WhatsApp) before go-live.

---

## 3. Provider choice (longest lead time — start first)

Indian brand → regulatory overhead on both channels:

- **SMS:** TRAI **DLT** registration (entity + sender/header ID + pre-approved templates).
- **WhatsApp:** WhatsApp Business API via Meta BSP + pre-approved templates.

**Recommendation:** one vendor for both channels.

| Provider | SMS | WhatsApp | Notes |
|----------|-----|----------|-------|
| **MSG91** (recommended) | ✅ | ✅ | India pricing, OTP product, one vendor |
| Gupshup | ✅ | ✅ | Strong WhatsApp BSP |
| Twilio | ✅ | ✅ | Clean API; pricier / less India-optimized |

**Open decision:** confirm provider before implementation. Abstraction must allow swap later.

### 3.1 Templates to register (DLT + WhatsApp)

| Purpose | Approx. body (variables only) | Priority |
|---------|-------------------------------|----------|
| Auth OTP | `Your Nidhi Masala code is {#var#}. Valid 10 min. Do not share.` | P0 |
| Order confirmed | `Order {#var#} placed. Total Rs.{#var#}. Track: {#var#}` | P0 |
| Order status | `Order {#var#} is now {#var#}. Track: {#var#}` | P0 |
| Shipped + tracking | `Order {#var#} shipped. Tracking ID: {#var#}` | P0 |
| Order cancelled | `Order {#var#} cancelled. Contact support if unexpected.` | P1 |

Exact wording must match DLT/WhatsApp approval; keep copy short (SMS ~160 chars ideal).

---

## 4. Abstraction layer

### 4.1 Module layout

Prefer a small dedicated app (cleaner than stuffing into `users`):

```
Backend/notifications/
  __init__.py
  apps.py
  backends/
    base.py          # NotificationBackend protocol
    email.py         # wraps send_mail
    sms.py           # MSG91/Twilio/Gupshup
    whatsapp.py
  service.py         # send_otp(), send_order_sms(), dispatch()
  phone.py           # normalize / validate E.164 (India-first)
  models.py          # optional DeliveryLog (audit + cost visibility)
  throttles.py       # phone-scoped cache counters (not only DRF IP throttles)
```

Public API (examples):

```python
send_otp(destination, code, *, channel, purpose)   # purpose: login | verify | password_reset
notify_order(order, event)                         # event: confirmed | status | shipped | cancelled
```

### 4.2 Env config (Razorpay-style clarity)

```env
# Master switches (comma list). Empty / missing = email only (safe default).
OTP_CHANNELS=email,sms,whatsapp
ORDER_NOTIFY_CHANNELS=email,sms          # WhatsApp order templates optional later

# SMS
SMS_PROVIDER=msg91                       # msg91 | gupshup | twilio | console
SMS_API_KEY=...
SMS_SENDER_ID=NIDHIS                     # DLT header
SMS_OTP_TEMPLATE_ID=...
SMS_ORDER_CONFIRMED_TEMPLATE_ID=...
SMS_ORDER_STATUS_TEMPLATE_ID=...
SMS_ORDER_SHIPPED_TEMPLATE_ID=...
SMS_ORDER_CANCELLED_TEMPLATE_ID=...

# WhatsApp (optional phase)
WHATSAPP_PROVIDER=msg91
WHATSAPP_API_KEY=...
WHATSAPP_SENDER=...
WHATSAPP_OTP_TEMPLATE_ID=...
# WHATSAPP_ORDER_* later if needed

# Behavior
SMS_ENABLED=True                         # hard off switch for prod incidents
OTP_TTL_MINUTES=10
OTP_MAX_FAILED_ATTEMPTS=5
PHONE_DEFAULT_COUNTRY=IN                 # assume +91 when 10-digit local entered
```

- **`console` backend** for local/dev: logs the OTP, never hits a network.
- Boot: if `SMS_ENABLED=True` but keys missing → log loud warning (or refuse boot in prod) so misconfig is obvious.

### 4.3 Fail-soft delivery

Mirror `orders/emails.py`:

- Background daemon thread (or existing scheduler/outbox later).
- Retry with short backoff (2–3 attempts).
- Log final failure with order id / purpose; never raise into the request path.
- Close DB connections in the worker thread.

---

## 5. Data model changes

### 5.1 `User` (`users/models.py`)

| Field | Type | Notes |
|-------|------|--------|
| `phone` | existing | **Normalize to E.164** on save (e.g. `+919876543210`) |
| `phone_verified` | `BooleanField(default=False)` | Trust gate |
| `phone_verified_at` | `DateTimeField(null=True)` | Audit |
| `sms_notifications_opt_in` | `BooleanField(default=True)` | Order SMS preference (auth OTP always allowed when user requested it) |

Constraints / indexes:

- **Unique on normalized phone when non-blank** — partial unique preferred (`phone != ''`).  
  SQLite tests: enforce uniqueness in application + a non-partial unique if needed; Postgres production can use a conditional unique index.
- Changing `phone` **clears** `phone_verified` / `phone_verified_at` until re-verified.

### 5.2 Generalized OTP model

Today `PasswordResetOTP` is password-reset only. Either:

**Option A (recommended):** rename/generalize to `PhoneEmailOTP` / `AuthOTP` with:

| Field | Purpose |
|-------|---------|
| `user` | FK nullable (login/register-by-phone may create user on verify) |
| `purpose` | `password_reset` \| `phone_verify` \| `phone_login` |
| `channel` | `email` \| `sms` \| `whatsapp` |
| `destination` | email or E.164 phone actually messaged (audit) |
| `otp_code` | hashed |
| `expires_at`, `is_used`, `failed_attempts` | same as today |
| `reset_token` | only for password-reset purpose |
| `session_token` | opaque one-time token after successful login-OTP verify (optional 2-step) |

**Option B:** keep `PasswordResetOTP` and add `PhoneOTP` for login/verify.  
Slightly more code duplication; OK if we want smaller migrations.

Reuse: `set_otp` / `check_otp`, `is_expired`, `is_locked`, `MAX_FAILED_ATTEMPTS = 5`.

### 5.3 Optional `NotificationDeliveryLog`

For cost/debug (phase 2):

- `channel`, `provider`, `template_id`, `destination_hash`, `purpose`, `order_id`, `status`, `provider_message_id`, `created_at`
- Store **hashed** destinations if privacy-sensitive; never store raw OTP.

### 5.4 Order side

No required schema change for v1: use `order.phone_number` (checkout) and fall back to `order.user.phone` if verified.

Optional later: `Order.sms_notified_statuses` JSON / flags to prevent duplicate status SMS on noisy admin edits.

---

## 6. Phone normalization & validation

- Accept India local `10-digit` starting with 6–9, or full `+91…`.
- Canonical store: **E.164** (`+91XXXXXXXXXX`).
- Reject landlines / obvious garbage; max length aligned with E.164.
- Shared helper: `notifications.phone.normalize_phone(raw, default_country='IN') -> str | raise ValidationError`.
- All rate-limit keys and uniqueness use the **normalized** form.

---

## 7. API endpoints

Base path remains under `/api/auth/` for auth OTP; order SMS is not a public endpoint (triggered server-side).

### 7.1 Phone verification (authenticated)

| Method | Path | Auth | Body | Success |
|--------|------|------|------|---------|
| `POST` | `/api/auth/phone/send-otp/` | JWT required | `{ "phone": "9876543210" }` or omit to use profile phone | `200` `{ "detail": "If eligible, an OTP has been sent.", "expires_in": 600 }` |
| `POST` | `/api/auth/phone/verify/` | JWT required | `{ "phone": "...", "otp_code": "123456" }` | `200` `{ "detail": "Phone verified.", "phone": "+91...", "phone_verified": true }` |

Behavior:

1. Normalize phone; if another user already owns verified phone → `400` “Phone already in use” (authenticated path may be slightly more revealing — only for *this user’s* attempt to claim a taken number).
2. Invalidate prior unused OTPs for `(user, purpose=phone_verify)`.
3. Generate 6-digit OTP, hash, store with channel=`sms` (or whatsapp if requested).
4. Send async; response does not include the code.
5. On verify success: set `user.phone`, `phone_verified=True`, `phone_verified_at=now`.

### 7.2 Mobile OTP login (passwordless) — **in scope**

| Method | Path | Auth | Body | Success |
|--------|------|------|------|---------|
| `POST` | `/api/auth/phone/login/request/` | AllowAny | `{ "phone": "9876543210", "channel": "sms" }` | `200` always: `{ "detail": "If an account exists for this number, an OTP has been sent.", "expires_in": 600 }` |
| `POST` | `/api/auth/phone/login/verify/` | AllowAny | `{ "phone": "...", "otp_code": "123456" }` | `200` + **same JWT cookies** as email login (`access_token`, `refresh_token`) + user payload |

#### Login request flow

```
Client                         Backend                         SMS provider
  │                               │                                 │
  │ POST {phone, channel} ───────▶│                                 │
  │                               │ normalize phone                 │
  │                               │ rate-limit IP + phone           │
  │                               │ lookup User by phone            │
  │                               │   + phone_verified=True         │
  │                               │ if missing:                     │
  │                               │   constant-time dummy work      │  ← no enumeration
  │                               │   no SMS                        │
  │                               │ else:                           │
  │                               │   invalidate old login OTPs     │
  │                               │   create AuthOTP (hashed)       │
  │                               │   async send ──────────────────▶│
  │◀── 200 identical message ─────│                                 │
```

#### Login verify flow

```
Client                         Backend
  │                               │
  │ POST {phone, otp_code} ──────▶│
  │                               │ rate-limit IP + phone
  │                               │ find latest unused login OTP for destination
  │                               │ check expired / locked / hash
  │                               │ on fail: bump failed_attempts; generic error
  │                               │ on success: mark used
  │                               │ issue JWT via same serializer as password login
  │                               │ set HttpOnly cookies (access 1h, refresh 7d)
  │◀── 200 + cookies + user ──────│
```

**Account linking rules (v1 — decide explicitly):**

| Policy | Behavior | Recommendation |
|--------|----------|----------------|
| **A. Existing verified users only** | OTP login only if `phone_verified` user exists; else silent no-op on request | **Recommended for v1** — no orphan phone accounts |
| B. Auto-register on first verify | Create user with phone as primary id, placeholder email | Later phase; needs email collection for invoices/GST |
| C. Hybrid | Request always “sends”; verify creates soft account | Higher abuse surface |

**v1 recommendation: Policy A.** Signup remains email (or Google); user verifies phone in profile; then phone OTP login works.

Optional later: `POST /api/auth/phone/login/register/` after OTP to complete profile (name, email) for phone-first onboarding.

### 7.3 Password reset — multi-channel

Extend existing endpoints (or add optional fields, backward compatible):

`POST /api/auth/password-reset-request/`

```json
{ "email": "user@example.com", "channel": "email" | "sms" | "whatsapp" }
```

Rules:

- Default `channel=email` (current clients keep working).
- `sms` / `whatsapp` only if that user’s phone is **verified** and matches the account for the given email.
- If channel unavailable → fall back message in response *without* leaking whether email exists; still constant-time path. Safer UX: if authenticated N/A, return same generic 200 always; if channel requested but phone unverified, still generic 200 and only send if fully eligible.
- Store `channel` + `destination` on OTP row.

Verify/confirm stay email-keyed as today (`email` + `otp_code` / `reset_token`), or accept phone when channel was SMS (prefer keep email as account key for reset to avoid dual identity bugs).

### 7.4 Preference endpoints (profile)

| Method | Path | Body |
|--------|------|------|
| `PATCH` | `/api/auth/profile/` | `{ "sms_notifications_opt_in": true/false, "phone": "..." }` |

Changing phone clears verification (must re-run phone verify).

### 7.5 Endpoints explicitly **not** public

- No client endpoint to “blast SMS”.
- Order status SMS only from server after admin status transitions / order create.
- Admin may later get “resend order SMS” under staff permissions (rate-limited, audited).

### 7.6 URL registration sketch (`spices_backend/urls.py`)

```python
path('api/auth/phone/send-otp/', PhoneVerifySendView.as_view()),
path('api/auth/phone/verify/', PhoneVerifyConfirmView.as_view()),
path('api/auth/phone/login/request/', PhoneLoginRequestView.as_view()),
path('api/auth/phone/login/verify/', PhoneLoginVerifyView.as_view()),
# existing password-reset + login unchanged
```

Document in `Backend/docs/API_PERMISSIONS.md` and `Backend/docs/AUTH.md` when implemented.

---

## 8. Rate limits & anti-abuse (critical)

SMS pumping and OTP brute-force are **direct rupee risk**. IP-only throttles are not enough.

### 8.1 DRF throttle scopes (add to `DEFAULT_THROTTLE_RATES`)

| Scope | Default | Applied to | Dimension |
|-------|---------|------------|-----------|
| `phone_otp_send` | `3/hour` | phone verify send, phone login request, password-reset SMS | **per IP** |
| `phone_otp_send_day` | `10/day` | same | **per IP** |
| `phone_otp_verify` | `10/hour` | all OTP verify endpoints (phone + password-reset verify) | **per IP** |
| `phone_login` | `5/minute` | phone login request + verify | **per IP** (align with password login) |
| existing `password_reset` | `10/day` | email+SMS password reset | **per IP** |
| existing `login` | `5/minute` | email/password login | **per IP** |

All new throttles should subclass the existing `_FlaggedThrottle` pattern (`spices_backend/throttles.py`) so denials call `flag_suspicious(request, reason=f"rate_limit:{scope}")`.

### 8.2 Application-level counters (Redis/cache — **required**)

DRF is IP-centric. Add cache keys (TTL = window):

| Key pattern | Limit | Window | On exceed |
|-------------|-------|--------|-----------|
| `otp:send:phone:{e164}` | **3** | 1 hour | 429, no SMS |
| `otp:send:phone:{e164}:day` | **5** | 24 hours | 429 |
| `otp:send:ip:{ip}` | **10** | 1 hour | 429 + abuse strike |
| `otp:verify:phone:{e164}` | **10** | 1 hour | 429 |
| `otp:fail:phone:{e164}` | lock after **5** wrong codes | OTP lifetime | force new request |
| `order_sms:phone:{e164}` | **20** | 24 hours | skip send + log (runaway admin edits) |
| `order_sms:global` | env budget e.g. **5000** | 24 hours | skip + alert ops |

Helpers live in `notifications/throttles.py` or `spices_backend/limits.py`:

```python
def allow_otp_send(phone: str, ip: str) -> bool: ...
def allow_order_sms(phone: str) -> bool: ...
```

Fail-**open** only for *order* transactional SMS if cache is down? Prefer fail-**closed** for OTP send (cost), fail-open for order SMS (customer experience) — document the choice. **Recommendation:** OTP send fail-closed; order SMS fail-open with error log.

### 8.3 Security behaviors (must implement)

| Threat | Mitigation |
|--------|------------|
| Phone enumeration | Identical 200 body/timing on login request whether user exists |
| OTP brute force | 6-digit + 5 attempts lock + short TTL + verify rate limit |
| SMS pumping / toll fraud | Per-phone + per-IP + daily caps; verified-phone-only for login |
| Credential stuffing on verify | Generic errors; no “user not found” vs “bad OTP” distinction on login verify where possible |
| Replay | `is_used=True` after success; invalidate siblings on new send |
| Stolen session after phone change | Changing phone clears verification; optional: revoke refresh tokens on phone change (phase 2) |
| Provider webhook spoofing | N/A for send-only; if delivery receipts added later, verify signatures |
| Insider / admin spam | Order SMS only on real status/tracking transitions; de-dupe per status |
| Log leakage | Never log raw OTP or full phone in INFO logs; mask `+91******3210` |

### 8.4 Response codes

| Situation | HTTP |
|-----------|------|
| Throttled | `429` + `Retry-After` when known |
| Bad/expired/locked OTP | `400` or `429` (locked) — match password-reset style |
| Phone taken (authenticated claim) | `400` |
| SMS provider hard-disabled | `503` only for authenticated verify-send if we want UX; login request still generic 200 |

### 8.5 Env-tunable knobs

```env
THROTTLE_PHONE_OTP_SEND=3/hour
THROTTLE_PHONE_OTP_SEND_DAY=10/day
THROTTLE_PHONE_OTP_VERIFY=10/hour
THROTTLE_PHONE_LOGIN=5/minute
OTP_SEND_PER_PHONE_HOUR=3
OTP_SEND_PER_PHONE_DAY=5
ORDER_SMS_PER_PHONE_DAY=20
ORDER_SMS_GLOBAL_DAY=5000
```

---

## 9. Order status SMS (transactional)

### 9.1 When to send

Hook next to existing email calls so behavior stays in sync:

| Event | Trigger today | Email | SMS (new) |
|-------|---------------|-------|-----------|
| Order placed | `OrderViewSet.create` after success | `send_order_confirmation` | `notify_order(order, 'confirmed')` |
| Status advanced | admin `partial_update` | `send_order_status_email(..., status_changed=True)` | same event with status |
| Tracking added | admin update | `send_order_status_email(..., tracking_added=True)` | shipped/tracking template |
| Cancelled | status → `cancelled` | status email | cancelled template |

Implement as `orders/notifications.py` or extend `orders/emails.py` → rename conceptually to “order notifications” calling the shared `notifications` service:

```python
def notify_order_placed(order):
    send_order_confirmation(order)          # email (existing)
    send_order_sms(order, event='confirmed')  # new

def notify_order_update(order, status_changed=False, tracking_added=False):
    send_order_status_email(...)
    send_order_sms(order, event=..., status_changed=..., tracking_added=...)
```

### 9.2 Recipient resolution

Priority:

1. `order.phone_number` (checkout phone — customer expects updates here).
2. Else `order.user.phone` if present.

Normalization before send. Invalid phone → skip SMS, log warning, email still sent.

### 9.3 Opt-in / legal

- **Transactional** order updates are generally allowed under Indian commercial practice when the number was provided at checkout for that order.
- Still honor `user.sms_notifications_opt_in=False` for marketing; **v1:** treat order SMS as transactional and send if phone present, *or* gate on opt-in if legal counsel prefers. **Recommendation:** send transactional order SMS when phone provided at checkout; profile opt-out applies to future marketing only (document for DPDP readiness).
- Auth OTPs are user-initiated → always allowed when rate limits pass.

### 9.4 Content mapping

Reuse `STATUS_MESSAGES` spirit from `orders/emails.py`, shortened for SMS:

| Status / event | SMS intent |
|----------------|------------|
| confirmed / placed | Order number + total |
| processing | Being prepared |
| shipped | Tracking ID if present |
| delivering | Out for delivery |
| delivered | Delivered thank-you |
| cancelled | Cancelled + support hint |

Include order number `ORD-000123` so support chat matches admin search.

### 9.5 De-duplication

- Send status SMS only when `status` **actually changes** (compare pre/post update — already done for email).
- Tracking SMS only when tracking number newly set or changed.
- Optional: skip SMS for `pending` noise if admin toggles back and forth; only notify on forward progress if desired.

### 9.6 Failure isolation

Order create / status PATCH must succeed even if SMS provider is down (same as email).

### 9.7 WhatsApp for orders

Phase 2: same events, template messages only (24h session rules). v1 can be **SMS-only** for orders while WhatsApp is used for OTP if templates approve faster.

---

## 10. Frontend / admin touchpoints

### 10.1 Storefront (`Frontend/nidhi-brand-forge`)

| Screen | Change |
|--------|--------|
| Login | Tab or toggle: **Email** \| **Phone OTP** — phone input + “Send OTP” + OTP field + verify |
| Profile | Phone field + “Verify” / verified badge; SMS order opt-in toggle |
| Forgot password | Channel selector when phone verified (email default) |
| Checkout | Keep collecting `phone_number` (feeds order SMS); hint “We’ll SMS order updates” |

UX rules:

- Disable “Send OTP” button client-side cooldown (e.g. 60s) matching server min interval.
- Show generic success toast on login request (no “number not found”).
- Reuse cookie-based session handling identical to password login response.

### 10.2 Admin panel

- Customer detail: show `phone`, `phone_verified`.
- Order detail: no change required for sending (server-side); optional “SMS sent” log later.
- Do **not** expose bulk SMS tools in v1.

---

## 11. Security properties checklist

| Property | How |
|----------|-----|
| OTP at rest | `make_password` / hasher only |
| OTP in transit | HTTPS only (prod cookies already Secure) |
| Session after phone login | Same HttpOnly JWT cookies as `CustomTokenObtainPairView` |
| Enumeration | Uniform responses on public phone login request |
| Brute force | Attempt lock + rate limits + short TTL |
| Cost abuse | Multi-key send caps + global daily budget |
| Account takeover via phone swap | Re-verify required; unique verified phone |
| Staff abuse | No free-form SMS API; templates only |

---

## 12. Testing plan

### 12.1 Unit / API (`Backend/`, pytest)

- Normalize phone: local, E.164, invalid.
- OTP hash/expiry/lock same as `TestOTPModel`.
- Login request: unknown phone → 200, **zero** backend send calls (mock).
- Login request: verified phone → send called once; second request within window → 429.
- Login verify: wrong code increments attempts; 5th locks.
- Login verify: success sets cookies `access_token` / `refresh_token`.
- Verify send requires auth; cannot verify another user’s number.
- Unique phone constraint on second verified claim.
- Order status SMS: mock backend; status change triggers SMS; no change → no SMS.
- Order SMS respects per-phone daily cap.
- Password-reset SMS only when `phone_verified`.

### 12.2 Integration

- `SMS_PROVIDER=console` in test settings; assert log/call args contain template id + masked phone.
- Concurrency: two parallel send-otp for same phone — only one active OTP (invalidate others).

### 12.3 Manual / staging

- Real MSG91 test credits + DLT test template.
- Full Chrome flow: profile verify → logout → phone OTP login → place order → admin status change → SMS received.

---

## 13. Rollout phases

| Phase | Work | Depends on |
|-------|------|------------|
| **0** | Provider account, DLT entity/header, OTP + order templates submitted | Business docs |
| **1** | `notifications` app, backends, env, console provider, phone normalize | — |
| **2** | User fields migration + phone verify endpoints + profile UI | Phase 1 |
| **3** | **Phone OTP login endpoints** + storefront login UI + throttles/abuse | Phase 2 |
| **4** | Password-reset channel selection | Phase 2 |
| **5** | **Order confirmation + status SMS** wired beside email | Phase 1 + DLT order templates |
| **6** | WhatsApp OTP (and optional order templates) | BSP approval |
| **7** | Delivery log, admin resend, metrics/dashboards | Optional |

**Ship order recommendation:** 0 → 1 → 2 → 3 → 5 → 4 → 6.  
Phone login (3) and order SMS (5) are both in scope for the product goal; they can parallelize after Phase 1–2.

Feature flags:

```env
FEATURE_PHONE_OTP_LOGIN=True
FEATURE_ORDER_SMS=True
FEATURE_WHATSAPP_OTP=False
```

---

## 14. Observability

- Structured logs: `purpose`, `channel`, `provider`, `success`, masked destination, `order_id`.
- Metrics (later): sends/day, failures, 429 rates, cost estimate.
- On global budget hit: `logger.error` + existing abuse/monitoring path (`MONITORING_PLAN.md`).
- Never put OTP codes in logs or Sentry breadcrumbs.

---

## 15. Docs to update when implementing

| Doc | Update |
|-----|--------|
| `Backend/docs/AUTH.md` | Phone verify + phone OTP login flows, throttles table |
| `Backend/docs/API_PERMISSIONS.md` | New routes + auth requirements |
| `Backend/docs/ORDER_LIFECYCLE.md` | SMS side effects on create/status |
| `Backend/docs/ARCHITECTURE.md` | `notifications` app |
| `CLAUDE.md` / env section | SMS/WhatsApp env vars |
| `DEPLOYMENT.md` | DLT/provider secrets on EC2 `~/NGU/.env.backend` |

---

## 16. Open decisions

1. **Provider** — MSG91 (recommended) vs Gupshup vs Twilio?
2. **Phone-first registration** — v1 verified-only login (Policy A) vs auto-create accounts?
3. **Order SMS opt-out** — always transactional if checkout phone present, or honor profile flag?
4. **WhatsApp in v1** — OTP only, or defer entirely until SMS is stable?
5. **Generalize OTP model** vs separate `PhoneOTP` table?
6. **Partial unique index** on phone — Postgres-only migration strategy for SQLite tests?

---

## 17. Resolved product scope (this revision)

| Item | Decision in this plan |
|------|------------------------|
| Mobile number login | **In scope** — `/api/auth/phone/login/request/` + `/verify/` |
| Rate limits | **Layered** — DRF IP scopes + per-phone cache caps + verify lockout + order SMS budgets |
| Order status SMS | **In scope** — confirmed, status changes, tracking, cancelled; fail-soft beside email |
| Password-reset SMS | In scope after phone verification |
| WhatsApp | Supported in abstraction; OTP first, orders later |

---

## 18. Implementation sketch (for engineers)

### 18.1 Throttle classes (`users/throttles.py` or `spices_backend/throttles.py`)

```python
class PhoneOtpSendThrottle(_FlaggedThrottle):
    scope = "phone_otp_send"

class PhoneOtpSendDayThrottle(_FlaggedThrottle):
    scope = "phone_otp_send_day"

class PhoneOtpVerifyThrottle(_FlaggedThrottle):
    scope = "phone_otp_verify"

class PhoneLoginThrottle(_FlaggedThrottle):
    scope = "phone_login"
```

Views stack **both** DRF classes and `allow_otp_send(phone, ip)` before calling the provider.

### 18.2 Cookie issuance

Extract shared helper from `CustomTokenObtainPairView` / Google login:

```python
def set_jwt_cookies(response, user):
    # issue refresh+access via RefreshToken.for_user(user)
    # set access_token + refresh_token cookies (same flags/max-age as today)
    return response
```

Phone login verify and Google login both call it — one session model.

### 18.3 Minimal acceptance criteria (done means)

- [ ] User can verify phone in profile and see verified badge.
- [ ] User can log in with phone + OTP and receive the same session cookies as password login.
- [ ] Unregistered phone cannot be distinguished via login request response.
- [ ] Exceeding per-phone OTP send limit returns 429 and sends **zero** provider API calls.
- [ ] Placing an order and advancing status in admin results in SMS (staging) without breaking the HTTP handlers if provider fails.
- [ ] `SMS_ENABLED=False` or missing keys does not take down the API.
- [ ] Tests cover happy path + abuse path for login OTP and order SMS de-dupe.
