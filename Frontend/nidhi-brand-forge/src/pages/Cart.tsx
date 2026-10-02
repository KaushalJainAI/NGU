import { useEffect, useRef, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Trash2,
  AlertCircle,
  ShoppingCart,
  MapPin,
  CreditCard,
  Check,
  Minus,
  Plus,
  Truck,
  ArrowLeft,
  ArrowRight,
} from "lucide-react";
import CachedImage from "@/components/CachedImage";
import ProductCarousel, { type CarouselProductItem } from "@/components/ProductCarousel";
import product1 from "@/assets/product-1.jpg";
import { useCart } from "@/context/CartContext";
import { useAuth } from "@/context/AuthContext";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { searchAPI } from "@/lib/api";
import {
  FREE_SHIPPING_THRESHOLD,
  SHIPPING_CHARGE,
  DEFAULT_TAX_RATE,
  MAX_ITEM_QUANTITY,
  shippingTaxFor,
} from "@/config/limits";
import { formatWeight, resolveImageUrl } from "@/lib/utils";
import { PriceBreakup } from "@/components/PriceBreakup";

type CartLine = ReturnType<typeof useCart>["cart"][number];

const lineKey = (item: Pick<CartLine, "id" | "itemType" | "variantId">) =>
  `${item.itemType}-${item.id}-${item.variantId ?? ""}`;

// Whole rupees print bare (₹120); anything else keeps its paise (₹120.50).
const inr = (n: number) => {
  const rounded = Math.round(n * 100) / 100;
  return `₹${Number.isInteger(rounded) ? rounded : rounded.toFixed(2)}`;
};

// How long to wait after the last +/- tap before telling the server.
const QUANTITY_DEBOUNCE_MS = 350;

/**
 * Cart page, laid out phone-first: every row is a fixed thumbnail beside a
 * column that can shrink (name wraps to two lines, price and stepper share the
 * bottom edge), and the checkout button lives in a bar pinned above the bottom
 * nav so it is always one tap away. From `lg` up the same markup becomes the
 * two-column list + summary layout.
 */
const Cart = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { isLoggedIn } = useAuth();
  const {
    cart,
    updateQuantity,
    removeFromCart,
    clearCart,
    fetchCartFromBackend,
  } = useCart();
  const [isRefreshing, setIsRefreshing] = useState(isLoggedIn);
  const [isVerifying, setIsVerifying] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [recommendations, setRecommendations] = useState<CarouselProductItem[]>([]);

  // Quantities the customer has tapped but we have not sent yet. Shown at once
  // so the stepper never lags; a burst of taps becomes ONE request when it stops.
  const [pendingQty, setPendingQty] = useState<Record<string, number>>({});
  const flushers = useRef<Record<string, { timer: ReturnType<typeof setTimeout>; run: () => Promise<void> }>>({});

  // Refresh from the server on entry. The cart context owns the mapping — this
  // page must never build its own copy of the cart, or the lines lose their
  // size, stock and GST rate.
  useEffect(() => {
    if (!isLoggedIn) {
      toast.warning(t('product.loginRequired'));
      navigate('/login', { state: { from: '/cart' } });
      return;
    }

    let cancelled = false;
    setIsRefreshing(true);
    fetchCartFromBackend().finally(() => {
      if (!cancelled) setIsRefreshing(false);
    });
    return () => {
      cancelled = true;
    };
  }, [isLoggedIn]); // Only depend on isLoggedIn

  // Leaving the page inside the debounce window must not drop the change.
  useEffect(() => {
    const pending = flushers.current;
    return () => {
      Object.values(pending).forEach(({ timer, run }) => {
        clearTimeout(timer);
        void run();
      });
    };
  }, []);

  useEffect(() => {
    const fetchRecommendations = async () => {
      // Swallows its own errors and resolves to an empty list.
      const response = await searchAPI.getRecommendations(8);
      setRecommendations(
        (response.products || []).map((p) => ({
          id: Number(p.id),
          name: p.name,
          image: resolveImageUrl(p.image, product1),
          price: p.price,
          originalPrice: p.original_price > p.price ? p.original_price : undefined,
          weight: formatWeight(p.weight, p.unit),
          itemType: "product" as const,
          inStock: p.in_stock !== false,
        })),
      );
    };

    fetchRecommendations();
  }, []);

  // The cart as displayed: server state with any not-yet-sent quantity on top.
  const lines = cart.map((item) => ({
    ...item,
    quantity: pendingQty[lineKey(item)] ?? item.quantity,
  }));
  const inStockItems = lines.filter(item => item.inStock !== false);
  const outOfStockItems = lines.filter(item => item.inStock === false);
  // Lines the server says cannot be bought as they stand: everything in the
  // unavailable group, plus a line that is only SHORT of stock (it stays in the
  // main list so its quantity can be lowered). Checkout waits until none is left.
  const blockedItems = lines.filter(item => item.inStock === false || item.unavailableReason);

  const subtotal = inStockItems.reduce((sum, item) => sum + item.price * item.quantity, 0);
  // Total units (not distinct lines) so this count matches the navbar and
  // floating cart bar, which both sum item quantities.
  const inStockQuantity = inStockItems.reduce((sum, item) => sum + item.quantity, 0);
  // Prices are GST-inclusive, so this is the tax ALREADY CONTAINED in the
  // subtotal — displayed for disclosure and never added to the total. Extracted
  // as price * rate/(100+rate), matching Backend/orders/pricing.py. Papad lines
  // (explicit 0) contribute nothing; an absent rate falls back to the backend
  // default so the split we show matches the invoice.
  const tax = inStockItems.reduce((sum, item) => {
    const rate = item.taxRate ?? DEFAULT_TAX_RATE;
    return sum + (item.price * item.quantity * rate) / (100 + rate);
  }, 0);
  // Per-rate breakup for the bill, mirroring group_tax_by_rate() on the backend:
  // a cart mixing papad (0%) with spices (5%) must show both slabs.
  const taxBreakdown = Object.values(
    inStockItems.reduce<Record<number, { rate: number; taxable_value: number; tax_amount: number }>>(
      (acc, item) => {
        const rate = item.taxRate ?? DEFAULT_TAX_RATE;
        const gross = item.price * item.quantity;
        const slabTax = (gross * rate) / (100 + rate);
        const slab = acc[rate] ?? (acc[rate] = { rate, taxable_value: 0, tax_amount: 0 });
        slab.taxable_value += gross - slabTax;
        slab.tax_amount += slabTax;
        return acc;
      },
      {},
    ),
  ).sort((a, b) => a.rate - b.rate);
  // Delivery fee, mirroring the backend rule (waived at/above the free-shipping
  // threshold, which is checked against the subtotal). Quoting it here keeps the
  // cart total consistent with checkout instead of jumping up on the next page.
  const shipping = subtotal > 0 && subtotal < FREE_SHIPPING_THRESHOLD ? SHIPPING_CHARGE : 0;
  // The delivery fee is quoted NET and taxed at 18% on top (SAC 9968) — the
  // opposite convention to goods. Rounded to paisa the same way the backend
  // does it, so the cart total matches the order to the last paisa.
  const shippingTax = shippingTaxFor(shipping);
  // Goods `tax` is a component of `subtotal`, not an addend; delivery tax IS.
  const total = subtotal + shipping + shippingTax;

  const freeShippingShortfall = Math.max(0, FREE_SHIPPING_THRESHOLD - subtotal);
  const freeShippingPct = Math.min(100, Math.round((subtotal / FREE_SHIPPING_THRESHOLD) * 100));

  const checkoutDisabled = isVerifying || inStockItems.length === 0 || blockedItems.length > 0;
  const checkoutLabel = isVerifying
    ? t('cart.processing')
    : inStockItems.length === 0
      ? t('cart.noItems')
      : t('cart.checkout');

  const withoutKey = (map: Record<string, number>, key: string) => {
    const next = { ...map };
    delete next[key];
    return next;
  };

  const dropPending = (key: string) => {
    const entry = flushers.current[key];
    if (entry) {
      clearTimeout(entry.timer);
      delete flushers.current[key];
    }
    setPendingQty(prev => withoutKey(prev, key));
  };

  // Send every not-yet-sent quantity now, and wait for the server to take it.
  const flushPending = () =>
    Promise.all(
      Object.values(flushers.current).map(({ timer, run }) => {
        clearTimeout(timer);
        return run();
      }),
    );

  const handleRemoveItem = (item: CartLine) => {
    dropPending(lineKey(item));
    removeFromCart(item.id, item.itemType, item.variantId);
  };

  // One by one: the cart context queues its writes, so this stays in order.
  const handleRemoveUnavailable = async () => {
    for (const item of outOfStockItems) {
      dropPending(lineKey(item));
      await removeFromCart(item.id, item.itemType, item.variantId);
    }
    toast.success(t('cart.unavailableRemoved'));
  };

  // The server's reason for a line it will not sell, in the customer's words.
  const reasonText = (item: CartLine) => {
    const code = item.unavailableReason;
    if (code === "insufficient_stock") {
      return t('cart.unavailable.insufficient_stock', { count: item.stock ?? 0 });
    }
    return code
      ? t(`cart.unavailable.${code}`, { defaultValue: t('product.outOfStock') })
      : t('product.outOfStock');
  };

  const handleQuantityChange = (item: CartLine, next: number) => {
    if (next < 1) {
      handleRemoveItem(item);
      return;
    }
    if (next > MAX_ITEM_QUANTITY) return;

    const key = lineKey(item);
    setPendingQty(prev => ({ ...prev, [key]: next }));

    const run = () => {
      delete flushers.current[key];
      return updateQuantity(item.id, next, item.itemType, item.variantId).finally(() => {
        // A newer tap may have replaced this value while the request was out.
        setPendingQty(prev => (prev[key] === next ? withoutKey(prev, key) : prev));
      });
    };
    const previous = flushers.current[key];
    if (previous) clearTimeout(previous.timer);
    flushers.current[key] = { timer: setTimeout(run, QUANTITY_DEBOUNCE_MS), run };
  };

  const handleClearCart = () => {
    Object.keys(flushers.current).forEach(dropPending);
    setConfirmClear(false);
    clearCart();
  };

  const handleCheckout = async () => {
    if (inStockItems.length === 0) {
      toast.error(t('cart.noStock'));
      return;
    }
    if (blockedItems.length > 0) {
      toast.error(t('cart.fixToContinue'));
      return;
    }

    setIsVerifying(true);
    try {
      await flushPending();
      // Re-read the cart so checkout never starts from a stale price or a line
      // that sold out while this page was open. The context reports a failure.
      const fresh = await fetchCartFromBackend();
      if (!fresh) return;

      if (fresh.length === 0) {
        toast.error(t('cart.emptyToast'));
        return;
      }
      if (!fresh.some(item => item.inStock !== false)) {
        toast.error(t('cart.noStock'));
        return;
      }
      // Something changed while this page was open (a size retired, a combo sold
      // out): the lines are now flagged — stay here so the customer can see which.
      if (fresh.some(item => item.inStock === false || item.unavailableReason)) {
        toast.error(t('cart.fixToContinue'));
        return;
      }

      navigate('/billing');
    } finally {
      setIsVerifying(false);
    }
  };

  // The effect above is already redirecting to /login.
  if (!isLoggedIn) return null;

  if (isRefreshing && cart.length === 0) {
    return (
      <div className="container max-w-6xl px-3 sm:px-4 py-4 sm:py-8 pb-24 md:pb-8" aria-busy="true">
        <span className="sr-only">{t('cart.loading')}</span>
        <div className="h-7 w-40 rounded bg-muted animate-pulse mb-4" />
        <div className="rounded-lg border border-border divide-y divide-border">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex gap-3 p-3 sm:p-4">
              <div className="h-[4.5rem] w-[4.5rem] shrink-0 rounded-lg bg-muted animate-pulse" />
              <div className="flex-1 space-y-2 py-1">
                <div className="h-4 w-3/4 rounded bg-muted animate-pulse" />
                <div className="h-3 w-1/4 rounded bg-muted animate-pulse" />
                <div className="h-5 w-1/3 rounded bg-muted animate-pulse" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (cart.length === 0) {
    return (
      <div className="container max-w-6xl px-3 sm:px-4 py-4 sm:py-8 pb-24 md:pb-8">
        <h1 className="text-xl sm:text-3xl font-bold mb-4 sm:mb-6">{t('cart.title')}</h1>
        <Card>
          <CardContent className="flex flex-col items-center justify-center px-4 py-12 sm:py-16 text-center">
            <span className="mb-4 grid h-16 w-16 place-items-center rounded-full bg-muted text-muted-foreground">
              <ShoppingCart className="h-7 w-7" aria-hidden />
            </span>
            <p className="text-base sm:text-lg text-muted-foreground mb-5">{t('cart.empty')}</p>
            <Button asChild>
              <Link to="/products">{t('cart.continueShopping')}</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const renderLine = (item: CartLine) => {
    const href = item.itemType === 'combo' ? `/combos/${item.id}` : `/products/${item.variantSlug || item.id}`;
    const soldOut = item.inStock === false;
    const lineTotal = item.price * item.quantity;
    // The API always sends an original price; it only means "discounted" when higher.
    const originalLineTotal =
      item.originalPrice && item.originalPrice > item.price ? item.originalPrice * item.quantity : null;

    return (
      <li key={lineKey(item)} className="flex gap-3 p-3 sm:gap-4 sm:p-4">
        <Link to={href} className="shrink-0">
          <CachedImage
            src={item.image || product1}
            fallbackSrc={product1}
            alt={item.name}
            cldWidth={96}
            className={`h-[4.5rem] w-[4.5rem] sm:h-24 sm:w-24 rounded-lg bg-muted object-contain ${soldOut ? "opacity-50" : ""}`}
          />
        </Link>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-start gap-1">
            <div className="min-w-0 flex-1">
              <Link to={href} className="hover:text-primary transition-colors">
                <h3 className={`text-sm sm:text-base font-semibold leading-snug line-clamp-2 break-words ${soldOut ? "text-muted-foreground" : ""}`}>
                  {item.name}
                </h3>
              </Link>
              {(item.itemType === "combo" || item.weight) && (
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {item.itemType === "combo" ? t('cart.combo', { defaultValue: "Combo" }) : item.weight}
                </p>
              )}
              {!soldOut && item.unavailableReason && (
                <p className="mt-1 text-xs font-medium text-destructive">{reasonText(item)}</p>
              )}
            </div>
            <button
              type="button"
              onClick={() => handleRemoveItem(item)}
              aria-label={`${t('cart.remove')}: ${item.name}`}
              className="-mr-1.5 -mt-1.5 grid h-9 w-9 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" aria-hidden />
            </button>
          </div>

          <div className="mt-2 flex items-end justify-between gap-2">
            {soldOut ? (
              <span className="rounded-full bg-destructive/10 px-2.5 py-1 text-xs font-medium text-destructive">
                {reasonText(item)}
              </span>
            ) : (
              <>
                <div className="min-w-0 notranslate">
                  <div className="flex flex-wrap items-baseline gap-x-1.5">
                    <span className="text-base font-bold text-primary">{inr(lineTotal)}</span>
                    {originalLineTotal !== null && (
                      <span className="text-xs text-muted-foreground line-through">
                        {inr(originalLineTotal)}
                      </span>
                    )}
                  </div>
                  {item.quantity > 1 && (
                    <p className="text-[11px] text-muted-foreground">
                      {inr(item.price)} × {item.quantity}
                    </p>
                  )}
                </div>

                <div className="flex h-9 shrink-0 items-center rounded-full border border-primary/40 bg-background">
                  <button
                    type="button"
                    onClick={() => handleQuantityChange(item, item.quantity - 1)}
                    aria-label={t('cart.decrease', { defaultValue: "Decrease quantity" })}
                    className="grid h-9 w-9 place-items-center rounded-full text-primary active-press"
                  >
                    {item.quantity === 1 ? <Trash2 className="h-3.5 w-3.5" aria-hidden /> : <Minus className="h-4 w-4" aria-hidden />}
                  </button>
                  <span className="min-w-[1.75rem] text-center text-sm font-semibold tabular-nums" aria-live="polite">
                    {item.quantity}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleQuantityChange(item, item.quantity + 1)}
                    disabled={item.quantity >= MAX_ITEM_QUANTITY}
                    aria-label={t('cart.increase', { defaultValue: "Increase quantity" })}
                    className="grid h-9 w-9 place-items-center rounded-full text-primary active-press disabled:opacity-40"
                  >
                    <Plus className="h-4 w-4" aria-hidden />
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </li>
    );
  };

  return (
    // Phones: clear the bottom nav AND the pinned checkout bar above it.
    <div className="container max-w-6xl px-3 sm:px-4 py-4 sm:py-8 pb-40 md:pb-8">
      <div className="mb-3 sm:mb-6 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h1 className="min-w-0 text-xl sm:text-3xl font-bold">
          {t('cart.title')}
          <span className="ml-2 text-sm font-normal text-muted-foreground notranslate">
            ({inStockQuantity} {inStockQuantity === 1 ? t('cart.item') : t('cart.items')})
          </span>
        </h1>
        {confirmClear ? (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">
              {t('cart.clearConfirm', { defaultValue: "Remove all items?" })}
            </span>
            <Button size="sm" variant="destructive" className="h-8 px-3 text-xs shadow-none" onClick={handleClearCart}>
              {t('cart.clearCart')}
            </Button>
            <Button size="sm" variant="ghost" className="h-8 px-3 text-xs" onClick={() => setConfirmClear(false)}>
              {t('cart.cancel', { defaultValue: "Cancel" })}
            </Button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmClear(true)}
            className="py-1.5 text-xs sm:text-sm font-medium text-muted-foreground underline-offset-4 hover:text-destructive hover:underline"
          >
            {t('cart.clearCart')}
          </button>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-3 lg:gap-8">
        <div className="min-w-0 space-y-3 sm:space-y-4 lg:col-span-2">
          {inStockItems.length > 0 && (
            <div className="rounded-lg border border-border bg-card p-3">
              <p className="flex items-center gap-2 text-[13px] sm:text-sm font-medium">
                {freeShippingShortfall > 0 && <Truck className="h-4 w-4 shrink-0 text-primary" aria-hidden />}
                <span className="min-w-0">
                  {freeShippingShortfall > 0
                    ? t('cart.addMoreForShipping', { amount: Math.ceil(freeShippingShortfall) })
                    : t('cart.freeShippingUnlocked')}
                </span>
              </p>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className={`h-full rounded-full transition-all duration-500 ease-out ${freeShippingShortfall > 0 ? "bg-primary" : "bg-secondary"}`}
                  style={{ width: `${Math.max(freeShippingPct, 4)}%` }}
                />
              </div>
            </div>
          )}

          {inStockItems.length > 0 && (
            <ul className="divide-y divide-border rounded-lg border border-border bg-card">
              {inStockItems.map(renderLine)}
            </ul>
          )}

          {outOfStockItems.length > 0 && (
            <div>
              <div className="mb-1.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                <p className="flex items-center gap-1.5 text-xs sm:text-sm font-medium text-destructive">
                  <AlertCircle className="h-4 w-4 shrink-0" aria-hidden />
                  {t('cart.unavailableNote', {
                    defaultValue: "Unavailable — not included in your total",
                  })}
                </p>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-8 px-3 text-xs"
                  onClick={handleRemoveUnavailable}
                >
                  {t('cart.removeUnavailable')}
                </Button>
              </div>
              <ul className="divide-y divide-border rounded-lg border border-destructive/30 bg-card">
                {outOfStockItems.map(renderLine)}
              </ul>
            </div>
          )}

          <Link
            to="/products"
            className="inline-flex items-center gap-1.5 py-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden />
            {t('cart.continueShopping')}
          </Link>
        </div>

        <div className="min-w-0 space-y-4 lg:sticky lg:top-24 lg:self-start">
          <Card>
            <CardContent className="p-4">
              <h2 className="mb-3 text-base sm:text-lg font-semibold">{t('cart.orderSummary')}</h2>
              <PriceBreakup
                subtotal={subtotal}
                tax={tax}
                taxableValue={subtotal - tax}
                taxBreakdown={taxBreakdown}
                shipping={shipping}
                shippingTax={shippingTax}
                total={total}
              />
              {blockedItems.length > 0 && (
                <p className="mt-3 text-xs font-medium text-destructive">{t('cart.fixToContinue')}</p>
              )}
              {/* Phones use the pinned bar below instead. */}
              <Button className="mt-4 hidden h-11 w-full md:inline-flex" onClick={handleCheckout} disabled={checkoutDisabled}>
                {checkoutLabel}
              </Button>
            </CardContent>
          </Card>

          {/* Checkout progress timeline */}
          <div className="hidden rounded-lg border border-border bg-card p-4 md:block">
            <div className="flex items-center justify-between">
              {[
                { Icon: ShoppingCart, label: t('cart.steps.cart', { defaultValue: "Cart" }), active: true },
                { Icon: MapPin, label: t('cart.steps.address', { defaultValue: "Address" }) },
                { Icon: CreditCard, label: t('cart.steps.payment', { defaultValue: "Payment" }) },
                { Icon: Check, label: t('cart.steps.done', { defaultValue: "Done" }) },
              ].map((step, i, arr) => (
                <div key={i} className="relative flex flex-1 flex-col items-center text-center">
                  {i < arr.length - 1 && (
                    <span className="absolute top-4 left-1/2 right-[-50%] h-0.5 bg-border" />
                  )}
                  <span
                    className={`relative z-10 grid h-8 w-8 place-items-center rounded-full ${
                      step.active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                    }`}
                  >
                    <step.Icon className="h-4 w-4" />
                  </span>
                  <span className={`mt-1.5 text-xs font-medium ${step.active ? "text-primary" : "text-muted-foreground"}`}>
                    {step.label}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {recommendations.length > 0 && (
        <section className="mt-8 sm:mt-12">
          <h2 className="mb-3 sm:mb-5 text-lg sm:text-2xl font-bold">{t('cart.peopleAlsoBuy')}</h2>
          <ProductCarousel items={recommendations} />
        </section>
      )}

      {/* Pinned checkout bar — phones only, floating just above the bottom nav
          (h-16, with the chat button rising ~10px out of it). */}
      <div className="fixed inset-x-3 bottom-[4.75rem] z-40 rounded-2xl border border-border bg-card/95 p-2.5 shadow-xl backdrop-blur-md md:hidden">
        <div className="flex items-center gap-3">
          <div className="min-w-0 pl-1.5 notranslate">
            <p className="truncate text-[11px] leading-tight text-muted-foreground">
              {t('cart.total')} · {inStockQuantity} {inStockQuantity === 1 ? t('cart.item') : t('cart.items')}
            </p>
            <p className="text-lg font-bold leading-tight">₹{total.toFixed(2)}</p>
          </div>
          <Button className="h-11 min-w-0 flex-1 px-4" onClick={handleCheckout} disabled={checkoutDisabled}>
            {/* The short "Checkout" — the full label does not fit beside the total at 320px. */}
            <span className="truncate">{checkoutDisabled ? checkoutLabel : t('billing.checkout')}</span>
            {!checkoutDisabled && <ArrowRight aria-hidden />}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default Cart;
