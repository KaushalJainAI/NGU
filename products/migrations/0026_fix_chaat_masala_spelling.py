import re

from django.db import migrations
from django.db.models import Q


# Matches the misspelling "chat masala" (any casing) as a whole phrase so we
# don't touch unrelated words like "chatpata" or "chatani".
_PATTERN = re.compile(r"chat masala", re.IGNORECASE)


def _fix_names(model):
    """Rename any product/combo whose display name says 'Chat Masala' to the
    correct 'Chaat Masala'. Slugs are intentionally left untouched so existing
    URLs / SEO / bookmarks keep working.
    """
    for obj in model.objects.filter(Q(name__icontains="chat masala")):
        new_name = _PATTERN.sub("Chaat Masala", obj.name)
        if new_name != obj.name:
            obj.name = new_name
            obj.save(update_fields=["name"])


def fix_chaat_spelling(apps, schema_editor):
    _fix_names(apps.get_model("products", "Product"))
    _fix_names(apps.get_model("products", "ProductCombo"))


def reverse_noop(apps, schema_editor):
    # Correcting a spelling mistake is not meaningfully reversible.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0025_recategorize_catalog"),
    ]

    operations = [
        migrations.RunPython(fix_chaat_spelling, reverse_noop),
    ]
