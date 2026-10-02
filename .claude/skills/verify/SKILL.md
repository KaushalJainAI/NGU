---
name: verify
description: Run the NGU stack locally (Django API + admin panel) against an isolated SQLite DB and drive a real flow end-to-end in Chrome. Use when verifying a change to the backend API or the admin panel.
---

# Verifying NGU locally

Brings up the real backend and the real admin panel, isolated from every remote
database, and drives them in a real browser.

## Do not use the checked-in env files

`Backend/.env.local` points `DB_HOST` at a **remote** database. `Backend/.env`
and `.env.dev` expect a local Postgres that usually isn't running. Instead
override via environment variables — `settings.py` falls back to SQLite when
`DB_ENGINE` is unset, and `python-decouple` reads `os.environ` before `.env`.

Write a `smokeenv.sh` into your scratchpad and `source` it:

```sh
export DB_ENGINE=django.db.backends.sqlite3
export DB_NAME="<scratchpad>/smoke.sqlite3"
export DB_USER=""; export DB_PASSWORD=""; export DB_HOST=""; export DB_PORT=""
export DEBUG=True
export USE_CLOUDINARY=False      # Cloudinary is a hard startup dependency otherwise
export USE_S3=False
export REDIS_URL=""
export SECRET_KEY="smoke-test-only"
export ALLOWED_HOSTS="127.0.0.1,localhost,testserver"
export CORS_ALLOWED_ORIGINS="http://localhost:5174,http://127.0.0.1:5174"
export CSRF_TRUSTED_ORIGINS="http://localhost:5174,http://127.0.0.1:5174"
export RAZORPAY_KEY_ID="rzp_test_smoke"
export RAZORPAY_KEY_SECRET="smokesecret"
export RAZORPAY_WEBHOOK_SECRET="whsec_smoke"
export EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
```

## Launch

```sh
cd Backend && source <scratchpad>/smokeenv.sh
./venv/Scripts/python.exe manage.py migrate --noinput
./venv/Scripts/python.exe manage.py shell -c "exec(open('seed.py').read())"
./venv/Scripts/python.exe manage.py runserver 127.0.0.1:8901 --noreload   # background

cd "Admin Panel/e-commerce-command-center"
VITE_API_URL=http://127.0.0.1:8901/api npx vite --port 5174 --host 127.0.0.1  # background
```

The admin panel serves at **`http://127.0.0.1:5174/panel/`** (not `/`), vite
port is pinned to 5174 in `vite.config.ts`. Keep `CORS_ALLOWED_ORIGINS` in sync
with whatever port you use, or every API call fails.

## Seeding

`User` has a **required unique `username`** separate from `email` — set both in
`get_or_create` defaults or you get `UNIQUE constraint failed: users_user.username`.

## Auth

`POST /api/auth/login/` with `{"email","password"}` returns `{access, refresh}`
and also sets cookies. For curl, grab `.access` and send
`Authorization: Bearer <token>`.

## Driving the browser

No Playwright in the repo, but Chrome is installed. Install `playwright-core`
into a scratchpad dir and drive the installed Chrome — no browser download:

```sh
mkdir -p <scratchpad>/browser && cd <scratchpad>/browser
npm init -y && npm install playwright-core
```

```js
const browser = await chromium.launch({ channel: 'chrome', headless: true });
```

Gotchas:
- **`page.screenshot()` fails while a Radix dialog is animating**
  (`Protocol error (Page.captureScreenshot)`). Screenshot the dialog element
  instead (`dialog.screenshot()`) and wait ~900ms after opening.
- On the Orders page, a row's **first** button is the green "Confirm order →",
  which **mutates order status**. To open the read-only detail dialog target the
  eye icon: `button:has(svg.lucide-eye)`.
- `GET /api/auth/profile/ 401` before login is normal, not a failure.

## Simulating a Razorpay webhook

The webhook is signature-gated but verification is pure local HMAC, so
placeholder keys work and nothing contacts Razorpay. Sign the **exact** body
bytes with `RAZORPAY_WEBHOOK_SECRET`:

```python
sig = hmac.new(b'whsec_smoke', body, hashlib.sha256).hexdigest()
# POST to /api/payments/webhook/ with headers:
#   X-Razorpay-Signature: <sig>
#   X-Razorpay-Event-Id: <unique per event; reuse to test idempotency>
```

Payment entity shape: `{"event":"payment.captured","payload":{"payment":{"entity":
{"id","order_id","amount","method","vpa"|"card"{...}|"bank"|"wallet"}}}}`.

Useful flows to drive: capture (UPI/card), `payment.failed`, replaying the same
event id (must stay idempotent), and `/api/payments/verify/` *before* the
webhook (the client callback carries no payment entity — signature is
`HMAC(key_secret, "<order_id>|<payment_id>")`).
