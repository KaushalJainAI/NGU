# NGU Spices — Customer Frontend

React + TypeScript e-commerce storefront for Nidhi Masala spices.

## Features

- **Product Browsing** — categories, search with autocomplete, filters
- **Product/Combo Details** — image gallery, reviews, add to cart
- **Shopping Cart** — persistent cart, stock validation
- **Checkout** — address, Razorpay payment, order confirmation
- **User Auth** — JWT login/register, Google OAuth, password reset
- **My Orders** — order history and status tracking
- **Favorites** — save products for later
- **AI Shopping Assistant** — conversational product Q&A widget
- **Personalized Recommendations** — based on browsing/purchase history
- **Voice Order** — voice-input via MediaRecorder + self-hosted whisper.cpp transcription
- **AI Chat Support** — unified AI + human-admin chat widget (via `AssistantWidget`)
- **Multilingual** — English, Hindi, Hinglish, Gujarati, Marathi, Punjabi
- **Responsive** — mobile-first design

## Tech Stack

| Technology | Purpose |
|------------|---------|
| React 18 | UI framework |
| TypeScript | Type safety |
| Vite | Build tool |
| TailwindCSS | Styling |
| Shadcn/UI | Component library |
| React Router v6 | Navigation |
| Axios | API calls |
| i18next | Multilingual UI |
| Lucide | Icons |

## Project Structure

```
src/
├── components/     # Reusable UI components
├── pages/          # Route-level page components
├── lib/api/        # API client functions (grouped by domain)
├── contexts/       # Global state (Auth, Cart)
├── hooks/          # Custom React hooks
├── i18n/           # i18next config + locale JSON files (en/hi/hinglish/gu/mr/pa)
├── types/          # TypeScript type definitions
└── utils/          # Helpers (Google Translate patch, etc.)
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
npm run preview
```

### Docker

```bash
docker build -t ngu-frontend .
docker run -p 3000:80 ngu-frontend
```

## Environment Variables

Create `.env.local` for local dev:

```env
VITE_API_URL=http://localhost:8000/api
VITE_GOOGLE_CLIENT_ID=your_google_client_id
```

For production builds (baked in at build time):

```env
VITE_API_URL=https://nidhimasala.com/api
VITE_GOOGLE_CLIENT_ID=860732387709-osb9oeant94oa302egqqqvqdj4jmkiuh.apps.googleusercontent.com
```

> Both variables are compile-time — they are embedded in the JS bundle during `npm run build`.
> Changing them requires a rebuild and redeploy.

## Pages

| Route | Page | Description |
|-------|------|-------------|
| `/` | Index | Home — featured sections, assistant widget |
| `/products` | Products | Browse + filter all products |
| `/products/:slug` | ProductDetail | Product detail, gallery, reviews |
| `/combos` | Combos | Combo packs listing |
| `/offer-zone` | OfferZone | Highlighted deals/offers |
| `/combos/:slug` | ComboDetail | Combo detail |
| `/search` | SearchResults | Full search results page |
| `/cart` | Cart | Shopping cart |
| `/billing` | Billing | Address + payment details entry |
| `/checkout` | Checkout | Order review + placement |
| `/my-orders` | MyOrders | Order history (auth required) |
| `/track-order` | TrackOrder | Track order by ID |
| `/order-success` | OrderSuccess | Confirmation after purchase |
| `/favorites` | Favorites | Saved products (auth required) |
| `/login` | Login | JWT + Google OAuth login |
| `/register` | Register | New user signup |
| `/profile` | Profile | User profile + address (auth required) |
| `/forgot-password` | ForgotPassword | Request password reset |
| `/reset-password` | ResetPassword | Set new password |
| `/about` | About | Company info |
| `/contact` | Contact | Contact form |
| `/shipping-policy` | ShippingPolicy | Shipping policy content |
| `/return-policy` | ReturnPolicy | Return policy content |

## Multilingual Support

The UI is fully translated into 6 languages via **i18next**:

| Code | Language |
|------|----------|
| `en` | English (default) |
| `hi` | Hindi |
| `hinglish` | Hinglish |
| `gu` | Gujarati |
| `mr` | Marathi |
| `pa` | Punjabi |

Language is stored in `localStorage` (key: `site_lang`) and sent to the backend as a
`?lang=` query parameter so API responses (product names, descriptions) return in the
selected language. The AI assistant also replies in the chosen language.

## Deployment

See [DEPLOYMENT.md](../../DEPLOYMENT.md) for EC2 deployment.
