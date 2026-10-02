# NGU Improvement Plan — admin sessions, /panel routing, courier link, dashboard, GST, basic accounts

Written 2026-10-01. This file is the full instruction set for the implementer.
Do the work packages (WP) in the order given. Each WP is independent unless it
says "Needs WPn".

---

## 0. Rules for the implementer (read first, apply to every WP)

**Repos.** `NGU/` is not a git repo. There are three separate repos:

| Short name | Path |
|---|---|
| Backend | `Backend/` |
| Panel | `Admin Panel/e-commerce-command-center/` |
| Storefront | `Frontend/nidhi-brand-forge/` |

Create a branch named `improvement-plan` in each repo you touch. Make one commit
per WP per repo. Do not push. Do not deploy. Do not SSH anywhere.

**Never touch production.** Do not run anything against `nidhigrahudyog.com`,
`nidhimasala.com`, `13.235.238.99` or `13.201.33.243`. Never load
`Backend/.env.local` (it points at a remote database).

**How to check your work.**

- Backend: `cd Backend && venv/Scripts/python.exe -m pytest -q`
  Expected before you start: about 1280 passed, 8 skipped. Two tests,
  `orders/test_concurrency.py::test_G4` and `test_G5`, fail on SQLite with
  "database table is locked". That is known. Any other failure is yours.
- Panel and Storefront: `npx tsc --noEmit` and `npm run build`, both must pass.
- To run the stack locally and click through it, follow
  `.claude/skills/verify/SKILL.md`.

**Code rules.**

1. Money is always `Decimal`, rounded with `.quantize(Decimal('0.01'))`. Never use `float` for arithmetic.
2. "Today" is `timezone.localdate()`, never `date.today()` or `timezone.now().date()`.
3. Date-range filters use `range_filter` from `Backend/spices_backend/timeranges.py`, e.g. `Order.objects.filter(**range_filter('created_at', start, end))`. It also works on related paths such as `'invoice__issued_at'`.
4. New migrations are generated with `venv/Scripts/python.exe manage.py makemigrations <app>`. Never edit an existing migration file.
5. Every new or changed HTTP route must be added to `Backend/docs/API.md` in the same commit.
6. Every new Panel string goes in BOTH `src/i18n/locales/en/*.json` and `src/i18n/locales/hi/*.json`. Storefront strings go in `src/i18n/locales/en.json` and `hi.json` and are called as `t('key', 'English default')`.
7. Match the comment style and naming of the file you are editing.

**Do NOT change any of these** (they are waiting on the owner's accountant):

- any product `tax_rate` or `hsn_code`;
- how delivery is taxed (`SHIPPING_CHARGE_NET`, `SHIPPING_TAX_RATE`, SAC 9968);
- the name `SHIPPING_CHARGE_NET` (do not rename it back to `SHIPPING_CHARGE`);
- the disabled `refund.processed` webhook branch in `payments/views.py`.

**If the code you find does not match what this plan describes, stop that WP and
report the difference. Do not improvise.**

**After each WP, report:** files changed, tests added, and the last lines of the
pytest / tsc / build output.

---

## WP1 — Backend: separate admin session cookies, admin Google login, logout

### Why

Today the Panel and the Storefront share the cookies `access_token` and
`refresh_token`. Logging in or out on one changes the other. Also, there is **no
logout route in the backend at all**: both apps POST `/api/auth/logout/`, get a
404, and ignore it, so the HttpOnly cookies are never cleared.

### Design (do exactly this)

- Customer cookies keep their names: `access_token`, `refresh_token`.
- Admin cookies are new: `admin_access_token`, `admin_refresh_token`.
- The Panel sends the header `X-Admin-Panel: 1` on every API request.
- When that header is present, the backend reads ONLY the admin cookie. When it
  is absent, the backend reads ONLY the customer cookie.
- Admin tokens carry the JWT claim `scope = "admin"` and are issued only to
  users with `is_staff=True`.
- Do not change any `permission_classes` anywhere. Only authentication changes.

### Step 1 — `Backend/spices_backend/settings.py`

Change the CORS header line to:

```python
CORS_ALLOW_HEADERS = list(_cors_default_headers) + ['x-language', 'x-admin-panel']
```

### Step 2 — `Backend/users/authentication.py`

Replace the `authenticate` method. Keep `enforce_csrf` as it is.

```python
from rest_framework.exceptions import AuthenticationFailed

ADMIN_ACCESS_COOKIE = 'admin_access_token'
ADMIN_REFRESH_COOKIE = 'admin_refresh_token'
ADMIN_SCOPE = 'admin'


def is_admin_panel_request(request):
    """True when the request came from the admin panel SPA."""
    return request.META.get('HTTP_X_ADMIN_PANEL') == '1'


class CookieJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                return None
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token

        admin = is_admin_panel_request(request)
        cookie_name = ADMIN_ACCESS_COOKIE if admin else 'access_token'
        raw_token = request.COOKIES.get(cookie_name) or None
        if raw_token is None:
            return None

        self.enforce_csrf(request)
        validated_token = self.get_validated_token(raw_token)
        user = self.get_user(validated_token)
        if admin and (validated_token.get('scope') != ADMIN_SCOPE or not user.is_staff):
            raise AuthenticationFailed('Admin session required.')
        return user, validated_token
```

### Step 3 — `Backend/users/views.py`

1. Give the two cookie helpers a `key` argument, defaulting to the current names:
   `set_access_cookie(response, access_token, key='access_token')` and
   `set_refresh_cookie(response, refresh_token, key='refresh_token')`.
2. Add:

```python
def clear_auth_cookies(response, access_key, refresh_key):
    for key in (access_key, refresh_key):
        response.delete_cookie(key, samesite=settings.AUTH_COOKIE_SAMESITE)


def _blacklist_quietly(raw_refresh):
    """Invalidate a refresh token; never raise (logout must always succeed)."""
    if not raw_refresh:
        return
    try:
        RefreshToken(raw_refresh).blacklist()
    except Exception:  # noqa: BLE001
        pass


def admin_tokens_for(user):
    refresh = CustomTokenObtainPairSerializer.get_token(user)
    refresh['scope'] = ADMIN_SCOPE          # set BEFORE reading .access_token
    return refresh, refresh.access_token
```

   (`RefreshToken` is `rest_framework_simplejwt.tokens.RefreshToken`.)

3. Move the Google token checks out of `GoogleLogin.post` into a helper so both
   Google views share them. The helper returns the verified, lower-cased email
   and the `idinfo` dict, or raises `ValueError`:

```python
def verify_google_id_token(token):
    client_id = settings.SOCIALACCOUNT_PROVIDERS['google']['APP']['client_id']
    idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
    email = (idinfo.get('email') or '').strip().lower()
    if not email:
        raise ValueError('Email not provided by Google')
    if idinfo.get('email_verified') not in (True, 'true'):
        raise ValueError('Google account email is not verified')
    return email, idinfo
```

   `GoogleLogin` must keep returning the same status codes and messages as now
   (all tests in `users/test_google_login.py` must still pass unchanged). Also
   add `authentication_classes = []` to `GoogleLogin`, so a stale cookie cannot
   block a login.

4. Add five views. Every one has `permission_classes = [AllowAny]` and
   `authentication_classes = []`.

| View | Route | Behaviour |
|---|---|---|
| `LogoutView` | `POST /api/auth/logout/` | Blacklist the `refresh_token` cookie quietly, clear `access_token` + `refresh_token`, return `{'success': True}`. Must NOT touch admin cookies. |
| `AdminLoginView` | `POST /api/auth/admin/login/` | Throttle `LoginRateThrottle`. Validate `{email, password}` with `CustomTokenObtainPairSerializer(data=request.data)` and `is_valid(raise_exception=True)`; the user is `serializer.user`. If `not user.is_staff`: return 401 `{'detail': 'Invalid credentials or not an admin account.'}` and set no cookies. Otherwise set admin cookies from `admin_tokens_for(user)` and return `{'success': True, 'user': UserSerializer(user).data}`. Never put tokens in the body. |
| `AdminGoogleLoginView` | `POST /api/auth/admin/google/` | Throttle `LoginRateThrottle`. Token comes from `request.data['id_token']` (also accept `access_token`). Missing → 400. `verify_google_id_token` raising `ValueError` → 401 `{'detail': 'Invalid Google token'}`. Then `User.objects.filter(email__iexact=email, is_staff=True, is_active=True).first()`. None → 403 `{'detail': 'This Google account is not an admin of this store.'}`. **Never create a user here.** Found → same success response as `AdminLoginView`. |
| `AdminTokenRefreshView` | `POST /api/auth/admin/token/refresh/` | Read the `admin_refresh_token` cookie. Missing → 401. Build `RefreshToken(raw)`; on `TokenError` → 401. If `token.get('scope') != ADMIN_SCOPE` → 401. If no active staff user has `pk == token['user_id']` → clear admin cookies and 401. Then run `TokenRefreshSerializer(data={'refresh': raw})`, `is_valid(raise_exception=True)` (catch `TokenError` → 401), set `admin_access_token` from `data['access']` and, if present, `admin_refresh_token` from `data['refresh']`. Return `{'success': True}`. |
| `AdminLogoutView` | `POST /api/auth/admin/logout/` | Blacklist the `admin_refresh_token` cookie quietly, clear the two admin cookies, return `{'success': True}`. Must NOT touch customer cookies. |

### Step 4 — `Backend/users/serializers.py`

In `UserSerializer.Meta`, add `'is_staff'` to `fields` and to `read_only_fields`.

### Step 5 — `Backend/spices_backend/urls.py`

Add the five routes next to the other `api/auth/` routes, using the exact paths
in the table above.

### Step 6 — tests: new file `Backend/users/test_admin_session.py`

Use DRF `APIClient`. Pass the header as `HTTP_X_ADMIN_PANEL='1'`. Mock Google the
same way `users/test_google_login.py` does. Required tests:

1. Staff admin login returns 200, sets `admin_access_token` and `admin_refresh_token`, and does NOT set `access_token`.
2. Non-staff admin login returns 401 and sets no cookie.
3. With header + admin cookie, `GET /api/dashboard/actions/` returns 200.
4. With header + only a customer `access_token` cookie of a staff user, `GET /api/dashboard/actions/` is refused (401 or 403).
5. Without the header + only the admin cookie, `GET /api/auth/profile/` returns 401.
6. A customer token (no `scope` claim) placed in `admin_access_token`, with the header, returns 401.
7. `POST /api/auth/logout/` clears the customer cookies and leaves the admin cookies; `POST /api/auth/admin/logout/` does the reverse.
8. Admin refresh returns 200 and the new access token still has `scope == 'admin'`.
9. Admin refresh with a customer refresh token in the admin cookie returns 401.
10. Admin refresh after the user's `is_staff` is set to False returns 401.
11. Admin Google login: staff email → 200 + admin cookies; unknown email → 403 and `User.objects.count()` unchanged; unverified email → 401.
12. `GET /api/auth/profile/` includes `is_staff`.

### Done when

All existing tests pass, the 12 new tests pass, and `API.md` + `Backend/docs/AUTH.md` describe the new routes and cookies.

---

## WP2 — Panel: use the admin session, add Google sign-in, block non-admins

Needs WP1. All Panel HTTP goes through `src/api/axiosInstance.ts` (checked:
there is no raw `fetch()` in the Panel), so the header is added in one place.

### Step 1 — `src/api/axiosInstance.ts`

1. Add `'X-Admin-Panel': '1'` to the default `headers` of `axios.create`.
2. In `refreshSession`, call `/auth/admin/token/refresh/` and pass
   `{ withCredentials: true, headers: { 'X-Admin-Panel': '1' } }`.
3. Replace the `isAuthCall` test. It currently matches any URL containing
   `/auth/`, which wrongly includes `/auth/profile/`, so an expired session is
   never refreshed on page load. New rule: `isAuthCall` is true only when the URL
   contains one of `/auth/admin/login/`, `/auth/admin/google/`,
   `/auth/admin/token/refresh/`, `/auth/admin/logout/`.

### Step 2 — `src/api/admin.ts`

- `login` posts to `/auth/admin/login/`.
- Add `googleLogin = (credential: string) => api.post('/auth/admin/google/', { id_token: credential })`.
- Add `is_staff: boolean` to `AdminInfo`.

### Step 3 — `src/contexts/AuthContext.tsx`

- In `initAuth` and after any login: treat the user as authenticated only if `response.data.is_staff === true`. Otherwise set `isAuthenticated` false.
- `logout` posts to `/auth/admin/logout/`.
- Add `loginWithGoogle(credential)` that calls `googleLogin`, then loads the profile, then navigates to `/dashboard`. Expose it on the context.

### Step 4 — Google button on `src/pages/Login.tsx`

- `npm install @react-oauth/google` (the Storefront already uses this package; copy its usage from `Frontend/nidhi-brand-forge/src/App.tsx` and its login page).
- Read the client id as: `window.APP_CONFIG?.GOOGLE_CLIENT_ID || import.meta.env.VITE_GOOGLE_CLIENT_ID || ''`.
- If the client id is empty, do not render the Google button at all.
- Wrap only the login page in `GoogleOAuthProvider`. On success call `loginWithGoogle(credentialResponse.credential)`.
- On a 403, show the toast text from the response `detail` field.

### Step 5 — runtime config and build

- `docker-entrypoint.d/40-runtime-config.sh`: change the default `API_URL` from `https://nidhimasala.com/api` to `/api`, and add `GOOGLE_CLIENT_ID: "${GOOGLE_CLIENT_ID:-}"` to the generated object.
- `public/config.js`: add the same `GOOGLE_CLIENT_ID` key with an empty string.
- `Dockerfile`: add `ARG VITE_GOOGLE_CLIENT_ID` and `ENV VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID}` beside the existing `VITE_API_URL` lines, and fix the comment that says the Panel has no Google sign-in.
- `NGU/docker-compose.prod.yml` and `NGU/docker-compose.yml`: under `admin-panel` → `environment`, add `- GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID:-}`.

### Step 6 — stop accidental jumps to the Storefront

- `src/pages/NotFound.tsx`: replace `<a href="/">` with `<Link to="/dashboard">` from `react-router-dom`.
- `index.html`: set `<title>Nidhi Masala — Admin</title>`, add `<meta name="robots" content="noindex, nofollow" />`, and change the two `/logo.png` meta image paths to `/panel/favicon.ico`.
- `src/components/AdminLayout.tsx`: add a visible "ADMIN" badge in the top bar so the Panel never looks like the Storefront.

### Done when

`npx tsc --noEmit` and `npm run build` pass, and locally: a staff user can log in
with password; a customer account is refused; logging in or out of the
Storefront in another tab does not change the Panel session, and the reverse.

---

## WP3 — nginx: make `/panel` robust

### Step 1 — `Frontend/nidhi-brand-forge/nginx.conf`

1. Delete both `upstream backend { … }` and `upstream admin_panel { … }` blocks.
2. Inside `server { … }`, directly under `index index.html;`, add:

```nginx
    # Docker's embedded DNS. With a variable in proxy_pass, nginx re-resolves the
    # container name at request time, so recreating the backend or admin-panel
    # container no longer needs `nginx -s reload`.
    resolver 127.0.0.11 valid=10s ipv6=off;
    set $backend_upstream http://backend:8000;
    set $admin_upstream http://admin-panel:80;

    # Redirects must stay relative: this server listens on plain :80 behind the
    # TLS-terminating host nginx, so an absolute redirect would say http://.
    absolute_redirect off;
```

3. In every location that proxies to the backend (`= /sitemap.xml`,
   `= /robots.txt`, `/api/`, `/admin/`, `^~ /static/`), replace the
   `proxy_pass http://backend/...;` line with exactly:
   `proxy_pass $backend_upstream;`
   (With a variable and no path, nginx forwards the original request path
   unchanged, which is what every one of these locations already did.)
4. Add this location directly above `location ^~ /panel/`:

```nginx
    # /panel without the trailing slash used to fall through to the storefront.
    location = /panel {
        return 301 /panel/;
    }
```

5. In `location ^~ /panel/`, keep the `rewrite` line and change
   `proxy_pass http://admin_panel;` to `proxy_pass $admin_upstream;`.
6. Do not touch the `/s3-media/` location.

### Step 2 — `Admin Panel/e-commerce-command-center/nginx.conf`

Add this location above `location /`. nginx drops inherited `add_header` lines
as soon as a location defines its own, so the four security headers are repeated:

```nginx
    # The HTML shell must never be cached, or an admin keeps running an old
    # bundle after a deploy. Hashed files under /assets/ stay cached for a year.
    location = /index.html {
        add_header Cache-Control "no-cache" always;
        add_header X-Robots-Tag "noindex, nofollow" always;
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-XSS-Protection "1; mode=block" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    }
```

Add the same block to the Storefront `nginx.conf` above its `location /`, but
without the `X-Robots-Tag` line.

### Step 3 — check

Run for each of the two files (PowerShell or Git Bash, from the folder holding it):

```bash
docker run --rm -v "$PWD/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:alpine nginx -t
```

Both must print `syntax is ok` and `test is successful`.

### Step 4 — docs

In `NGU/CLAUDE.md` and `NGU/DEPLOYMENT.md`, replace the "REQUIRED after any
deploy … `docker exec ngu-frontend nginx -s reload`" instruction with a note that
the frontend nginx now re-resolves upstreams itself (since this change) and the
reload is only needed for images built before it.

---

## WP4 — Courier name and tracking link in the shipping email

### Why

The owner ships with any courier, so the "your order has shipped" email must name
the courier and carry a clickable tracking link. Today it has only the tracking ID.

### Backend

1. `Backend/orders/models.py`, on `Order`, below `tracking_number`:

```python
    # Which courier carried the parcel, and where the customer can track it.
    # Free text + a pasted URL because the store ships with any provider.
    courier_name = models.CharField(max_length=60, blank=True, default='')
    tracking_url = models.URLField(max_length=500, blank=True, default='')
```

   Then `makemigrations orders`.

2. `Backend/orders/views.py`:
   - Add `'courier_name'` and `'tracking_url'` to `ADMIN_EDITABLE_FIELDS`.
   - In `update()`, BEFORE the `with transaction.atomic():` line, validate the URL
     if the key is present and non-empty: it must pass
     `URLValidator(schemes=['http', 'https'])`. If not, return 400
     `{'tracking_url': ['Enter a valid http(s) link.']}`. (Validate before the
     transaction; returning a 400 from inside it would commit earlier writes.)
   - Beside `old_tracking = …`, add `old_tracking_url = (order.tracking_url or '').strip()`.
   - Beside the existing `if 'tracking_number' in data:` block, add:

```python
            if 'courier_name' in data:
                order.courier_name = (data['courier_name'] or '').strip()[:60]
            if 'tracking_url' in data:
                order.tracking_url = (data['tracking_url'] or '').strip()
```

   - Replace the `tracking_added` calculation at the end of `update()` with:

```python
        new_tracking = (order.tracking_number or '').strip()
        new_tracking_url = (order.tracking_url or '').strip()
        tracking_added = (
            (bool(new_tracking) and new_tracking != old_tracking)
            or (bool(new_tracking_url) and new_tracking_url != old_tracking_url)
        )
```

3. `Backend/orders/serializers.py`: add `"courier_name"` and `"tracking_url"` right after `"tracking_number"` in the `fields` list of BOTH `OrderDetailSerializer` and `OrderListSerializer`.

4. `Backend/orders/emails.py`, in `send_order_status_email`, replace the
   `if tracking_added and tracking:` block that builds `parts` with:

```python
    tracking = (order.tracking_number or '').strip()
    courier = (getattr(order, 'courier_name', '') or '').strip()
    tracking_url = (getattr(order, 'tracking_url', '') or '').strip()
    if tracking_added and (tracking or tracking_url):
        parts.append("")
        if courier:
            parts.append(f"Shipped with: {courier}")
        if tracking:
            parts.append(f"Your tracking ID is: {tracking}")
        if tracking_url:
            parts.append(f"Track your parcel here: {tracking_url}")
        else:
            parts.append(
                "You can track your parcel on the courier partner's website "
                "using this tracking ID.")
```

   and change the subject condition to `if tracking_added and (tracking or tracking_url):`.

5. Tests (add to `Backend/orders/test_checkout_and_ops.py`, copying how the
   existing tracking-email test captures the email): the email body contains the
   courier name and the URL when all three fields are sent in one PATCH; a PATCH
   with `tracking_url: "javascript:alert(1)"` returns 400 and changes nothing;
   re-sending the same values sends no second email.

### Panel — `src/pages/Orders.tsx` and `src/api/orders.ts`

- Add `courier_name?: string` and `tracking_url?: string` to the `Order` type and to the update payload type.
- In the order dialog, next to the tracking number input, add two inputs: "Courier" (text) and "Tracking link" (type `url`).
- Use ONE Save button for all three. It must send all three fields in a SINGLE `updateOrder` call. (Two separate calls would send the customer two emails.)
- In the WhatsApp message builder near line 313, append the tracking link when it exists.

### Storefront — `src/pages/MyOrders.tsx` and `src/lib/api/orders.ts`

- Add the two fields to the order type.
- Where the tracking number is shown (near line 606), also show the courier name, and if `tracking_url` starts with `http://` or `https://`, a link "Track parcel" with `target="_blank"` and `rel="noopener noreferrer"`.

---

## WP5 — Dashboard rebuild

### Problems being fixed

- "Today's sales" counts online checkouts that have not been paid.
- The "Delivery today" tile is meaningless: courier cost is entered days later, so today's cost is almost always 0.
- A five-line GST breakdown sits on the landing page; it belongs on the GST page.
- No comparison with any earlier period, no average order value, no month-to-date.
- `GET /api/dashboard/` returns four totals the page never shows.
- The customer list computes GST from `orders__tax` only and misses delivery GST.

### Backend — `Backend/admin_panel/views.py`

1. Customer list: change `total_gst=Sum('orders__tax', filter=not_cancelled)` to
   `total_gst=Sum(F('orders__tax') + F('orders__shipping_tax'), filter=not_cancelled)` (import `F`).

2. In `DashboardViewSet.actions`, change the cache key to `'ngu:dashboard:actions:v2'`
   and add a helper for "real" orders. An online order is real only once it is
   paid; a COD order is real from placement:

```python
        ONLINE = ['ONLINE', 'razorpay']

        def real_orders(start, end):
            return (Order.objects
                    .filter(is_deleted=False, **range_filter('created_at', start, end))
                    .exclude(status='cancelled')
                    .exclude(payment_method__in=ONLINE,
                             payment_status__in=['pending', 'processing', 'failed', 'rejected']))
```

3. Add these keys to the response. Keep every existing key (old Panel builds read them).

| Key | Meaning |
|---|---|
| `today_sales` | `Sum(total_amount)` of `real_orders(today, today)` |
| `today_real_orders` | count of the same |
| `today_aov` | `today_sales / today_real_orders`, 2 decimals, `0` when no orders |
| `today_online_received` | part of `today_sales` where `payment_method in ONLINE` |
| `today_cod_booked` | part of `today_sales` where `payment_method == 'COD'` |
| `last_week_same_day_sales` | `today_sales` computed for `today - 7 days` |
| `today_sales_delta_pct` | percent change vs the line above, 1 decimal; `None` when the earlier value is 0 |
| `mtd_sales` | `real_orders(month_start, today)` total |
| `prev_mtd_sales` | same number of days from the start of the previous month (clamp the end day to that month's last day) |
| `mtd_sales_delta_pct` | percent change, same rule |
| `orders_unshipped_aged` | not deleted, status in `confirmed`/`processing`, created more than 48 hours ago, and (COD or `payment_status='paid'`) |
| `out_of_stock_count` | active products with `stock <= 0` |
| `invoices_missing` | not deleted, not cancelled, `invoice__isnull=True`, and (`payment_status` in `paid`/`refunded` OR status in `shipped`/`delivering`/`delivered`) |
| `failed_payments_today` | today's orders with `payment_method in ONLINE` and `payment_status` in `failed`/`rejected` |
| `unclassified_hsn_count` | `unclassified_products().count()` from `orders/gst_reports.py` |
| `top_products_7d` | top 5 `OrderItem.product_name` by `Sum(final_price)` over `real_orders(today-6, today)`; each `{name, units, revenue}` |

4. In `DashboardViewSet.list`: return 8 recent orders instead of 5 and add
   `paymentMethod` and `paymentStatus` to each row (extend `RecentOrderSerializer`).
   Leave the four unused totals in place.

5. Tests in `Backend/admin_panel/tests.py`: an unpaid ONLINE order is excluded
   from `today_sales` and a COD order is included; `today_sales_delta_pct` is
   `None` when last week was 0; `invoices_missing` counts a paid order with no
   invoice; customer `total_gst` includes `shipping_tax`.

### Panel — `src/pages/Dashboard.tsx`, `src/api/dashboard.ts`, locale files

Add the new keys to the `DashboardActions` type. Read every new value with a
fallback (`?? 0`), because a cached old response may lack it.

New page layout, top to bottom:

1. **Greeting** (keep).
2. **Four KPI cards** using `KpiCard` from `src/components/insights/KpiCard.tsx`:
   - Sales today = `today_sales`, delta `today_sales_delta_pct`, hint "vs same day last week".
   - Orders today = `today_real_orders`.
   - Average order = `today_aov`.
   - This month = `mtd_sales`, delta `mtd_sales_delta_pct`, hint "vs last month to date".

   Under the first card show one small line: "Online received ₹X · COD to collect ₹Y".
3. **Needs your attention** (keep the existing list and add these items, each shown only when its count is above 0):
   - `orders_unshipped_aged` → "N orders waiting more than 2 days to ship" → `/orders?status=confirmed` (urgent).
   - `out_of_stock_count` → "N products are out of stock" → `/products?stock=low` (urgent).
   - `invoices_missing` → "N orders have no invoice yet" → `/orders` (urgent).
   - `unclassified_hsn_count` → "N products have no HSN code" → `/gst`.
   - `failed_payments_today` → "N online payments failed today" → `/orders?status=pending`.
4. **Two cards side by side:**
   - COD cash (keep the existing tile unchanged).
   - Top sellers, last 7 days: a small table from `top_products_7d` (name, units, revenue).
5. **Recent orders**: 8 rows. Each row is a button that goes to
   `/orders?search=ORD-000123` (six-digit zero-padded id; the Orders page already
   reads the `search` param). Show date AND time, and a payment badge.
6. **One line**: "GST collected this month: ₹`mtd_gst_net_collected` — open GST report", linking to `/gst`.

Delete from the page: the large GST tile and the "Delivery today" tile. Remove
their now-unused i18n keys only if nothing else uses them.

---

## WP6 — GST reports on the invoice basis, and real credit notes

### Why

Today the HSN report and the GST figures are built from **orders by order date**.
GST is owed on **invoices by invoice date**. Three things go wrong:

1. Orders that never got an invoice are reported as sales.
2. A COD order placed on the 30th and dispatched on the 2nd is invoiced in one month but reported in the other.
3. An invoiced order that is later cancelled (for example a COD parcel that comes back) silently disappears from a month that may already be filed, and no credit note exists for it.

Also, credit notes are numbered `CN-<database id>`, which has gaps and no
financial-year series.

### Step 1 — new model `CreditNote` in `Backend/orders/models.py`

A credit note is the TAX document. `OrderRefund` stays the CASH record.

```python
class CreditNote(models.Model):
    """A GST credit note: reduces the output tax declared on an invoice.

    Created (a) for every recorded refund, and (b) when an invoiced order is
    cancelled while no money is held (e.g. a COD parcel returned to origin).
    `OrderRefund` remains the record of money actually paid back.
    """
    REASONS = [('refund', 'Refund'), ('cancellation', 'Cancelled after invoice')]

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='credit_notes')
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='credit_notes')
    refund = models.OneToOneField(OrderRefund, on_delete=models.PROTECT, null=True,
                                  blank=True, related_name='credit_note')
    reason = models.CharField(max_length=20, choices=REASONS)
    number = models.CharField(max_length=16, unique=True, db_index=True)
    series = models.CharField(max_length=16, db_index=True)
    sequence = models.PositiveIntegerField()
    issued_at = models.DateTimeField(db_index=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)  # value credited, GST included
    total_tax = models.DecimalField(max_digits=10, decimal_places=2)
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-issued_at', '-id']
        constraints = [models.UniqueConstraint(fields=['series', 'sequence'],
                                               name='uniq_credit_note_series_sequence')]
```

Run `makemigrations orders`.

### Step 2 — new file `Backend/orders/credit_notes.py`

Number format: `CN/25-26/000001`. Series string: `f"CN/{financial_year_label(when)}"`.
Reuse `allocate_invoice_number(series)` and `financial_year_label` from
`orders/invoicing.py` (the counter table works for any series name).

Snapshot shape (all money as strings with 2 decimals; use `_s` from `invoicing.py`):

```json
{
  "version": 1,
  "invoice_number": "NM/25-26/000123",
  "place_of_supply": {"code": "23", "interstate": false},
  "rows": [
    {"rate": "5.0", "taxable_value": "95.24", "tax_amount": "4.76",
     "cgst": "2.38", "sgst": "2.38", "igst": "0.00"}
  ]
}
```

- `place_of_supply` is copied from `invoice.snapshot['place_of_supply']` (`code` and `interstate`). Do not recompute it.
- Split each row's tax using the frozen `interstate` flag: interstate → all IGST; otherwise CGST = half rounded to paisa, SGST = the rest.
- `rate` and `taxable_value` may be `null` (legacy rows); keep them `null`.

Functions to write:

1. `issue_credit_note_for_refund(refund)`
   - Return the existing note if `CreditNote.objects.filter(refund=refund)` has one.
   - Return `None` if the order has no invoice.
   - Rows = `credit_note_tax_rows(refund)` from `orders/invoice.py`.
   - `total_amount = refund.amount`, `total_tax = refund.tax_amount`, `issued_at = refund.created_at`, `reason = 'refund'`.

2. `issue_credit_note_for_cancellation(order)`
   - Return `None` unless ALL are true: `order.status == 'cancelled'`; the order has an invoice; `order.payment_status not in ('paid', 'refunded')`; no credit note with `reason='cancellation'` exists for this order.
   - `total_amount = invoice.total_amount − sum of this order's existing credit notes' total_amount`; `total_tax` the same way from `total_tax`. If `total_amount <= 0`, return `None`.
   - Rows = the invoice's `snapshot['gst_summary']` rows scaled by `total_tax / invoice.total_tax` (when no earlier note exists the scale is 1 and the rows are copied as they are). Give any rounding remainder to the row with the largest tax so the rows add up to `total_tax`.
   - `issued_at = timezone.now()`, `refund = None`.

3. `maybe_issue_credit_note_for_refund(refund)` and
   `maybe_issue_credit_note_for_cancellation(order)`: wrappers that run the
   function inside `transaction.atomic()` within `try/except Exception`, log
   with `logger.exception`, and return `None` on failure. Copy the pattern of
   `maybe_issue_invoice` in `orders/invoicing.py`.

### Step 3 — call sites

- `Backend/orders/refunds.py::record_refund`: right after the `OrderRefund` row is created and the order is saved, call `maybe_issue_credit_note_for_refund(refund)` (import inside the function to avoid a circular import).
- `Backend/orders/views.py`: call `maybe_issue_credit_note_for_cancellation(order)`
  (a) in the `cancel` action, right after `order.save(update_fields=['status', 'cancelled_at'])`, inside the `with transaction.atomic()` block;
  (b) in `update()`, right after the `order.save()` that follows `order.cancelled_at = timezone.now()` (near line 1305–1311), only when the new status is `cancelled`.
- `Backend/orders/invoice.py::credit_note_number(refund)`: return the linked
  credit note's number if `CreditNote.objects.filter(refund=refund).first()`
  exists, otherwise the old `f"CN-{refund.id:06d}"`. Update its docstring.
- `update()` in `orders/views.py`: if the request tries to change
  `place_of_supply_state_code` and the order already has an invoice, return 400
  `{'place_of_supply_state_code': ['Cannot change after the invoice is issued.']}`.
  Do this check before the transaction starts.

### Step 4 — management command `Backend/orders/management/commands/backfill_credit_notes.py`

Copy the structure of `backfill_invoices.py`, including `--dry-run`. For every
`OrderRefund` with no credit note whose order has an invoice, oldest first, call
`issue_credit_note_for_refund`. Print how many were created and how many were
skipped because the order has no invoice.

### Step 5 — place-of-supply fallback flag

- Add to `Order`: `place_of_supply_is_fallback = models.BooleanField(default=False)`.
- In `orders/views.py` near line 806 (the `place_of_supply_for(` call): call
  `resolve_state_code(state=..., address=...)` first with the same arguments. If
  it returns `None`, set `place_of_supply_is_fallback=True` on the new order.
  The stored state code must stay exactly what it is today.

### Step 6 — new file `Backend/orders/gst_ledger.py`

All functions take inclusive dates `start`, `end`.

```python
def invoices_in(start, end):
    return Invoice.objects.filter(**range_filter('issued_at', start, end)).select_related('order')

def credit_notes_in(start, end):
    return CreditNote.objects.filter(**range_filter('issued_at', start, end)).select_related('order', 'invoice')
```

Invoices are counted even if the order was later cancelled or moved to the
Recycle Bin. The credit note is what reverses them.

1. `period_summary(start, end)` returns three blocks with the same keys
   `count, taxable_value, cgst, sgst, igst, tax, total`:
   - `invoices`: `total` = sum of `total_amount`; `tax` = sum of `total_tax`; `taxable_value = total − tax`; heads summed from each `snapshot['gst_summary']` row.
   - `credit_notes`: the same from credit notes (`snapshot['rows']`).
   - `net`: invoices minus credit notes, key by key (`count` omitted).

2. `b2c_by_state(start, end)` returns rows keyed by
   `(place_of_supply code, rate)`: `state_code`, `state_name` (use
   `state_name()` from `orders/place_of_supply.py`), `rate`, then
   `taxable_value, cgst, sgst, igst` three times with the prefixes `gross_`,
   `credit_`, `net_`. A `rate` of `None` is reported as its own row labelled
   "Unattributed". Sort by state code, then rate.

3. `documents_issued(start, end)` returns, for invoices and for credit notes,
   one row per `series`: `from_number`, `to_number`, `count`, and
   `gap = (max sequence − min sequence + 1) − count`.

4. `invoice_register(start, end)` yields one row per invoice: number, issue date
   (local date), order number `ORD-000123`, buyer name (from the snapshot),
   place of supply name, taxable value, CGST, SGST, IGST, total tax, total,
   payment method, current order status.

5. `credit_note_register(start, end)` yields one row per credit note: number,
   issue date, reason, invoice number, order number, taxable value, CGST, SGST,
   IGST, total tax, total.

6. `fallback_place_of_supply(start, end)` returns the invoices in range whose
   order has `place_of_supply_is_fallback=True` (number, order number, address).

### Step 7 — switch the HSN summary to the invoice basis

In `Backend/orders/gst_reports.py::hsn_summary`, replace the `orders = …` line with:

```python
    orders = Order.objects.filter(
        invoice__isnull=False, **range_filter('invoice__issued_at', start, end))
```

and replace `_refunds_in_period` with the `credit_notes` block of
`period_summary` (`amount` = `total`, `tax` = `tax`). Remove `_countable_orders`
if nothing else uses it. Rewrite the module docstring's "WHICH ORDERS COUNT"
section to say: invoices issued in the period, by issue date. **Do not net credit
notes into the HSN rows** — keep them as a separate figure, as now.

Tests in `Backend/orders/test_hsn_summary.py` will need their orders to have
invoices: call `issue_invoice(order, when=...)` in the fixtures. Do not weaken
any assertion.

### Step 8 — endpoints in `Backend/orders/gst_views.py`

All `IsAdminUser`, all accept `?from=&to=` through the existing `_parse_range`,
all support `?download=csv` through `csv_response`.

| Route | Returns |
|---|---|
| `GET /api/admin/gst/summary/` | `period_summary` + `fallback_place_of_supply` |
| `GET /api/admin/gst/b2c/` | `b2c_by_state` |
| `GET /api/admin/gst/documents/` | `documents_issued` |
| `GET /api/admin/gst/invoices/` | `invoice_register` |
| `GET /api/admin/gst/credit-notes/` | `credit_note_register` |

`/api/admin/hsn-summary/` keeps its path and shape.

### Step 9 — dashboard GST line

In `DashboardViewSet.actions`, compute `mtd_gst_collected`, `mtd_gst_refunded`
and `mtd_gst_net_collected` from `period_summary(month_start, today)`
(`invoices.tax`, `credit_notes.tax`, `net.tax`). Leave the `today_*` GST keys
and the analytics rollup as they are.

### Step 10 — Panel GST page (`src/pages/GstReport.tsx`, `src/api/gst.ts`)

Keep the date picker and the two warning cards. Below them use `Tabs` with:

1. **Summary** — three rows (Invoices, Credit notes, Net) × columns Taxable, CGST, SGST, IGST, Total tax, Total. Above it, a warning card listing invoices from `fallback_place_of_supply` ("State could not be read from the address; billed as Madhya Pradesh").
2. **HSN** — the existing table, unchanged.
3. **State-wise (B2C)** — the `b2c_by_state` table.
4. **Documents** — the `documents_issued` table; show a red badge when `gap > 0`.
5. **Registers** — two download buttons: Invoice register CSV, Credit note register CSV.

Every tab has its own "Download CSV" button.

### Step 11 — tests: new file `Backend/orders/test_gst_ledger.py`

1. An order placed on 30 Aug and invoiced on 2 Sep appears in September, not August.
2. A paid order with no invoice appears in no report.
3. Cancelling an invoiced, unpaid COD order creates one `cancellation` credit note for the full invoice value; cancelling again creates no second one.
4. Cancelling an invoiced PAID order creates no credit note; recording the refund afterwards creates one `refund` credit note.
5. Credit note numbers are `CN/<FY>/000001`, `…002` with no gap.
6. `period_summary` net = invoices − credit notes, and CGST + SGST + IGST = tax in every block.
7. An interstate invoice lands under IGST in `b2c_by_state`; an in-state one under CGST + SGST.
8. `documents_issued` reports `gap == 0` for a continuous series.
9. Changing `place_of_supply_state_code` on an invoiced order returns 400.
10. `backfill_credit_notes --dry-run` writes nothing.

---

## WP7 — Basic accounts (expenses + a monthly summary)

Needs WP6. This is deliberately small: a list of expenses, and one summary
screen. No ledgers, no double entry, no balance sheet.

### Step 1 — model in `Backend/admin_panel/models.py`

```python
class Expense(models.Model):
    """One business expense, entered by an admin. Feeds the monthly summary."""
    CATEGORIES = [
        ('raw_material', 'Raw material / purchases'),
        ('packaging', 'Packaging'),
        ('marketing', 'Marketing'),
        ('rent_utilities', 'Rent & utilities'),
        ('salary', 'Salary & wages'),
        ('other', 'Other'),
    ]
    PAYMENT_MODES = [('cash', 'Cash'), ('bank', 'Bank transfer'), ('upi', 'UPI'), ('card', 'Card')]

    date = models.DateField(db_index=True)
    category = models.CharField(max_length=20, choices=CATEGORIES)
    vendor = models.CharField(max_length=120, blank=True, default='')
    description = models.CharField(max_length=255, blank=True, default='')
    # Total paid, GST INCLUDED.
    amount = models.DecimalField(max_digits=12, decimal_places=2,
                                 validators=[MinValueValidator(Decimal('0.01'))])
    # GST contained inside `amount` (0 when the bill has none).
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                     validators=[MinValueValidator(0)])
    # True when this GST can be claimed back as input tax credit.
    itc_eligible = models.BooleanField(default=False)
    bill_number = models.CharField(max_length=60, blank=True, default='')
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODES, default='bank')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-id']
```

There is no "courier" or "payment gateway" category on purpose: those two costs
are already recorded per order and are added automatically in the summary.
Entering them here too would count them twice.

Serializer validation: `gst_amount <= amount`; `itc_eligible` may be true only
when `gst_amount > 0`.

### Step 2 — API

- `ExpenseViewSet` (ModelViewSet, `IsAdminUser`, `UserRateThrottle`) registered
  at `expenses` in `spices_backend/urls.py`. Filters: `?from=&to=&category=`.
  `perform_create` sets `created_by`. An extra action `GET /api/expenses/export/`
  returns CSV through `csv_response`.
- `GET /api/admin/books/summary/?from=&to=` (default: the current month to
  today), `IsAdminUser`. New file `Backend/admin_panel/books.py` holds the
  calculation; the view only calls it.

### Step 3 — what the summary returns

`ONLINE = ['ONLINE', 'razorpay']`. All values are strings with 2 decimals.

**sales** (from `period_summary` in WP6)

| Key | Value |
|---|---|
| `invoiced_total` | `invoices.total` |
| `credit_notes_total` | `credit_notes.total` |
| `net_sales_ex_gst` | `net.taxable_value` |

**cash**

| Key | Value |
|---|---|
| `online_received` | `Sum(Payment.amount)`, status `completed` or `refunded`, order not deleted, `order__created_at` in range |
| `cod_received` | `Sum(Order.total_amount)` with `cod_paid_at` in range, not deleted |
| `refunds_paid` | `Sum(OrderRefund.amount)` with `created_at` in range, order not deleted |
| `cod_outstanding_now` | not deleted, COD, `cod_paid_at` null, status in `shipped`/`delivering`/`delivered` (a current figure, not for the range) |

**costs**

| Key | Value |
|---|---|
| `gateway_fees_ex_gst` | `Sum(gateway_fee) − Sum(gateway_tax)` over the same payments as `online_received` |
| `gateway_fee_coverage` | `{recorded: payments with gateway_fee > 0, total: all those payments}` |
| `courier_cost` | `Sum(Order.shipping_cost)`, not deleted, not cancelled, `created_at` in range |
| `courier_cost_coverage` | `{recorded: orders with shipping_cost > 0, total: orders in range with status shipped/delivering/delivered}` |
| `expenses_by_category` | list of `{category, label, cost}` where `cost = Sum(amount) − Sum(gst_amount where itc_eligible)` |
| `expenses_total` | sum of those `cost` values |

**profit**

| Key | Value |
|---|---|
| `estimated_profit` | `net_sales_ex_gst − gateway_fees_ex_gst − courier_cost − expenses_total` |

**gst**

| Key | Value |
|---|---|
| `output_tax` | `invoices.tax` |
| `credit_note_tax` | `credit_notes.tax` |
| `input_tax_expenses` | `Sum(Expense.gst_amount)` where `itc_eligible`, date in range |
| `input_tax_gateway` | `Sum(Payment.gateway_tax)` over the same payments as above |
| `estimated_net_gst` | `output_tax − credit_note_tax − input_tax_expenses − input_tax_gateway` |

The JSON also carries `"is_estimate": true`.

### Step 4 — Panel page `src/pages/Accounts.tsx`

- Route `/accounts`, lazy-loaded in `App.tsx`; sidebar item "Accounts" directly under "GST" in `AdminSidebar.tsx`; new `src/api/accounts.ts`.
- A month picker (default: the current month).
- Summary cards: Net sales, Money received (online + COD), Costs, Estimated profit, Estimated GST to pay.
- Under the profit and GST cards, always show this text: "Estimate from the entries in this panel. Confirm with your accountant before filing or paying."
- When `gateway_fee_coverage.recorded < total`, show: "Gateway fee recorded on X of Y online payments." Same pattern for courier cost.
- Expense table with Add / Edit / Delete (dialog form: date, category, vendor, description, amount, GST amount, "GST can be claimed" checkbox, bill number, payment mode) and a "Download CSV" button.

### Step 5 — tests: `Backend/admin_panel/test_books.py`

1. A non-staff user gets 403 on both routes.
2. `gst_amount > amount` is rejected with 400.
3. An expense of 118.00 with GST 18.00 counts as cost 100.00 when `itc_eligible`, and 118.00 when not.
4. `estimated_profit` and `estimated_net_gst` match a hand-worked example in the test (one invoice, one credit note, one expense, one gateway fee).
5. Expenses outside the date range are excluded.

---

## WP8 — Tell the customer when a refund is recorded

`Backend/orders/emails.py`: add `send_refund_recorded_email(order, amount)` using
`_send_async`. Subject: `Refund of Rs. <amount> — <order number> | Nidhi Masala`.
Body: the amount, the order number, "It should reach your account within a few
business days.", and the My Orders link.

`Backend/orders/views.py::update()`: after the transaction block, if a refund
was recorded in this request, call it with the amount that was actually
recorded (the return value of `record_refund`, field `amount`). Add one test:
recording a partial refund sends one email that contains the partial amount.

---

## 9. Final documentation pass (after all WPs)

Update `NGU/CLAUDE.md`:

- Admin panel now has Google sign-in for existing staff accounts only; remove the "do not pass `VITE_GOOGLE_CLIENT_ID`" notes.
- Admin and customer sessions use separate cookies; the Panel sends `X-Admin-Panel: 1`.
- `/api/auth/logout/` and `/api/auth/admin/logout/` exist.
- GST reports are on the invoice basis; credit notes are `CN/<FY>/<seq>` rows in `orders.CreditNote`.
- New: `courier_name`, `tracking_url`, `Expense`, `/accounts`, `backfill_credit_notes`.

Update `Backend/docs/ORDER_LIFECYCLE.md`, `Backend/docs/ANALYTICS.md` and
`Backend/docs/DATABASE_SCHEMA.md` for the same changes.

---

## 10. For the owner — not for the implementer

**Deploy order** (after review): Backend and scheduler first, then `migrate`,
then the Panel image, then the Storefront image. Everyone must log in to the
Panel again once.

**Run once on the server after deploying, in this order:**

Production is the GCP VM (`34.0.5.162`), where the compose file in `~/NGU` is
`docker-compose.yml`, so no `-f` flag is needed:

```bash
cd ~/NGU
docker compose exec backend python manage.py backfill_invoices --dry-run
docker compose exec backend python manage.py backfill_invoices
docker compose exec backend python manage.py backfill_credit_notes --dry-run
docker compose exec backend python manage.py backfill_credit_notes
```

For the Google button to appear on the Panel login, pass
`--build-arg VITE_GOOGLE_CLIENT_ID=<id>` when building the Panel image, or add
`GOOGLE_CLIENT_ID=<id>` to `~/NGU/.env` (Compose reads that file, not
`.env.backend`).

**Set `RAZORPAY_LIVE_WEBHOOK_SECRET`** (steps are in `CLAUDE.md`). Without it the
gateway fee is not recorded and the Accounts page under-states costs.

**Ask the accountant** (nothing in this plan changes these):

1. Delivery is charged at 18% under SAC 9968. For a seller shipping its own goods, freight is usually part of the goods' value and taxed at the goods' rate. Which is right for this business?
2. For sales to unregistered buyers, should credit notes be netted into Table 7 and the HSN table? The new reports show gross, credit notes and net side by side, so either answer can be filed.
3. Masala blends: HSN 0910 at 5%, or 2103 at 18%?

**Not included in this plan:** a PDF for cancellation credit notes, line-by-line
partial refunds, locking a filed month, matching Razorpay settlements and
refunds automatically, uploading expense bills, buyer GSTIN (B2B invoices), and
courier URL presets.
