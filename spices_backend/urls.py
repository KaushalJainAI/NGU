from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


# Simple health check view for Docker health checks
def health_check(request):
    return JsonResponse({'status': 'healthy', 'service': 'ngu-backend'})

from users.views import (
    UserRegistrationView, UserProfileView, CustomTokenObtainPairView, CustomTokenRefreshView, ChangePasswordView,
    PasswordResetRequestView, PasswordResetVerifyView, PasswordResetConfirmView, GoogleLogin
)
from products.views import (
    CategoryViewSet, ProductViewSet, ComboProductViewSet, ProductImageViewSet,
    ProductVariantViewSet, ProductSectionViewSet, get_spice_forms, unified_search,
    search_suggest
)
from cart.views import CartViewSet, ValidateCouponAPIView, FavoritesViewSet
from orders.views import OrderViewSet
from reviews.views import ReviewViewSet
from payments.views import PaymentMethodViewSet
from admin_panel.views import ReceivableAccountViewSet, DashboardViewSet, CouponViewSet, PaymentAccountView
from support.views import ContactSubmissionViewSet
from assistant.views import (
    AssistantChatView,
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

# Policy management is retired for now — the storefront serves static policy
# pages directly. The Policy model/viewset remain in the codebase but are not
# routed. Re-register here to bring the endpoint back if needed.
router.register(r'dashboard', DashboardViewSet, basename='dashboard')

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
    path('api/auth/profile/', UserProfileView.as_view(), name='profile'),
    path('api/auth/change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('api/auth/password-reset-request/', PasswordResetRequestView.as_view(), name='password-reset-request'),
    path('api/auth/password-reset-verify/', PasswordResetVerifyView.as_view(), name='password-reset-verify'),
    path('api/auth/password-reset-confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('api/auth/google/', GoogleLogin.as_view(), name='google_login'),
    
    # Standard dj-rest-auth routes
    path('api/auth/', include('dj_rest_auth.urls')),
    path('api/auth/registration/', include('dj_rest_auth.registration.urls')),

    # Coupon validation endpoint
    path('api/auth/validate-coupon/', ValidateCouponAPIView.as_view(), name='validate-coupon'),
    
    # Payment account for checkout (authenticated users)
    path('api/payment-account/', PaymentAccountView.as_view(), name='payment-account'),

    path('api/spice-forms/', get_spice_forms, name='spice-forms'),
    path('api/search/suggest/', search_suggest, name='search-suggest'),
    path('api/search/', unified_search, name='unified-search' ),

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
