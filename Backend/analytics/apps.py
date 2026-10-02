from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'analytics'

    def ready(self):
        # Subscribe to model signals (e.g. order -> purchase events) so other
        # apps don't have to call analytics inline. See analytics/signals.py.
        from . import signals
        signals.register()
