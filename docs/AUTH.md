# Authentication & Session Management

All authentication is **cookie-based JWT**. Tokens are never returned in response bodies
for client-side storage — the server sets HttpOnly cookies and the browser sends them
automatically on every subsequent request.

---

## Token Lifecycle

### Login (`POST /api/auth/login/`)

Handled by `CustomTokenObtainPairView` (`users/views.py`). On success the server sets two
HttpOnly cookies and also returns the token values in the response body (for clients that
need them, e.g. server-side rendering):

| Cookie | Value | Max-Age | Flags |
|--------|-------|---------|-------|
| `access_token` | Short-lived JWT | `SIMPLE_JWT['ACCESS_TOKEN_LIFETIME']` — currently 1 hour | HttpOnly, SameSite=Lax, Secure=True in prod |
| `refresh_token` | Long-lived JWT | `SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']` — currently 7 days | HttpOnly, SameSite=Lax, Secure=True in prod |

`Secure` is `not settings.DEBUG` — cookies are plain-HTTP in local dev, HTTPS-only in
production.

All three views that set these cookies (login, refresh, Google) go through the shared
`set_access_cookie()` / `set_refresh_cookie()` helpers in `users/views.py`, which read
the max-age from `SIMPLE_JWT` rather than hardcoding it — so a cookie can never outlive
(or expire before) the token it carries.

### Token Refresh (`POST /api/auth/token/refresh/`)

Handled by `CustomTokenRefreshView`. If the request body does not include a `refresh`
field, the view falls back to `request.COOKIES.get('refresh_token')`. This means the
frontend can call the endpoint with an empty body `{}` and the cookie is used automatically.

On success a fresh `access_token` cookie is set (same flags, 1-hour max-age). If refresh
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
   via email/password until they explicitly set one via `change-password`.
5. On subsequent logins: name is updated if it was previously blank; everything else
   is left unchanged.
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

**Why three steps (not two)?** Separating verify (step 2) from confirm (step 3) means the
user proves they have access to the email before their new password travels over the
network. A two-step flow (verify + set in one request) sends the new password before
the OTP is validated.

---

## Change Password (`POST /api/auth/change-password/`)

Requires the current session (authenticated). Accepts `{old_password, new_password}`.
Validates `old_password` via `check_password()`, then runs Django's `validate_password()`
validators on the new one before saving. No token refresh is needed after a password change
— existing cookies remain valid.

---

## Security Properties Summary

| Property | Implementation |
|----------|---------------|
| Tokens not in JS memory | HttpOnly cookies |
| Tokens not sent to wrong origin | SameSite=Lax |
| Tokens encrypted in transit | Secure=True (prod) |
| Login brute-force | 5/min rate limit + OTP for reset |
| Email enumeration | Constant-time dummy branch on reset request |
| OTP brute-force | 5-attempt lock, 10-minute expiry |
| Google token forgery | Server-side `verify_oauth2_token` against Google certs |
| Google unverified-email takeover | `email_verified` claim required before any account match |
| CSRF | Cookie + `X-CSRFToken` header double-submit |
| Password strength | Django's built-in `validate_password()` validators |
| Card numbers | Never stored; gateway tokens only |
