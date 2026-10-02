# NGU — Nidhi Masala online store

The full e-commerce platform for **Nidhi Masala**, an Indian spice brand.

- **Shop**: browse spices and combo packs in six languages, search in Hindi or
  Hinglish, add to cart, pay online (Razorpay) or cash on delivery, track the
  order.
- **Assistant**: a chat helper that answers questions and suggests products, by
  text or voice. It can only *propose* cart changes; the customer confirms.
- **Admin panel**: products, stock, orders, refunds, coupons, reviews, sales
  insights and GST reports.
- **Paperwork**: a numbered tax invoice for every sale and a credit note for
  every refund.

## New here?

Read **[learning/README.md](learning/README.md)**. It explains the design from
the big picture down to the classes, with diagrams, and it is written for
someone who is still learning Django and React.

## Folders

| Folder | What it is |
|---|---|
| [`Backend/`](Backend/README.md) | Django REST Framework API: ten apps, Postgres, Redis |
| [`Frontend/nidhi-brand-forge/`](Frontend/nidhi-brand-forge/README.md) | Customer storefront (React, TypeScript, Vite) |
| [`Admin Panel/e-commerce-command-center/`](Admin%20Panel/e-commerce-command-center/README.md) | Admin dashboard (React, TypeScript, Vite) |
| [`learning/`](learning/README.md) | HLD, LLD, interview kit and lessons learned |
| [`testing/`](testing/README.md) | Black-box end-to-end and security tests that call a running server |
| [`whisper/`](whisper/Dockerfile) | Image for the self-hosted speech-to-text fallback |
| `tmp/` | Working notes (refund pipeline, accounting items, audits) |
| `introduction reel/` | Marketing brief for the launch reel |

This is **one git repository** (since 2026-10-02). The backend, the storefront
and the admin panel used to be three separate repositories; their histories
were merged in under their folders. The three old `.git` folders are kept,
untracked, in `.git-backup/`.

## Quick start (local)

```bash
# 1. Backend — details in Backend/LOCAL_DEV.md
cd Backend
docker compose up -d                 # local Postgres + Redis
cp .env.example .env                 # then set the local values LOCAL_DEV.md lists
python -m venv venv && venv/Scripts/activate     # Windows; use bin/activate elsewhere
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver           # http://127.0.0.1:8000/api/

# 2. Storefront (second terminal)
cd Frontend/nidhi-brand-forge
npm install && npm run dev           # http://localhost:5173

# 3. Admin panel (third terminal)
cd "Admin Panel/e-commerce-command-center"
npm install && npm run dev           # http://127.0.0.1:5174/panel/
```

Never point a local run at `Backend/.env.local`: it names a remote database.

Run the backend tests from `Backend/` (that folder owns `pytest.ini`):

```bash
cd Backend && venv/Scripts/python.exe -m pytest -q
```

[docker-compose.yml](docker-compose.yml) in this folder builds and runs the whole
stack in containers.

## Documentation map

**Start here**

| Document | What it is |
|---|---|
| [learning/](learning/README.md) | Design guide: HLD, LLD, patterns, interview kit, lessons |
| [CLAUDE.md](CLAUDE.md) | Project rules, production facts and decision history (written for AI assistants; useful for people too) |
| [Backend/docs/API.md](Backend/docs/API.md) | Every HTTP route, who may call it, what it touches |

**How it works** (reference, in `Backend/docs/`)

[ARCHITECTURE](Backend/docs/ARCHITECTURE.md) ·
[DATABASE_SCHEMA](Backend/docs/DATABASE_SCHEMA.md) ·
[ORDER_LIFECYCLE](Backend/docs/ORDER_LIFECYCLE.md) ·
[PAYMENTS_INTEGRATION](Backend/docs/PAYMENTS_INTEGRATION.md) ·
[AUTH](Backend/docs/AUTH.md) ·
[CART](Backend/docs/CART.md) ·
[ASSISTANT](Backend/docs/ASSISTANT.md) ·
[AI_SEARCH_ENGINE](Backend/docs/AI_SEARCH_ENGINE.md) ·
[ANALYTICS](Backend/docs/ANALYTICS.md) ·
[CACHING_STRATEGY](Backend/docs/CACHING_STRATEGY.md) ·
[MULTILINGUAL](Backend/docs/MULTILINGUAL.md) ·
[API_PERMISSIONS](Backend/docs/API_PERMISSIONS.md)

Frontend: [storefront ARCHITECTURE](Frontend/nidhi-brand-forge/ARCHITECTURE.md) ·
[admin panel ARCHITECTURE](Admin%20Panel/e-commerce-command-center/ARCHITECTURE.md)

**Running it**

| Document | What it is |
|---|---|
| [DEPLOYMENT.md](DEPLOYMENT.md) | Step-by-step deployment guide, written for the earlier AWS EC2 setup. CLAUDE.md has the current server. |
| [docker-compose.yml](docker-compose.yml) / [docker-compose.prod.yml](docker-compose.prod.yml) | The local and production stacks |
| [.env.backend.example](.env.backend.example) | Template for the backend's production settings |
| [RAZORPAY_GO_LIVE_CHECKLIST.md](RAZORPAY_GO_LIVE_CHECKLIST.md) | Steps to take payments live |
| [MONITORING_PLAN.md](MONITORING_PLAN.md) | Monitoring and incident plan |
| [TROUBLESHOOTING_AWS_MIGRATION.md](TROUBLESHOOTING_AWS_MIGRATION.md) | First-response notes from the April 2026 downtime on AWS |
| [HOSTINGER_MIGRATION.md](HOSTINGER_MIGRATION.md) | A planned move to another host. Not carried out. |
| [testing/README.md](testing/README.md) | How to run the end-to-end and security suites (never against production) |

**Plans, audits and decisions**

| Document | What it is |
|---|---|
| [AUDIT_AND_PLAN_2026-10.md](AUDIT_AND_PLAN_2026-10.md) | Security, assistant and voice audit, and the plan that followed |
| [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) | October 2026 plan: admin sessions, courier link, dashboard, GST reports, basic accounts |
| [CHANGES_AND_DECISIONS_2026-08.md](CHANGES_AND_DECISIONS_2026-08.md) | The changes of 1–4 August 2026 and the reasoning behind them |
| [SCALING_AUDIT.md](SCALING_AUDIT.md) | Resource use and scaling audit |
| [PLATFORM_QUALITY_PLAYBOOK.md](PLATFORM_QUALITY_PLAYBOOK.md) | A repeatable check of customer experience, robustness and security |
| [COMPLIANCE_CHECKLIST.md](COMPLIANCE_CHECKLIST.md) | Legal, regulatory, payment and data-protection checklist, with current status |
| [PRICING_STRATEGY.md](PRICING_STRATEGY.md) | Competitor prices, shipping policies and pricing strategy |
| [OTP_SMS_WHATSAPP_PLAN.md](OTP_SMS_WHATSAPP_PLAN.md) | Proposal for login codes by SMS and WhatsApp. Not built. |
| [UPCOMING_WORK.md](UPCOMING_WORK.md) | Roadmap of planned features |
| [DATABASE_FILLING.md](DATABASE_FILLING.md) | The catalogue content update of June 2026 |
| [ADMIN_GUIDE_HINDI.md](ADMIN_GUIDE_HINDI.md) | Admin panel guide in Hindi, for the shop owner |

## What is not in the repository

Secrets and private files are ignored on purpose: every `.env` file, server
keys (`*.pem`), cloud access keys, the GST certificate and other PDFs,
screenshots of the admin panel, databases and dumps. See
[.gitignore](.gitignore). Templates with placeholder values (`*.example`) are
tracked.
