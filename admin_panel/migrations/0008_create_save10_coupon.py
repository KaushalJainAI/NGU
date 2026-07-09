"""
Create the standing 10%-off coupon (min order Rs. 1500).

Idempotent via update_or_create, so re-running is safe.

(Policies are intentionally not seeded here — the storefront serves static
policy pages; the Policy model is kept but inactive.)
"""
from django.db import migrations


def create_coupon(apps, schema_editor):
    Coupon = apps.get_model("admin_panel", "Coupon")
    Coupon.objects.update_or_create(
        code="SAVE10",
        defaults={
            "discount_percent": 10,
            "minimum_order_amount": 1500,
            "is_active": True,
        },
    )


def remove_coupon(apps, schema_editor):
    Coupon = apps.get_model("admin_panel", "Coupon")
    Coupon.objects.filter(code="SAVE10").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0007_alter_policy_type"),
    ]

    operations = [
        migrations.RunPython(create_coupon, remove_coupon),
    ]
