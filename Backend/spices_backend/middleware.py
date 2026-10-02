"""Request-language activation for django-modeltranslation.

The storefront has no URL-prefixed locales; instead the frontend sends the
active language as a `?lang=` query param (or an `X-Language` header). This
middleware activates that language for the request so modeltranslation returns
the matching translated columns (with English fallback). Unknown/blank values
leave the default language active.
"""
from django.conf import settings
from django.http import JsonResponse
from django.utils import translation
from django.utils.cache import patch_vary_headers

from .abuse import get_client_ip, is_blocked

_VALID_LANGUAGES = {code for code, _ in settings.LANGUAGES}


class AbuseGuardMiddleware:
    """Reject requests from manually-banned IPs with 403, before any work is
    done. Independent of the business logic and fail-open: any error in the
    block check lets the request proceed (we never lock out real shoppers due
    to a cache hiccup)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            if is_blocked(get_client_ip(request)):
                return JsonResponse(
                    {"error": "Access denied."}, status=403
                )
        except Exception:
            pass  # fail-open
        return self.get_response(request)


class LanguageQueryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = (request.GET.get('lang') or request.headers.get('X-Language') or '').strip().lower()
        activated = False
        if lang in _VALID_LANGUAGES:
            translation.activate(lang)
            request.LANGUAGE_CODE = lang
            activated = True
        try:
            response = self.get_response(request)
            # Without this, the browser HTTP cache ignores X-Language and serves
            # a cached English response to subsequent Hindi/Gujarati/etc. requests
            # for the same URL — making product names appear stuck in English.
            patch_vary_headers(response, ['X-Language'])
            return response
        finally:
            if activated:
                translation.deactivate()
