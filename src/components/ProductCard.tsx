import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Minus, Plus, Heart, ShoppingBag } from "lucide-react";
import { useCart } from "@/context/CartContext";
import { useFavorites } from "@/context/FavoritesContext";
import { toast } from "sonner";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import CachedImage from "@/components/CachedImage";
import { trackEvent } from "@/lib/api/analytics";
import { useTranslation } from "react-i18next";


interface ProductCardProps {
  id: number;
  name: string;
  image: string;
  price: number;
  originalPrice?: number;
  badge?: string;
  weight?: string | number;
  itemType?: "product" | "combo";
  variantCount?: number;
}


const ProductCard = ({
  id,
  name,
  image,
  price,
  originalPrice,
  badge,
  // AP12: no made-up default — a product with no weight shows none, not "100g".
  weight,
  itemType,
  variantCount = 1,
}: ProductCardProps) => {
  const { t } = useTranslation();
  const { isLoggedIn } = useAuth();
  const { cart, addToCart, updateQuantity } = useCart();
  const { isFavorite: checkIsFavorite, toggleFavorite } = useFavorites();
  const navigate = useNavigate();

  // Products offered in more than one packaging size are chosen on the detail
  // page (each size is a separate cart entry), so the card links there instead
  // of adding a single default size.
  const hasMultipleSizes = itemType !== "combo" && (variantCount ?? 1) > 1;

  // Find item by BOTH id AND itemType
  const itemInCart = cart.find(item => item.id === id && item.itemType === itemType);

  const handleAddToCart = () => {
    if (!isLoggedIn) {
      toast.warning(t('product.loginRequired'));
      navigate('/login', { state: { from: '/cart' } });
      return;
    }
    addToCart({
      id,
      itemType,  // Include itemType
      name,
      image,
      price,
      originalPrice,
      badge,
    });
    // toast.success("Added to cart");
  };

  const handleToggleFavorite = () => {
    // Only the "add" direction is a positive taste signal worth tracking.
    if (!checkIsFavorite(id)) {
      trackEvent({ event_type: "favorite", [itemType === "combo" ? "combo_id" : "product_id"]: id });
    }
    toggleFavorite({ id, name, image, price, originalPrice, badge, weight });
    toast.success(checkIsFavorite(id) ? t('product.removedFromFavorites') : t('product.addedToFavorites'));
  };

  const handleCardClick = () => {
    trackEvent({ event_type: "click", [itemType === "combo" ? "combo_id" : "product_id"]: id });
  };

  // Some callers pass a bare numeric weight (e.g. 100 from a favorite saved off
  // the catalog list) with no unit. Append "g" so it never renders as just "100".
  // Missing weight renders nothing (AP12 — never a made-up "100g").
  const displayWeight =
    weight === undefined || weight === null || String(weight).trim() === ""
      ? ""
      : typeof weight === "number" || /^\s*\d+(\.\d+)?\s*$/.test(String(weight))
        ? `${String(weight).trim()}g`
        : weight;

  // The discount is shown ONCE per card (AP12): the badge below. No separate
  // "% off" text or "you save" line.
  const discountPercent =
    originalPrice && originalPrice > price
      ? Math.round((1 - price / originalPrice) * 100)
      : 0;

  return (
    <Card className="group flex h-full flex-col overflow-hidden rounded-lg border border-border/80 bg-card shadow-sm transition-colors duration-300 hover:border-primary/25">
      <Link to={itemType === 'combo' ? `/combos/${id}` : `/products/${id}`} onClick={handleCardClick} className="flex-grow flex flex-col">
        <CardContent className="p-0 flex flex-col h-full">
          <div className="relative overflow-hidden spice-backdrop px-2 pt-3 sm:px-3 sm:pt-4">
            <CachedImage
              src={image}
              alt={name}
              cldWidth={220}
              className="relative z-[1] h-32 w-full object-contain transition-transform duration-500 group-hover:scale-[1.08] sm:h-44"
            />
            {/* Discount badge takes priority; otherwise show the text badge */}
            {discountPercent > 0 ? (
              <Badge className="absolute z-10 top-1 sm:top-2 left-1 sm:left-2 bg-secondary text-secondary-foreground text-[10px] sm:text-xs px-1.5 sm:px-2 rounded-full">
                {discountPercent}{t('product.off')}
              </Badge>
            ) : badge ? (
              <Badge className="absolute z-10 top-1 sm:top-2 left-1 sm:left-2 bg-accent text-accent-foreground text-[10px] sm:text-xs px-1.5 sm:px-2 rounded-full">
                {badge}
              </Badge>
            ) : null}
            {hasMultipleSizes && (
              <Badge className="absolute z-10 bottom-1 sm:bottom-2 left-1 sm:left-2 bg-secondary text-secondary-foreground text-[10px] sm:text-xs px-1 sm:px-2">
                {variantCount} {t('product.sizes')}
              </Badge>
            )}
            <Button
              variant="ghost"
              size="icon"
              className={`absolute z-10 top-1 sm:top-2 right-1 sm:right-2 h-7 w-7 sm:h-9 sm:w-9 rounded-full bg-background/80 backdrop-blur-sm hover:bg-background active-press ${
                checkIsFavorite(id) ? "text-red-500" : "text-muted-foreground"
              }`}
              onClick={(e) => {
                e.preventDefault();
                handleToggleFavorite();
              }}
            >
              <Heart className={`h-3 w-3 sm:h-4 sm:w-4 ${checkIsFavorite(id) ? "fill-current" : ""}`} />
            </Button>
          </div>
          <div className="p-3 sm:p-4 flex-grow flex flex-col">
            <h3 className="font-semibold text-foreground mb-1.5 sm:mb-2 line-clamp-2 min-h-[2.3rem] sm:min-h-[2.85rem] text-sm sm:text-base leading-snug flex-grow">
              {name}
            </h3>
            <div className="mt-auto">
              <div className="flex items-baseline flex-wrap gap-x-1.5 gap-y-0.5 mb-1.5">
                {hasMultipleSizes && (
                  <span className="text-[10px] sm:text-xs text-muted-foreground">{t('product.from')}</span>
                )}
                <span className="text-sm sm:text-lg font-bold text-primary">₹{price}</span>
                {originalPrice && originalPrice > price && (
                  <span className="text-xs sm:text-sm text-muted-foreground line-through">
                    ₹{originalPrice}
                  </span>
                )}
              </div>
              {displayWeight ? (
                <p className="text-[11px] sm:text-xs text-muted-foreground">{displayWeight}</p>
              ) : null}
            </div>
          </div>
        </CardContent>
      </Link>
      <div className="px-3 sm:px-4 pb-3 sm:pb-4 mt-auto">
        {hasMultipleSizes ? (
          <Button asChild className="w-full h-9 sm:h-10 text-xs sm:text-sm rounded-lg border-2 border-primary text-primary font-bold hover:bg-primary/10 active-press" size="sm" variant="outline">
            <Link to={`/products/${id}`} onClick={handleCardClick}>{t('product.selectSize')}</Link>
          </Button>
        ) : itemInCart ? (
          <div className="flex items-center justify-between gap-1 sm:gap-2 bg-primary text-primary-foreground rounded-lg h-9 sm:h-10 px-1 animate-bounce-in">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => updateQuantity(id, itemInCart.quantity - 1, itemType)}
              className="h-7 sm:h-9 px-2 sm:px-3 text-primary-foreground hover:bg-white/20 hover:text-primary-foreground active-press"
            >
              <Minus className="h-3 w-3 sm:h-4 sm:w-4" />
            </Button>
            <span className="font-bold min-w-[1.5rem] sm:min-w-[2rem] text-center text-xs sm:text-base">
              {itemInCart.quantity}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => updateQuantity(id, itemInCart.quantity + 1, itemType)}
              className="h-7 sm:h-9 px-2 sm:px-3 text-primary-foreground hover:bg-white/20 hover:text-primary-foreground active-press"
            >
              <Plus className="h-3 w-3 sm:h-4 sm:w-4" />
            </Button>
          </div>
        ) : (
          <Button
            onClick={handleAddToCart}
            variant="outline"
            className="w-full h-9 sm:h-10 text-xs sm:text-sm rounded-lg border-2 border-primary text-primary font-bold hover:bg-primary/10 active-press"
            size="sm"
          >
            <ShoppingBag className="mr-1.5 h-3.5 w-3.5" />
            {t('product.addToCart')}
          </Button>
        )}
      </div>
    </Card>
  );
};


export default ProductCard;
