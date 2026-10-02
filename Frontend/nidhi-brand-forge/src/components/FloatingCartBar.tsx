import { useLocation, useNavigate } from "react-router-dom";
import { ShoppingCart, ArrowRight } from "lucide-react";
import { useCart } from "@/context/CartContext";
import { useTranslation } from "react-i18next";
import { FREE_SHIPPING_THRESHOLD } from "@/config/limits";

/**
 * Swiggy-style floating action bar that slides up whenever the cart has items.
 * Mounted globally; hidden on the cart/checkout/billing routes where it would
 * be redundant. Sits just above the mobile bottom nav (which is h-16).
 */
const FloatingCartBar = () => {
  const { t } = useTranslation();
  const { cart } = useCart();
  const navigate = useNavigate();
  const location = useLocation();

  const totalQuantity = cart.reduce((sum, item) => sum + item.quantity, 0);
  const subtotal = cart.reduce((sum, item) => sum + item.price * item.quantity, 0);

  // Don't show on pages that already focus on the cart/checkout flow.
  const hiddenRoutes = ["/cart", "/billing", "/checkout"];
  if (totalQuantity === 0 || hiddenRoutes.includes(location.pathname)) return null;

  const remaining = Math.max(0, FREE_SHIPPING_THRESHOLD - subtotal);

  return (
    <div className="fixed left-1/2 -translate-x-1/2 z-40 w-[92%] max-w-md bottom-20 md:bottom-6 animate-cart-slide-up">
      <button
        onClick={() => navigate("/cart")}
        className="w-full bg-secondary text-secondary-foreground rounded-2xl shadow-2xl px-4 sm:px-5 py-2.5 sm:py-3 flex items-center justify-between active-press hover:brightness-105 transition"
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="relative shrink-0">
            <ShoppingCart className="h-6 w-6" />
            <span className="absolute -top-2 -right-2 bg-background text-secondary text-[10px] font-bold w-4 h-4 rounded-full flex items-center justify-center">
              {totalQuantity}
            </span>
          </div>
          <div className="text-left leading-tight min-w-0">
            <div className="text-sm font-bold notranslate">
              {totalQuantity} {totalQuantity === 1 ? t('cart.item') : t('cart.items')} · ₹{subtotal}
            </div>
            <div className="text-[11px] text-secondary-foreground/85 truncate">
              {remaining > 0
                ? t('cart.addMoreForShipping', { amount: remaining })
                : t('cart.freeShippingUnlocked')}
            </div>
          </div>
        </div>
        <span className="flex items-center gap-1 bg-background/15 rounded-xl px-3 py-1.5 text-sm font-bold shrink-0">
          {t('cart.viewCart')}
          <ArrowRight className="h-4 w-4" />
        </span>
      </button>
    </div>
  );
};

export default FloatingCartBar;
