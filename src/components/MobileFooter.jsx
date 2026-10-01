import { Link, useLocation } from "react-router-dom";
import { useCart } from "@/context/CartContext";
import { Button } from "@/components/ui/button";
import { useTranslation } from "react-i18next";
import { Home, ShoppingBag, MessageCircle, Gift, Package } from "lucide-react";

const MobileFooterNav = () => {
  const { t } = useTranslation();
  const { cart } = useCart();
  const location = useLocation();

  const openChat = () => {
    window.dispatchEvent(new CustomEvent("assistant:open"));
  };

  // AP12: one icon set (lucide) — no emoji icons.
  const footerItems = [
    { label: t('mobileNav.home'), Icon: Home, path: "/" },
    { label: t('mobileNav.shop'), Icon: ShoppingBag, path: "/products" },
    { label: t('mobileNav.chat'), Icon: MessageCircle, isSpecial: true },
    { label: t('mobileNav.offers'), Icon: Gift, path: "/offer-zone" },
    { label: t('mobileNav.orders'), Icon: Package, path: "/my-orders" },
  ];

  return (
    <nav className="fixed inset-x-0 bottom-0 z-50 w-full max-w-full bg-card border-t border-border flex justify-around items-end md:hidden h-16 transition-all duration-300">
      {footerItems.map((item, i) => {
        const isActive = location.pathname === item.path;

        // Chat button - special elevated styling
        if (item.isSpecial) {
          return (
            <div
              key={i}
              className="flex flex-col items-center justify-center flex-1 -mt-5"
            >
              <Button
                onClick={openChat}
                className="h-14 w-14 rounded-full shadow-lg hover:shadow-xl
                           transition-all duration-300 hover:scale-105 active:scale-95"
                size="icon"
                aria-label="Open Chat"
              >
                <item.Icon className="h-6 w-6" aria-hidden />
              </Button>
              <span className="text-xs text-primary font-medium mt-0.5 transition-colors duration-200">{item.label}</span>
            </div>
          );
        }

        return (
          <Link
            key={i}
            to={item.path}
            className={`flex flex-col items-center justify-center flex-1 py-1
                        transition-all duration-200 active:scale-95
                        ${isActive
                          ? "text-primary font-bold"
                          : "text-muted-foreground hover:text-foreground"
                        }`}
          >
            <span
              className={`relative grid place-items-center h-9 w-9 rounded-full transition-all duration-200 ${
                isActive ? "bg-primary/10 scale-105" : ""
              }`}
            >
              <item.Icon className="h-5 w-5" aria-hidden />
              {item.label === t('mobileNav.shop') && cart.length > 0 && (
                <span className="absolute -top-0.5 -right-0.5 bg-primary text-primary-foreground text-[10px] w-4 h-4 rounded-full flex items-center justify-center animate-bounce-in">
                  {cart.reduce((sum, it) => sum + it.quantity, 0)}
                </span>
              )}
            </span>
            <span className={`text-[11px] mt-0.5 transition-all duration-200 ${isActive ? "font-semibold" : ""}`}>
              {item.label}
            </span>
          </Link>
        );
      })}
    </nav>
  );
};

export default MobileFooterNav;
