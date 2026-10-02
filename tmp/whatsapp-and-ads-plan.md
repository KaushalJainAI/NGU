# WhatsApp (Cloud API) + Promo Banners + Campaigns — Implementation Plan

Status: **PLAN ONLY — nothing implemented.** Written 2026-08-08.

Scope agreed with owner:
- WhatsApp: phone login/signup, password reset, phone verification, order notifications
- Provider: **Meta WhatsApp Cloud API** (direct, not a BSP reseller)
- Ads: **in-store promo banners** (admin-managed) + **WhatsApp marketing campaigns**

Explicitly out of scope: Meta Pixel / Google Ads tags, Merchant Center feed.

---

## 0. What already exists (grounding)

| Thing | Where | Note |
|---|---|---|
| Email OTP (password reset only) | `users/views.py:193-355`, `users/models.py:53` (`PasswordResetOTP`) | Already hashed (`make_password`), 10-min expiry, 5-attempt lock, previous-OTP invalidation, opportunistic cleanup, enumeration-safe response. **Good base — copy the discipline, don't extend the model.** |
| `User.phone` | `users/models.py:12` | `CharField(max_length=15, blank=True)` — **not unique, not verified, not normalised**. Duplicates and junk almost certainly exist in prod. |
| Auth = email | `users/models.py:27` `USERNAME_FIELD = 'email'` | JWT issued as httpOnly cookies via `set_access_cookie`/`set_refresh_cookie` (`users/views.py:31-53`). |
| Async notification pattern | `orders/emails.py:60` `_send_async` | Fire-and-forget daemon thread, best-effort, never breaks the transaction. Reused by `send_daily_digest`/`send_weekly_summary`. |
| Notification call sites | `orders/views.py:67`, `payments/services.py:86` | Exactly where WhatsApp sends must hook in. |
| Throttle scopes | `spices_backend/settings.py:335-354` | Named-scope convention already established; add OTP scopes here. |
| Signature-verified webhook precedent | `payments/views.py` (Razorpay L2) | Fail-closed on missing secret. **Mirror this for the Meta webhook.** |
| Scheduler container | `manage.py run_scheduler` | Where queued/retried WhatsApp sends and campaign drains belong. |
| Existing hardcoded WhatsApp link | `Frontend/.../FloatingWhatsApp.tsx:7` → `wa.me/919300005040` | See A.1 — this number may be the blocker. |
| Hardcoded hero | `Frontend/.../HeroSection.tsx:75` static `heroImage` import | The banner feature replaces this with API-driven content + static fallback. |
| Placement precedents | `DealsStrip.tsx`, `PromoCouponStrip.tsx`, `CategoryCapsules.tsx` | Existing homepage slots the banner system can fill. |

---

# PART A — WhatsApp via Meta Cloud API

## A.1 Phase 0 — Meta onboarding (BLOCKING, no code, 1–3 weeks)

This is the long pole. None of the backend work can be verified end-to-end until it clears.

1. **Meta Business Account** for Nidhi Grah Udyog, then **Business Verification** (GST certificate, bank statement / utility bill matching the legal name). Rejections here are common and slow.
2. **WhatsApp Business Account (WABA)** + a **phone number**.
   - **The number must not be registered on the WhatsApp or WhatsApp Business consumer app.** `+919300005040` is currently live as a `wa.me` link on the storefront — if that is a WhatsApp Business app account, migrating it to Cloud API **deletes the app account and its chat history**. Decide early: migrate it, or provision a fresh number and repoint `FloatingWhatsApp.tsx`.
3. **Display name approval** (must plausibly match the business).
4. **System User access token** — a permanent token from Business Settings, *not* the 24-hour temp token in the Getting Started panel. Scope it to `whatsapp_business_messaging` + `whatsapp_business_management`.
5. **Message template approval** — per-category, each needs review (minutes to ~24h):
   - **AUTHENTICATION** (OTP): Meta mandates the fixed authentication-template format. Use the **copy-code** or **one-tap autofill** button variant; free-written OTP copy is no longer accepted. One template can cover all OTP purposes if the body stays generic.
   - **UTILITY** (order placed / shipped / delivered / COD confirmation): one template per event, with `{{1}}`-style variables for order number, tracking, amount.
   - **MARKETING** (campaigns, Part C): separate approval, stricter review.
6. **Pricing / limits** — Meta bills **per message**, tiered by category (authentication < utility < marketing, marketing several times dearer). India rates changed repeatedly through 2025–26, so **pull the current rate card from Meta's pricing page before committing to a budget** rather than trusting any number in this doc. New WABAs start at a low **messaging tier (1k unique recipients/24h)** that scales with quality rating.
7. **24-hour customer service window** — free-form (non-template) messages are only permitted within 24h of the customer's last inbound message. **Every transactional send must therefore be a template.**

**Deliverable of Phase 0:** WABA id, phone number id, permanent token, app secret, webhook verify token, approved template names — the values that populate the env block in A.2.

## A.2 Phase 1 — `messaging` Django app (provider-agnostic core)

A new app so WhatsApp isn't smeared across `users`/`orders`. Provider-agnostic so a BSP swap later, or an SMS fallback, is a new file rather than a rewrite.

```
Backend/messaging/
├── providers/
│   ├── base.py       # WhatsAppProvider ABC: send_template(to, template, lang, params) -> wamid
│   ├── meta.py       # Cloud API: POST https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages
│   └── console.py    # dev/test: logs and returns a fake wamid. NEVER touches the network.
├── models.py         # WhatsAppMessage, OtpChallenge
├── services.py       # queue_template(), the only public entry point
├── views.py          # webhook (public, signature-verified) + admin log endpoints
└── management/commands/drain_whatsapp_queue.py
```

**Settings / env** (mirror the Razorpay boot-guard style — fail loudly on misconfiguration):

```env
WHATSAPP_ENABLED=False              # master kill switch; False => console provider
WHATSAPP_PROVIDER=meta              # meta | console
WHATSAPP_API_VERSION=v21.0
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_WABA_ID=
WHATSAPP_ACCESS_TOKEN=              # System User permanent token
WHATSAPP_APP_SECRET=                # for X-Hub-Signature-256 verification
WHATSAPP_WEBHOOK_VERIFY_TOKEN=      # random string, echoed during GET handshake
WHATSAPP_TEMPLATE_OTP=ngu_otp
WHATSAPP_TEMPLATE_ORDER_PLACED=ngu_order_placed
WHATSAPP_TEMPLATE_ORDER_SHIPPED=ngu_order_shipped
WHATSAPP_TEMPLATE_ORDER_DELIVERED=ngu_order_delivered
WHATSAPP_DAILY_SEND_CAP=2000        # hard cost guard; breach => stop + alert admin
```

**Model `WhatsAppMessage`** (the audit/cost/debug ledger — do not skip it):
`to_e164, template, category, params(JSON), wamid, status(queued|sent|delivered|read|failed), error_code, error_detail, attempts, user FK(null), order FK(null), campaign FK(null), created_at, sent_at`.

Why it earns its place: delivery-status webhooks arrive asynchronously and need a row to update; per-message billing needs an auditable count; Meta error codes (131047 re-engagement, 131026 undeliverable, 132000 template param mismatch) are otherwise invisible.

**Sending discipline:**
- `services.queue_template()` writes a `queued` row inside the caller's transaction and returns immediately. **Never** an HTTP call in the request path.
- The **scheduler container** drains the queue (new command, ~30–60s cadence) with retry + backoff. Strictly better than `orders/emails.py`'s daemon-thread pattern here, because a dropped OTP is a user-visible failure and money is involved.
- Optional interim: reuse `_send_async` for OTP only (latency matters) with the queue as the retry net.

**Webhook** `POST /api/messaging/whatsapp/webhook/` + `GET` for the `hub.challenge` handshake:
- Verify `X-Hub-Signature-256` = HMAC-SHA256(raw body, `WHATSAPP_APP_SECRET`). **Fail closed** if the secret is blank — same rule as Razorpay (and note from CLAUDE.md that prod's Razorpay webhook secret is *currently* blank; that's the failure mode to not repeat).
- Read the raw body *before* DRF parses it, or the HMAC won't match.
- Handle `statuses[]` → update `WhatsAppMessage.status`. Handle `messages[]` (inbound) → opt-out keywords (`STOP`/`UNSUBSCRIBE`) and, later, routing into the existing `assistant` human-support inbox.
- Idempotent on `wamid` — Meta retries.

**Testing:** `console` provider + `requests_mock` for the Meta path. The suite must never reach `graph.facebook.com`.

## A.3 Phase 2 — Phone identity (the risky migration)

Do **not** change `USERNAME_FIELD`. Email stays the login identifier; phone becomes an *additional verified identifier* with its own login endpoint that issues the same JWT cookies. This keeps SimpleJWT, Google OAuth, and every existing auth test untouched.

New fields on `User`:
- `phone_e164 = CharField(max_length=16, unique=True, null=True, blank=True)` — nullable so unverified/duplicate legacy rows don't collide.
- `phone_verified_at = DateTimeField(null=True)`
- `wa_opt_in = BooleanField(default=False)` + `wa_opt_out_at` (needed for Part C compliance)

**Data migration** — normalise legacy `User.phone` → E.164 (assume `+91` when 10 digits, else leave):
- Use `phonenumbers` (new dependency) for parsing/validation; a hand-rolled regex will not survive Indian number variety.
- On collision (two accounts, same number) **leave both `phone_e164` NULL** and write the conflicts to a report file. Do not guess which account owns the number.
- Run `--dry-run` against a prod DB dump first. Expect a non-trivial conflict count.
- Keep the old `phone` column as-is (display/shipping); `phone_e164` is the identity column.

**Signup-by-phone open question:** a phone-first signup still needs an email, because `email` is unique+required and every order email keys off it. Two options:
- **(recommended)** Require email at signup; phone is a verified second identifier and a login shortcut. No synthetic data, no broken emails.
- Synthesise `+91XXXXXXXXXX@phone.nidhimasala.com`. Cheaper UX, but order confirmations bounce silently and the "email already exists" path gets weird. If chosen, order emails must be suppressed for synthetic addresses and WhatsApp becomes the only receipt channel — a real dependency on Meta uptime.

## A.4 Phase 3 — OTP flows

**New model `OtpChallenge`** (in `messaging`) — do **not** overload `PasswordResetOTP`, whose semantics are email+reset-specific and whose `reset_token` field is load-bearing for the existing flow.

Carry over verbatim from `PasswordResetOTP` (they're already correct): hashed code via `make_password`, `expires_at`, `failed_attempts` + `MAX_FAILED_ATTEMPTS` lock, invalidate-previous-on-issue, opportunistic cleanup of >24h rows, constant-time compare.

Add:
- `purpose` ∈ {`login`, `signup`, `reset`, `verify_phone`}
- `channel` ∈ {`whatsapp`, `email`, `sms`} — lets password reset offer WhatsApp *alongside* email through one code path
- `destination` (E.164 or email) — challenges must be issuable to a number with **no user row yet** (signup), so the `user` FK must be nullable. This alone justifies the new model.
- `send_count` + `last_sent_at` for resend cooldown (e.g. 60s)

**Endpoints** (all need rows added to `Backend/docs/API.md` — see the maintain-API-map rule):

| Route | Method | Access | Notes |
|---|---|---|---|
| `/api/auth/phone/otp/request/` | POST | AllowAny | `{phone, purpose}`. **Enumeration-safe**: identical response whether the number exists or not (the email reset endpoint already does this — copy it). |
| `/api/auth/phone/otp/verify/` | POST | AllowAny | `{phone, code, purpose}`. `login` → sets JWT cookies. `verify_phone` → stamps `phone_verified_at`. `reset` → returns `reset_token`, then reuses the **existing** `PasswordResetConfirmView`. |
| `/api/auth/phone/register/` | POST | AllowAny | Only if phone-first signup is chosen (A.3). |
| `/api/users/me/phone/` | POST/DELETE | IsAuthenticated | Start/clear phone verification from the profile page. |

**Abuse + cost controls** — an OTP is real money, so this is not optional:
- New throttle scopes in `settings.py`: `otp_send` (~3/min per IP), `otp_send_day`, `otp_verify` (~10/min).
- **DRF throttles by IP/user, not by the phone number in the request body.** A per-destination counter in Redis (e.g. 5/hour, 15/day per E.164) must be enforced in the view. Without it, one attacker rotating IPs bills you at will.
- Global `WHATSAPP_DAILY_SEND_CAP` circuit breaker → stop sending, alert admin (reuse `orders/emails.py::_admin_recipient`).
- Resend cooldown surfaced to the frontend so the button can grey out.
- Never return the code in any response, and never log it (the current email flow keeps it out of logs — hold that line).

## A.5 Phase 4 — Order notifications

Mirror `orders/emails.py` as `orders/whatsapp.py`, hooked at the **same call sites** so the two channels stay in step:
- `orders/views.py:67` (status transitions, tracking added)
- `payments/services.py:86` (payment captured → confirmation)
- COD "Paid in cash" tick (per CLAUDE.md) → a natural utility-template moment.

Rules:
- Only to users with `phone_verified_at IS NOT NULL` **and** `wa_opt_in=True`. Unverified numbers produce Meta error 131026 and hurt quality rating.
- Templates only (24h window rule). Params must exactly match the approved template's variable count or Meta 400s with 132000.
- Best-effort: a WhatsApp failure must never roll back an order — same contract as the email layer.
- Send on both channels at first; consider making email the fallback only once delivery rates are proven.

---

# PART B — In-store promo banners (independent, unblocked, do this first)

Needs no Meta approval, so it can ship while Phase 0 grinds.

**Model `PromoBanner`** (put it in `admin_panel`, alongside coupons/policies):

```
title, subtitle, image (Cloudinary ImageField + existing validate_file_size/
validate_image_extension/validate_image_content), mobile_image,
placement ∈ {home_hero, home_strip, category_top, cart, product_detail},
link_type ∈ {product, category, combo, url, none} + link_target,
cta_label, display_order, is_active, starts_at, ends_at, created_at
```

Scheduling is a query-time filter on `starts_at <= now <= ends_at` — no cron needed.

**API:**
- `GET /api/banners/?placement=home_hero` — AllowAny, Redis-cached per `docs/CACHING_STRATEGY.md`, invalidated on save/delete.
- Admin CRUD viewset (`IsAdminUser`), image upload identical to `ProductImage`.
- Add both to `docs/API.md`.

**Frontend:**
- `HeroSection.tsx:75` currently imports a static `heroImage`. Make it API-driven **with the static image as fallback** — a failed fetch or empty result must never blank the hero.
- `DealsStrip` / `PromoCouponStrip` are existing slots that can render `home_strip` banners.
- Admin panel: a Banners page with drag-order + live preview, following the existing product-section UI patterns.

**Measurement:** emit `banner_impression` / `banner_click` through the **existing** `analytics` event ingest (`/api/analytics/events/`). No new pipeline — the rollup and Insights API already exist, so banner performance lands in the admin dashboard for free.

---

# PART C — WhatsApp marketing campaigns

Depends on Part A shipping first. Highest reward and highest risk — a bad campaign gets the number quality-rated down and eventually blocked.

**Policy, non-negotiable:**
- MARKETING-category templates, separately approved.
- **Explicit opt-in required** (`wa_opt_in`), captured with timestamp and source (checkout checkbox / profile toggle). Do not blanket-opt-in the existing customer base.
- Honour `STOP` inbound instantly via the webhook, and never send to anyone with `wa_opt_out_at` set.
- Respect the messaging tier; start small and let the quality rating raise the cap.

**Models:** `Campaign` (name, template, param map, audience filter JSON, scheduled_at, status, spend cap) + `CampaignRecipient` (campaign, user, `WhatsAppMessage` FK, status). Per-recipient rows are what prevent double-sends on retry and give per-campaign delivery stats.

**Audience segments** — reuse what `analytics` already computes (`analytics/insights_views.py::customers`): ordered-in-last-90d, never-ordered, high-value, lapsed. **Abandoned cart is the highest-ROI segment and the `cart` app already holds the data.**

**Sending:** the scheduler container drains `CampaignRecipient` in rate-limited batches. Never in a request. Hard spend cap per campaign, enforced against `WhatsAppMessage` counts.

---

# Sequencing & effort

| Phase | Work | Blocked by | Rough effort |
|---|---|---|---|
| **B** Promo banners | model + API + admin UI + hero rewire | nothing | 3–5 days |
| **0** Meta onboarding | business verification, number, templates | Meta review | 1–3 weeks wall-clock, ~0 dev |
| **1** `messaging` app | provider, queue, webhook, log | 0 (only partially — build against `console`) | 4–6 days |
| **2** Phone identity | fields + E.164 migration + conflict report | — | 2–3 days + careful prod dry-run |
| **3** OTP flows | model, endpoints, throttles, frontend screens | 0, 1, 2 | 5–7 days |
| **4** Order notifications | `orders/whatsapp.py` + hooks | 0, 1, 2 | 2–3 days |
| **C** Campaigns | models, segments, drain, admin UI | 0, 1, 2, 4 | 6–8 days |

**Recommendation:** start Phase 0 (paperwork) and Part B (banners) **in parallel** — Phase 0 is pure waiting, Part B is pure code with no external dependency. Build Phase 1 against the `console` provider so it's finished and tested the day the Meta credentials land.

# Top risks

1. **`+919300005040` conflict** — migrating a number off the WhatsApp Business app is destructive. Resolve before anything else.
2. **Business verification rejection** — restarts the clock. Get the GST/bank documents exactly name-matched first time.
3. **Phone-number collisions in prod data** — the E.164 migration will find duplicates. Plan a manual reconciliation pass; do not auto-merge accounts.
4. **OTP send abuse = direct billing** — the per-destination Redis counter is the control that matters; the DRF IP throttle is not sufficient.
5. **Blank `WHATSAPP_APP_SECRET` in prod** — exactly the failure mode the Razorpay webhook secret is currently in (see CLAUDE.md). Fail closed *and* add a startup warning so it can't sit broken unnoticed.
6. **Template drift** — changing an approved template's variable count without updating the params dict silently 400s every send. Pin template names in env and assert param counts in tests.
7. **Quality rating** — one aggressive campaign can throttle or block the number that OTPs also depend on. Consider a **separate number for marketing** vs transactional if volume justifies it.

# Open decisions for the owner

1. Migrate `+919300005040` to Cloud API, or provision a new number?
2. Phone-first signup: require an email (recommended), or synthesise one?
3. Order notifications: WhatsApp *in addition to* email, or eventually replacing it?
4. One WhatsApp number for both OTP and marketing, or two?
