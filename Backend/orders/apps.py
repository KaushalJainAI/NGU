import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class OrdersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'orders'

    def ready(self):
        _warn_on_legacy_shipping_config()


def _warn_on_legacy_shipping_config():
    """Say so at boot when a deployment still carries the dead SHIPPING_CHARGE.

    Delivery became a taxed, net-priced supply on 2026-08-04 and the setting was
    renamed to SHIPPING_CHARGE_NET so a stale value could not silently change
    meaning (69 was "what the customer pays"; under the new code it would have
    become "the net fee", billing 69 + 18% = 81.42).

    The rename makes the old variable inert, which is the point — but an inert
    variable sitting in a live .env is a lie waiting for the next person who
    reads it, so it gets flagged rather than ignored.

    A warning, deliberately, not ImproperlyConfigured: pricing is already correct
    by the time this runs, and taking the whole API down over a leftover env line
    would be a far worse outage than the tidy-up it is asking for.
    """
    from spices_backend.limits import (
        LEGACY_SHIPPING_CHARGE, SHIPPING_CHARGE_NET, SHIPPING_TAX_RATE,
    )
    if LEGACY_SHIPPING_CHARGE is None:
        return
    gross = SHIPPING_CHARGE_NET + (SHIPPING_CHARGE_NET * SHIPPING_TAX_RATE / 100)
    logger.warning(
        "Ignoring obsolete SHIPPING_CHARGE=%s in the environment. Delivery is now "
        "priced NET + GST: SHIPPING_CHARGE_NET=%s at %s%%, so the customer pays "
        "%s. Remove SHIPPING_CHARGE from the env file — it does nothing, and "
        "leaving it there implies a delivery fee that is not the one charged.",
        LEGACY_SHIPPING_CHARGE, SHIPPING_CHARGE_NET, SHIPPING_TAX_RATE, gross,
    )
