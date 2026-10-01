from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

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

    def enforce_csrf(self, request):
        from rest_framework.authentication import CSRFCheck
        from rest_framework.exceptions import PermissionDenied

        check = CSRFCheck(lambda req: None)  # placeholder view
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise PermissionDenied(f'CSRF Failed: {reason}')
