"""Tests for the fix_junk_products management command."""
from io import StringIO

import pytest
from django.core.management import call_command

from conftest import create_test_image
from products.models import Category, Product


def _category():
    return Category.objects.get_or_create(name="Test Cat", defaults={"description": "d"})[0]


def _product(name, slug=None, **kw):
    cat = kw.pop("category", None) or _category()
    return Product.objects.create(
        name=name, slug=slug, category=cat, description="d",
        spice_form="powder", price="10.00",
        image=create_test_image(f"{name}.jpg"), stock=1, **kw,
    )


@pytest.mark.django_db
class TestFixJunkProducts:
    def test_dry_run_changes_nothing(self):
        p = _product("logo2", slug="logo2-50000")
        out = StringIO()
        call_command("fix_junk_products", stdout=out)
        p.refresh_from_db()
        assert p.is_active is True
        assert "DRY RUN" in out.getvalue()

    def test_default_regex_deactivates_logo_products(self):
        junk = _product("logo2", slug="logo2-50000")
        real = _product("Turmeric Powder", slug="turmeric-powder-100")
        call_command("fix_junk_products", "--apply", stdout=StringIO())
        junk.refresh_from_db()
        real.refresh_from_db()
        assert junk.is_active is False      # matched ^logo\d*$
        assert real.is_active is True       # untouched

    def test_slug_target_deactivates(self):
        p = _product("Weird Thing", slug="logo2-50000")
        # name doesn't match default regex, but explicit slug does
        call_command("fix_junk_products", "--slug", "logo2-50000",
                     "--name-regex", "", "--apply", stdout=StringIO())
        p.refresh_from_db()
        assert p.is_active is False

    def test_delete_removes_unordered_product(self):
        p = _product("logo", slug="logo-1")
        pid = p.id
        call_command("fix_junk_products", "--delete", "--apply", stdout=StringIO())
        assert not Product.objects.filter(pk=pid).exists()

    def test_no_match_is_noop(self):
        p = _product("Cumin", slug="cumin-100")
        out = StringIO()
        call_command("fix_junk_products", "--apply", stdout=out)
        p.refresh_from_db()
        assert p.is_active is True
        assert "No matching products" in out.getvalue()
