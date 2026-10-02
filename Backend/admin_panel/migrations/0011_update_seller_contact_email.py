"""Point the stored policy text at the current support email.

The brand email moved from `nidhigrahudyog@rediffmail.com` to
`nidhispicesandfood@gmail.com`. Migration 0009 baked the old address into the
seeded `Policy(type='privacy')` row, and an applied migration never re-runs — so
editing 0009 would fix a fresh database while leaving every existing one (prod
included) serving the dead address.

This replaces the address IN PLACE rather than re-seeding the whole document, so
any edit the owner has since made through the admin panel survives. Policies
whose text doesn't mention the old address are left untouched.
"""
from django.db import migrations


OLD_EMAIL = "nidhigrahudyog@rediffmail.com"
NEW_EMAIL = "nidhispicesandfood@gmail.com"


def _swap(apps, frm, to):
    Policy = apps.get_model("admin_panel", "Policy")
    for policy in Policy.objects.filter(content__contains=frm):
        policy.content = policy.content.replace(frm, to)
        policy.save(update_fields=["content"])


def forward(apps, schema_editor):
    _swap(apps, OLD_EMAIL, NEW_EMAIL)


def backward(apps, schema_editor):
    _swap(apps, NEW_EMAIL, OLD_EMAIL)


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0010_coupon_assigned_user_coupon_discount_amount_and_more"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
