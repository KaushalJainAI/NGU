# API Permissions Reference

Complete reference for all API endpoints and their permission requirements.

---

## Permission Classes Used

| Class | Description |
|-------|-------------|
| `AllowAny` | No authentication required |
| `IsAuthenticated` | Must be logged in |
| `IsAuthenticatedOrReadOnly` | Read = public, Write = auth required |
| `IsAdminOrReadOnly` | Read = public, Write = admin only |
| `IsAdminUser` | Admin only (`is_staff=True`) |

---

## Public Endpoints (No Authentication)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/categories/` | GET | List all categories |
| `/api/categories/{slug}/` | GET | Category detail |
| `/api/products/` | GET | List products (with filters) |
| `/api/products/{slug}/` | GET | Product detail |
| `/api/combos/` | GET | List combos |
| `/api/combos/{slug}/` | GET | Combo detail |
| `/api/product-images/` | GET | List product images |
| `/api/sections/` | GET | Homepage sections |
| `/api/reviews/` | GET | List reviews |
| `/api/policies/{type}/` | GET | View shipping/return policy |
| `/api/spice-forms/` | GET | Spice form options |
| `/api/search/` | GET | Full-text product/combo search |
| `/api/search/suggest/` | GET | Search autocomplete suggestions |
| `/api/auth/register/` | POST | User registration |
| `/api/auth/login/` | POST | User login (JWT) |
| `/api/auth/token/refresh/` | POST | Refresh JWT token |
| `/api/auth/google/` | POST | Google OAuth login (requires a verified Google email — see AUTH.md) |
| `/api/auth/password-reset-request/` | POST | Request password reset |
| `/api/auth/password-reset-verify/` | POST | Verify reset token |
| `/api/auth/password-reset-confirm/` | POST | Confirm new password |
| `/api/contact/` | POST | Submit contact form |
| `/api/health/` | GET | Service health check |
| `/sitemap.xml` | GET | SEO sitemap (site root, nginx-proxied) — product/combo/category/static URLs |
| `/robots.txt` | GET | SEO robots policy (site root, nginx-proxied) |

---

## Authenticated Users

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/profile/` | GET | Get user profile |
| `/api/auth/profile/` | PUT/PATCH | Update profile |
| `/api/auth/change-password/` | POST | Change password |
| `/api/cart/` | GET | View cart |
| `/api/cart/add_item/` | POST | Add to cart |
| `/api/cart/update_item/` | POST | Update cart quantity |
| `/api/cart/remove_item/` | DELETE/POST | Remove from cart |
| `/api/cart/clear/` | POST | Clear cart |
| `/api/cart/sync/` | POST | Sync localStorage cart |
| `/api/cart/qr/` | POST | Generate UPI QR |
| `/api/favorites/` | GET | List favorites |
| `/api/favorites/` | POST | Add to favorites |
| `/api/favorites/{id}/` | DELETE | Remove from favorites |
| `/api/favorites/sync/` | POST | Sync favorites |
| `/api/orders/` | GET | List user's orders |
| `/api/orders/` | POST | Create order |
| `/api/orders/{id}/` | GET | Order detail |
| `/api/orders/{id}/cancel/` | POST | Cancel order |
| `/api/auth/validate-coupon/` | POST | Validate coupon |
| `/api/reviews/` | POST | Create review* |
| `/api/payment-account/` | GET | Get payment account for checkout |
| `/api/payment-methods/` | GET/POST | List/add saved payment methods |
| `/api/assistant/chat/` | POST | AI assistant (login-only; cart/order tools) |
| `/api/assistant/transcribe/` | POST | Voice → text (self-hosted whisper.cpp); audio upload |
| `/api/assistant/conversations/` | GET/POST | List / create chat threads |
| `/api/assistant/conversations/{id}/messages/` | GET | Thread message history |
| `/api/events/` | POST | Ingest behavioral events (view, click, purchase…) |
| `/api/recommendations/` | GET | Personalized product recommendations |

*Reviews require a verified purchase (delivered order containing the product).

---

## Admin Only (`is_staff=True`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/categories/` | POST/PUT/DELETE | Manage categories |
| `/api/products/` | POST/PUT/DELETE | Manage products |
| `/api/product-images/` | POST/PUT/DELETE | Manage images |
| `/api/combos/` | POST/PUT/DELETE | Manage combos |
| `/api/sections/` | POST/PUT/DELETE | Manage homepage sections |
| `/api/policies/{type}/` | PUT/PATCH | Update policies |
| `/api/dashboard/` | GET | Dashboard statistics |
| `/api/coupons/` | ALL | Manage coupons |
| `/api/receivable-accounts/` | ALL | Manage payment accounts |
| `/api/contact/` | GET/PUT/DELETE | Manage contact submissions |
| `/api/contact/{id}/mark_read/` | POST | Mark submission as read |
| `/api/contact/{id}/reply/` | POST | Mark as replied |
| `/api/assistant/conversations/admin/` | GET | List all chat threads |
| `/api/assistant/conversations/{id}/admin-reply/` | POST | Reply into a thread as admin |
| `/api/assistant/conversations/{id}/` | PATCH | Update thread status / assignment |
| `/api/assistant/admin-chat/` | POST | Admin business-data assistant (persona=`admin`, stateless, read-only reporting tools) |
| `/api/admin-search/` | GET | Global admin search across catalog/orders/customers |
| `/api/admin/bulk-products/` | GET | Bulk-edit grid data |
| `/api/admin/bulk-products/apply/` | POST | Apply bulk product edits |
| `/api/admin/bulk-products/import/` | POST | CSV product import |
| `/api/admin/products-export/` | GET | Export products to CSV |
| `/api/reviews/{id}/set-hidden/` | POST | Moderate: hide/unhide a review (`is_hidden`) |
| `/api/orders/` | GET (all) | View all orders |
| `/api/orders/{id}/` | PUT/PATCH | Update order status |
| `/api/orders/{id}/packing-slip/` | GET | Packing slip PDF |
| `/api/orders/{id}/delivery-bill/` | GET/POST/DELETE | Admin-only courier receipt (private media; never shown to customers) |

---

## Rate Limiting

| Scope | Limit | Applied To |
|-------|-------|------------|
| `anon` | 100/hour | Anonymous requests |
| `user` | 1000/hour | Authenticated requests |
| `login` | 5/minute | Login endpoint |
| `register` | 3/minute | Registration endpoint |
| `contact` | 5/hour | Contact form submission |
| `assistant` | 20/minute | AI assistant burst |
| `assistant_day` | 500/day | AI assistant daily cap (cost guard) |

---

## Data Access Control (BOLA Protection)

Users can only access their own:
- **Cart** — One cart per user
- **Orders** — Only their own orders
- **Favorites** — Their saved products
- **Profile** — Their own profile only
- **Assistant Conversations** — Scoped to user ID (chat is login-only)

Admins (`is_staff=True`) can access all data.

---

## Special Permissions

### Review Verification
- Users can only review products from **delivered** orders
- Reviews are marked `is_verified_purchase=True`

### Order Access
- Regular users: Own orders only
- Admins: All orders (for management)

### AI Assistant
- The chat endpoint is **login-only** (`IsAuthenticated`) — the whole assistant is gated behind login by design; there is no anonymous chat.
- Authenticated users: full access to product Q&A, navigation, and cart-query / order-status tools.

---

## Security Notes

1. **Receivable Accounts** — Admin-only to protect payment collection details
2. **Dashboard** — Admin-only to protect business metrics
3. **JWT Tokens** — 1 hour access, 7 day refresh
4. **Password Hashing** — Django's PBKDF2 with SHA256
5. **CORS** — Configured for specific origins only
6. **Google sign-in** — the `email_verified` claim is required; a signed token with an
   unverified email is rejected 401 so it can never match an existing account
7. **dj-rest-auth routes** — unmounted (2026-07-25). Auth is served only by the
   hand-written views listed above; do not re-add the stock routes without tests

---

*Last Updated: 2026-07-25*
