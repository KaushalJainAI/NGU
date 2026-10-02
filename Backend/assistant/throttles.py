"""Rate limits for the assistant (G4). Both apply per authenticated user and
per anonymous IP. The minute throttle caps burst; the daily throttle caps cost."""

from rest_framework.throttling import SimpleRateThrottle


class AssistantBurstThrottle(SimpleRateThrottle):
    scope = 'assistant'

    def get_cache_key(self, request, view):
        ident = request.user.pk if request.user and request.user.is_authenticated \
            else self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class AssistantDailyThrottle(SimpleRateThrottle):
    scope = 'assistant_day'

    def get_cache_key(self, request, view):
        ident = request.user.pk if request.user and request.user.is_authenticated \
            else self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class AssistantTranscribeThrottle(SimpleRateThrottle):
    """Voice transcription is CPU-heavy on our self-hosted whisper server, so it
    gets a tighter per-minute cap than text chat."""
    scope = 'assistant_stt'

    def get_cache_key(self, request, view):
        ident = request.user.pk if request.user and request.user.is_authenticated \
            else self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}
