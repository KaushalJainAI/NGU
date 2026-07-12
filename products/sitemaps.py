"""XML sitemap for the storefront (audit issue #32).

Hand-rolled rather than django.contrib.sitemaps because the canonical host is
the storefront domain, not the Django SITE_ID host, and the URLs are frontend
routes (/products/<slug>) that Django itself never serves.
"""
from django.http import HttpResponse
from django.utils import timezone
from django.utils.http import http_date
from django.views.decorators.cache import cache_page
from xml.sax.saxutils import escape

from .models import Category, Product, ProductCombo

SITE_URL = "https://nidhimasala.com"

# (path, changefreq, priority) for routes that always exist.
STATIC_ROUTES = [
    ("/", "daily", "1.0"),
    ("/products", "daily", "0.9"),
    ("/combos", "weekly", "0.8"),
    ("/offer-zone", "daily", "0.8"),
    ("/about", "monthly", "0.5"),
    ("/contact", "monthly", "0.5"),
    ("/faq", "monthly", "0.4"),
    ("/shipping-policy", "yearly", "0.3"),
    ("/return-policy", "yearly", "0.3"),
    ("/privacy-policy", "yearly", "0.3"),
    ("/terms-and-conditions", "yearly", "0.3"),
]


def _url(loc, lastmod=None, changefreq="weekly", priority="0.5"):
    parts = [f"    <loc>{escape(loc)}</loc>"]
    if lastmod is not None:
        parts.append(f"    <lastmod>{lastmod.date().isoformat()}</lastmod>")
    parts.append(f"    <changefreq>{changefreq}</changefreq>")
    parts.append(f"    <priority>{priority}</priority>")
    body = "\n".join(parts)
    return f"  <url>\n{body}\n  </url>"


@cache_page(60 * 60 * 6)  # catalog changes are not minute-to-minute
def sitemap_xml(request):
    urls = [
        _url(f"{SITE_URL}{path}", changefreq=freq, priority=prio)
        for path, freq, prio in STATIC_ROUTES
    ]

    for product in (
        Product.objects.filter(is_active=True)
        .only("slug", "updated_at")
        .iterator()
    ):
        urls.append(_url(
            f"{SITE_URL}/products/{product.slug}",
            lastmod=getattr(product, "updated_at", None),
            changefreq="weekly",
            priority="0.8",
        ))

    for combo in (
        ProductCombo.objects.filter(is_active=True)
        .only("slug", "updated_at")
        .iterator()
    ):
        urls.append(_url(
            f"{SITE_URL}/combos/{combo.slug}",
            lastmod=getattr(combo, "updated_at", None),
            changefreq="weekly",
            priority="0.7",
        ))

    for category in Category.objects.filter(is_active=True).only("slug").iterator():
        urls.append(_url(
            f"{SITE_URL}/products?category={category.slug}",
            changefreq="weekly",
            priority="0.6",
        ))

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    response = HttpResponse(xml, content_type="application/xml")
    response["Last-Modified"] = http_date(timezone.now().timestamp())
    return response


def robots_txt(request):
    """Served from the backend so it can always point at a live sitemap."""
    lines = [
        "User-agent: *",
        "Allow: /",
        # Nothing useful to crawl, and they leak session-shaped URLs.
        "Disallow: /cart",
        "Disallow: /billing",
        "Disallow: /profile",
        "Disallow: /my-orders",
        "Disallow: /order-success",
        "Disallow: /login",
        "Disallow: /register",
        "Disallow: /reset-password",
        "Disallow: /forgot-password",
        "",
        f"Sitemap: {SITE_URL}/sitemap.xml",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
