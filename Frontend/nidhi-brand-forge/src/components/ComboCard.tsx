import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Minus, Plus, Heart, ShoppingBag, Package, Check } from "lucide-react";
import { useCart } from "@/context/CartContext";
import { useFavorites } from "@/context/FavoritesContext";
import { toast } from "sonner";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import CachedImage from "@/components/CachedImage";
import { trackEvent } from "@/lib/api/analytics";
import { useTranslation } from "react-i18next";
import type { Combo } from "@/lib/api/combos";

interface ComboCardProps {
  combo: Combo;
}

/**
 * Dedicated bundle card for combos. Unlike a product, a combo has no single
 * hero image, so the card leads with a collage of the products inside it and
 * a "what's included" list — making the value of the bundle obvious at a glance.
 */
const ComboCard = ({ combo }: ComboCardProps) => {
  const { t } = useTranslation();
  const { isLoggedIn } = useAuth();
  const { cart, addToCart, updateQuantity } = useCart();
  const { isFavorite, toggleFavorite } = useFavorites();
  const navigate = useNavigate();

  const id = Number(combo.id);
  const name = combo.display_title || combo.title || combo.name;
  const items = combo.items || [];
  const itemCount = items.reduce((sum, it) => sum + (it.quantity || 1), 0);

  const price = Number(combo.final_price ?? combo.price);
  const mrp = combo.discount_price ? Number(combo.price) : Number(combo.total_original_price);
  // AP12: the discount shows ONCE per card (the ribbon badge above).
  const discountPercent =
    mrp && mrp > price ? Math.round((1 - price / mrp) * 100) : 0;

  // Prefer the combo's own image; otherwise fall back to the first item's image.
  const heroImage = combo.image || items[0]?.product_image || "";

  const itemInCart = cart.find((it) => it.id === id && it.itemType === "combo");
  // A payload that predates the flag has none: treat that as buildable.
  const inStock = combo.in_stock !== false;

  const handleAddToCart = () => {
    if (!isLoggedIn) {
      toast.warning(t('product.loginRequired'));
      navigate("/login", { state: { from: "/cart" } });
      return;
    }
    addToCart({
      id,
      itemType: "combo",
      name,
      image: heroImage,
      price,
      originalPrice: mrp || undefined,
      badge: combo.badge || "Combo",
    });
  };

  const handleToggleFavorite = () => {
    if (!isFavorite(id)) {
      trackEvent({ event_type: "favorite", combo_id: id });
    }
    toggleFavorite({
      id,
      name,
      image: heroImage,
      price,
      originalPrice: mrp || undefined,
      badge: combo.badge || "Combo",
      weight: combo.total_weight,
    });
    toast.success(isFavorite(id) ? t('product.removedFromFavorites') : t('product.addedToFavorites'));
  };

  const handleCardClick = () => {
    trackEvent({ event_type: "click", combo_id: id });
  };

  // Up to 3 thumbnails in the collage; the rest collapse into a "+N" tile.
  const collage = items.slice(0, 3);
  const extra = items.length - collage.length;

  return (
    <Card className="group flex h-full flex-col overflow-hidden rounded-2xl border border-border/80 bg-card shadow-sm transition-colors duration-300 hover:border-primary/30">
      <Link
        to={`/combos/${id}`}
        onClick={handleCardClick}
        className="flex flex-grow flex-col"
      >
        <CardContent className="flex h-full flex-col p-0">
          {/* Bundle hero: collage of products inside */}
          <div className="relative spice-backdrop px-3 pt-4 pb-3">
            {/* Top ribbon — hidden when a combo image already carries these badges */}
            {!combo.image && (
            <div className="relative z-[2] mb-2.5 flex items-center justify-between">
              <span className="inline-flex items-center gap-1 rounded-full bg-primary/90 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-primary-foreground shadow-sm sm:text-xs">
                <Package className="h-3 w-3" />
                {itemCount} {t('combo.items')}
              </span>
              {discountPercent > 0 && (
                <Badge className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-bold text-secondary-foreground shadow-sm sm:text-xs">
                  {discountPercent}{t('product.off')}
                </Badge>
              )}
            </div>
            )}

            {combo.image ? (
              <div className="relative z-[1] aspect-square overflow-hidden rounded-xl border border-border/60 bg-background/70">
                <CachedImage
                  src={combo.image}
                  alt={name}
                  className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.05]"
                />
              </div>
            ) : (
            <div className="relative z-[1] grid grid-cols-3 gap-1.5 sm:gap-2">
              {collage.map((it, i) => (
                <div
                  key={it.product ?? i}
                  className="relative aspect-square overflow-hidden rounded-xl border border-border/60 bg-background/70 backdrop-blur-sm"
                >
                  <CachedImage
                    src={it.product_thumbnail || it.product_image}
                    alt={it.product_name}
                    className="h-full w-full object-contain p-1.5 transition-transform duration-500 group-hover:scale-[1.08]"
                  />
                  {it.quantity > 1 && (
                    <span className="absolute bottom-0.5 right-0.5 rounded-md bg-foreground/80 px-1 text-[9px] font-bold text-background">
                      ×{it.quantity}
                    </span>
                  )}
                </div>
              ))}
              {extra > 0 && (
                <div className="flex aspect-square items-center justify-center rounded-xl border border-dashed border-primary/40 bg-primary/5 text-sm font-bold text-primary">
                  +{extra}
                </div>
              )}
            </div>
            )}

            <Button
              variant="ghost"
              size="icon"
              className={`absolute bottom-2 right-3 z-[2] h-8 w-8 rounded-full bg-background/85 shadow-sm backdrop-blur-sm hover:bg-background active-press sm:h-9 sm:w-9 ${
                isFavorite(id) ? "text-red-500" : "text-muted-foreground"
              }`}
              onClick={(e) => {
                e.preventDefault();
                handleToggleFavorite();
              }}
            >
              <Heart className={`h-4 w-4 ${isFavorite(id) ? "fill-current" : ""}`} />
            </Button>
          </div>

          {/* Body */}
          <div className="flex flex-grow flex-col p-3 sm:p-4">
            <h3 className="mb-1 line-clamp-2 min-h-[2.3rem] text-sm font-bold leading-snug text-foreground sm:min-h-[2.6rem] sm:text-base">
              {name}
            </h3>
            {combo.subtitle && (
              <p className="mb-2 line-clamp-1 text-[11px] text-muted-foreground sm:text-xs">
                {combo.subtitle}
              </p>
            )}

            {/* What's inside — skipped when the combo image already lists contents */}
            {!combo.image && (
            <ul className="mb-3 hidden space-y-0.5 sm:block">
              {items.slice(0, 3).map((it, i) => (
                <li
                  key={it.product ?? i}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground"
                >
                  <Check className="h-3 w-3 shrink-0 text-primary" />
                  <span className="line-clamp-1">{it.product_name}</span>
                </li>
              ))}
              {items.length > 3 && (
                <li className="pl-[1.125rem] text-xs font-medium text-primary">
                  + {items.length - 3} {t('combo.more')}
                </li>
              )}
            </ul>
            )}

            {/* Price (discount already badged in the ribbon above) */}
            <div className="mt-auto">
              <div className="mb-1 flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
                <span className="text-lg font-bold text-primary sm:text-xl">₹{price}</span>
                {mrp > price && (
                  <span className="text-xs text-muted-foreground line-through sm:text-sm">
                    ₹{mrp}
                  </span>
                )}
              </div>
            </div>
          </div>
        </CardContent>
      </Link>

      {/* Action */}
      <div className="mt-auto px-3 pb-3 sm:px-4 sm:pb-4">
        {!inStock ? (
          <Button disabled variant="outline" className="h-9 w-full rounded-lg text-xs font-bold sm:h-10 sm:text-sm" size="sm">
            {t("product.outOfStock")}
          </Button>
        ) : itemInCart ? (
          <div className="flex h-9 animate-bounce-in items-center justify-between gap-1 rounded-lg bg-primary px-1 text-primary-foreground sm:h-10 sm:gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => updateQuantity(id, itemInCart.quantity - 1, "combo")}
              className="h-7 px-2 text-primary-foreground hover:bg-white/20 hover:text-primary-foreground active-press sm:h-9 sm:px-3"
            >
              <Minus className="h-3 w-3 sm:h-4 sm:w-4" />
            </Button>
            <span className="min-w-[1.5rem] text-center text-xs font-bold sm:min-w-[2rem] sm:text-base">
              {itemInCart.quantity}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => updateQuantity(id, itemInCart.quantity + 1, "combo")}
              className="h-7 px-2 text-primary-foreground hover:bg-white/20 hover:text-primary-foreground active-press sm:h-9 sm:px-3"
            >
              <Plus className="h-3 w-3 sm:h-4 sm:w-4" />
            </Button>
          </div>
        ) : (
          <Button
            onClick={handleAddToCart}
            className="h-9 w-full rounded-lg bg-primary text-xs font-bold text-primary-foreground hover:bg-primary/90 active-press sm:h-10 sm:text-sm"
            size="sm"
          >
            <ShoppingBag className="mr-1.5 h-3.5 w-3.5" />
            {t("product.addToCart")}
          </Button>
        )}
      </div>
    </Card>
  );
};

export default ComboCard;
