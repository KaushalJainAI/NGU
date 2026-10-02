# 🌶️ NGU Spices - Backend API

A production-ready Django REST Framework backend for the NGU Spices e-commerce platform.

## ✨ Features

- **Authentication** - JWT in HttpOnly cookies, Google sign-in, email verification, separate admin session
- **Product Catalog** - Products sold by size (variants), combo packs, categories, homepage sections, six languages
- **Search** - Fuzzy search with offline-generated Hindi/Hinglish synonyms
- **Shopping Cart** - Persistent cart for products and combos, favorites
- **Orders** - Stock-safe checkout, coupons, cancellation, refunds, courier tracking
- **Payments** - Razorpay (browser verify, webhook and timed reconciliation) and cash on delivery
- **GST** - Numbered tax invoices, credit notes, HSN codes, GST reports
- **Reviews** - Verified-purchase ratings with admin moderation
- **Assistant** - Tool-calling AI shopping assistant with voice input and human hand-off
- **Analytics** - Sales and behaviour roll-ups, owner email digests
- **Admin APIs** - Dashboard, coupons, bulk product edits, CSV import/export, expenses

## 🛠️ Tech Stack

| Technology | Purpose |
|------------|---------|
| Django 5.2 | Web framework |
| Django REST Framework | API |
| PostgreSQL 17 + PgBouncer | Database and connection pool |
| Redis | Caching, rate limits, counters |
| Cloudinary | Media storage (product and profile images) |
| Razorpay | Payments |
| OpenRouter | Chat model and voice transcription |
| APScheduler | Timed jobs (`manage.py run_scheduler`) |
| Docker | Containerization |

## 📦 Project Structure

```
Backend/
├── spices_backend/     # Settings, URLs, middleware, limits, throttles
├── users/              # Authentication & profiles
├── products/           # Products, variants, combos, categories, search
├── cart/               # Shopping cart, favorites
├── orders/             # Orders, pricing, invoices, refunds, credit notes, GST
├── payments/           # Razorpay, payment audit trail, scheduler command
├── reviews/            # Product reviews
├── assistant/          # AI shopping assistant, voice transcription
├── analytics/          # Events, roll-ups, insights
├── admin_panel/        # Dashboard, coupons, expenses, owner emails
├── support/            # Contact form
├── docs/               # Reference documentation
├── Dockerfile          # Container config
└── requirements.txt    # Dependencies
```

This folder is part of the NGU repository. The design is explained, with
diagrams, in [`../learning/`](../learning/README.md).

## 📚 Official Documentation

Detailed system documentation is located in the [`docs/`](./docs/) directory:

**General Setup:**
- [Local development](./LOCAL_DEV.md)
- [Setup Guide](./docs/SETUP-GUIDE.md)
- [API map: every route](./docs/API.md)
- [API Permissions](./docs/API_PERMISSIONS.md)
- [Architecture Details](./docs/ARCHITECTURE.md)

**System Components:**
- [Database Schema](./docs/DATABASE_SCHEMA.md)
- [Order Lifecycle](./docs/ORDER_LIFECYCLE.md)
- [Payments Integration](./docs/PAYMENTS_INTEGRATION.md)
- [Authentication](./docs/AUTH.md)
- [Cart](./docs/CART.md)
- [AI Search Engine](./docs/AI_SEARCH_ENGINE.md)
- [Assistant](./docs/ASSISTANT.md)
- [Analytics](./docs/ANALYTICS.md)
- [Caching Strategy](./docs/CACHING_STRATEGY.md)
- [Multilingual Content](./docs/MULTILINGUAL.md)
- [Storage Config](./docs/S3_STORAGE.md)

## 🚀 Quick Start

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env with your values

# Run migrations
python manage.py migrate

# Create admin user
python manage.py createsuperuser

# Start server
python manage.py runserver
```

### Docker

```bash
docker build -t ngu-backend .
docker run -p 8000:8000 --env-file .env ngu-backend
```

## 🔧 Environment Variables

```env
# Django
SECRET_KEY=your-secret-key
DEBUG=False
ALLOWED_HOSTS=localhost,your-domain.com

# Database (RDS)
DB_ENGINE=django.db.backends.postgresql
DB_NAME=ngu_db
DB_USER=admin
DB_PASSWORD=password
DB_HOST=your-rds-endpoint.rds.amazonaws.com
DB_PORT=5432

# AWS S3
USE_S3=True
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_STORAGE_BUCKET_NAME=your-bucket
AWS_S3_REGION_NAME=ap-south-1

# Redis
REDIS_URL=redis://localhost:6379/0

# Payments
RAZORPAY_KEY_ID=your-key
RAZORPAY_KEY_SECRET=your-secret
```

## 📊 API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register/` | Register user |
| POST | `/api/auth/login/` | Login (JWT) |
| POST | `/api/auth/token/refresh/` | Refresh token |
| GET | `/api/auth/profile/` | Get profile |

### Products
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/products/` | List products |
| GET | `/api/products/{slug}/` | Product detail |
| GET | `/api/combos/` | List combos |
| GET | `/api/categories/` | List categories |

### Cart & Orders
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/cart/` | View cart |
| POST | `/api/cart/add_item/` | Add to cart |
| GET | `/api/orders/` | List orders |
| POST | `/api/orders/` | Create order |

### Admin Panel
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/dashboard/` | Dashboard stats |
| GET | `/api/coupons/` | Manage coupons |
| GET | `/api/policies/{type}/` | Get policies |

Full API documentation: `/api/docs/`

## 🔐 Permissions

| Endpoint | Permission |
|----------|------------|
| Products/Categories | Public read, Admin write |
| Cart | Authenticated users |
| Orders | Authenticated users |
| Dashboard/Coupons | Admin only |

## 🧪 Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=.
```

## 🚢 Deployment

See [DEPLOYMENT.md](../DEPLOYMENT.md) for EC2 deployment instructions.

---

Made with ❤️ for NGU Spices
