from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


# Simple health check view for Docker health checks
def health_check(request):
    return JsonResponse({'status': 'healthy', 'service': 'ngu-backend'})

from users.views import (
    UserRegistrationView, UserProfileView, CustomTokenObtainPairView, CustomTokenRefreshView, ChangePasswordView,
    PasswordResetRequestView, PasswordResetVerifyView, PasswordResetConfirmView, GoogleLogin,
    LogoutView, AdminLoginView, AdminGoogleLoginView, AdminTokenRefreshView, AdminLogoutView,
)
from products.sitemaps import sitemap_xml, robots_txt
from products.views import (
    CategoryViewSet, ProductViewSet, ComboProductViewSet, ProductImageViewSet,
    ProductVariantViewSet, ProductSectionViewSet, get_spice_forms, unified_search,
    search_suggest
)
from products.bulk_views import (
    bulk_products, bulk_products_apply, bulk_products_import, export_products_csv,
    hsn_coverage, hsn_reference,
)
from orders.gst_views import (
    gst_b2c, gst_credit_notes, gst_documents, gst_invoices, gst_summary,
    hsn_summary_report,
)
from cart.views import CartViewSet, ValidateCouponAPIView, FavoritesViewSet
from orders.views import OrderViewSet
from reviews.views import ReviewViewSet
from payments.views import PaymentMethodViewSet
from admin_panel.views import (
    ReceivableAccountViewSet, DashboardViewSet, CouponViewSet, PaymentAccountView,
    GlobalAdminSearchView, AdminCustomerViewSet, ExpenseViewSet, BooksSummaryView,
)
from support.views import ContactSubmissionViewSet
from assistant.views import (
    AssistantChatView,
    AdminAssistantChatView,
    AssistantTranscribeView,
    ConversationListCreateView,
    ConversationMessagesView,
    AdminConversationListView,
    AdminConversationReplyView,
    AdminConversationPatchView,
)
from analytics.views import ingest_events, ingest_anon, reverse_geocode, user_geo
from analytics.insights_views import (
    overview as analytics_overview,
    sales as analytics_sales,
    funnel as analytics_funnel,
    search_insights as analytics_search,
    customers as analytics_customers,
    anonymous as analytics_anonymous,
)
from products.views import recommendations

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='categories')
router.register(r'products', ProductViewSet, basename='products')
router.register(r'combos', ComboProductViewSet, basename='combos')
router.register(r'cart', CartViewSet, basename='cart')
router.register(r'favorites', FavoritesViewSet, basename='favorites')
router.register(r'orders', OrderViewSet, basename='orders')
router.register(r'reviews', ReviewViewSet, basename='reviews')
router.register(r'payment-methods', PaymentMethodViewSet, basename='payment-methods')
router.register(r'receivable-accounts', ReceivableAccountViewSet, basename='receivable-accounts')
router.register(r'product-images', ProductImageViewSet, basename='product-image')
router.register(r'product-variants', ProductVariantViewSet, basename='product-variant')
router.register(r'product-sections', ProductSectionViewSet, basename='product-section')
router.register(r'coupons', CouponViewSet, basename='coupon')
router.register(r'expenses', ExpenseViewSet, basename='expenses')

# Policy management is retired for now — the storefront serves static policy
# pages directly. The Policy model/viewset remain in the codebase but are not
# routed. Re-register here to bring the endpoint back if needed.
router.register(r'dashboard', DashboardViewSet, basename='dashboard')
# Admin panel: customer directory (read-only) — /api/admin-customers/
router.register(r'admin-customers', AdminCustomerViewSet, basename='admin-customers')

# Support endpoints
router.register(r'contact', ContactSubmissionViewSet, basename='contact')


urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Health check endpoint for Docker
    path('api/health/', health_check, name='health-check'),

    # Main API endpoints
    path('api/', include(router.urls)),

    # Razorpay payment endpoints (create-order / verify / webhook / status)
    path('api/payments/', include('payments.urls')),

    # Authentication endpoints
    path('api/auth/register/', UserRegistrationView.as_view(), name='register'),
    path('api/auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/logout/', LogoutView.as_view(), name='logout'),
    path('api/auth/admin/login/', AdminLoginView.as_view(), name='admin-login'),
    path('api/auth/admin/google/', AdminGoogleLoginView.as_view(), name='admin-google-login'),
    path('api/auth/admin/token/refresh/', AdminTokenRefreshView.as_view(), name='admin-token-refresh'),
    path('api/auth/admin/logout/', AdminLogoutView.as_view(), name='admin-logout'),
    path('api/auth/profile/', UserProfileView.as_view(), name='profile'),
    path('api/auth/change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('api/auth/password-reset-request/', PasswordResetRequestView.as_view(), name='password-reset-request'),
    path('api/auth/password-reset-verify/', PasswordResetVerifyView.as_view(), name='password-reset-verify'),
    path('api/auth/password-reset-confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('api/auth/google/', GoogleLogin.as_view(), name='google_login'),
    
    # dj-rest-auth routes were UNMOUNTED (2026-07-25). They exposed a second,
    # public, untested auth surface (login/logout/password-reset/registration)
    # alongside the hand-written views above, with different validation and
    # different throttles. Nothing in the storefront or admin panel called them.
    # Do not re-add without owning the tests and rate limits.

    # Coupon validation endpoint
    path('api/auth/validate-coupon/', ValidateCouponAPIView.as_view(), name='validate-coupon'),
    
    # Payment account for checkout (authenticated users)
    path('api/payment-account/', PaymentAccountView.as_view(), name='payment-account'),

    # Admin panel global search (orders/products/customers/coupons in one box)
    path('api/admin-search/', GlobalAdminSearchView.as_view(), name='admin-search'),

    # Basic accounts: monthly books estimate (no ledgers).
    path('api/admin/books/summary/', BooksSummaryView.as_view(), name='books-summary'),

    # Admin panel bulk product tools (edit grid + CSV import/export)
    path('api/admin/bulk-products/', bulk_products, name='bulk-products'),
    path('api/admin/bulk-products/apply/', bulk_products_apply, name='bulk-products-apply'),
    path('api/admin/bulk-products/import/', bulk_products_import, name='bulk-products-import'),
    path('api/admin/products-export/', export_products_csv, name='products-export'),

    # GST classification: the curated HSN code list with the statutory rate for
    # each (reference for the product form), a coverage report of what is still
    # unclassified or rate-mismatched, and the HSN-wise summary of outward
    # supplies that GSTR-1 Table 12 is filed from (`?format=csv` to download).
    path('api/admin/hsn-reference/', hsn_reference, name='hsn-reference'),
    path('api/admin/hsn-coverage/', hsn_coverage, name='hsn-coverage'),
    path('api/admin/hsn-summary/', hsn_summary_report, name='hsn-summary'),
    path('api/admin/gst/summary/', gst_summary, name='gst-summary'),
    path('api/admin/gst/b2c/', gst_b2c, name='gst-b2c'),
    path('api/admin/gst/documents/', gst_documents, name='gst-documents'),
    path('api/admin/gst/invoices/', gst_invoices, name='gst-invoices'),
    path('api/admin/gst/credit-notes/', gst_credit_notes, name='gst-credit-notes'),

    path('api/spice-forms/', get_spice_forms, name='spice-forms'),
    path('api/search/suggest/', search_suggest, name='search-suggest'),
    path('api/search/', unified_search, name='unified-search' ),

    # SEO. Served at the site root by nginx (it proxies /sitemap.xml and
    # /robots.txt here) so crawlers find them on the storefront domain.
    path('sitemap.xml', sitemap_xml, name='sitemap'),
    path('robots.txt', robots_txt, name='robots'),

    # Behavioral event ingest + personalized recommendations
    path('api/events/', ingest_events, name='events-ingest'),
    path('api/anon-events/', ingest_anon, name='anon-events-ingest'),
    path('api/recommendations/', recommendations, name='recommendations'),

    # Admin-only analytics insights (overview / sales / funnel / search / customers / anonymous)
    path('api/analytics/overview/', analytics_overview, name='analytics-overview'),
    path('api/analytics/sales/', analytics_sales, name='analytics-sales'),
    path('api/analytics/funnel/', analytics_funnel, name='analytics-funnel'),
    path('api/analytics/search/', analytics_search, name='analytics-search'),
    path('api/analytics/customers/', analytics_customers, name='analytics-customers'),
    path('api/analytics/anonymous/', analytics_anonymous, name='analytics-anonymous'),

    # Location: reverse-geocode proxy + coarse user-location upsert
    path('api/geocode/reverse/', reverse_geocode, name='geocode-reverse'),
    path('api/geo/', user_geo, name='user-geo'),

    # AI shopping assistant + unified chat
    # NOTE: the static `admin/` route is declared before the `<uuid>` routes so
    # it is matched first and never shadowed.
    path('api/assistant/chat/', AssistantChatView.as_view(), name='assistant-chat'),
    path('api/assistant/admin-chat/', AdminAssistantChatView.as_view(), name='assistant-admin-chat'),
    path('api/assistant/transcribe/', AssistantTranscribeView.as_view(), name='assistant-transcribe'),
    path('api/assistant/conversations/admin/', AdminConversationListView.as_view(), name='assistant-admin-list'),
    path('api/assistant/conversations/', ConversationListCreateView.as_view(), name='assistant-conversations'),
    path('api/assistant/conversations/<uuid:conversation_id>/messages/', ConversationMessagesView.as_view(), name='assistant-messages'),
    path('api/assistant/conversations/<uuid:conversation_id>/admin-reply/', AdminConversationReplyView.as_view(), name='assistant-admin-reply'),
    path('api/assistant/conversations/<uuid:conversation_id>/', AdminConversationPatchView.as_view(), name='assistant-admin-patch'),
]

if settings.DEBUG:
    # API Documentation
    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
        path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
