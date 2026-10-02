import { useEffect } from "react";

const SITE_NAME = "Nidhi Grah Udyog";
const SITE_URL = "https://nidhimasala.com";
const DEFAULT_IMAGE = `${SITE_URL}/logo.png`;

interface SeoProps {
  title?: string;
  description?: string;
  image?: string;
  /** Path only, e.g. "/products/kitchen-king-masala". Defaults to current URL. */
  path?: string;
  type?: "website" | "product" | "article";
  /** JSON-LD structured data. Emitted as a single <script type="application/ld+json">. */
  schema?: Record<string, unknown> | Record<string, unknown>[];
  noindex?: boolean;
}

/** Upsert a <meta> tag keyed by name= or property=. */
function setMeta(attr: "name" | "property", key: string, content: string) {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

function setLink(rel: string, href: string) {
  let el = document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);
  if (!el) {
    el = document.createElement("link");
    el.setAttribute("rel", rel);
    document.head.appendChild(el);
  }
  el.setAttribute("href", href);
}

const SCHEMA_ID = "seo-jsonld";

/**
 * Per-route document head. index.html only carries static site-wide tags, so
 * every route previously shared the homepage's title, description and OG image
 * — and no page emitted structured data. Mount this per page to fix both.
 *
 * Client-side, which Google renders; the sitemap tells it what to come for.
 */
const Seo = ({
  title,
  description,
  image,
  path,
  type = "website",
  schema,
  noindex = false,
}: SeoProps) => {
  useEffect(() => {
    const fullTitle = title ? `${title} | ${SITE_NAME}` : SITE_NAME;
    const url = `${SITE_URL}${path ?? window.location.pathname}`;
    const img = image || DEFAULT_IMAGE;

    document.title = fullTitle;
    if (description) {
      setMeta("name", "description", description);
      setMeta("property", "og:description", description);
      setMeta("name", "twitter:description", description);
    }
    setMeta("property", "og:title", fullTitle);
    setMeta("property", "og:type", type);
    setMeta("property", "og:url", url);
    setMeta("property", "og:image", img);
    setMeta("property", "og:site_name", SITE_NAME);
    setMeta("name", "twitter:card", "summary_large_image");
    setMeta("name", "twitter:title", fullTitle);
    setMeta("name", "twitter:image", img);
    setMeta("name", "robots", noindex ? "noindex,nofollow" : "index,follow");
    setLink("canonical", url);

    // Structured data. Replaced (not appended) so navigating between products
    // can't leave the previous product's schema behind.
    document.getElementById(SCHEMA_ID)?.remove();
    if (schema) {
      const script = document.createElement("script");
      script.id = SCHEMA_ID;
      script.type = "application/ld+json";
      script.textContent = JSON.stringify(schema);
      document.head.appendChild(script);
    }

    return () => {
      document.getElementById(SCHEMA_ID)?.remove();
    };
  }, [title, description, image, path, type, noindex, JSON.stringify(schema)]);

  return null;
};

export { SITE_URL, SITE_NAME };
export default Seo;
