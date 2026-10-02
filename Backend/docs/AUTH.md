# Authentication & Session Management

All authentication is **cookie-based JWT**. Tokens are never returned in response bodies
for client-side storage — the server sets HttpOnly cookies and the browser sends them
automatically on every subsequent request.

---

## Token Lifecycle

### Registration + email verification (`POST /api/auth/register/`, `/api/auth/verify-email/`)

Handled by `UserRegistrationView` (`users/views.py`). For a valid form the response
is **always** `201 {'detail': 'If this email is new, a verification code was sent.'}`
— whether the address is new or already registered — and an invalid form 400s the
same way in both cases, so registration never reveals which emails have accounts
(S9). What happens behind that response:

| The address is… | Effect |
|---|---|
| new | Account created with `email_verified=False`; a 6-digit code is mailed. |
| an **unclaimed** row (unverified, never logged in, not staff) | Its password and details are **replaced** by this registration and a fresh code is mailed. A squatter who registered someone else's address cannot keep their password once the owner signs up. |
| any other existing row | Untouched. Its owner gets one "you already have an account" notice per day. |

Codes live in the `PasswordResetOTP` table, told apart by its `purpose` column
(`reset` / `verify` / `change_email`). Each purpose has its own live code and its
own quota of 5 codes per account per 24 h, so a stranger spamming "forgot
password" can neither cancel nor use up the owner's verification codes. Account
mail is sent from a background thread (`_send_auth_email`; inline under tests);
a mail failure is logged and never fails the request.

- `POST /api/auth/verify-email/` `{email, otp_code, password}` → consumes the code,
  sets `email_verified=True`, revokes pre-verification sessions, returns
  `{'success': True}`. **The password is required and must be the account's
  current one.** The code proves the inbox; the password proves the person holding
  the code is the one who set the credentials. Without it, an attacker could
  register a victim's address with their own password and wait for the victim to
  type the code that arrives — verifying the attacker's password. A wrong password
  reads exactly like a wrong code and counts toward the 5-attempt lock (400 / 429,
  10-minute expiry).
- `POST /api/auth/verify-email/request/` `{email}` → re-sends a code to an
  unverified address (this is how accounts left unverified by the migration obtain
  one). Always the same generic 200; capped at 5 verification codes per account
  per 24 h.
- Clients: the storefront sends new sign-ups to `/verify-email`, and sends a login
  that answers `403 email_not_verified` there too (requesting a fresh code first);
  the admin panel's login form grows a code field on the same 403. Both hold the
  password the user just typed and replay the login after verifying.
- A superuser made with `createsuperuser` is created verified (`UserManager`).
  Staff made any other way verify once at the panel login.
- Existing accounts were grandfathered by migration `users/0010`: delivered-order
  owners, rows with an unusable password (Google-created), and staff/superusers start
  verified; everyone else confirms once.

### Login (`POST /api/auth/login/`)

Handled by `CustomTokenObtainPairView` (`users/views.py`). On success the server sets two
HttpOnly cookies (tokens are never returned in the response body):

| Cookie | Value | Max-Age | Flags |
|--------|-------|---------|-------|
| `access_token` | Short-lived JWT | `SIMPLE_JWT['ACCESS_TOKEN_LIFETIME']` — 15 minutes (AP6; was 1 hour) | HttpOnly, SameSite=Lax, Secure=True in prod |
| `refresh_token` | Long-lived JWT | `SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']` — currently 7 days | HttpOnly, SameSite=Lax, Secure=True in prod |

`Secure` is `not settings.DEBUG` — cookies are plain-HTTP in local dev, HTTPS-only in
production.

Unverified emails cannot log in: valid credentials with `email_verified=False`
return `403 {'detail': 'Email not verified.', 'code': 'email_not_verified'}` and
set no cookies (the freshly minted tokens are discarded, never leaked in the
403 body). `POST /api/auth/admin/login/` applies the same gate after the staff
check, so non-staff still see the unchanged 401.

All three views that set these cookies (login, refresh, Google) go through the shared
`set_access_cookie()` / `set_refresh_cookie()` helpers in `users/views.py`, which read
the max-age from `SIMPLE_JWT` rather than hardcoding it — so a cookie can never outlive
(or expire before) the token it carries.

### Token Refresh (`POST /api/auth/token/refresh/`)

Handled by `CustomTokenRefreshView`. If the request body does not include a `refresh`
field, the view falls back to `request.COOKIES.get('refresh_token')`. This means the
frontend can call the endpoint with an empty body `{}` and the cookie is used automatically.

On success a fresh `access_token` cookie is set (same flags, 15-minute max-age). If refresh
token rotation is enabled in SimpleJWT settings, a new `refresh_token` cookie is also set.

### Logout (`POST /api/auth/logout/`)

`LogoutView` blacklists the `refresh_token` cookie quietly (logout always
succeeds) and clears `access_token` + `refresh_token`. It never touches the
admin cookies — customer and admin sessions are independent.

### Admin session (`POST /api/auth/admin/*`)

The Panel sends `X-Admin-Panel: 1` on every request. When that header is
present `CookieJWTAuthentication` reads ONLY `admin_access_token` (JWT claim
`scope == "admin"`, user must have `is_staff=True`); otherwise it reads ONLY
the customer `access_token`. Customer cookies keep their names.

| Route | Behaviour |
|---|---|
| `POST /api/auth/admin/login/` | `{email, password}` via `CustomTokenObtainPairSerializer`; non-staff → 401, no cookies. Staff → admin cookies + `{success, user}` |
| `POST /api/auth/admin/google/` | `id_token` (or `access_token`); missing → 400, bad → 401, non-staff → 403. Never creates a user |
| `POST /api/auth/admin/token/refresh/` | Reads `admin_refresh_token` cookie; rejects non-admin scope, unknown or demoted users |
| `POST /api/auth/admin/logout/` | Blacklists the admin refresh cookie quietly, clears admin cookies only |

`UserSerializer` exposes read-only `is_staff` so the Panel can refuse
non-staff accounts client-side as well.

---

## Rate Limiting

| Endpoint | Throttle class | Scope | Default limit |
|----------|---------------|-------|---------------|
| `/auth/login/` | `LoginRateThrottle` | `login` | 5/minute (per IP) |
| `/auth/register/` | `RegisterRateThrottle` | `register` | 3/minute (per IP) |
| `/auth/password-reset-*` | `PasswordResetRateThrottle` | `password_reset` | 10/day (per IP) |
| `/auth/verify-email/`, `/auth/verify-email/request/` | `EmailVerifyRateThrottle` | `email_verify` | 30/hour (per IP), plus 5 verification codes per account per 24 h |

Limits are configured in `DEFAULT_THROTTLE_RATES` in Django settings and applied at the
view level — not globally.

---

## CSRF

`UserProfileView` is decorated with `@ensure_csrf_cookie` so the browser always receives
a CSRF token in its cookie. The frontend reads `csrftoken` from the cookie and sends it as
`X-CSRFToken` on all state-changing requests (set in `axiosInstance.ts` and
`lib/api/config.ts`).

---

## Google OAuth Flow

Endpoint: `POST /api/auth/google/`  
Class: `GoogleLogin` (`users/views.py`)

The frontend uses `@react-oauth/google` to obtain a Google ID token credential in the
browser. It posts this as `access_token` (or `id_token`) to the backend. The backend
**never redirects to Google** — verification is entirely server-side:

```
Frontend                  Backend                    Google
   │                         │                          │
   │── POST /auth/google/ ──▶│                          │
   │   {access_token: ...}   │                          │
   │                         │── verify_oauth2_token ──▶│
   │                         │◀── idinfo (email, verified)│
   │                         │  reject if !email_verified│
   │                         │                          │
   │                         │  get_or_create User      │
   │                         │  set_unusable_password   │
   │                         │  generate JWT tokens     │
   │                         │  set HttpOnly cookies    │
   │◀── 200/201 + cookies ───│                          │
```

1. `id_token.verify_oauth2_token()` validates the token signature against Google's
   public certificates and checks the `aud` (audience) matches `GOOGLE_CLIENT_ID`.
2. **The `email_verified` claim must be true** (bool `True` or the string `"true"`;
   a missing claim is treated as unverified) — otherwise the request is rejected 401
   and no account is created or matched. This is load-bearing: step 3 matches existing
   accounts *by email*, so accepting an unverified address would let the holder of a
   validly-signed token sign in as any user with that email. See
   `users/test_google_login.py::test_unverified_email_rejected`.
3. Email is extracted and used as the unique key for `get_or_create`. Username derives
   from the part before `@` in the email (e.g. `kaushaljain` from
   `kaushaljain7000@gmail.com`), with a numeric suffix appended if that username is
   taken — the bare local part collides across domains (`a@x.com` vs `a@y.com`).
4. On first login: `set_unusable_password()` is called — Google-only users cannot log in
   via email/password until they explicitly set one via `change-password`. The row is
   created with `email_verified=True` (Google proved the inbox; no OTP needed).
5. On subsequent logins: an inactive account is refused (403). If the row's email was
   **never verified** and it has a usable password (someone registered the address
   with a password first — the S1 pre-hijack case), the password is made unusable and
   every session for that user is revoked; the row is then marked verified. A
   **verified** account keeps its password — its owner chose it, and wiping it would
   silently break password login (for staff, the admin panel) just for using Google
   once. Name is updated if it was previously blank.
6. The same `CustomTokenObtainPairSerializer.get_token(user)` is used as for password
   login — OAuth users get identical JWT cookies.
7. Response status is `201 Created` for new users, `200 OK` for returning users.

---

## Password Reset Flow

A three-step OTP flow. All three endpoints share `PasswordResetRateThrottle` (10/day/IP).

### Step 1 — Request OTP (`POST /api/auth/password-reset-request/`)

```
Client                    Backend                    Email Server
  │                          │                            │
  │── POST {email} ─────────▶│                            │
  │                          │  try User.objects.get(email)
  │                          │  if DoesNotExist:           │
  │                          │    dummy set_password()    │  ← constant-time no-op
  │                          │    (no OTP, no email)      │  ← prevents email enumeration
  │                          │  else:                     │
  │                          │    invalidate old OTPs     │
  │                          │    generate 6-digit OTP    │
  │                          │    hash OTP (make_password)│
  │                          │    create PasswordResetOTP │
  │                          │      expires_at = now+10m  │
  │                          │    spawn daemon thread ───▶│── send_mail() ──▶
  │◀── 200 "If account..." ──│                            │
```

**Email enumeration prevention:** whether or not the email exists, the response body and
status code are identical (`200 OK`, `"If an account exists..."`). The server performs a
dummy `set_password('dummy_password')` for the not-found branch to equalise response time.

**OTP hashing:** the 6-digit code is stored via `make_password()` (Django's password
hasher). The raw OTP is only ever in the email — it is never logged or stored in plain text.

**Email threading:** `send_mail()` runs in a daemon `threading.Thread` so the HTTP response
returns immediately regardless of email server latency.

### Step 2 — Verify OTP (`POST /api/auth/password-reset-verify/`)

Request: `{email, otp_code}`

```
Client                    Backend
  │                          │
  │── POST {email, otp} ────▶│
  │                          │  get latest unused OTP for user
  │                          │  check is_expired (now > expires_at)
  │                          │  check is_locked (failed_attempts >= 5)
  │                          │  check_otp(submitted_code)  ← constant-time compare
  │                          │  if wrong:
  │                          │    failed_attempts += 1
  │                          │    if >= 5: locked
  │                          │  if correct:
  │                          │    is_used = True
  │                          │    reset_token = uuid4()
  │◀── 200 {reset_token} ───│
```

The `reset_token` (a UUID) is returned to the client. It is a one-time-use opaque value —
it does not expire independently (it uses the same `expires_at` as the OTP record).

**Brute-force protection:** after 5 failed `otp_code` submissions the OTP is locked. The
user must request a new OTP (step 1) to continue. Failed attempts are counted on the
`PasswordResetOTP` model (`failed_attempts` field, `MAX_FAILED_ATTEMPTS = 5`).

### Step 3 — Confirm New Password (`POST /api/auth/password-reset-confirm/`)

Request: `{email, reset_token, new_password}`

```
Client                    Backend
  │                          │
  │── POST {email, token,   ▶│
  │         new_password}    │  find OTP by (user, reset_token, is_used=True)
  │                          │  check is_expired
  │                          │  user.set_password(new_password)
  │                          │  Django password validators run
  │                          │  otp_record.reset_token = None
  │◀── 200 "Password reset" ─│
```

After success the `reset_token` is nulled out so the same token cannot be reused.
Every outstanding refresh token for the user (customer and admin) is revoked first
(AP3), so whoever was in before the reset no longer is. The reset also sets
`email_verified=True`: the emailed code proved the inbox, and without it an
unverified account would reset successfully and still be refused at login.

**Why three steps (not two)?** Separating verify (step 2) from confirm (step 3) means the
user proves they have access to the email before their new password travels over the
network. A two-step flow (verify + set in one request) sends the new password before
the OTP is validated.

---

## Change Email (`POST /api/auth/change-email/`)

Two steps, proof at both ends (AP6/S3). Call 1 `{new_email, current_password}`
re-proves the password, validates the new address (format + unused), and mails it
an OTP (`PasswordResetOTP` row whose `reset_token` column holds the pending address).
Call 2 adds `otp_code` (password required again — the session alone may be hijacked):
the code is checked against the pending row, then the email swaps, `email_verified`
is set (the OTP proved the new inbox), every session is revoked and the caller's own
cookies are re-issued, and the OLD address gets a "your login email changed" notice.
A wrong current password is a 400 (a 401 would make the SPA treat the session as
expired and log the user out). Codes are capped at 5 per account per 24 h. `PATCH /api/auth/profile/` with a
differing email is a 400 pointing here — the profile never changes the login identifier.

## Change Password (`POST /api/auth/change-password/`)

Requires the current session (authenticated). Accepts `{old_password, new_password}`.
Validates `old_password` via `check_password()`, then runs Django's `validate_password()`
validators on the new one before saving. Every outstanding refresh token for the user
(customer and admin) is then revoked (AP3/S4): other devices must log in again. The
caller's own cookies are re-issued in the same response (`_reissue_session`, in the
scope the request came in on) — revoking everything includes the caller's own refresh
token, so without that the person changing their password would be logged out at the
next refresh. Stateless access tokens on other devices live out their remaining
minutes (≤ 15); the refresh path dies immediately.

---

## Security Properties Summary

| Property | Implementation |
|----------|---------------|
| Tokens not in JS memory | HttpOnly cookies |
| Tokens not sent to wrong origin | SameSite=Lax |
| Tokens encrypted in transit | Secure=True (prod) |
| Login brute-force | 5/min rate limit + OTP for reset |
| Email enumeration | Constant-time dummy branch on reset request; uniform 201 on register, generic 200 on verify resend |
| OTP brute-force | 5-attempt lock, 10-minute expiry (reset + verification + change-email codes); `secrets` randomness; 5 codes per account per 24 h **per purpose** |
| Silent email takeover (S3) | Login email changes only via password + new-inbox OTP; old address notified (AP6) |
| Pre-hijack via registration (S1) | `email_verified` gate on login (AP5); verification needs the code AND the password; re-registering replaces an unclaimed row; Google sign-in kills an unverified row's password + sessions |
| Stale sessions after credential change (S4) | Password change/reset/email change revokes all refresh tokens, both scopes (AP3); the caller's own session is re-issued |
| Google token forgery | Server-side `verify_oauth2_token` against Google certs |
| Google unverified-email takeover | `email_verified` claim required before any account match |
| CSRF | Cookie + `X-CSRFToken` header double-submit |
| Password strength | Django's built-in `validate_password()` validators |
| Card numbers | Never stored; gateway tokens only |
