# NGU Spices — Admin Panel

A React + TypeScript dashboard for managing the NGU Spices e-commerce platform.

## Features

- **Dashboard** — Sales overview, recent orders, stats
- **Products** — CRUD operations, gallery images, stock management
- **Combos** — Create/manage product combos with item quantities
- **Categories** — Organize products into categories
- **Sections** — Manage homepage display sections (drag-to-reorder products)
- **Orders** — View all orders, update status
- **Coupons** — Create and manage discount codes
- **Policies** — Edit shipping and return policies
- **Chat Support** — Respond to customer order-scoped chat sessions
- **Contact Submissions** — View and reply to contact form entries

## Tech Stack

| Technology | Purpose |
|------------|---------|
| React 18 | UI framework |
| TypeScript | Type safety |
| Vite | Build tool |
| TailwindCSS | Styling |
| Shadcn/UI | Component library |
| React Router | Navigation |
| Axios | API calls |

## Project Structure

```
src/
├── components/     # Shared UI components
├── pages/          # Admin pages (one per resource)
├── api/            # API client functions
├── contexts/       # Auth context
└── hooks/          # Custom hooks
```

## Quick Start

### Development

```bash
npm install
npm run dev
```

Open `http://localhost:5173`

### Build for Production

```bash
npm run build
```

### Docker

```bash
docker build -t ngu-admin .
docker run -p 3001:80 ngu-admin
```

## Environment Variables

Create `.env.local`:

```env
VITE_API_URL=http://localhost:8000/api
```

> The admin panel signs staff in with **email + password and Google**
> (`src/pages/Login.tsx`). Google works for **existing staff accounts only** —
> it never creates one. Set `VITE_GOOGLE_CLIENT_ID` (or runtime
> `GOOGLE_CLIENT_ID`); when empty the Google button is hidden.

## Pages

| Route | Page | Description |
|-------|------|-------------|
| `/` | Dashboard | Stats overview, recent orders |
| `/products` | Products | Manage products + gallery images |
| `/combos` | Combos | Manage combo packs |
| `/categories` | Categories | Manage categories |
| `/sections` | Sections | Homepage section ordering |
| `/orders` | Orders | Order management + status updates |
| `/coupons` | Coupons | Discount code management |
| `/chat` | Chat Support | Order-scoped customer chat |
| `/contact` | Contact | Contact form submissions |
| `/shipping-policy` | Shipping | Edit shipping policy |
| `/return-policy` | Returns | Edit return policy |
| `/admin-info` | Admin Info | Account settings |
| `/login` | Login | Admin authentication |

## Access Control

All pages require admin authentication (`is_staff=True`). The route guard redirects
unauthenticated users to `/login`. All API calls include a JWT `Authorization` header.

## Deployment

See [DEPLOYMENT.md](../../DEPLOYMENT.md) for EC2 deployment instructions.
