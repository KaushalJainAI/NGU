# Admin Panel Architecture

This document explains the design principles and patterns specific to the admin panel.

---

## Design Principles

### 1. CRUD-Centric Pages
Each page manages one resource type with consistent patterns:
- **List view** — table with actions
- **Create dialog** — form modal
- **Edit dialog** — form modal with pre-filled data
- **Delete/Toggle** — inline actions

### 2. Optimistic Updates
Status toggles update the UI immediately, then sync to the backend:
```typescript
// Update UI first
setProducts(prev => prev.map(p =>
  p.id === id ? { ...p, is_active: !p.is_active } : p
));

// Then sync to backend
await updateProduct(id, { is_active: !isActive });
```

### 3. Admin-Only Access
All routes require `is_staff=True`. Auth check happens at:
- **Frontend**: Route guard redirects to `/login`
- **Backend**: `IsAdminUser` permission class on all write endpoints

---

## Application Flow

### Page Load Pattern

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│  Route  │────▶│  Page   │────▶│  Fetch  │────▶│  Table  │
│         │     │  Init   │     │  Data   │     │ Render  │
└─────────┘     └─────────┘     └─────────┘     └─────────┘
```

### CRUD Pattern

```
┌─────────────────────────────────────────────────────────────┐
│                        Table View                           │
├─────────────────────────────────────────────────────────────┤
│  [+ Add New]                                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Name    │ Price  │ Status │ Actions              │   │
│  │ Item 1  │ ₹100   │ Active │ [Edit] [Toggle]      │   │
│  │ Item 2  │ ₹200   │ Draft  │ [Edit] [Toggle]      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
         │                               │
         ▼                               ▼
   ┌──────────┐                   ┌──────────┐
   │  Create  │                   │   Edit   │
   │  Dialog  │                   │  Dialog  │
   └──────────┘                   └──────────┘
```

---

## Key Implementation Details

### 1. Auth Context

Same cookie-based auth as the customer frontend, with admin-specific checks:
- Login validates `is_staff` on the backend; non-staff accounts are rejected
- JWTs are stored in **HttpOnly cookies** — the Axios instance sends them automatically via `withCredentials: true`
- On 401, the Axios interceptor clears `admin_token`/`refresh_token` from localStorage and redirects to `/login` (unless already on the login page, to avoid a refresh loop)
- On 403, localStorage is also cleared but no redirect is forced

### 2. Products: Gallery Image Upload

Products support a primary image and multiple gallery images:
```typescript
const [galleryImages, setGalleryImages] = useState<ProductImage[]>([]);
const [newGalleryImages, setNewGalleryImages] = useState<File[]>([]);

// On submit, product saved first, then gallery images uploaded individually
await createProductImage(productId, file, altText);
```

**Upload flow:**
1. User selects multiple images
2. Images previewed locally
3. On form submit, product saved first
4. Gallery images uploaded individually
5. Existing images deleted via API

### 3. Order Status Management

Orders follow this workflow:
```
PENDING → CONFIRMED → PROCESSING → SHIPPED → (DELIVERING) → DELIVERED
```
`CANCELLED` is a terminal branch, not the end of the chain. `DELIVERING` is an
intermediate state used by some delivery integrations (between SHIPPED and DELIVERED).
Admin updates status via a dropdown in the order detail view.

### 4. Homepage Sections

The **Sections** page (`/sections`) manages homepage sections and the products placed
in each (`position` on `ProductSectionPlacement` for ordering). Products can also be
placed into sections from the product dialog.

### 5. Policy Pages (Shipping/Return — no panel page yet)

The backend `PolicyViewSet` supports PUT-upsert (saving a non-existent policy
auto-creates it), but this panel has **no** dedicated policy-editing page — policies
are currently edited in the Django admin.

### 6. Conversations (Chat Support)

The **Conversations** page (`/conversations`) is the admin inbox for the unified AI + human chat system.

**Data sources:**
- `GET /api/assistant/conversations/admin/` — lists all threads (supports `?needs_human=true` and `?status=resolved` filters)
- `GET /api/assistant/conversations/{id}/messages/` — full message history for a thread
- `POST /api/assistant/conversations/{id}/admin-reply/` — send an admin message into a thread
- `PATCH /api/assistant/conversations/{id}/` — update thread status (`active`/`resolved`/`archived`) or assignment

**Polling:**
- Thread list refreshes every **10 seconds**
- Open thread messages refresh every **5 seconds**

**Filter tabs:** All / Needs Human / Resolved — mapped to `?needs_human` and `?status` query params.

**Message roles displayed:** `user` (customer), `assistant` (AI), `admin` (human staff reply), `tool` (internal agent step — shown collapsed).

```typescript
// Marking a thread resolved
await patchConversation(convId, { status: 'resolved' });
setConversations(prev => prev.map(c =>
  c.conversation_id === convId ? { ...c, status: 'resolved' } : c
));
```

### 8. Dashboard Caching

Dashboard stats are cached server-side for ~60 seconds (Redis `ngu:dashboard:*` key) to
avoid expensive aggregations on every page load.

---

## Data Fetching (`hooks/useAdminData.ts`)

Every list page fetches through **`useAdminData(key, fetcher)`** — a thin wrapper over
React Query. Do not hand-roll `useState` + `useEffect` fetches in a page; they were
removed because they refetched from scratch on every navigation and blanked the screen
while doing it.

```typescript
const { data, isInitialLoading, refreshing, refetch } =
  useAdminData(['products'], () => getProducts().then(r => r.data));
```

**The two loading states are not interchangeable:**

| State | Meaning | What to render |
|-------|---------|----------------|
| `isInitialLoading` | nothing cached yet | `<TableSkeleton />` in place of the table |
| `refreshing` | revalidating over data already on screen | dim the table (`opacity-60`) — **never unmount it** |

Returning `<div>Loading...</div>` for the whole page is the anti-pattern this replaced:
it unmounts the search box mid-keystroke, so the input loses focus and the page reads as
a spontaneous reload.

**Query defaults** (`App.tsx`): `staleTime` 30 s, `gcTime` 5 min, `refetchOnWindowFocus`
off, one retry. A shared `QueryCache.onError` toasts load failures once, and only when
there is no cached data to fall back on.

**Cache keys are shared across pages** — `['products']` is used by Products, Sections,
Combos and Recycle Bin, so opening one after another costs no request.

⚠️ **Because data is now cached, mutations must invalidate what they affect.** Use
`useInvalidate()` and list every key the write touches, not just the current page's:

```typescript
// Saving a product also changes section placements, bulk rows, low-stock counts
invalidate(['products'], ['sections'], ['bulk-products'], ['dashboard']);
```

For single-field toggles, patch the cache directly with `queryClient.setQueryData` so the
row updates instantly instead of refetching the list.

**Searches** debounce through `useDebouncedValue` and put the query in the cache key, so
responses for a query the admin has already typed past can never overwrite newer results.

---

## Routing & Session

- **All pages below the layout are `lazy()`-loaded** (`App.tsx`), each behind a
  `<RouteFallback />` Suspense boundary that stays invisible for 150 ms so a cached chunk
  never flashes a skeleton. Keep new pages lazy — the main bundle is ~435 kB and the one
  eager exception is Dashboard (the landing screen).
- **Never navigate with `window.location`.** A 401 is handled in
  `api/axiosInstance.ts`: it silently calls `/auth/token/refresh/` (single-flight) and
  replays the original request. Only when that fails does it dispatch
  `SESSION_EXPIRED_EVENT`, which `AuthContext` turns into a router navigation. A hard
  assignment to `window.location` throws away filters, dialogs and scroll position — that
  is what made the panel appear to reload itself once the 1-hour access token expired.

---

## Page Responsibilities

| Page | Manages |
|------|---------|
| Dashboard | Stats overview, recent orders |
| Insights | Sales / funnel / search / customer / anonymous-traffic analytics (recharts) |
| Products | Product CRUD + gallery images + variants + homepage-section placement; client-side search/filter/sort |
| Bulk Edit | Spreadsheet-style bulk product edits + CSV import/export |
| Combos | Combo CRUD + product items |
| Categories | Category CRUD (dedicated page) |
| Sections | Homepage section CRUD + product placement/ordering |
| Orders | Order list (server-side search/filter/sort/pagination incl. date range), status updates, invoice + packing-slip download, delivery-bill upload, Razorpay payment-instrument details |
| Reviews | Review moderation — hide/unhide (`is_hidden`) |
| Customers | Customer list + per-customer detail (orders, spend) |
| Recycle Bin | Soft-deleted orders; restore |
| Coupons | Discount code CRUD: % or flat ₹, minimum order, usage cap, and optional restriction to a single customer |
| Conversations | All customer chat threads (AI + human); admin reply, status management |
| Contact | Contact form submissions |
| Admin Info | Admin account settings |

> Homepage **policy pages** are still managed in the Django admin (no panel page).
> A **global search** (`components/GlobalSearch.tsx` → `GET /api/admin-search/`) spans
> catalog/orders/customers from the top bar, and an **ask-assistant** widget
> (`api/assistant.ts` → `POST /api/assistant/admin-chat/`) answers business-data
> questions from a read-only reporting persona.

---

## Form Patterns

### FormData for File Uploads

```typescript
const buildFormData = () => {
  const form = new FormData();
  form.append('name', formData.name);
  form.append('price', String(formData.price));
  if (imageFile) form.append('image', imageFile);
  return form;
};
```

### Combo Items as JSON

Combo items are serialized as JSON within FormData. `variant` — the packaging
SIZE bundled — is the real key; `product` is sent alongside for older backends.
```typescript
form.append('items', JSON.stringify(
  comboItems.map(item => ({
    product: item.productId,
    variant: item.variantId,
    quantity: item.quantity,
  }))
));
```

**No `price` is posted.** A combo's MRP is derived server-side as the sum of its
component sizes' prices, so the form shows it read-only (`computedMrp`, which
must sum `variant.price` — not `product.price`, a mirror of whichever size is
default — or the displayed figure won't match what the API returns). The admin
sets only `discount_price`, the actual selling price, validated client-side to
be below the MRP. There is no combo GST field: tax is charged per component at
its own product's rate.

---

## Error Handling

### Toast Notifications
```typescript
try {
  await saveProduct(data);
  toast({ title: 'Success', description: 'Product saved' });
} catch {
  toast({ title: 'Error', variant: 'destructive' });
}
```

### Form Validation
Client-side validation runs before submit:
```typescript
if (!formData.name.trim()) {
  toast({ title: 'Error', description: 'Name is required' });
  return;
}
```

---

## Extending the Admin Panel

### Adding a New Resource Page

1. Create API functions in `src/api/resource.ts`
2. Create page component `src/pages/Resources.tsx`
3. Add route in `App.tsx`
4. Add sidebar link if needed

### Adding a New Field to an Existing Resource

1. Add to the TypeScript interface
2. Add to form state
3. Add form input in dialog
4. Add to `buildFormData()` if applicable
5. Add column to the table (optional)
