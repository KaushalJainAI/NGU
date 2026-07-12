"""Sitemap + robots.txt must be real, crawlable files (audit issue #32).

/sitemap.xml used to be swallowed by the SPA catch-all and returned index.html,
so crawlers got HTML where XML was promised.
"""
import pytest
from xml.etree import ElementTree

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


@pytest.mark.django_db
class TestSitemap:
    def test_serves_xml_not_html(self, client):
        response = client.get("/sitemap.xml")

        assert response.status_code == 200
        assert "xml" in response["Content-Type"]
        assert not response.content.lstrip().startswith(b"<!doctype")

    def test_is_wellformed_and_has_urls(self, client, test_product):
        response = client.get("/sitemap.xml")

        root = ElementTree.fromstring(response.content)
        locs = [e.text for e in root.findall(".//sm:loc", NS)]

        assert len(locs) > 0
        assert "https://nidhimasala.com/" in locs
        assert all(loc.startswith("https://nidhimasala.com") for loc in locs)

    def test_includes_active_products(self, client, test_product):
        response = client.get("/sitemap.xml")

        root = ElementTree.fromstring(response.content)
        locs = [e.text for e in root.findall(".//sm:loc", NS)]

        assert f"https://nidhimasala.com/products/{test_product.slug}" in locs

    def test_excludes_inactive_products(self, client, test_product):
        test_product.is_active = False
        test_product.save()

        response = client.get("/sitemap.xml")

        root = ElementTree.fromstring(response.content)
        locs = [e.text for e in root.findall(".//sm:loc", NS)]

        assert f"https://nidhimasala.com/products/{test_product.slug}" not in locs


@pytest.mark.django_db
class TestRobots:
    def test_points_at_the_sitemap(self, client):
        response = client.get("/robots.txt")
        body = response.content.decode()

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/plain")
        assert "Sitemap: https://nidhimasala.com/sitemap.xml" in body

    def test_keeps_private_routes_out_of_the_index(self, client):
        body = client.get("/robots.txt").content.decode()

        for private in ("/cart", "/billing", "/profile", "/my-orders"):
            assert f"Disallow: {private}" in body
