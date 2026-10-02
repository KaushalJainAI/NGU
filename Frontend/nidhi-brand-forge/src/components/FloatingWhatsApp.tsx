import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useCart } from "@/context/CartContext";

const FloatingWhatsApp = () => {
  const { t } = useTranslation();
  const { cart } = useCart();
  const location = useLocation();
  // AP12: at most one floating action at a time on phones — the cart bar owns
  // the slot whenever it shows (same visibility rule, mirrored here), so the
  // two never stack above the bottom nav.
  const hasItems = cart.reduce((sum, item) => sum + item.quantity, 0) > 0;
  const cartBarVisible =
    hasItems && !["/cart", "/billing", "/checkout"].includes(location.pathname);
  if (cartBarVisible) return null;
  // The cart page pins its own checkout bar in this slot on phones.
  const checkoutBarVisible = hasItems && location.pathname === "/cart";
  return (
    <a
      href="https://wa.me/919300005040"
      target="_blank"
      rel="noopener noreferrer"
      aria-label={t('footer.whatsapp')}
      className={`fixed right-6 z-50 md:bottom-24 bottom-28
                 h-14 w-14 rounded-full shadow-lg hover:shadow-xl
                 ${checkoutBarVisible ? "hidden md:flex" : "flex"} items-center justify-center
                 bg-[#25D366] hover:bg-[#20b858]
                 transition-all duration-300 hover:scale-110 active:scale-95`}
    >
      {/* WhatsApp SVG */}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 32 32"
        className="h-7 w-7"
        fill="white"
      >
        <path d="M16 0C7.164 0 0 7.163 0 16c0 2.82.737 5.469 2.027 7.774L0 32l8.489-2.001A15.93 15.93 0 0016 32c8.837 0 16-7.163 16-16S24.837 0 16 0zm0 29.23a13.21 13.21 0 01-6.737-1.844l-.483-.287-4.99 1.177 1.243-4.857-.317-.499A13.19 13.19 0 012.77 16C2.77 8.686 8.686 2.77 16 2.77S29.23 8.686 29.23 16 23.314 29.23 16 29.23zm7.24-9.875c-.397-.199-2.347-1.158-2.71-1.29-.364-.132-.63-.198-.895.199-.265.397-1.027 1.29-1.259 1.556-.232.265-.464.298-.861.1-.397-.2-1.676-.618-3.192-1.972-1.18-1.053-1.977-2.353-2.208-2.75-.232-.397-.025-.611.174-.809.18-.178.397-.464.596-.696.199-.232.265-.397.397-.662.132-.265.066-.497-.033-.696-.1-.199-.895-2.156-1.226-2.952-.323-.774-.65-.669-.895-.681l-.762-.013c-.265 0-.695.1-1.059.497-.364.397-1.39 1.358-1.39 3.312s1.423 3.842 1.622 4.107c.199.265 2.8 4.273 6.782 5.993.948.41 1.688.654 2.265.838.952.303 1.818.26 2.503.157.763-.114 2.347-.959 2.678-1.884.33-.925.33-1.718.232-1.884-.099-.166-.364-.265-.762-.464z" />
      </svg>
    </a>
  );
};

export default FloatingWhatsApp;
