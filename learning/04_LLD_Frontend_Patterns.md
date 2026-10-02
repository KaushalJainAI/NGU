# Part 4 — Frontend LLD Patterns

> The recurring code patterns in the React storefront and the admin panel.
> Back to the [index](README.md).

This file explains **the recurring code patterns in the React storefront** (`Frontend/nidhi-brand-forge`, and the same patterns in the Admin Panel): what boilerplate we write to achieve a thing, why, and what an interviewer is actually testing.

It assumes **you do not know React, TypeScript, or the libraries**. Every concept is built up from scratch.

---

## 0. The 60-second mental model

A React app is **one HTML page** whose contents JavaScript rewrites as you click around. No page reloads. To do that it needs three ideas:

**1. A component is a function that returns markup.**

```tsx
const ProductCard = ({ product }) => {
  return <div className="rounded-xl">{product.name}</div>;
};
```

That `<div>` inside JavaScript is **JSX** — HTML-flavored syntax that compiles to function calls. `{product.name}` interpolates a value. `product` is a **prop**: an input to the component, exactly like a function argument. Data flows **down** from parent to child through props; that one-way flow is what makes a React UI traceable.

**2. State is memory, and changing it re-renders.**

```tsx
const [products, setProducts] = useState([]);   // value, setter
```

`useState` gives a component memory that survives re-renders. When you call `setProducts(...)`, React re-runs the component function and updates only the parts of the real DOM that actually changed. **You never touch the DOM yourself.** You describe what the UI *should look like* for the current state, and React figures out the minimal edit. This is the core inversion: imperative DOM manipulation (`document.getElementById(...).innerHTML = ...`) becomes **declarative** rendering.

**3. Effects are for talking to the outside world.**

Rendering must be pure — no network calls, no timers. Anything that reaches outside React (fetching, subscriptions, localStorage) goes in `useEffect`.

The rest of this document is: **what patterns we build on top of those three ideas, and why each one exists.**

The stack: **React** (UI) + **TypeScript** (types) + **Vite** (build tool) + **React Router** (URL → page) + **Tailwind** (styling) + **shadcn/ui + Radix** (components) + **TanStack Query** (server data) + **i18next** (translations).

---

## 1. Pattern: TypeScript interfaces as the API contract

```ts
export interface Product {
  id: number;
  name: string;
  price: number;
  discount_price?: number;   // ? = may be absent
  in_stock: boolean;
  variants?: ProductVariant[];
}
```

**What it is:** TypeScript is JavaScript plus type annotations. It runs entirely at *build* time — the browser never sees it. Its only job is to fail your build when you make a mistake.

**Why it matters here:** this interface is the **mirror image of the backend's serializer**. It is a written contract: "this is the shape the API sends." Type a typo (`product.nmae`) and the build breaks in your editor rather than rendering `undefined` to a customer. Rename a backend field and every place that reads it lights up red instantly. That's the real payoff — TypeScript turns a whole category of runtime bug into a compile-time error, and it makes large refactors *safe* rather than terrifying.

Note `discount_price?` — the `?` means optional. TypeScript then **forces** you to handle the absent case before you can use the value. The compiler is nagging you about the exact bug (`undefined is not a number`) that would otherwise reach production.

> **Interviewer:** *"Why TypeScript in a small project?"*
> **Answer:** It documents the API contract in code and enforces it. The benefit scales with how often you refactor, not with codebase size.

---

## 2. Pattern: The API layer — one module per resource

Components **never** call `fetch()` directly. Every network call goes through [src/lib/api/](../Frontend/nidhi-brand-forge/src/lib/api/), one file per backend resource: `products.ts`, `cart.ts`, `orders.ts`, `auth.ts`, `payments.ts`…

```ts
export const productsAPI = {
  getAll:      (params?) => publicFetch<Product[]>(`${API_BASE_URL}/products/?${qs}`),
  getBySlug:   (slug: string) => publicFetch<Product>(`${API_BASE_URL}/products/${slug}/`),
  getSections: () => publicFetch<ProductSection[]>(`${API_BASE_URL}/products/sections/`),
};
```

**The pattern is Facade + Repository:** components ask for *what they want* (`productsAPI.getBySlug("garam-masala")`), not *how to get it*. The URL, the method, the headers, the credential handling, the response shape — all hidden. Consequences:

- Change an endpoint's URL → **one** line changes, not thirty components.
- `publicFetch<Product>` is **generic**: the `<Product>` type parameter flows through and the caller gets a fully typed object. The type contract holds all the way from the wire to the JSX.
- All URLs are built from `API_BASE_URL`. A plain Vite app reads that from `import.meta.env.VITE_API_URL`, which is **baked in at build time** — the value is compiled into the JS bundle, because a browser has no environment variables. This app adds a runtime layer on top so one image can serve any deployment; see §12.

---

## 3. Pattern: `authFetch` — the fetch wrapper that carries all the cross-cutting policy

This is the single most interview-worthy file on the frontend: [src/lib/api/config.ts](../Frontend/nidhi-brand-forge/src/lib/api/config.ts). It's a **Decorator** around the browser's `fetch`, adding five concerns that would otherwise be copy-pasted into every call site.

```ts
export const authFetch = async <T = unknown>(url: string, options: RequestInit = {}): Promise<T> => {
  const csrfToken = getCookie("csrftoken");
  const headers = { 'Content-Type': 'application/json', ...getLangHeader(),
                    ...(csrfToken && { 'X-CSRFToken': csrfToken }) };

  let response = await fetchWithTimeout(url, { ...options, credentials: "include", headers });

  if (response.status === 401) {                 // access token expired
    try {
      await refreshAccessToken();                // silently mint a new one
      response = await fetchWithTimeout(url, {...});  // replay the original request
    } catch { /* refresh failed → session is over */ }
  }

  if (!response.ok) {
    if (response.status === 401) forceLogout();  // survived the retry → truly dead
    throw new APIError(response.status, response.statusText, await response.json().catch(() => ({})));
  }
  if (response.status === 204) return null as T;
  return response.json() as Promise<T>;
};
```

### The five concerns, and the question behind each

**a) `credentials: "include"` — cookie auth.**
There is **no token in JavaScript**. The backend sets an `HttpOnly` cookie, which JS cannot read, and this flag tells the browser to attach it. Storing a JWT in `localStorage` (the tutorial default) means any XSS can steal it; `HttpOnly` cookies can't be read by script at all. That's the security trade we're making, and the price is CSRF, handled next.

**b) `X-CSRFToken` — the CSRF defence.**
Because cookies are sent automatically, a malicious site could make *your* browser fire a request with *your* cookies. The countermeasure: read the non-HttpOnly `csrftoken` cookie and echo it back in a header. An attacker's page can send the cookie but **cannot read it** (same-origin policy), so it cannot forge the header. This is the double-submit-cookie pattern.

**c) Transparent 401 refresh-and-retry.**
The access token is deliberately short-lived. When it expires mid-session, the user should not be logged out — they should not even notice. So: catch the 401, refresh, replay the *original* request, return its result. The calling component's `await` simply takes a bit longer and then succeeds. **This is why the wrapper must exist:** you cannot sanely implement silent refresh in every component.

**d) The refresh stampede lock.**
```ts
let refreshPromise: Promise<boolean> | null = null;
export const refreshAccessToken = async () => {
  if (refreshPromise) return refreshPromise;   // a refresh is already in flight — join it
  refreshPromise = (async () => { ... })();
  return refreshPromise;
};
```
A page loads and fires six parallel requests; the token has just expired; **all six get a 401 at the same moment.** Without this, all six hit `/token/refresh/` simultaneously — and with refresh-token rotation, five of them present an already-consumed token and the user is logged out for no reason. Caching the in-flight promise means five callers *await the same promise* and one network call happens. This is **promise memoization / single-flight**, and being able to name the failure mode it prevents is exactly what a senior interviewer is listening for.

**e) `forceLogout()` — the single choke point.**
```ts
export const forceLogout = (): void => {
  localStorage.removeItem("user");
  window.dispatchEvent(new Event("auth:unauthorized"));  // AuthContext listens
};
```
The problem it solves: the API layer knows the session is dead, but the React state lives in `AuthContext`, and a plain module can't call a hook. So it fires a **DOM event** and the context listens. That's the Observer pattern used to bridge two worlds that can't import each other. Because it's the *one* path out of a session, the localStorage cache and the React state can never drift apart.

Also note the deliberate **403 ≠ 401** comment in the source: 401 means "who are you?" (session dead → log out); 403 means "I know who you are, you're just not allowed" (a permission denial → do **not** log out). Conflating them logs admins out when they hit any forbidden resource.

**f) `fetchWithTimeout`.** Browser `fetch` has **no default timeout** — a stalled connection hangs the promise forever and the page spins its loading skeleton indefinitely. So we race it against an `AbortController`, and take care to respect a caller-supplied signal too. A request that never settles is worse than one that fails.

**g) `APIError`.** A custom `Error` subclass that digs the human-readable message out of whatever shape DRF returned (`error` / `detail` / `non_field_errors[0]` / first field error), so every `catch` block can just show `err.message`. **Normalize errors once, at the boundary.**

---

## 4. Pattern: Context — global state without prop-drilling

Problem: `isLoggedIn` is needed by the Navbar, the Cart page, the product card, the checkout button. Passing it down through eight layers of props ("prop drilling") is miserable and couples every intermediate component to data it doesn't use.

**Context** is React's built-in dependency injection: a provider puts a value at the top of the tree, and any descendant reads it directly.

The boilerplate — the same four steps in all four of our contexts:

```tsx
// 1. Create the channel
const CartContext = createContext<CartContextType | undefined>(undefined);

// 2. A custom hook that reads it — with a guard rail
export const useCart = () => {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error("useCart must be within CartProvider");
  return ctx;
};

// 3. A provider that owns the state and the operations
export const CartProvider = ({ children }) => {
  const [cart, setCart] = useState<CartItem[]>(...);
  const addToCart = async (item) => { ... };
  return <CartContext.Provider value={{ cart, addToCart, ... }}>{children}</CartContext.Provider>;
};

// 4. Wrap the app (App.tsx)
<AuthProvider><LanguageProvider><FavoritesProvider><CartProvider>...</CartProvider></FavoritesProvider></LanguageProvider></AuthProvider>
```

Two details worth calling out in an interview:

- **The `if (!ctx) throw` guard.** It converts a confusing runtime `undefined` crash deep in a child into an immediate, explicit "you forgot the provider." Also, thanks to that check, TypeScript narrows the return type from `CartContextType | undefined` to `CartContextType`, so consumers never need `?.`.
- **The provider nesting order encodes a dependency.** `CartProvider` sits *inside* `AuthProvider` because the cart calls `useAuth()` — it must clear itself on logout and refetch on login. Nesting order is not cosmetic.

We have four: **`AuthContext`** (session), **`CartContext`**, **`FavoritesContext`**, **`LanguageContext`**.

---

## 5. Pattern: Optimistic updates with rollback

The single most user-visible pattern in the app. In [CartContext.tsx](../Frontend/nidhi-brand-forge/src/context/CartContext.tsx):

```tsx
const updateQuantity = async (id, quantity, itemType, variantId) => {
  const previousCart = [...cart];                          // 1. snapshot
  setCart(prev => prev.map(i => match(i) ? { ...i, quantity } : i));  // 2. update UI NOW

  try {
    const response = await cartAPI.updateItem({...});      // 3. tell the server
    if (response.success) setCart(mapBackendToFrontend(response.items));  // 4. reconcile
    else { setCart(previousCart); toast.error(...); }      // 5. ROLL BACK
  } catch (e) {
    setCart(previousCart);                                 // 5. ROLL BACK
    toast.error(...);
  } finally { setIsLoading(false); }
};
```

**The idea:** the network takes 200–800ms. Waiting for it before updating the UI makes every "+" click feel broken. So we **assume success**, update the UI instantly, and undo it if the server disagrees.

Three things make it correct, and each is a question:
1. **Snapshot before mutating** (`previousCart`). You cannot roll back to a state you didn't keep.
2. **Roll back on *both* failure branches** — an HTTP error *and* a thrown exception (network down). Missing the second is the classic bug: the UI shows an item quantity that the server never accepted.
3. **Reconcile with the server's response, don't just keep your guess.** The server is authoritative — it may have clamped the quantity to available stock. We overwrite our optimistic guess with the truth. Optimistic UI is a *latency mask*, never a second source of truth.

**Immutability:** notice `[...cart]` and `{ ...i, quantity }` — we never write `cart[0].quantity = 5`. React decides whether to re-render by comparing object *references*; mutating in place leaves the reference identical, so React sees "nothing changed" and the screen doesn't update. **Always produce a new object/array.** This is the #1 React bug for newcomers and an extremely common interview question.

**Line identity:** `getCartKey(id, itemType, variantId)` → `"product-12-3"`. The same spice in 100g and 500g are *different* cart lines, so identity is the composite key, not the product id. Getting this wrong means adding the 500g pack silently bumps the 100g line.

---

## 6. Pattern: Data fetching — two approaches, and knowing when each is right

**A) `useEffect` + `useState` (most pages, e.g. [Products.tsx](../Frontend/nidhi-brand-forge/src/pages/Products.tsx)):**

```tsx
const [products, setProducts] = useState([]);
const [loading, setLoading]   = useState(true);
const [error, setError]       = useState("");

useEffect(() => {
  setLoading(true);
  productsAPI.getByCategory(selectedCategory)
    .then(data => setProducts(data.results || data || []))
    .catch(err => { console.error(err); setError(t('products.loadError')); })
    .finally(() => setLoading(false));
}, [selectedCategory]);   // ← the dependency array
```

**The dependency array is the whole pattern.** `[]` = run once on mount. `[selectedCategory]` = re-run whenever the category changes. Omit it entirely and the effect runs after *every* render — which sets state — which triggers a render — infinite loop. That's the classic `useEffect` interview trap.

Then the three-state render, which every data-driven page repeats:
```tsx
if (loading) return <Loader2 className="animate-spin" />;
if (error)   return <p>{error}</p>;
return products.map(p => <ProductCard key={p.id} product={p} />);
```
**Loading / error / success are three real states.** Rendering `products.map` while `products` is still `[]` gives an empty page that looks like a bug rather than a wait.

Note also the **error-masking** in the catch: the raw backend error is `console.error`'d, but the user sees a friendly translated string. Never leak backend validation text to customers.

**B) TanStack Query (`useQuery`) — used where the extra machinery pays for itself,** e.g. [SearchAutocomplete.tsx](../Frontend/nidhi-brand-forge/src/components/SearchAutocomplete.tsx):

```tsx
const [debouncedQuery, setDebouncedQuery] = useState("");
useEffect(() => {
  const timer = setTimeout(() => setDebouncedQuery(query.trim()), 250);
  return () => clearTimeout(timer);      // ← cleanup: cancel the previous timer
}, [query]);

const { data } = useQuery({
  queryKey: ["search", debouncedQuery],  // cache identity
  queryFn:  () => searchAPI.suggest(debouncedQuery),
  enabled:  debouncedQuery.length > 1,   // don't fire on empty input
});
```

Two patterns stacked:

- **Debouncing.** Typing "garam masala" is 12 keystrokes = 12 API calls. The `setTimeout` + `clearTimeout` pair means a request only fires 250ms *after* typing stops. **The `return () => clearTimeout(timer)` is the effect cleanup function** — React runs it before the next effect and on unmount. Without it, every keystroke leaves a live timer and you get all 12 calls anyway. Cleanup functions are the other half of `useEffect` and are always worth mentioning.

- **`useQuery`.** Server data is not really "state" — it's a *cached copy* of something that lives elsewhere. TanStack Query models that properly: keyed cache, dedup of identical in-flight requests, background refetching, stale-time, plus `isLoading`/`error` for free. `queryKey: ["search", debouncedQuery]` means each search term is cached separately, so retyping a previous term is instant with zero network.

> **Interviewer:** *"Why not use React Query everywhere?"*
> **Honest answer:** we should, mostly — it would delete the hand-rolled loading/error triplet from every page. It earns its keep most where caching and dedup matter (autocomplete, assistant), which is why it's there first. Knowing *why* the manual approach is worse — no cache, no dedup, no refetch, no request cancellation on unmount → possible "set state on unmounted component" — is the point of the question.

---

## 7. Pattern: shadcn/ui + CVA — variants as data

Buttons come in six looks and four sizes. The naive approach is `<Button primary large />` and a thicket of `if`s inside. Instead, **class-variance-authority** turns styling into a lookup table:

```tsx
const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-full font-semibold transition-all active:scale-95 disabled:opacity-50",  // base: always applied
  {
    variants: {
      variant: {
        default:     "bg-primary text-primary-foreground shadow-lg hover:brightness-110",
        outline:     "border-2 border-primary text-primary bg-transparent hover:bg-primary/5",
        ghost:       "hover:bg-primary/10 hover:text-primary",
        destructive: "bg-destructive text-destructive-foreground",
      },
      size: { default: "h-10 px-5", sm: "h-9 px-4", lg: "h-11 px-8", icon: "h-10 w-10" },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

<Button variant="outline" size="lg">Add to cart</Button>
```

- **Tailwind** = utility CSS classes in the markup (`rounded-full`, `h-10`). No separate stylesheet, no naming things, no dead CSS — the styles live where they're used and are deleted when the component is.
- **CVA** = the variant→classes map. And because of `VariantProps<typeof buttonVariants>`, **TypeScript autocompletes the variant names and rejects typos.** The design system is type-checked.
- **`cn()`** (`twMerge(clsx(...))`) merges class lists *and resolves Tailwind conflicts*: `cn("px-5", "px-8")` → `"px-8"`, last wins. Plain string concatenation would emit both and let CSS specificity decide arbitrarily. This is why every component ends with `className={cn(variants({...}), className)}` — it lets a caller override any single style without `!important`.
- **`asChild` + Radix `Slot`.** `<Button asChild><Link to="/cart">Cart</Link></Button>` renders an `<a>` that *looks* like a button. This is **composition over configuration** — instead of adding an `href` prop and branching, the component hands its styles and behavior to whatever child you give it. Big accessibility win: a link stays a link to a screen reader.
- **shadcn/ui isn't a dependency** — the components are *copied into* `src/components/ui/`. You own the source and can edit it. Radix underneath supplies the unstyled, fully accessible behavior (focus traps, keyboard nav, ARIA) that is genuinely hard to get right by hand.

---

## 8. Pattern: Routing and page composition

```tsx
<BrowserRouter>
  <Routes>
    <Route path="/" element={<Index />} />
    <Route path="/products/:id" element={<ProductDetail />} />
    <Route path="/wishlist" element={<Navigate to="/favorites" replace />} />
    <Route path="*" element={<NotFound />} />
  </Routes>
</BrowserRouter>
```

- **Client-side routing:** clicking a `<Link>` swaps the component and pushes a history entry — no server round trip, no white flash.
- `:id` is a **URL parameter**, read inside the page with `useParams()`. Our backend accepts either a numeric id or a slug at the same endpoint, so `/products/garam-masala` and `/products/12` both work — good for SEO and for old links.
- `<Navigate replace>` is a **redirect as a component** — declarative, and `replace` keeps the dead URL out of the back-button history.
- `path="*"` is the catch-all 404. Always last.
- **`useSearchParams`** keeps filter state in the URL (`/products?category=whole-spices`) rather than only in React state. That means a filtered view is **shareable, bookmarkable, and survives a refresh**. "Where should this piece of state live?" — if a user would expect to be able to send someone the link, it belongs in the URL.

**Deployment consequence worth knowing:** because the client owns routing, the server must return `index.html` for *every* path, or a hard refresh on `/products/garam-masala` 404s. That's the SPA-fallback rule in the nginx config.

---

## 9. Pattern: Custom hooks — reusable stateful logic

Any function starting with `use` that calls other hooks is a **custom hook**. It's how you share *behavior* (as opposed to markup, which you share with components).

We have `useAuth`, `useCart`, `useFavorites` (context readers), plus `useGeolocation`, `useVoiceInput`, `usePageTracking`, `use-mobile`.

`usePageTracking()` is a nice one-liner example: called once in `AnimatedRoutes`, it watches `useLocation()` and fires an analytics event on every route change. One line in the app, all the logic encapsulated, zero markup.

**The rule of hooks that gets asked:** hooks may only be called at the **top level** of a component or another hook — never inside an `if`, a loop, or a callback. React identifies hooks by *call order*, so a conditional hook shifts the order between renders and React reads the wrong state slot. Say "call order" and you've answered it.

---

## 10. Pattern: i18n — no hardcoded user-facing strings

```tsx
const { t } = useTranslation();
<h1>{t('products.title')}</h1>
setError(t('products.loadError'));
```

Text lives in `src/i18n/locales/*.json`, keyed. The chosen language is stored in `localStorage` under `site_lang` — and, crucially, **the same key is read by `getLangHeader()` in the API layer** and sent as an `X-Language` header, so the backend returns translated *product* names too (Django `modeltranslation`). UI strings and data strings stay in sync because they're driven by one value. That handshake — a frontend preference that has to reach the backend to be complete — is a good thing to be able to explain.

---

## 11. Cross-cutting: what the frontend must *never* be trusted for

The cart clamps quantity client-side (`MAX_ITEM_QUANTITY`, `clampQuantity`) — and the backend clamps it *again*, independently.

This is not redundancy, it's a division of responsibility:
- The client-side check is **UX**: instant feedback, no wasted round trip.
- The server-side check is **security**: anyone can open devtools or `curl` the API directly and skip your React app entirely.

**Client-side validation is not a security control.** If an interviewer asks why the same limit exists in both places, that's the sentence they're waiting for.

---

## 12. Pattern: Runtime config for a static bundle

A built React app is just static files. Vite replaces every `import.meta.env.VITE_*`
with its value **while building**, so the number is frozen into the JavaScript.
To change it you would have to rebuild the image.

This app avoids that with a small bridge, [src/config/runtimeEnv.ts](../Frontend/nidhi-brand-forge/src/config/runtimeEnv.ts):

```ts
export function readEnv(viteName: string): string | undefined {
  const key = viteName.replace(/^VITE_/, "");
  const r = runtime?.[key];                       // window.APP_CONFIG, written at container start
  if (r != null && r !== "") return r;            // runtime value wins
  const b = import.meta.env[viteName];            // else the value baked at build
  return b != null && b !== "" ? b : undefined;
}
```

When the container starts, a shell script
([docker-entrypoint.d/40-runtime-config.sh](../Frontend/nidhi-brand-forge/docker-entrypoint.d/40-runtime-config.sh))
writes `config.js` from the container's environment variables. That file sets
`window.APP_CONFIG`. `readEnv` prefers it and falls back to the baked value, so
`npm run dev` still works with a plain `.env`.

Two rules come out of this, and both were learned the hard way:

- **`API_URL` stays relative (`/api`).** The site is served on more than one
  domain. A relative URL always calls the domain the page was loaded from, so the
  auth cookie (which is `SameSite=Lax`) is sent. An absolute URL makes every other
  domain cross-site and the login silently stops working.
- **An empty runtime value falls back to the baked one.** So a number can be
  "right" in the backend and still wrong in the browser. That is exactly how a
  ₹499 cart showed "free delivery" and was then billed for delivery — see
  [lessons/02](lessons/02_build_time_vs_runtime_config.md).

**Interview line:** "A SPA has no environment at runtime, so I generate a small
`config.js` when the container starts and read it before the baked value. One
image, many deployments."

---

## 13. The admin panel: same patterns, different client

The admin panel (`Admin Panel/e-commerce-command-center`) is a second React app.
It uses the same ideas with one different tool: **axios with interceptors**
instead of a hand-written `fetch` wrapper
([src/api/axiosInstance.ts](../Admin%20Panel/e-commerce-command-center/src/api/axiosInstance.ts)).

| Concern | Storefront (`authFetch`) | Admin panel (axios) |
|---|---|---|
| Cookies sent | `credentials: "include"` | `withCredentials: true` |
| CSRF header | set inside `authFetch` | request interceptor |
| 401 → refresh → replay | inside `authFetch` | response interceptor, `_retried` flag |
| One refresh for many 401s | `refreshPromise` | `refreshInFlight` |
| Session is gone | DOM event `auth:unauthorized` | DOM event `admin:session-expired` |
| Which session | customer cookies | header `X-Admin-Panel: 1` → admin cookies |

An **interceptor** is a function axios runs on every request or every response.
It is the same Decorator idea as `authFetch`, just registered with the library
instead of wrapped around it.

The header `X-Admin-Panel: 1` matters. The backend keeps two separate sessions:
`access_token`/`refresh_token` for the shop and `admin_access_token`/`admin_refresh_token`
for the panel. The header tells the backend which cookie to read
(`users/authentication.py`), and the admin token must carry `scope: admin` and
belong to a staff user. So logging out of the shop does not log you out of the
panel, and the other way round.

The session-expired event exists for a reason written in the file: the
interceptor must never do `window.location = '/login'`. That is a full page
reload, and the admin would lose their filters and open dialogs. It fires an
event, and `AuthContext` navigates through the router.

**Interview line:** "Both apps solve the same five problems at the API
boundary: cookies, CSRF, silent refresh, one refresh at a time, and one way out
of a dead session. One does it with a fetch wrapper, the other with axios
interceptors."

---

## Quickfire recap

| Pattern | Where | The one-line answer |
|---|---|---|
| Declarative rendering | everywhere | Describe the UI for a state; React does the DOM diff |
| Interfaces as contract | `lib/api/*.ts` | Mirrors the serializer; refactors become safe |
| Facade / Repository | `lib/api/` | Components ask *what*, never *how* |
| Decorator (`authFetch`) | `lib/api/config.ts` | CSRF, timeout, refresh, error-normalizing — once |
| Single-flight refresh | `refreshPromise` | 6 parallel 401s → 1 refresh, not 6 |
| Observer bridge | `forceLogout()` | Non-React module notifies React via a DOM event |
| HttpOnly cookie auth | `credentials: "include"` | No token in JS ⇒ XSS can't steal it |
| Context = DI | `context/*.tsx` | Global state without prop-drilling; guard the provider |
| Optimistic update + rollback | `CartContext` | Snapshot → apply → reconcile or revert |
| Immutability | `{...i}`, `[...cart]` | New reference or React won't re-render |
| Dep array | `useEffect(fn, [x])` | Controls *when*; omit it and you loop forever |
| Cleanup function | `return () => clearTimeout` | The other half of every subscription/timer |
| Debounce | `SearchAutocomplete` | 12 keystrokes → 1 request |
| `useQuery` | search, assistant | Server data is a cache, not state |
| CVA + `cn()` | `components/ui/` | Variants as a typed lookup table; conflicts resolved |
| `asChild` / Slot | `Button` | Composition over configuration; keeps `<a>` an `<a>` |
| URL as state | `useSearchParams` | Shareable, bookmarkable, refresh-proof |
| Trust boundary | limits in both tiers | Client validation is UX; server validation is security |
