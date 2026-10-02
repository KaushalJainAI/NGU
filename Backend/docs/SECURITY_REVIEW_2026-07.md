# Security Review — 2026-07-23

Full-stack review of the NGU platform (Backend / Frontend / Admin Panel / infra).
Overall the codebase is defensively strong: no SQL injection, no `eval`/`exec`/
`pickle`, no `mark_safe`/`dangerouslySetInnerHTML`, server-side money math with
row locks, IDOR closed via `get_queryset`, an assistant agent with a closed tool
registry, magic-byte upload validation, and SSRF-safe outbound proxies. The
issues below were the real findings; **all are fixed in this change** except where
noted as "server config" (must be applied to the running environment).

---

## HIGH — Rate-limit bypass via `X-Forwarded-For` spoofing  ✅ fixed

**Root cause.** `REST_FRAMEWORK['NUM_PROXIES']` was unset, so DRF derived a
request's throttle identity from `''.join(xff.split())` — the *entire*
`X-Forwarded-For` header concatenated. Our nginx layers append to XFF
(`$proxy_add_x_forwarded_for`), so a client-supplied XFF value sits at the
**front** of that string. An attacker rotating a fake `X-Forwarded-For:` value
therefore got a **new throttle bucket on every request**, defeating every
IP-keyed limit at once:

- `login` 5/min → unlimited password brute-force (there is no per-account lockout;
  the IP throttle was the only guard).
- `register`, `password_reset` (OTP), `order`/`order_day`, `payment`.

*Bounded even before the fix:* the OTP flow has an independent per-record
5-attempt DB lock, and `/payments/verify/` still requires a valid HMAC. Login
brute-force was the real exposure.

**Fix.**
- `spices_backend/settings.py` — `REST_FRAMEWORK['NUM_PROXIES'] = config('NUM_PROXIES', default=2)`.
  DRF now reads the client as the **2nd-from-last** XFF entry (host nginx +
  frontend-container nginx = 2 trusted hops). A client-supplied prefix can no
  longer influence the identity because it is always to the *left* of what our
  own proxies appended.
- `spices_backend/abuse.py` — `get_client_ip()` rewritten to the same
  trusted-hop logic (it previously took `xff.split(",")[0]`, the most
  attacker-controlled value), so the abuse-ban list and throttles agree on the
  real IP.
- `docker-compose.prod.yml` — backend/frontend/admin ports rebound to
  `127.0.0.1` (see below). This is load-bearing for the fix: the `NUM_PROXIES=2`
  assumption only holds if no one can reach Django on a *shorter* proxy chain.
- Regression test: `spices_backend/test_proxy_throttle.py`.

**Picking `NUM_PROXIES`:** it must equal the number of trusted proxies in front
of Django. Too low re-opens the spoof; too high reads past our proxies into
client-controlled data. Current chain: `client → host nginx → frontend nginx →
backend` = **2**. Re-verify if the topology changes.

---

## MEDIUM — Docker ports published on `0.0.0.0`  ✅ fixed (config)

`8000:8000`, `3000:80`, `3001:80` bound to all interfaces, so if the EC2 security
group ever allowed those ports the API/admin were reachable directly over
cleartext HTTP, bypassing nginx TLS and the trusted-proxy chain. Rebound to
`127.0.0.1:...` in `docker-compose.prod.yml` — host nginx proxies from localhost,
so nothing legitimate breaks; the internet simply can't reach the containers
directly. **Also confirm the EC2 security group only exposes 22/80/443.**

> Deploy note: this only takes effect after `docker compose -f
> docker-compose.prod.yml up -d` recreates the containers on the server.

---

## MEDIUM/LOW — Session/CSRF cookies not `Secure`  ✅ fixed (server env)

`CSRF_COOKIE_SECURE` / `SESSION_COOKIE_SECURE` were `False` on an HTTPS-only site,
so those cookies could ride a cleartext request before nginx's HTTP→HTTPS
redirect (HSTS limits this to the first-ever visit). The JWT auth cookies were
already `Secure` (`AUTH_COOKIE_SECURE = not DEBUG`).

**Fix:** set both `True` in `~/NGU/.env.backend` on the deploy server (mirrored in
the local `backend_remote.env` reference copy). `SECURE_SSL_REDIRECT` stays
`False` on purpose — nginx does the redirect; enabling Django's too risks loops.
Trade-off: bare-IP HTTP debug access can no longer log in (real users unaffected).

---

## LOW — polish  ✅ fixed

- **JWT echoed in the login response body** (`users/views.py`). Login / refresh /
  Google-login set HttpOnly cookies *and* returned `access`/`refresh` in the JSON
  body, where page JS (and thus any XSS) could read them. Both SPAs authenticate
  via the cookie (verified in `AuthContext`), so the tokens were removed from all
  three response bodies. Auth tests updated to assert the cookie contract.
- **Exception handler leaked `str(exc)`** (`spices_backend/exceptions.py`). The
  `ValueError`/`TypeError`/`KeyError` branches echoed the exception message to the
  client. Now return a generic message; the detail stays in the server log only.
- **OTP legacy compare not constant-time** (`users/models.py`). The plaintext
  fallback used `==`; switched to `hmac.compare_digest`. Only affected legacy
  un-hashed records (new OTPs already use `check_password`).

---

## Reviewed and found solid (no action)

Payments (server-side amounts, raw-body webhook HMAC, fail-closed, idempotent
capture under `select_for_update`, boot guards); orders/coupons (race-safe stock
& coupon redemption, admin-editable field whitelist); the AI assistant (closed
tool registry, user injected server-side, prompt-injection spotlighting, write
actions require UI confirmation, admin persona double-gated); uploads (magic-byte
verification, SVG blocked, staff-gated private media); reviews (verified-purchase
enforced); reverse-geocode proxy (fixed URL, bounds-checked floats); chat
markdown renderer (pure React elements, no `dangerouslySetInnerHTML`).

---

## Checklist to fully close on the server

1. Deploy the new backend image (code fixes: `NUM_PROXIES`, `get_client_ip`,
   exception handler, OTP, JWT-body removal).
2. Edit `~/NGU/.env.backend`: `CSRF_COOKIE_SECURE=True`, `SESSION_COOKIE_SECURE=True`.
   (Optionally set `NUM_PROXIES` there if the proxy count ever differs from 2.)
3. `docker compose -f docker-compose.prod.yml up -d` to apply the loopback port
   binding + env.
4. Confirm the EC2 security group exposes only 22/80/443.
5. Verify: rotating `X-Forwarded-For` against `/api/auth/login/` still yields
   `429`; login response body carries no `access`/`refresh`; CSRF/session
   `Set-Cookie` headers include `Secure`.
