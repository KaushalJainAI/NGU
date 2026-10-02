import { Link, useNavigate, useLocation } from "react-router-dom";
import {
  Languages, ChevronDown, Check, Home, ShoppingBag, Package, Gift,
  Heart, User, ShoppingCart,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import SearchAutocomplete from "@/components/SearchAutocomplete";
import { useTranslation } from "react-i18next";
import { useCart } from "@/context/CartContext";
import { useAuth } from "@/context/AuthContext";
import { useLanguage } from "@/context/LanguageContext";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const Navbar = () => {
  const { t } = useTranslation();
  const { language, setLanguage, languages } = useLanguage();
  const navigate = useNavigate();
  const location = useLocation();
  const { cart } = useCart();
  const { isLoggedIn } = useAuth();

  const totalQuantity = cart.reduce((sum, item) => sum + item.quantity, 0);
  const currentLangLabel =
    languages.find((l) => l.code === language)?.label ?? "English";

  // Active-tab styling: highlight the current section with a brand underline.
  const isActivePath = (path: string) =>
    path === "/" ? location.pathname === "/" : location.pathname.startsWith(path);
  const navLinkClass = (path: string, base = "text-foreground") =>
    `hidden md:flex items-center gap-1.5 text-sm font-semibold transition-colors active-press border-b-2 pb-0.5 ${
      isActivePath(path)
        ? "border-primary text-primary"
        : `border-transparent hover:text-primary ${base}`
    }`;

  const handleProfileClick = () => {
    if (isLoggedIn) {
      navigate('/profile');
    } else {
      navigate('/login', { state: { from: '/profile' } });
    }
  };

  // Small badge reused on the cart buttons (desktop + mobile).
  const CartBadge = () =>
    totalQuantity > 0 ? (
      <span className="notranslate absolute -top-0.5 -right-0.5 bg-primary text-primary-foreground text-[10px] w-4 h-4 rounded-full flex items-center justify-center font-bold animate-bounce-in">
        {totalQuantity}
      </span>
    ) : null;

  // A single language menu reused on desktop (with label) and mobile (icon only).
  const LanguageMenu = ({ compact = false }: { compact?: boolean }) => (
    // modal={false}: a nav menu must not lock body scroll — modal mode mutates
    // <body> styles and breaks the sticky navbar (it visually disappears on open).
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        {compact ? (
          <Button variant="ghost" size="icon" className="text-primary font-bold" aria-label={t('nav.language')}>
            <Languages className="h-5 w-5" />
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            className="h-9 px-2 flex items-center gap-1 font-bold text-primary"
            aria-label={t('nav.language')}
          >
            <Languages className="h-4 w-4" />
            <span className="notranslate">{currentLangLabel}</span>
            <ChevronDown className="h-3.5 w-3.5" />
          </Button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        {languages.map((l) => (
          <DropdownMenuItem
            key={l.code}
            onClick={() => setLanguage(l.code)}
            className="flex items-center justify-between"
          >
            <span className="notranslate">{l.label}</span>
            {l.code === language && <Check className="h-4 w-4 text-primary" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );

  return (
    <nav className="sticky top-0 z-50 bg-background/90 border-b border-border backdrop-blur-md shadow-sm">
      <div className="container mx-auto px-4">
        {/* Main Navbar Row */}
        <div className="flex items-center justify-between gap-4 h-16 md:h-18">
          {/* Logo Section */}
          <div className="flex items-center shrink-0">
            <Link to="/" className="flex items-center gap-2">
              <img
                src="/logo.png"
                alt="Logo"
                className="h-9 w-auto md:h-11 object-contain shrink-0"
              />
              {/* Stacked brand lock-up matching the redesign concept. The
                  lock-up must never shrink: with min-w-0 the flex row collapses
                  it to "Ni..." once the search pill competes for space. */}
              <div className="leading-tight notranslate shrink-0">
                <div className="font-extrabold text-primary text-base md:text-lg whitespace-nowrap">Nidhi Masala</div>
                <div className="text-[10px] text-muted-foreground -mt-0.5 whitespace-nowrap">निधि गृह उद्योग</div>
              </div>
            </Link>
          </div>

          {/* Centered search pill — inline only at lg+. On tablet (md) it moves
              to a full-width bar below the nav (see bottom of this component) so
              it isn't squeezed between the logo, nav links and action icons. */}
          <div className="hidden lg:flex flex-1 max-w-md mx-auto">
            <SearchAutocomplete
              placeholder={t('nav.search')}
              inputClassName="w-full"
            />
          </div>

          {/* Desktop nav links + actions */}
          <div className="hidden md:flex items-center gap-4 lg:gap-6 flex-shrink-0">
            <Link to="/" className={navLinkClass("/")}>
              <Home className="h-4 w-4" aria-hidden />{t('nav.home')}
            </Link>
            <Link to="/products" className={navLinkClass("/products")}>
              <ShoppingBag className="h-4 w-4" aria-hidden />{t('nav.products')}
            </Link>
            <Link to="/combos" className={navLinkClass("/combos")}>
              <Package className="h-4 w-4" aria-hidden />{t('nav.combos')}
            </Link>
            <Link to="/offer-zone" className={navLinkClass("/offer-zone", "text-primary")}>
              <Gift className="h-4 w-4" aria-hidden />{t('nav.offers')}
            </Link>

            {/* "More" Dropdown to free up space */}
            {/* modal={false}: prevents Radix's scroll-lock from mutating <body>,
                which otherwise breaks the sticky navbar (it disappears on open). */}
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <button className="hidden lg:flex items-center gap-1 text-sm font-semibold text-foreground hover:text-primary transition-colors outline-none">
                  <span aria-hidden>⋯</span>
                  <span>{t('nav.more')}</span>
                  <ChevronDown className="h-4 w-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <DropdownMenuItem onClick={() => navigate('/about')}>
                  {t('nav.aboutUs')}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => navigate('/contact')}>
                  {t('nav.contact')}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => navigate('/my-orders')}>
                  {t('nav.myOrders')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            <div className="flex items-center gap-1 lg:gap-2 border-l border-border pl-2 lg:pl-4">
              <LanguageMenu />

              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 rounded-full"
                onClick={() => navigate('/favorites')}
                title={t('nav.wishlist')}
              >
                <Heart className="h-5 w-5" aria-hidden />
              </Button>

              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 rounded-full"
                onClick={handleProfileClick}
                title={t('nav.account')}
              >
                <User className="h-5 w-5" aria-hidden />
              </Button>

              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 rounded-full relative"
                onClick={() => navigate('/cart')}
                title={t('nav.cart')}
              >
                <ShoppingCart className="h-5 w-5" aria-hidden />
                <CartBadge />
              </Button>
            </div>
          </div>

          {/* Mobile Actions Only */}
          <div className="md:hidden flex items-center gap-0.5">
            <LanguageMenu compact />
            <Button
              variant="ghost"
              size="icon"
              className="rounded-full"
              onClick={() => navigate('/favorites')}
            >
              <Heart className="h-5 w-5" aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="rounded-full"
              onClick={handleProfileClick}
              title={t('nav.account')}
            >
              <User className="h-5 w-5" aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="relative rounded-full"
              onClick={() => navigate('/cart')}
            >
              <ShoppingCart className="h-5 w-5" aria-hidden />
              <CartBadge />
            </Button>
          </div>
        </div>

        {/* Mobile + tablet search — full-width bar below the nav (hidden once the
            inline pill appears at lg). */}
        <div className="pb-3 lg:hidden">
          <SearchAutocomplete
            placeholder={t('nav.searchMobile')}
            inputClassName="w-full"
          />
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
