# Security, assistant, voice and storefront audit — 2026-10-01
# REWRITE 2026-10-01: step-by-step task cards, sequenced AFTER improvement-plan

Scope: Backend (Django API), storefront (`Frontend/nidhi-brand-forge`), deployment
config. The admin panel was only checked for auth behaviour.

How to read the "Evidence" column:

- **Tested** — reproduced with a throwaway pytest run against in-memory SQLite
  (nothing touched production).
- **Code** — read in the source or config; not executed.

Nothing in this audit was run against the live site, so anything that depends on
production data or the production env is marked as unknown.

**Status of this rewrite:** the original plan (Phase 0–4) assumed a clean tree.
`IMPROVEMENT_PLAN.md` is now being implemented on branch `improvement-plan` in
all three repos (WP1–WP3 committed, WP4 in progress as of this writing). This
rewrite keeps all findings, drops the one item WP1 already fixed (S2 logout),
and re-expresses everything else as task cards (AP1–AP12) that start FROM the
`improvement-plan` tip and reuse WP1's code. No code in the three repos was
changed to produce this rewrite.

---

## 0. Start here — read before any AP (sequencing + WP1 reuse)

### 0.1 Where to branch from

`NGU/` is not a git repo. There are three separate repos:

| Short name | Path |
|---|---|
| Backend | `Backend/` |
| Panel | `Admin Panel/e-commerce-command-center/` |
| Storefront | `Frontend/nidhi-brand-forge/` |

Do NOT branch off `main`. Do NOT work on `improvement-plan` directly.

1. In each repo: `git checkout improvement-plan`, `git pull` (local only — do
   not push), then `git checkout -b audit-plan`.
2. All APs below run on `audit-plan`, in the order given. Each AP is
   independent unless it says "Needs APn".
3. Make one commit per AP per repo you touch. Do not push. Do not deploy.
   Do not SSH anywhere.

Expected `improvement-plan` tip (2026-10-01, verify with `git log --oneline -3`):

- Backend: `c835e47 WP4` on top of `40bfd89 WP1`
- Panel: `c068570 WP4` on top of `a106945 WP2`
- Storefront: `06b4e71 WP4` on top of `eafcac8 WP3`

If the tip has moved (WP5–WP8 landed), still branch from the tip — do not
rebase back to these hashes. If `improvement-plan` has already been merged to
`main`, branch `audit-plan` from the merged `main` instead and note it in the
AP1 report.

### 0.2 What WP1 already gives you (do not reimplement)

WP1 (`Backend/users/authentication.py`, `users/views.py`,
`spices_backend/urls.py`, `spices_backend/settings.py`) already did:

- Customer cookies stay `access_token` / `refresh_token`.
- Admin cookies are `admin_access_token` / `admin_refresh_token`
  (`ADMIN_ACCESS_COOKIE`, `ADMIN_REFRESH_COOKIE`, `ADMIN_SCOPE = 'admin'`).
- Panel sends `X-Admin-Panel: 1`; `is_admin_panel_request(request)` picks the
  cookie. Admin tokens carry `scope='admin'` via `admin_tokens_for(user)`.
- `POST /api/auth/logout/` (customer only) and
  `POST /api/auth/admin/logout/` (admin only) exist, using
  `_blacklist_quietly(raw)` + `clear_auth_cookies(response, access_key, refresh_key)`.
- `verify_google_id_token(token)` helper shared by both Google views.
  `GoogleLogin` keeps its old statuses; `AdminGoogleLoginView` never creates.
- Tests in `Backend/users/test_admin_session.py` (12 tests).

**Reuse these in every auth AP below.** S2 (logout 404) is therefore CLOSED —
do not add another logout route. When an AP says "blacklist", call
`_blacklist_quietly` (single token) or blacklist every outstanding token for
the user (S4/AP3). When it says "clear cookies", call `clear_auth_cookies`
with the matching pair — never clear the other session's cookies.

### 0.3 Rules for the implementer (apply to every AP)

Copied from `IMPROVEMENT_PLAN.md`, adapted:

**Never touch production.** Do not run anything against `nidhigrahudyog.com`,
`nidhimasala.com`, `13.235.238.99` or `13.201.33.243`. Never load
`Backend/.env.local` (it points at a remote database).

**How to check your work.**

- Backend: `cd Backend && venv/Scripts/python.exe -m pytest -q`
  Expected at AP start: whatever `improvement-plan` tip gives (about
  1280 passed + 12 new WP1 tests, 8 skipped). Two tests,
  `orders/test_concurrency.py::test_G4` and `test_G5`, fail on SQLite with
  "database table is locked". That is known. Any other failure is yours.
- Panel and Storefront: `npx tsc --noEmit` and `npm run build`, both must pass.
- To run the stack locally and click through it, follow
  `.claude/skills/verify/SKILL.md`.

**Code rules.**

1. Money is always `Decimal`, rounded with `.quantize(Decimal('0.01'))`. Never use `float` for arithmetic.
2. "Today" is `timezone.localdate()`, never `date.today()` or `timezone.now().date()`.
3. Date-range filters use `range_filter` from `Backend/spices_backend/timeranges.py`.
4. New migrations are generated with `venv/Scripts/python.exe manage.py makemigrations <app>`. Never edit an existing migration file.
5. Every new or changed HTTP route must be added to `Backend/docs/API.md` in the same commit.
6. Every new Panel string goes in BOTH `src/i18n/locales/en/*.json` and `src/i18n/locales/hi/*.json`. Storefront strings go in `src/i18n/locales/en.json` and `hi.json` and are called as `t('key', 'English default')`.
7. Match the comment style and naming of the file you are editing.

**Do NOT change any of these** (waiting on the owner's accountant):

- any product `tax_rate` or `hsn_code`;
- how delivery is taxed (`SHIPPING_CHARGE_NET`, `SHIPPING_TAX_RATE`, SAC 9968);
- the name `SHIPPING_CHARGE_NET` (do not rename it back to `SHIPPING_CHARGE`);
- the disabled `refund.processed` webhook branch in `payments/views.py`.

**If the code you find does not match what this plan describes, stop that AP and
report the difference. Do not improvise.**

**After each AP, report:** files changed, tests added, and the last lines of the
pytest / tsc / build output.

---

## 1. Security findings

### High

| ID | Finding | Evidence | Where |
|----|---------|----------|-------|
| S1 | **Account pre-hijack via registration + Google sign-in.** Anyone can register with someone else's email (no proof of ownership). When the real owner later signs in with Google, they are merged into that account and the attacker's password keeps working. The attacker then sees the owner's orders, addresses and phone. | Tested: register → Google sign-in → attacker password login returns 200 | `users/views.py` `UserRegistrationView`, `GoogleLogin` |
| S2 | **CLOSED by WP1 — do not reimplement.** `POST /api/auth/logout/` and `POST /api/auth/admin/logout/` now exist with separate cookies (`test_admin_session.py` tests 7–10 cover them). The audit's "logout 404" no longer reproduces on `improvement-plan`. | Was: Tested logout → 404 | Now: `users/views.py` `LogoutView`, `AdminLogoutView` |
| S3 | **Email can be changed with no proof and no password.** `PATCH /api/auth/profile/` accepts a new email immediately. This is a second route to S1 (point your account at a victim's address and wait), and it turns any stolen session into a permanent takeover: change email, then use password reset. | Tested: PATCH returns 200 with the new email | `users/serializers.py` `UserSerializer` |
| S4 | **Sessions survive a password change or reset.** Old access and refresh tokens keep working, so resetting a password does not evict whoever is already in. | Tested: old refresh token still refreshes after the password changed | `ChangePasswordView`, `PasswordResetConfirmView` |
| S5 | **The chat endpoint can stall the whole API.** Gunicorn runs 3 workers × 2 threads = 6 concurrent requests. One chat turn makes up to 4 sequential LLM calls with no request timeout configured. One account may send 20 turns/min, and accounts are free to create (S1). Six slow chats block checkout and payment verification for everyone. | Code | `Backend/Dockerfile` CMD, `assistant/agent.py` |
| S6 | **Django admin is on the public internet with password-only login.** `/admin/` is proxied by the storefront nginx. DRF throttles do not apply to it, so there is no rate limit on staff password guessing, and no second factor. | Code (nginx + urls) | `Frontend/nidhi-brand-forge/nginx.conf` |

### Medium

| ID | Finding | Evidence | Where |
|----|---------|----------|-------|
| S7 | **Fake COD orders can drain stock.** An unverified throwaway account can place COD orders (limits: 10/min, 100/day, 100 units × 50 lines, no value cap below ₹99.9 lakh). Stock is held until an admin cancels; the auto-cancel job only covers unpaid ONLINE orders. | Code | `orders/views.py` `create`, `spices_backend/limits.py` |
| S8 | **Uncapped LLM spend per account.** 500 turns/day × up to 4 calls each, and each call may carry up to ~200k tokens of thread history. Combined with free accounts this is a cost-abuse path. | Code | `assistant/agent.py` `MODEL_CONTEXT_TOKENS`, throttles in `settings.py` |
| S9 | **Registration reveals which emails have accounts** ("User with this email already exists"), while the password-reset flow carefully hides the same fact. | Tested | `UserRegistrationSerializer` |
| S10 | **Password-reset weaknesses.** OTP is generated with `random`, not a cryptographic source. Requests are capped per IP (10/day) but not per account, so a victim's inbox can be flooded from rotating IPs. Lookups use the exact-case email while stored emails are lower-cased, so `Me@Gmail.com` silently gets no OTP. | Code | `users/views.py` password reset views |
| S11 | **Admin assistant sends customer PII to a third-party model.** `find_customer` and `list_recent_orders` put names, emails and phone numbers into prompts sent through OpenRouter. | Code | `assistant/admin_tools.py` |

### Low

| ID | Finding | Evidence |
|----|---------|----------|
| S12 | Public product API returns exact `stock`, `low_stock_threshold` and `sku` — a competitor can track sales velocity by polling. | Code (`products/serializers.py`) |
| S13 | No Content-Security-Policy. nginx `add_header` inside nested `location` blocks drops the server-level security headers for JS/CSS assets and `config.js`. | Code |
| S14 | Google sign-in failure returns the raw library error string to the client. | Code |
| S15 | `KaushalJainAI_accessKeys (1).csv`, `my-pem.pem` and `backend_remote.env` sit in the project folder. They are not tracked in the Backend git repo (checked, including history). AWS is reportedly unused, so the access key should be deactivated rather than kept. | Checked git only; file contents not opened |

### Already known (from CLAUDE.md), still open

- Production has no Razorpay webhook secret, so every webhook is rejected.
- Database backups live on the same disk as the database.

### Checked and found sound

Payment verify/webhook signature handling, order ownership checks, cart and order
IDOR protection, review verified-purchase gate, CSRF on cookie auth, throttle
identity behind the two nginx hops, assistant tool scoping (the model cannot name
another user), no secrets in git.

---

## 2. Assistant findings

### Bugs

| ID | Finding | Evidence |
|----|---------|----------|
| A1 | **Search crashes whenever a combo matches.** `build_suggestions` calls `.only('price')` on `ProductCombo`, which has no `price` column. The storefront autocomplete (`/api/search/suggest/`) returns 500, and the assistant's `search_products` returns "That lookup failed". | Tested (`FieldDoesNotExist`) — `products/recommendations.py:214` |
| A2 | **A provider error becomes a 500.** `Agent.run` does not catch exceptions from the LLM call. The customer's message is saved with no reply. CLAUDE.md records the API keys as revoked on 2026-08-08; if that still holds, the assistant is fully down in production (unknown — not checked). | Tested |
| A3 | **Multi-item requests fail.** One tool call per LLM round and a cap of 4 rounds means "haldi, jeera, dhaniya, mirch" exhausts the loop and returns the apology text. | Tested |
| A4 | **Every failure is escalated to a human.** Loop exhaustion and unparseable output both set `needs_human`, filling the admin inbox with threads nobody asked to escalate. A reply cut off by the 600-token output limit is unparseable, so long list answers (especially in Hindi/Gujarati scripts) are the most exposed. | Tested |
| A5 | **"Our team has been notified and will join shortly" is not true.** Escalation only sets a flag. The owner hears about it in the 08:00 daily digest unless they happen to have the panel open. | Code |

### Design problems

- **Hand-rolled JSON envelope instead of the model's native tool calling.** This is
  the root of A3 and A4: one tool per round trip, a repair retry, and a parse
  failure path. Native tool calling allows several lookups in one round and
  removes the parsing layer.
- **No awareness of pack sizes.** Tools return product-level price and stock, and
  `add_to_cart` has no `variant_id`, so "500 g haldi" always adds the default
  size. For a spice shop this is the main thing a customer specifies.
- **One item per turn, one click per item.** The prompt forbids proposing more
  than one item, so a five-item order is five round trips and five button taps.
- **Missing tools:** offers/coupons, delivery fee and free-shipping threshold,
  tracking number, change/remove cart lines.
- **Policy answers come from a retired table.** `get_policy` reads
  `admin_panel.Policy`, whose routes were retired; the storefront shows static
  pages instead. With no rows the tool says "no policy published" (whether
  production has rows is unknown).
- **No streaming.** The customer watches a spinner for the whole multi-call turn.
- **After any admin message the AI may never propose add-to-cart again** in that
  thread, even once the thread is handed back.
- **Action buttons are lost on reload** (not returned with message history) and
  stay clickable after use, so one tap can be repeated.
- **Dead route:** the navigation allowlist includes `/track-order`, which the
  storefront does not have.
- **Leftovers:** anonymous-session code paths remain although chat is login-only.

---

## 3. Voice ordering findings

Why it is not useful today:

1. **It is not hands-free.** Tap to start, tap to stop (no silence detection),
   wait for transcription, wait for the multi-call LLM turn, then tap a button to
   confirm — once per item. Tapping "Add" on a product card is faster.
2. **Voice mode never turns off.** Using the mic once sets `voiceMode` for the
   rest of the session, so every later typed reply is read aloud. Speech is not
   stopped when the widget closes.
3. **Read-aloud uses the browser's default voice with no language set**, so Hindi,
   Gujarati, Marathi and Punjabi replies are read by an English voice or skipped.
4. **Failures are silent.** A denied mic permission or a failed transcription
   shows nothing (the error is swallowed).
5. It inherits every assistant problem above: no sizes, one item per turn.

---

## 4. Storefront "AI slop" findings

Read from the code; not yet viewed in a browser.

### Content that is untrue or unverifiable

- **"1.1M+ happy customers / happy kitchens"** in the hero, the home CTA and the
  About counter. `settings.py` estimates about 25,000 orders a year. "50+
  products" and "100%" are likewise hardcoded.
- **Invented testimonials** ("Priya Sharma", "Rajesh Kumar") are no longer
  rendered but still ship in all six locale files.
- **Hardcoded coupon codes** `NIDHI20`, `FREESHIP`, `COMBO15` in
  `PromoCouponStrip` (currently imported but unused). If rendered, it advertises
  codes that may not exist.
- **Made-up default weight.** `ProductCard` defaults `weight` to `"100g"`, so a
  product with no weight shows a wrong pack size.

### Generic copy

"Taste of Tradition in Every Spice", "Made with love, delivered with care",
"Ready to Spice Up Your Kitchen?", "Quality Assured — Premium quality products",
four interchangeable "values" cards. None of it says anything specific to Nidhi.

### Decoration overload

- The same squiggle SVG on the hero, the categories block, every coupon and
  **every product card**.
- An uppercase "eyebrow" label above all seven home sections.
- Hover-lift on nearly every element; a pulsing discount badge on every card; a
  permanently pulsing chat launcher; floating emoji on About, Contact and My
  Orders; a marquee ribbon; an entrance animation on every route change.
- Discount shown three times on one card (badge, "% off", "you save").

### Inconsistency and crowding

- Emoji used as icons in the navbar and mobile bottom nav, lucide icons
  everywhere else.
- On a phone: ribbon + navbar on top; bottom nav + floating cart bar + WhatsApp
  button + chat + cookie banner at the bottom.

### Performance

- The home page shows a full-screen spinner until five requests finish, one of
  which downloads every product just to serve as a fallback.

---

## 5. Plan — task cards AP1–AP12 (do in order)

Overview:

- AP1–AP4: stop the bleeding. Backend-only, no frontend rebuild. S2 already
  done by WP1, so AP1 starts at the old Phase-0 item 4.
- AP5–AP8: auth and abuse hardening, built on WP1's cookies/helpers.
- AP9–AP10: rebuild the assistant (keeps the closed registry, user scoping,
  confirm-before-write, human handoff).
- AP11: voice — rebuild around one job, or remove.
- AP12: storefront clean-up.
- §6: final docs pass. §7: owner decisions + deploy order.

---

### AP1 — Combo crash fix (A1). Backend-only. Do first.

**Why:** one-line crash, blocks both autocomplete and the assistant's search.
Proves the new branch + test setup before touching auth.

**Needs:** nothing (starts from `audit-plan` = `improvement-plan` tip).

**Steps — `Backend/products/recommendations.py` (`build_suggestions`, ~line 214):**

1. The combo query uses `.only('id', 'name', 'slug', 'price', 'discount_price',
   'image', 'thumbnail')`. `ProductCombo` has NO `price` column — `price` is a
   `@property` (sum of components; see `products/models.py:909`). `.only()`
   on a property raises `FieldDoesNotExist` the moment a combo matches.
2. Change the combo `.only()` to
   `('id', 'name', 'slug', 'discount_price', 'image', 'thumbnail')` — drop
   `'price'` only. Do NOT touch the product `.only()` (Product HAS a column).
3. Do NOT add `select_related`/`prefetch_related` here; keep the diff to the
   one field. `final_price` stays as-is (it already handles
   `discount_price or price`).

**Tests — add to `Backend/products/test_search_suggest.py` (new file if missing):**

1. Seed 1 product + 1 combo whose names share a token; call
   `build_suggestions(token)` and assert 200-equivalent dict with both entries
   and no exception.
2. Direct regression: combo with `discount_price=None` still returns
   `price == float(combo.final_price)`.

**Done when:** the two new tests pass, `GET /api/search/suggest/?q=<token>`
returns both types locally, all existing tests pass, and no migration was
created.

---

### AP2 — LLM failure hardening + chat timeout (A2, S5-part). Backend-only.

**Why:** today a provider error (or the revoked key noted in CLAUDE.md) is a
500 with the message saved and no reply; a slow model also holds one of the 6
gunicorn slots indefinitely.

**Needs:** AP1.

**Steps:**

1. `Backend/assistant/agent.py` — `Agent.run`:
   - Wrap ONLY the `self._complete(messages)` call in `try/except Exception`:
     log with `logger.exception`, then `break` to the safe fallback (do not
     retry inside the loop; the retry lives in step 2).
   - The fallback for an LLM exception MUST return `escalate=False`
     (new key `reason='llm_error'` for analytics), NOT `escalate=True`.
     Reserve `escalate=True` for "customer wants a human" (AP9). Copy:
     `FALLBACK_REPLY` stays the reply text.
   - Keep the existing repair-retry for bad JSON and the loop-exhausted path
     as-is here — AP9 reworks them.
2. `Backend/assistant/agent.py` — `_build_llm`:
   - Add `request_timeout=20` (langchain `ChatOpenAI(request_timeout=20)`;
     `init_chat_model` passthrough if supported, else wrap invoke with a
     20 s timeout) and at most ONE retry on timeout/transient 5xx
     (`max_retries=1`). No other tuning.
3. `Backend/spices_backend/llm.py` (shared OpenRouter helper, if the timeout
   belongs there instead): same 20 s / 1-retry rule so search synonyms get it
   too. Pick ONE place and note it in the commit message — do not set
   timeouts in both.
4. `Backend/assistant/views.py` — `AssistantChatView.post`: on the
   `llm_error` fallback, still persist the assistant message (so history shows
   the friendly line) but do NOT set `needs_human=True`.

**Tests — `Backend/assistant/test_llm_failure.py` (new):**

1. Completion raising `TimeoutError` → 200 response, reply == `FALLBACK_REPLY`,
   `escalate is False`, thread `needs_human is False`.
2. Completion returning garbage twice → existing fallback path unchanged
   (still `escalate=True` here; AP9 changes it).
3. `_build_llm` returns object with timeout ≈ 20 and max_retries ≤ 1
   (or documents where the timeout lives if the provider wrapper differs).

**Done when:** new tests pass, no prompt/tool/behaviour change, `API.md`
unchanged (no route change).

---

### AP3 — Sessions die on password change/reset (S4). Builds on WP1.

**Why:** resetting a password must evict whoever is already in.

**Needs:** AP1 (branch only; logically independent of AP2).

**Steps — reuse WP1 helpers, do not invent new cookie code:**

1. `Backend/users/views.py`:
   - Add helper (next to `_blacklist_quietly`):
     ```python
     def _blacklist_all_for(user):
         from rest_framework_simplejwt.tokens import OutstandingToken, BlacklistedToken
         from django.utils import timezone
         for t in OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True):
             try:
                 if t.expires_at > timezone.now():
                     BlacklistedToken.objects.get_or_create(token=t)
             except Exception:  # noqa: BLE001
                 continue
     ```
     (If `OutstandingToken` is unavailable in this simplejwt version, fall
     back to blacklisting the presented refresh cookie quietly + rotating —
     note it in the commit. Do NOT add a new dependency.)
   - `ChangePasswordView.post`: after `user.save()`, call
     `_blacklist_all_for(user)`. This covers BOTH customer and admin cookies
     because `OutstandingToken` covers all scopes. Do NOT clear cookies here
     (the caller just proved they know the password; their current session
     re-authenticates on next refresh — document this choice).
   - `PasswordResetConfirmView.post`: after `user.set_password(...)`, call
     `_blacklist_all_for(user)` BEFORE clearing `reset_token`.
2. `Backend/users/test_session_invalidation.py` (new):
   - Change password → old `refresh_token` cookie fails on
     `POST /api/auth/token/refresh/` (401), old access fails on
     `GET /api/auth/profile/` after expiry-or-blacklist (at minimum the
     refresh path is 401).
   - Reset flow (request → verify → confirm) → pre-reset refresh token 401s.
   - Admin session of the same user is also dead:
     `POST /api/auth/admin/token/refresh/` with the old admin cookie 401s.
   - Existing `test_admin_session.py` still passes unchanged.

**Done when:** new tests pass, `API.md` notes "password change/reset revokes
all sessions" on the two routes (no new routes).

---

### AP4 — Interim pre-hijack fix (S1-interim). Builds on WP1.

**Why:** full email verification (AP5) takes days; this one-view change closes
the takeover window now. Trade-off (document in code + commit): a legitimate
user who registered with a password and later uses Google loses password login
and must go through password-reset — acceptable because reset proves inbox
ownership, which is the missing proof.

**Needs:** AP1. Must land BEFORE AP5.

**Steps — `Backend/users/views.py` `GoogleLogin.post` only:**

1. After `user = User.objects.filter(email__iexact=email).first()`:
   - If `created is False` (existing account) AND `user.has_usable_password()`:
     call `user.set_unusable_password(); user.save(update_fields=['password'])`
     and `_blacklist_all_for(user)` (the AP3 helper — if AP3 has not landed,
     inline `_blacklist_quietly` on presented cookies + note the follow-up;
     AP order says AP3 first, so just import it).
   - Do this for EVERY existing account Google signs into (we have no
     `email_verified` column yet to distinguish — AP5 adds it). Google already
     proved inbox ownership (`email_verified is True` checked in
     `verify_google_id_token`).
2. Do NOT touch `AdminGoogleLoginView` (it never creates; non-staff already 403).
3. Keep all existing statuses/messages in `users/test_google_login.py` passing
   unchanged — only ADD behaviour, and add a comment citing S1 + AP5.

**Tests — extend `Backend/users/test_google_login.py` (or new file):**

1. Register with password → Google sign-in same email → password login now
   401/400 (unusable) AND old refresh token 401s.
2. Google-first sign-in (new account) → still `set_unusable_password` path,
   201, works as before.
3. Attacker register `victim@x.com` → victim Google sign-in → attacker session
   dead (the S1 probe from the audit, now asserting the fix).

**Done when:** S1 probe fails (attacker locked out), old Google tests pass,
`API.md` notes the behaviour on `POST /api/auth/google/`.

---

### AP5 — Email verification + uniform registration (S1-full, S9). Needs AP3, AP4.

**Why:** the real fix for S1: no account is usable until its email is proven.
Also stops registration from revealing existing emails.

**Steps:**

1. `Backend/users/models.py` — `User`: add
   `email_verified = models.BooleanField(default=False, db_index=True)`.
   Then `makemigrations users`. Data migration in the SAME migration file
   (use `RunPython`, do not edit old migrations):
   - Set `email_verified=True` where the user already has a delivered order
     OR a prior Google login created the row (heuristic: `last_login` set and
     `password` unusable — comment it as grandfathering; owner decision §7.1
     can flip this to "all False + OTP at next login").
2. `Backend/users/views.py` (+ `serializers.py` where noted):
   - Registration (`UserRegistrationView.create`): after `serializer.save()`,
     create a `PasswordResetOTP`-shaped row for verification (REUSE the
     `PasswordResetOTP` model — do not invent a second OTP table; prefix the
     email subject "Verify your email"). Return **always**
     `201 {'detail': 'If this email is new, a verification code was sent.'}`
     — same body whether the email existed or not (S9). On duplicate email,
     send NOTHING and still return the same 201 (no enumeration).
   - Add `POST /api/auth/verify-email/` (`AllowAny`, `authentication_classes=[]`):
     `{email, otp_code}` → on success set `email_verified=True`, blacklist any
     pre-verification tokens via `_blacklist_all_for`, return `{'success': True}`.
     Wrong/expired/locked → same 400/429 shapes as the reset-verify view.
   - `CustomTokenObtainPairView.post` + `AdminLoginView.post`: after
     `is_valid`, if `not user.email_verified` → 403
     `{'detail': 'Email not verified.', 'code': 'email_not_verified'}` and set
     NO cookies. (Admin panel login uses the same gate — staff created via
     Django admin must verify once or be flipped by the owner, §7.1.)
   - `GoogleLogin.post`: after the AP4 block, set `email_verified=True` if
     False (Google proved it). New Google users are created verified.
   - `UserSerializer`: expose `email_verified` as read-only (like `is_staff`).
3. `Backend/spices_backend/urls.py`: add `path('api/auth/verify-email/', …)`.
4. Lower-case + `secrets`: reuse AP6's OTP hardening if AP6 lands first; at
   minimum use `email__iexact` lookups here (S10-part) even before AP6.

**Tests — `Backend/users/test_email_verification.py` (new):**

1. Register `new@x.com` → login 403 `email_not_verified` → verify OTP → login 200.
2. Register with existing email → same 201 body, `User.objects.count()` unchanged, no email sent (capture via `locmem` inbox).
3. Google sign-in marks `email_verified=True` and issues cookies despite no OTP.
4. `GET /api/auth/profile/` includes `email_verified`.

**Done when:** S1 probe now fails at registration (unusable until OTP),
S9 probe (register existing → 400 with "already exists") is gone, `API.md`
documents `verify-email` + the 403 code, `AUTH.md` updated.

---

### AP6 — Email change gate + reset hardening + 15-min access (S3, S10, token).

**Why:** S3 is the second S1 route; S10 is three small bugs in one flow.

**Needs:** AP5 (reuses `email_verified` + OTP).

**Steps:**

1. `Backend/users/serializers.py` — `UserSerializer`:
   - REMOVE `email` from writable fields (make it read-only). Email changes go
     ONLY through the new endpoint below. Keep `validate_email` for
     registration/admin use.
2. New `POST /api/auth/change-email/` (`IsAuthenticated`):
   `{new_email, current_password, otp_code?}` two-step, reusing `PasswordResetOTP`:
   - Call 1 (no `otp_code`): check `current_password` via `user.check_password`
     (401 on mismatch), validate new email unique `__iexact`, send OTP to the
     NEW address, return `{'detail': 'Code sent.'}`.
   - Call 2 (with `otp_code`): verify OTP for the NEW address, set
     `user.email=new (lower-cased)`, `email_verified=True`,
     `_blacklist_all_for(user)` (all other sessions die; current one keeps its
     cookies — document it), notify the OLD address ("your login email changed").
   - Throttle: `UserRateThrottle` (per-user) + existing IP throttle.
3. Reset hardening (`users/views.py` — all three reset views):
   - `import secrets; otp_code = f"{secrets.randbelow(900000)+100000}"`
     (replace `random.randint`).
   - Every `User.objects.get(email=email)` → `get(email__iexact=email.strip().lower())`
     (fixes `Me@Gmail.com` getting nothing).
   - Per-account cap: before creating an OTP, count unexpired OTPs for this
     user in the last 24 h; if ≥ 5, still return the generic
     `{'detail': 'If an account exists…'}` WITHOUT creating/sending (prevents
     inbox flooding from rotating IPs; IP throttle stays).
   - `S14` (in this AP as one line): Google views return
     `{'detail': 'Invalid Google token'}` ONLY — drop the `'error': msg`
     library string.
4. Token lifetime (`spices_backend/settings.py`):
   `SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'] = timedelta(minutes=15)`.
   Refresh (7 d) + rotation already exist — no other change. Note: both
   `set_access_cookie` max-ages derive from SIMPLE_JWT, so cookies follow
   automatically.

**Tests:**

- `test_email_change.py`: PATCH profile with email → 400/ignored; change-email
  without password 401; full two-step succeeds, old sessions dead, old address
  got the notice; `email_verified` True.
- Extend reset tests: `secrets` (mock `secrets.randbelow`), mixed-case email
  receives OTP, 6th request in 24 h sends nothing but returns the same 200.
- Access lifetime: decode a fresh access token, `exp - iat == 900`.

**Done when:** S3 probe (PATCH email) no longer changes email, S10 probes
fixed, access == 15 min, `API.md` documents `change-email` + OTP reuse.

---

### AP7 — Django admin, COD guard, chat limits (S6, S7, S5-rest, S8).

Three independent slices — one commit per slice, any order, all Needs AP5
(COD guard needs `email_verified`).

**AP7a — Django admin off the public internet (S6).**

- `Frontend/nidhi-brand-forge/nginx.conf`: DELETE the `location /admin/`
  proxy block (WP3 already rewrote proxy_pass lines — delete the whole block).
  Django admin is then reachable only via SSH tunnel / private network.
- If the owner answers §7.2 "yes, public admin needed": instead add IP
  allowlist (`allow <office-ip>; deny all;`) + `django-axes` lockout
  (5 fails → 30-min lock). Default is DELETE; implement allowlist ONLY on
  explicit owner sign-off in the commit message.
- Verify: `nginx -t` (same `docker run` check as WP3) + `API.md`/DEPLOYMENT note.

**AP7b — COD guard (S7).**

- `Backend/orders/views.py` `create` (and cart-validate path if it duplicates
  the check): reject COD unless ALL true, else 400 with a specific `code`:
  - `user.email_verified is True` (`email_not_verified`);
  - order `total_amount <= COD_MAX_VALUE` (new in `limits.py`:
    `COD_MAX_VALUE = config('COD_MAX_VALUE', default=Decimal('5000'))`);
  - open COD count (status in `confirmed/processing/shipped`, not deleted)
    `< COD_MAX_OPEN = config('COD_MAX_OPEN', default=3)` (`cod_limit`).
- No value-cap change for ONLINE; no auto-cancel change (that job stays
  ONLINE-only by design).
- Tests in `orders/test_cod_guard.py`: unverified 400, 4th open 400, ₹5001
  400, passing COD still holds stock; owner-tunable via env.

**AP7c — Chat abuse + spend caps (S5-rest, S8).**

- `settings.py` `DEFAULT_THROTTLE_RATES`: `assistant: 20/min → 10/min`,
  `assistant_day: 500/day → 100/day` (env-overridable as today).
- `assistant/views.py` `AssistantChatView`: one in-flight turn per account —
  cache key `ngu:chat:inflight:<user_id>` (60 s TTL, set-before-LLM,
  delete-after); second concurrent POST → 429 `{'detail': 'A reply is already
  in progress.'}`.
- `assistant/agent.py`: `MODEL_CONTEXT_TOKENS` default `200000 → 12000`
  (≈ a few thousand tokens of history; env still overrides), keep the
  char-estimate trimmer. Per-turn LLM calls stay ≤ 4 (AP9 may lower further).
- Tests: burst 11th 429, in-flight 429, history trim keeps newest under budget.

---

### AP8 — PII, public catalog, headers, secrets hygiene (S11, S12, S13, S15 + knowns).

**Needs:** AP1 only. Slices in one commit unless the owner splits them.

1. **S11 PII:** `assistant/admin_tools.py` `find_customer` / `list_recent_orders`:
   return `customer_ref` (e.g. `CUST-<id>` + masked email `a***@x.com`, no phone)
   by default; add `include_contact: bool = False` arg the LLM can set ONLY when
   the admin explicitly asked ("give me the phone") — log every unmasked call
   at WARNING with admin id. Update `ADMIN_SYSTEM_PROMPT` to state the masking
   rule. Test: default output contains no `@` full email / 10-digit phone.
2. **S12 catalog:** `products/serializers.py` public serializers (NOT the admin
   bulk ones): drop `stock`, `low_stock_threshold`, `sku`; keep
   `in_stock: bool` (already computed). Variant nested serializer: same drop.
   Test: public product JSON has `in_stock` but no `stock`/`sku` keys.
3. **S13 CSP:** storefront + panel `nginx.conf`: add
   `Content-Security-Policy "default-src 'self'; img-src 'self' data: https:
   res.cloudinary.com; script-src 'self'; style-src 'self' 'unsafe-inline';
   connect-src 'self' https://openrouter.ai"` at server level AND repeat inside
   any `location` that sets its own `add_header` (WP3's `= /index.html` blocks —
   nginx inheritance rule). Verify with `nginx -t` + curl headers locally.
4. **S15 + knowns (owner checklist, NOT code — do on the deploy box, never
   from this branch):** set `RAZORPAY_LIVE_WEBHOOK_SECRET`, copy `~/NGU/backups/`
   off-box (S3 + lifecycle), deactivate the unused AWS key, move
   `KaushalJainAI_accessKeys*.csv` / `my-pem.pem` / `backend_remote.env` out of
   `NGU/` (do NOT commit deletions of untracked files — just move them and note
   it). No test; report `backup.log` tail + webhook verify line instead.

---

### AP9 — Assistant rebuild, part 1: native tools + honest escalation (A3, A4, A5).

**Why:** the envelope is the root of multi-item failure and false escalation;
"A team has been notified" is untrue.

**Needs:** AP2 (fallback semantics). Keeps: closed registry, view-injected user
scoping, confirm-before-write, human handoff flag.

**Steps — `Backend/assistant/` (exact framework follows the installed
langchain version; behaviour contract is what matters):**

1. Replace the hand JSON envelope with the model's native function/tool calling
   (`ChatOpenAI.bind_tools([...])` or equivalent): ONE round may call SEVERAL
   read tools; delete `_parse_envelope` + the repair-retry message. Unparseable
   provider output → AP2 `llm_error` fallback (`escalate=False`), never
   `needs_human`.
2. `agent.run` return contract: `{reply, proposed_action, sources, escalate,
   reason}` where `reason ∈ {ok, llm_error, loop_exhausted, customer_asked}`.
   ONLY `customer_asked` (model explicitly chose `escalate_to_human` because
   the customer asked) sets `needs_human=True` on the thread.
   `loop_exhausted` (still capped at 4 iterations) → friendly "try fewer items"
   reply, `escalate=False`.
3. Long-reply truncation: raise `MAX_OUTPUT_TOKENS` 600 → 1000 for Indic
   scripts AND check `finish_reason == 'length'` → append "…(continued — ask me
   to continue)" instead of escalating.
4. Handoff honesty: customer line becomes "I've flagged this for our team —
   they usually reply within a day. Your thread stays here." Owner notify: on
   `customer_asked`, enqueue the SAME async mail path as order emails to
   `ADMIN_ALERT_EMAIL` immediately (not the 08:00 digest). Include thread id +
   last message.
5. Prompts: delete "propose at most one item" (AP10 replaces it); keep
   confirm-before-write + allowlist + no-URL rules.

**Tests — `assistant/test_agent_escalation.py`:**

1. "haldi, jeera, dhaniya" with stubbed multi-tool round → all three looked up
   in ONE turn, `escalate False`.
2. Forced loop exhaustion → `reason loop_exhausted`, `needs_human False`.
3. `escalate_to_human` chosen → `needs_human True` + exactly one admin email
   enqueued (django `locmem` outbox).
4. Truncated (`finish_reason length`) → continuation line, no escalation.

**Done when:** A3/A4/A5 probes pass, eval subset (AP10) not regressed, `API.md`
notes the new `reason` field on `POST /api/assistant/chat/`.

---

### AP10 — Assistant rebuild, part 2: sizes, cart proposal, tools, streaming, cleanup.

**Why:** sizes are the main thing a spice buyer specifies; one-item/one-tap is
five round trips for five items.

**Needs:** AP9.

1. **Size-aware tools** (`tools.py`, `prompts.py`): `search_products` returns
   per-VARIANT rows `{variant_id, weight, price, in_stock}` (from
   `ProductVariant`, not `Product`); `add_to_cart` takes required `variant_id`
   (+ `quantity`, clamped to `MAX_PROPOSE_QTY`); unknown size → ask, never guess
   the default. Combo rows unchanged (combos have no variants).
2. **Cart proposal:** replace single-item `proposed_action` with
   `{type:'cart_proposal', lines:[{variant_id, qty}], note}`; storefront renders
   ONE editable card (size, qty steppers) + single Confirm → existing cart-add
   endpoint called once with all lines. Keep `build_action` validation per line.
3. **Missing tools:** `get_offers` (active coupons, public fields only),
   `get_delivery_info` (fee, threshold, `SHIPPING_TAX_RATE` — read from
   `limits.py`, never hardcode), `get_tracking` (own orders only: courier +
   `tracking_url` from WP4), `edit_cart` (qty/remove by variant). Policies:
   point `get_policy` at the SAME static-page source the storefront renders
   (import the markdown/text, do not query retired `Policy`); empty → honest
   "see /shipping-policy" link.
4. **Ops:** stream replies (SSE `text/event-stream` on a NEW
   `POST /api/assistant/chat/stream/`; old route stays byte-identical);
   run chat in its own gunicorn worker pool / threadpool-in-front (document in
   `Dockerfile` + compose: chat no longer shares the 6 checkout slots — S5
   closed); return saved `proposed_action` WITH message history (`GET
   .../messages/`) and mark `used:true` after confirm (one-tap can't repeat);
   DELETE the permanent "no cart actions after an admin spoke" rule (pause only
   while `is_ai_paused`); remove `/track-order` from `NAV_STATIC_ROUTES`;
   delete anonymous-session args (chat is login-only — verify no anon path
   remains).
5. **Eval set (new `assistant/eval/`):** 40–50 real requests (Hindi, Hinglish,
   English; multi-item; sizes; status; policy). Script prints task-completion,
   median reply ms, false-escalation rate. Run before/after; AP10 must not
   regress AP9 and must improve multi-item completion. No prod data.

**Done when:** "500 g haldi ×2 + 100 g jeera" → one proposal, one confirm, right
variants; new tools + stream route in `API.md`; eval numbers in the commit
message.

---

### AP11 — Voice: one job ("say your shopping list") or remove (Phase 3).

**Needs:** AP10 (inherits sizes + cart proposal). Storefront-only except the
whisper-container decision.

1. Rebuild `AssistantWidget` voice around ONE flow: one utterance → STT →
   AP10 cart proposal → one tap confirm. Add: silence auto-stop (MediaRecorder
   + VAD or 1.5 s silence), visible mic + transcription errors (no more
   swallowed failures), read-aloud as an EXPLICIT toggle (default OFF) with
   `speechSynthesis` language set from the thread language (`hi-IN`, `gu-IN`,
   `mr-IN`, `pa-IN`, else `en-IN`); stop speech on widget close.
2. Add the mic button to the search bar (`SearchAutocomplete`) reusing the same
   hook (`useVoiceInput.ts`).
3. Instrument with existing analytics events (`assistant_voice_used`,
   `assistant_voice_confirmed`); review after 30 days of prod data: if
   negligible, DELETE the feature + `whisper` service from both compose files
   (second commit, owner sign-off).
4. `tsc` + `build` pass; test on a real phone browser (note device in report).

**Done when:** a 5-second Hindi list yields the AP10 card with one confirm; no
auto-read-aloud; errors visible; usage events fire.

---

### AP12 — Storefront clean-up (Phase 4). Needs nothing except AP1 (parallel-safe).

Storefront-only (`Frontend/nidhi-brand-forge`). One commit, but review in a
real browser at phone width before/after (screenshots in the report).

1. **Truth pass:** delete/replace `1.1M+`, `50+`, `100%` (hero, CTA, About —
   ask owner §7.4 for real numbers or drop the counters); delete fake
   testimonials from ALL SIX locale files (`en/hi/hinglish/gu/mr/pa.json`);
   DELETE `PromoCouponStrip.tsx` (or wire it to `GET /api/coupons/` — default
   DELETE); remove `"100g"` default in `ProductCard.tsx` (show nothing when
   weight missing).
2. **Copy:** rewrite hero/CTA/About with Nidhi-specifics (Barnagar, FSSAI
   `11414730000288`, how blends are made) — owner supplies one paragraph (§7.4).
3. **Decoration budget:** squiggle SVG out of `ProductCard` (+ all but ONE home
   instance); pulsing badges/launcher, floating emoji (About/Contact/MyOrders),
   route-change animation, marquee → delete; discount shown ONCE per card.
4. **Icons:** lucide everywhere (navbar + mobile bottom nav — no emoji).
5. **Overlays:** at most ONE floating element at a time on phones (priority:
   bottom nav > cart bar > chat > WhatsApp > cookie banner — others queue).
6. **Loading:** skeletons, not full-screen spinner; home MUST NOT fetch all
   products as a fallback (cap the fallback query or drop it).
7. `en.json` + `hi.json` updated for every touched string; `tsc` + `build` pass.

---

## 6. Final documentation pass (after all APs)

Update `NGU/CLAUDE.md`:

- S2 closed by WP1 (logout routes exist); AP3 revokes all sessions on
  password change/reset; AP4 interim + AP5 verification (`email_verified`,
  `verify-email`, `change-email`, 15-min access).
- Panel sends `X-Admin-Panel: 1` (WP1) — unchanged.
- GST/invoice/credit-note notes from WP5–WP7 still stand; add AP7b COD caps
  (`COD_MAX_VALUE`, `COD_MAX_OPEN`) and AP7c chat caps.
- Assistant: native tools, cart proposal, `reason` field, stream route,
  eval set (AP9–AP10); voice decision (AP11).
- Storefront truth/decoration/loading rules (AP12).

Update `Backend/docs/API.md` (every AP that touches a route — AP3–AP10 each
update their own rows in the same commit), plus `AUTH.md`, `ASSISTANT.md`,
`CART.md` (variant_id), `ORDER_LIFECYCLE.md` (COD guard), `CACHING_STRATEGY.md`
(in-flight key) as touched.

---

## 7. Decisions needed from the owner (answer before the implementer needs them)

1. **Existing accounts (AP5):** treat all as unverified (OTP at next password
   login) or grandfather accounts with a delivered order / Google-created rows?
   Default in AP5: grandfather delivered-order + Google rows; say the word to
   flip to "all unverified".
2. **Django admin (AP7a):** is public `/admin/` needed at all, given the panel
   exists? Default: DELETE the nginx block. Public access needs explicit sign-off.
3. **Voice (AP11):** rebuild as "say your shopping list", or remove now?
4. **Marketing numbers (AP12):** real customer/product counts + one Barnagar /
   FSSAI / blends paragraph, or drop the counters?
5. **COD limits (AP7b):** defaults are ₹5,000 max value, 3 open orders. Confirm
   or change.
6. **PII unmasking (AP8):** who may see full phones/emails via the admin
   assistant, and is logging each unmasked call enough?
7. **Deploy order (after review):** Backend + scheduler first, then `migrate`,
   then Panel image, then Storefront image. Everyone re-logs into the Panel
   once (new 15-min access + AP3 revocation). Run ONCE on the server, in order:
   ```bash
   docker compose -f docker-compose.prod.yml exec backend python manage.py migrate
   ```
   (No backfill commands in this plan — WP6's invoice/credit-note backfills
   already cover historical data. Do NOT re-run them.)
8. **Ask the accountant** (unchanged from WP plan — nothing here changes these):
   delivery 18% SAC 9968 vs goods rate; credit-note netting for unregistered
   buyers; masala blends HSN 0910 @5% vs 2103 @18%.

(End of rewrite — findings §§1–4 kept, plan §5 replaced by AP1–AP12, S2 marked
closed, auth work rebased on WP1 helpers, sequencing fixed to run AFTER
improvement-plan on a new audit-plan branch.)
