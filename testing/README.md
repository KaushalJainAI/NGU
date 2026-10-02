# NGU End-to-End Test Suite

Black-box end-to-end tests that exercise the **running** NGU API over HTTP.
They do not import Django — they hit the same endpoints a browser or the
admin panel would, so they validate the deployed system as a whole.

The design borrows the philosophy of the **Faultline** AI-assisted QA / chaos
platform: alongside happy-path coverage, the suite includes an adversarial
layer (`security/`) that fires hostile input — broken-access-control sweeps,
BOLA/IDOR probes, SQLi/XSS payloads, malformed bodies, throttle and CORS
checks — and asserts the API never 500s, never leaks a stack trace, and never
serves data to the wrong principal.

## Layout

```
testing/
├── conftest.py        # fixtures: base_url, sessions, throwaway users, auth tokens
├── pytest.ini         # markers + default options
├── requirements.txt   # pytest + requests
├── SECURITY_AUDIT.md  # audit report + findings (regenerate via the orchestrator)
├── e2e/               # functional happy paths (black-box HTTP)
│   ├── test_catalog.py            # health, categories, products, search, bounds
│   ├── test_auth_and_cart.py      # auth flow, registration, profile, cart, favorites, bounds
│   ├── test_checkout.py           # orders, coupons (G6), assistant Q&A, PDF invoice
│   ├── test_order_lifecycle.py    # COD place→invoice→cancel→restock, ONLINE create-order (self-cleaning)
│   ├── test_payments_http.py      # Razorpay create-order/verify/webhook/status — NON-charging surface
│   ├── test_reviews.py            # verified-purchase gate + can-review, opportunistic happy path
│   ├── test_assistant_support.py  # assistant login-gate + Q&A, contact form / admin inbox
│   └── test_account_cart.py       # cart add/update/remove/sync, favorites, password-reset request
├── security/          # Faultline-style adversarial probes
│   ├── test_access_control.py    # auth guards + BOLA/IDOR
│   └── test_hardening.py         # injection, robustness, rate limits & headers
├── tools/
│   ├── run_full_audit.py   # orchestrates the WHOLE pyramid into one transcript
│   └── seed_e2e.py         # seeds the local e2e server's catalog
├── ui/                     # browser-driven storefront video
│   ├── record_walkthrough.cjs  # Playwright script (records the session)
│   ├── record_website.sh       # boots backend + vite + Playwright, makes the mp4
│   ├── record_live.cjs         # live-prod personas (normal / malicious), stops before payment
│   └── record_payment_netbanking.cjs  # REAL Razorpay payment via netbanking — TEST MODE ONLY
├── SECURITY_AUDIT.md  # audit narrative + findings (F-1/F-2/F-3, all fixed)
└── reports/                # session_transcript.txt + storefront mp4 (gitignored)
```

## Full pyramid in one command (unit → integration → e2e → security + video)

`tools/run_full_audit.py` runs every layer and writes one combined transcript to
`reports/session_transcript.txt`:

```bash
# 1. local Postgres for the in-process suite (the :memory: SQLite default
#    deadlocks under full-suite load — see Backend/spices_backend/test_settings.py)
docker compose -f Backend/docker-compose.yml up -d db

# 2. run the whole audit (unit+integration on Postgres, then a live local
#    server for e2e+security). Razorpay flows are out of scope.
Backend/venv/Scripts/python testing/tools/run_full_audit.py

# 3. turn the captured transcript into a video
Backend/venv/Scripts/python testing/tools/make_video.py \
    testing/reports/session_transcript.txt testing/reports/ngu_test_run.mp4
```

The orchestrator:
- runs phase 1 against Postgres (the full suite, no quarantine — **346 passed**);
- spins up a throwaway file-SQLite server (`spices_backend.e2e_settings`), seeds
  a small catalog, runs the HTTP e2e + security suites at it, then tears it down.

The security
narrative and findings are in [SECURITY_AUDIT.md](SECURITY_AUDIT.md).

### Storefront walkthrough video

`ui/record_website.sh` boots the seeded backend (`:8000`) and the Vite dev
server (`:5173`, which proxies `/api` → the backend), then uses **Playwright** to
drive the real React storefront — home, products, product detail, search,
combos, offers, login/register, cart, about, contact — and records the browser
session. The capture is transcoded to
`reports/ngu_storefront_walkthrough.mp4`.

One-time setup (in `testing/ui/`):

```bash
npm i -D playwright
npx playwright install chromium chromium-headless-shell
```

Then: `bash testing/ui/record_website.sh`.

## Configuration (environment variables)

| Var | Default | Meaning |
|-----|---------|---------|
| `NGU_BASE_URL` | `http://localhost:8000` | API host (suite appends `/api/...`). Accepts host or host+`/api`. |
| `NGU_IS_PROD` | auto | `1` marks target as production -> all `destructive` (data-writing) tests skip. Auto-detects the live host. |
| `NGU_TIMEOUT` | `15` | Per-request timeout (seconds). |

`destructive` = anything that writes data (user registration, cart writes).
These are skipped automatically against production so the suite is **safe to
run read-only against the live API**.

## Install & run

```bash
cd testing
pip install -r requirements.txt

# Against a local dev/docker backend (full suite, incl. destructive writes):
NGU_BASE_URL=http://localhost:8000 pytest

# Read-only safety net against production:
NGU_BASE_URL=https://nidhimasala.com pytest -m "not destructive"

# Just the smoke layer / just the adversarial layer:
pytest -m smoke
pytest -m security
```

On Windows PowerShell:

```powershell
$env:NGU_BASE_URL = "http://localhost:8000"; pytest
```

Or use the wrappers: `./run.sh` (bash) / `./run.ps1` (PowerShell).

## Markers

`smoke`, `auth`, `catalog`, `cart`, `security`, `destructive`, `order`,
`payment`, `review`, `assistant`, `support` (see `pytest.ini`). Combine with
`-m`, e.g. `-m "security and not destructive"` or `-m "payment or order"`.

## Running against PRODUCTION safely (reusable account + payment safety)

The `order` / `payment` / `review` / `assistant` / `support` suites are designed
to run against a live target **without leaving a mess**: everything they create
they undo (cart clear, favorite remove, COD order **cancel** — which restocks).
They authenticate as **one reusable account** rather than minting a user per run:

```bash
export NGU_BASE_URL=https://nidhigrahudyog.com          # the resolving prod domain
export NGU_IS_PROD=1                                     # skip the non-undoable `destructive` tests
export NGU_TEST_ACCOUNT_EMAIL=qa.e2e@nidhimasala.com     # registered once, idempotently
export NGU_TEST_ACCOUNT_PASSWORD='<a-strong-password>'
pytest -m "order or payment or review or assistant or support or catalog"
```

The only residue on a prod run is **cancelled-order rows** (and, if paid, one
paid order) on that single account — nothing else persists.

### The payment safety model (why this can't charge real money)

* The **HTTP payment suite never completes a capture.** Only Razorpay can mint a
  valid `payment_id`+signature, so those tests only prove the *gates* (server-side
  amount, idempotency, signature rejection, ownership, honest status labels).
* Anything that opens a live Razorpay order depends on the
  **`require_razorpay_test_mode`** fixture, which reads the publishable key from
  `create-order/` and **hard-skips unless it starts with `rzp_test_`**. So the
  charging-adjacent tests physically cannot fire against live keys.
* The **only** flow that completes a real payment is the browser test
  `ui/record_payment_netbanking.cjs`, and it repeats the same `rzp_test_` guard
  before paying — aborting outright on live keys. Prod runs **live** keys by
  default (`RAZORPAY_TEST_MODE=False`), so **set `RAZORPAY_TEST_MODE=True` on the
  target first** or every charging test correctly skips/aborts.

### Real netbanking payment (browser, test mode only)

```bash
cd testing/ui && npm install     # playwright + browsers if not already present
export NGU_TEST_ACCOUNT_EMAIL=...    # same reusable account
export NGU_TEST_ACCOUNT_PASSWORD=...
node record_payment_netbanking.cjs https://nidhigrahudyog.com
```

It logs in, places an ONLINE order, **confirms the target is in test mode**,
drives Razorpay checkout → Netbanking → a test bank → **Success**, then polls
`/payments/status/` until the order is `paid` (proving both the `/verify/`
callback and the L2 webhook landed). Output: `reports/live/payment-netbanking.webm`
+ `payment-netbanking.findings.json`. Razorpay's checkout markup changes over
time, so the in-frame selectors are best-effort and log what they clicked.

> ⚠️ Prod currently has **no `RAZORPAY_WEBHOOK_SECRET`** (see project CLAUDE.md).
> Until it is set, webhooks are rejected fail-closed, so instrument details stay
> blank and `payment_status` flips to `paid` only via the `/verify/` callback —
> the netbanking test still passes, but L2 reconciliation won't be exercised.

## Live-prod browser recordings (`ui/record_live.cjs`)

Beyond the HTTP suite, `ui/record_live.cjs` drives a real Chromium session
against **live production**, records the whole session to a `.webm`, and writes
an interaction/security findings JSON. It covers two personas × two layouts:

| persona | what it does |
|---------|--------------|
| `normal` | browse → register/login (creates **one** shared test account) → cart → favorites → checkout **(stops before payment)** → logout |
| `malicious` | authorized, **non-destructive** abuse: anon auth-gate checks, unauth API hits, IDOR/BOLA on `/orders/{id}`, search XSS/SQLi payloads, admin-endpoint probes, `access_token` cookie tampering (verifies forced logout), and a login rate-limit probe capped at 7 requests |

```bash
cd testing/ui
npm install                       # playwright (browsers: npx playwright install chromium)

# one persona/layout:
node record_live.cjs normal desktop https://nidhimasala.com
node record_live.cjs malicious mobile https://nidhimasala.com

# whole matrix + combined markdown report (normal first so login isn't throttled):
node run_live_suite.cjs https://nidhimasala.com
```

Outputs land in `testing/reports/live/`: `<persona>-<device>.webm`,
`<persona>-<device>.findings.json`, and `LIVE_RUN_REPORT.md`. Expected noise
(401s while logged-out, `ERR_ABORTED` from fast navigation, the relative-`/api`
build warning, Google GSI cosmetics) is filtered so only genuine problems are
flagged as `issue`.

**Guarantees:** never completes a payment, never deletes data, creates at most
one `qa.bot.*@example.com` account (reused across runs via
`reports/live/test-account.json`), and caps the rate-limit probe.

## Notes

- The suite **fails fast** with a clear message if `/api/health/` is
  unreachable, so a misconfigured `NGU_BASE_URL` is obvious immediately.
- Throwaway accounts use random `e2e_*` / `bola_*` usernames so reruns don't
  collide.
- Tolerant assertions (e.g. assistant returning `503` when no LLM key is
  configured, throttling disabled in test settings) are treated as skips, not
  failures, so the suite is meaningful across local/staging/prod.
