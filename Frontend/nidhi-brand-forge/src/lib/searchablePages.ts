import {
  Home,
  Package,
  Boxes,
  Tag,
  ShoppingCart,
  Heart,
  ClipboardList,
  Truck,
  User,
  Info,
  Mail,
  HelpCircle,
  RotateCcw,
  ShieldCheck,
  FileText,
  LogIn,
  UserPlus,
  type LucideIcon,
} from "lucide-react";

export interface SearchablePage {
  path: string;
  title: string;
  description: string;
  /** Synonyms / aliases users might type instead of the exact page title. */
  keywords: string[];
  icon: LucideIcon;
}

/**
 * Registry of the pages a shopper can navigate to. The smart search box matches
 * a user's query against these so typing "cart", "shipping policy", "track my
 * order" etc. jumps straight to the right page — not just products.
 */
export const SEARCHABLE_PAGES: SearchablePage[] = [
  { path: "/", title: "Home", description: "Back to the homepage", keywords: ["home", "main", "start", "homepage"], icon: Home },
  { path: "/products", title: "All Products", description: "Browse every spice", keywords: ["products", "shop", "buy", "spices", "masala", "catalog", "store", "all products"], icon: Package },
  { path: "/combos", title: "Combos", description: "Value bundles & packs", keywords: ["combos", "bundles", "packs", "combo", "value pack"], icon: Boxes },
  { path: "/offer-zone", title: "Offer Zone", description: "Deals & discounts", keywords: ["offers", "offer zone", "deals", "discount", "sale", "coupon"], icon: Tag },
  { path: "/cart", title: "Cart", description: "Items in your cart", keywords: ["cart", "basket", "bag", "checkout", "my cart"], icon: ShoppingCart },
  { path: "/favorites", title: "Favorites", description: "Your saved items", keywords: ["favorites", "wishlist", "saved", "likes", "favourite"], icon: Heart },
  { path: "/my-orders", title: "My Orders", description: "Order history & bills", keywords: ["orders", "my orders", "purchases", "order history", "bill", "invoice"], icon: ClipboardList },
  { path: "/my-orders", title: "Track Order", description: "Track your shipment", keywords: ["track", "track order", "tracking", "shipment", "where is my order"], icon: Truck },
  { path: "/profile", title: "My Profile", description: "Account & addresses", keywords: ["profile", "account", "settings", "my account", "address"], icon: User },
  { path: "/about", title: "About Us", description: "Our story", keywords: ["about", "about us", "story", "company", "who we are"], icon: Info },
  { path: "/contact", title: "Contact Us", description: "Get in touch", keywords: ["contact", "support", "help", "reach us", "customer care", "email"], icon: Mail },
  { path: "/faq", title: "FAQ", description: "Frequently asked questions", keywords: ["faq", "questions", "help", "frequently asked"], icon: HelpCircle },
  { path: "/shipping-policy", title: "Shipping Policy", description: "Delivery details", keywords: ["shipping", "shipping policy", "delivery", "delivery policy"], icon: Truck },
  { path: "/return-policy", title: "Return Policy", description: "Returns & refunds", keywords: ["return", "return policy", "refund", "exchange", "returns"], icon: RotateCcw },
  { path: "/privacy-policy", title: "Privacy Policy", description: "How we use your data", keywords: ["privacy", "privacy policy", "data", "personal data"], icon: ShieldCheck },
  { path: "/terms", title: "Terms & Conditions", description: "Terms of use", keywords: ["terms", "terms and conditions", "conditions", "t&c", "legal"], icon: FileText },
  { path: "/login", title: "Login", description: "Sign in to your account", keywords: ["login", "log in", "sign in", "signin"], icon: LogIn },
  { path: "/register", title: "Create Account", description: "Register a new account", keywords: ["register", "sign up", "signup", "create account", "join"], icon: UserPlus },
];

/**
 * Fuzzy-ish match of a query against the page registry.
 * Ranking: exact title > title starts-with > keyword exact > keyword/title contains.
 */
export function matchPages(query: string, limit = 4): SearchablePage[] {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];

  const scored: { page: SearchablePage; score: number }[] = [];
  for (const page of SEARCHABLE_PAGES) {
    const title = page.title.toLowerCase();
    const keywords = page.keywords;
    let score = 0;

    if (title === q) score = 100;
    else if (title.startsWith(q)) score = 80;
    else if (keywords.some((k) => k === q)) score = 75;
    else if (keywords.some((k) => k.startsWith(q))) score = 60;
    else if (title.includes(q)) score = 45;
    else if (keywords.some((k) => k.includes(q) || q.includes(k))) score = 35;

    if (score > 0) scored.push({ page, score });
  }

  return scored
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((s) => s.page);
}
