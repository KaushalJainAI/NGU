# 🌶️ NGU Spices - Backend API

A production-ready Django REST Framework backend for the NGU Spices e-commerce platform.

## ✨ Features

- **JWT Authentication** - Secure token-based authentication
- **User Management** - Registration, profiles, addresses
- **Product Catalog** - Products, combos, categories with S3 image storage
- **Shopping Cart** - Persistent cart with product/combo support
- **Orders** - Full order lifecycle with status tracking
- **Payments** - Razorpay integration with COD support
- **Reviews** - Product ratings and reviews
- **Support Chat** - Real-time customer support per order
- **Admin Dashboard** - Sales stats, order management, coupons
- **Redis Caching** - Fast product/category caching
- **AWS S3** - Cloud storage for media files

## 🛠️ Tech Stack

| Technology | Purpose |
|------------|---------|
| Django 5.2 | Web framework |
| Django REST Framework | API |
| PostgreSQL (RDS) | Database |
| Redis | Caching |
| AWS S3 | File storage |
| Razorpay | Payments |
| Docker | Containerization |

## 📦 Project Structure

```
Backend/
├── spices_backend/     # Django settings
├── users/              # Authentication & profiles
├── products/           # Products, combos, categories
├── cart/               # Shopping cart
├── orders/             # Order management
├── payments/           # Payment processing
├── reviews/            # Product reviews
├── support/            # Chat support
├── admin_panel/        # Dashboard & policies
├── Dockerfile          # Container config
└── requirements.txt    # Dependencies
```

## 📚 Official Documentation

Detailed system documentation is located in the [`docs/`](./docs/) directory:

**General Setup:**
- [Setup Guide](./docs/SETUP-GUIDE.md)
- [API Permissions](./docs/API_PERMISSIONS.md)
- [Architecture Details](./docs/ARCHITECTURE.md)

**System Components:**
- [Database Schema](./docs/DATABASE_SCHEMA.md)
- [AI Search Engine](./docs/AI_SEARCH_ENGINE.md)
- [Payments Integration](./docs/PAYMENTS_INTEGRATION.md)
- [Caching Strategy](./docs/CACHING_STRATEGY.md)
- [S3 Storage Config](./docs/S3_STORAGE.md)
- [Support Chat System](./docs/SUPPORT_CHAT.md)

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
