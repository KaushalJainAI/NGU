# Frontend Architecture

This document explains the design principles, component structure, and state management patterns.

---

## Design Principles

### 1. Feature-Based Organization
Code is organized by feature/page rather than by type:
```
src/
├── pages/          # Route-level components (one file per page)
├── components/     # Reusable UI components
├── lib/api/        # API client functions (grouped by domain)
├── contexts/       # Global state (Auth, Cart)
├── i18n/           # Translations + language config
└── hooks/          # Custom React hooks
```

### 2. Colocation
Related code stays together — API functions in `lib/api/` mirror backend apps; each
page is self-contained with its own data-fetching state.

### 3. Composition over Inheritance
UI is built from small, composable Shadcn/UI + Tailwind components.

---

## Application Flow

### Page Load → Data Fetch

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Router    │────▶│    Page     │────▶│  API Call   │
│ (App.tsx)   │     │ Component   │     │ (useEffect) │
└──────��──────┘     └─────────────┘     └──────────���──┘
                          │                    │
                          ▼                    ▼
                   ┌─────────────┐     ┌─────────────┐
                   │   Render    │◀────│  setState   │
                   │     UI      │     │   (data)    │
                   └───���─────────┘     └─────────────┘
```

### Authentication Flow

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  Login   ���────▶│  POST    │────▶│  Store   │────▶│ Redirect │
│  Form    │     │ /login/  │     │  Token   │     │  Home    │
└──────────┘     └���─────────┘     ���──────────┘     └─────────��┘
                                       │
                             HttpOnly cookies (access + refresh)
                             User profile cached in localStorage("user")
```

### Cart Flow

```
Add to Cart → CartContext → localStorage → Sync with Backend
                  │
                  └─── Persists across page reloads
```

---

## State Management

### 1. AuthContext (Global)
Manages user authentication state:
```typescript
interface AuthContextType {
  user: User | null;
  isLoggedIn: boolean;
  isLoading: boolean;
  login: (email, password) => Promise<boolean>;
  logout: () => void;
  signup: (userData) => Promise<boolean>;
  googleLogin: (accessToken) => Promise<boolean>;
  refreshUser: () => Promise<void>;
}
```

JWTs are stored in **HttpOnly cookies** set by the server — never in JavaScript-accessible
storage. The user profile object is cached in `localStorage("user")` for instant initial
render, and cleared on 401/403 or logout.

### 2. CartContext (Global)
Manages shopping cart:
```typescript
interface CartContextType {
  items: CartItem[];
  addItem: (product, quantity) => void;
  removeItem: (itemId) => void;
  updateQuantity: (itemId, quantity) => void;
  clearCart: () => void;
  total: number;
}
```

Persists in localStorage and syncs to backend for logged-in users.

### 3. Local State (Per-Component)
Each page manages its own data loading:
```typescript
const [products, setProducts] = useState<Product[]>([]);
const [loading, setLoading] = useState(true);

useEffect(() => {
  fetchProducts().then(setProducts).finally(() => setLoading(false));
}, []);
```

---

## Key Implementation Details

### 1. API Client Structure

All API calls go through a configured Axios instance:
```
lib/api/
├── config.ts       # Axios instance with baseURL, interceptors, lang header
├── products.ts     # getProducts(), getProduct(slug)
├── cart.ts         # getCart(), addToCart(), etc.
├── orders.ts       # getOrders(), createOrder()
├── assistant.ts    # sendAssistantMessage()
└── auth.ts         # login(), register(), getProfile()
```

**Runtime config (one image, many deployments).** Vite inlines `VITE_*` at *build*
time, freezing them into the bundle. To reconfigure a built image per deployment
**without rebuilding**, the container entrypoint writes `window.APP_CONFIG` from its
env on every start, and `src/config/runtimeEnv.ts → readEnv()` prefers that runtime
value over the build-time Vite value (falling back so `npm run dev` still works).
`config.ts` resolves the API base URL this way, so `window.APP_CONFIG.API_URL` wins
over `VITE_API_URL`. Keep the deployed value **relative (`/api`)** so the SPA calls
whatever origin served it. (`public/config.js` is the local-dev stub.)

### 2. Authentication & Token Refresh

Auth tokens are HttpOnly cookies sent automatically with every `credentials: "include"` request.
On a 401 response, `authFetch` (in `lib/api/config.ts`) transparently calls
`POST /auth/token/refresh/` to get a new access token, then retries the original request.
If refresh also fails, it dispatches an `auth:unauthorized` event which `AuthContext` handles
by clearing the user state and localStorage cache.

```typescript
// config.ts — automatic token refresh on 401
if (response.status === 401) {
  await refreshAccessToken();   // hits /auth/token/refresh/ with cookie
  response = await fetch(url, options);  // retry with fresh cookie
}
// On 401 or 403: always clear the cached user from localStorage
if (response.status === 401 || response.status === 403) {
  localStorage.removeItem("user");
}
```

### 3. Language Header

The selected language is sent with every API request so the backend returns translated
content (product names, descriptions) in the right language:
```typescript
api.interceptors.request.use((config) => {
  const lang = localStorage.getItem('site_lang') || 'en';
  config.params = { ...config.params, lang };
  return config;
});
```

### 4. Protected Routes

Routes requiring auth redirect to login:
```typescript
if (!isAuthenticated) {
  return <Navigate to="/login" state={{ from: location }} />;
}
```

### 5. Product vs Combo Cart Items

Cart items can be products OR combos:
```typescript
interface CartItem {
  id: number;
  product?: Product;
  combo?: Combo;
  quantity: number;
}

const itemName = item.product?.name || item.combo?.name;
const itemPrice = item.product?.price || item.combo?.price;
```

### 6. Optimistic Cart Updates

Cart operations update UI immediately, then sync to backend:
```typescript
const addToCart = (product) => {
  setItems([...items, newItem]);            // 1. Update UI
  api.addToCart(product.id, quantity)       // 2. Sync
    .catch(() => setItems(items));           // 3. Revert on failure
};
```

### 7. Behavioral Event Ingest

Product views, clicks, and searches are sent to `POST /api/events/` to feed
personalized recommendations:
```typescript
// After a product page renders:
api.ingestEvent({ event_type: 'view', product_id: product.id });
```

Events fire and forget — failures are silently ignored to keep the UX clean.

### 8. AI Shopping Assistant

The chat widget (`components/AssistantWidget.tsx`) calls `POST /api/assistant/chat/`
with the user's message and conversation history. The backend runs the agent loop and
returns a `reply` plus an optional `proposed_action` (e.g., add-to-cart proposal the
UI must confirm). The selected language is forwarded so the assistant replies in the
right language.

**Login-only.** The assistant is gated behind login — the widget only fetches when
`!!user`, and a logged-out user who triggers it is routed to `/login` (the backend
rejects anonymous chat with `IsAuthenticated`). Logged-in users get product Q&A **and**
cart/order tools.

**Voice input:** `hooks/useVoiceInput` records with `MediaRecorder`, converts the
audio to 16 kHz mono WAV (`lib/audio.ts`), and POSTs it to `POST /api/assistant/transcribe/`
(self-hosted whisper.cpp). The returned transcript is sent through `/chat/` like typed
text. This replaced the old browser Web Speech API (`useSpeechRecognition`, removed).

---

## Multilingual Support (i18next)

The storefront supports 6 languages: `en`, `hi`, `hinglish`, `gu`, `mr`, `pa`.

- **Translation files:** `src/i18n/locales/<code>.json` — UI strings only (labels,
  buttons, placeholders).
- **Product content** (names, descriptions) comes translated from the backend via the
  `?lang=` query parameter.
- **Language storage:** `localStorage` key `site_lang`. The language picker updates
  this and triggers an i18n language change.
- **Assistant:** the selected language code is forwarded to `POST /api/assistant/chat/`
  so the assistant replies in the same language.

```typescript
// src/i18n/index.ts
export const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'हिन्��ी' },
  { code: 'hinglish', label: 'Hinglish' },
  { code: 'gu', label: 'ગુજરાતી' },
  { code: 'mr', label: 'मराठी' },
  { code: 'pa', label: 'ਪੰਜਾਬੀ' },
];
```

---

## Component Patterns

### Page Component Pattern
```typescript
const ProductsPage = () => {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    getProducts()
      .then(res => setProducts(res.data))
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Loading />;
  if (error) return <Error message={error} />;
  return <ProductGrid products={products} />;
};
```

### Form Pattern
```typescript
const [formData, setFormData] = useState({ name: '', email: '' });

const handleSubmit = async (e) => {
  e.preventDefault();
  try {
    await api.submit(formData);
    toast({ title: 'Success' });
  } catch {
    toast({ title: 'Error', variant: 'destructive' });
  }
};
```

---

## Routing Structure

```
/                   → Index (home, featured sections)
/products           → Product listing
/products/:slug     → Product detail
/combos             → Combo packs
/offer-zone         → Offer zone
/combos/:slug       → Combo detail
/search             → Search results
/cart               → Shopping cart
/billing            → Billing/address entry
/checkout           → Order review + placement
/login              → Login (JWT + Google OAuth)
/register           → Register
/profile            → User profile (auth required)
/my-orders          → Order history (auth required)
/track-order        → Track order by ID
/order-success      → Post-purchase confirmation
/favorites          → Saved products (auth required)
/about              → About page
/contact            → Contact form
/shipping-policy    → Shipping policy
/return-policy      → Return policy
```

---

## Error Handling

### API Errors
```typescript
try {
  await apiCall();
} catch (error) {
  // 401/403 are handled centrally in authFetch (token refresh + localStorage clear)
  toast({ title: 'Error', description: error.message });
}
```

### 404 Handling
React Router catches unmatched routes → `NotFound` page.

### Render-time crashes (Error Boundaries)
React error boundaries wrap the app so a thrown render error shows a recoverable
fallback ("something went wrong, try again") instead of a blank white page. This
contains a crash to the boundary's subtree rather than unmounting the whole SPA.
User-facing gate failures (e.g. "please log in") are surfaced as **styled toasts**,
never blocking `window.alert()`s.

---

## Known Quirk: Google Translate + React Portals

**Symptom:** page goes blank with `Uncaught NotFoundError: Failed to execute
'removeChild' on 'Node'`, usually inside a Radix `Select`/`Dialog`/`Tooltip`.

**Cause:** the site embeds the Google Translate widget (`index.html` →
`google_translate_element`). Translate replaces text nodes in place; React still holds
references to the originals, so `removeChild`/`insertBefore` on a swapped node throws
and crashes the React tree. This is not specific to any one component — portals just
surface it most often.
([facebook/react#11538](https://github.com/facebook/react/issues/11538))

**Fix:** `src/utils/googleTranslateReactFix.ts` patches `Node.prototype.removeChild`
and `insertBefore` to no-op when the node is not actually a child, turning the hard
crash into a safe warning. It runs once in `main.tsx` **before the first render**.

If this recurs: verify the patch is still the first thing in `main.tsx`. Do not "fix"
it by removing the Select/Portal that crashed — the root cause is Translate, not that
component. Adding `class="notranslate"` to volatile dynamic-text containers is a
complementary mitigation.

---

## Extending the Application

### Adding a New Page

1. Create `src/pages/NewPage.tsx`
2. Add route in `App.tsx`
3. Add navigation link in Header/Footer
4. Add i18n strings to each `src/i18n/locales/*.json`

### Adding a New API Endpoint

1. Add function in the appropriate `lib/api/*.ts` file
2. Call from component with proper error handling
