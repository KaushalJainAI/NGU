import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Minus, Plus, ShoppingBag, Check, ArrowRight, Sparkles } from "lucide-react";
import { useCart } from "@/context/CartContext";
import { useAuth } from "@/context/AuthContext";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import CachedImage from "@/components/CachedImage";
import { trackEvent } from "@/lib/api/analytics";
import { useTranslation } from "react-i18next";
import type { Combo } from "@/lib/api/combos";

interface ComboStoryCardProps {
  combo: Combo;
  /** Flip image to the right on alternating rows for editorial rhythm. */
  reverse?: boolean;
}

/**
 * Editorial "spotlight" layout for a single combo. Where ComboCard is a compact
 * grid tile, this leads with the combo's story (description / subtitle) to make
 * the case for the bundle — the narrative that turns a list of spices into a
 * reason to buy.
 */
const ComboStoryCard = ({ combo, reverse = false }: ComboStoryCardProps) => {
  const { t } = useTranslation();
  const { isLoggedIn } = useAuth();
  const { cart, addToCart, updateQuantity } = useCart();
  const navigate = useNavigate();

  const id = Number(combo.id);
  const name = combo.display_title || combo.title || combo.name;
  const items = combo.items || [];
  const itemCount = items.reduce((sum, it) => sum + (it.quantity || 1), 0);

  const price = Number(combo.final_price ?? combo.price);
  const mrp = combo.discount_price ? Number(combo.price) : Number(combo.total_original_price);
  const discountPercent = mrp && mrp > price ? Math.round((1 - price / mrp) * 100) : 0;
  const saveAmount = mrp && mrp > price ? Math.round(mrp - price) : 0;

  const heroImage = combo.image || items[0]?.product_image || "";
  const itemInCart = cart.find((it) => it.id === id && it.itemType === "combo");
  // A payload that predates the flag has none: treat that as buildable.
  const inStock = combo.in_stock !== false;

  // The story: prefer the editor's description; otherwise synthesise an honest
  // hook from the bundle's contents and savings so every combo still "sells".
  const story =
    combo.description?.trim() ||
    (saveAmount > 0
      ? t('combo.defaultStorySavings', { count: itemCount, amount: saveAmount })
      : t('combo.defaultStory', { count: itemCount }));

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

  const handleClick = () => trackEvent({ event_type: "click", combo_id: id });

  const collage = items.slice(0, 4);
  const extra = items.length - collage.length;

  return (
    <div className="group grid items-stretch gap-0 overflow-hidden rounded-2xl border border-border/80 bg-card shadow-sm transition-all duration-300 hover:border-primary/30 hover:shadow-[0_22px_46px_-26px_hsl(var(--primary)/0.55)] md:grid-cols-2">
      {/* Visual side */}
      <Link
        to={`/combos/${id}`}
        onClick={handleClick}
        className={`relative spice-backdrop p-5 sm:p-7 ${reverse ? "md:order-2" : ""}`}
      >
        <div className="absolute left-4 top-4 z-[2] flex flex-wrap gap-2">
          {combo.is_featured && (
            <Badge className="rounded-full bg-accent px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-accent-foreground shadow-sm sm:text-xs">
              <Sparkles className="mr-1 h-3 w-3" />
              {t('product.featured')}
            </Badge>
          )}
          {discountPercent > 0 && (
            <Badge className="rounded-full bg-secondary px-2.5 py-1 text-[10px] font-bold text-secondary-foreground shadow-sm sm:text-xs">
              {discountPercent}{t('product.off')}
            </Badge>
          )}
        </div>

        {combo.image ? (
          <div className="relative z-[1] mx-auto aspect-square max-w-sm overflow-hidden rounded-xl border border-border/60 bg-background/70">
            <CachedImage
              src={combo.image}
              alt={name}
              className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]"
            />
          </div>
        ) : (
          <div className="relative z-[1] mx-auto grid max-w-sm grid-cols-2 gap-2.5">
            {collage.map((it, i) => (
              <div
                key={it.product ?? i}
                className="relative aspect-square overflow-hidden rounded-xl border border-border/60 bg-background/70"
              >
                <CachedImage
                  src={it.product_thumbnail || it.product_image}
                  alt={it.product_name}
                  className="h-full w-full object-contain p-2 transition-transform duration-500 group-hover:scale-[1.06]"
                />
                {it.quantity > 1 && (
                  <span className="absolute bottom-1 right-1 rounded-md bg-foreground/80 px-1 text-[9px] font-bold text-background">
                    ×{it.quantity}
                  </span>
                )}
              </div>
            ))}
            {extra > 0 && (
              <div className="flex aspect-square items-center justify-center rounded-xl border border-dashed border-primary/40 bg-primary/5 text-base font-bold text-primary">
                +{extra}
              </div>
            )}
          </div>
        )}
      </Link>

      {/* Story side */}
      <div className={`flex flex-col justify-center p-5 sm:p-7 ${reverse ? "md:order-1" : ""}`}>
        <span className="mb-2 inline-flex w-fit items-center gap-1.5 rounded-full bg-primary/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-primary sm:text-xs">
          {combo.badge || t('combo.pieceKit', { count: itemCount })}
        </span>

        <Link to={`/combos/${id}`} onClick={handleClick}>
          <h3 className="text-xl font-extrabold leading-snug text-foreground transition-colors group-hover:text-primary sm:text-2xl">
            {name}
          </h3>
        </Link>
        {combo.subtitle && (
          <p className="mt-1 text-sm font-medium text-primary/90">{combo.subtitle}</p>
        )}

        {/* The story */}
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground line-clamp-4">{story}</p>

        {/* What's inside */}
        {items.length > 0 && (
          <ul className="mt-4 flex flex-wrap gap-1.5">
            {items.slice(0, 5).map((it, i) => (
              <li
                key={it.product ?? i}
                className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2.5 py-1 text-[11px] font-medium text-foreground sm:text-xs"
              >
                <Check className="h-3 w-3 text-secondary" />
                {it.product_name}
              </li>
            ))}
            {items.length > 5 && (
              <li className="inline-flex items-center rounded-full bg-primary/5 px-2.5 py-1 text-[11px] font-semibold text-primary sm:text-xs">
                +{items.length - 5} {t('combo.more')}
              </li>
            )}
          </ul>
        )}

        {/* Price + actions */}
        <div className="mt-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-extrabold text-primary sm:text-3xl">₹{price}</span>
              {mrp > price && (
                <span className="text-sm text-muted-foreground line-through">₹{mrp}</span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {!inStock ? (
              <Button disabled variant="outline" className="h-10 rounded-full px-5 font-bold">
                {t('product.outOfStock')}
              </Button>
            ) : itemInCart ? (
              <div className="flex h-10 animate-bounce-in items-center gap-1 rounded-full bg-primary px-1 text-primary-foreground">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => updateQuantity(id, itemInCart.quantity - 1, "combo")}
                  className="h-8 px-3 text-primary-foreground hover:bg-white/20 hover:text-primary-foreground active-press"
                >
                  <Minus className="h-4 w-4" />
                </Button>
                <span className="min-w-[2rem] text-center font-bold">{itemInCart.quantity}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => updateQuantity(id, itemInCart.quantity + 1, "combo")}
                  className="h-8 px-3 text-primary-foreground hover:bg-white/20 hover:text-primary-foreground active-press"
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            ) : (
              <Button
                onClick={handleAddToCart}
                className="h-10 rounded-full px-5 font-bold shadow-lg shadow-primary/25 hover:brightness-110 active-press"
              >
                <ShoppingBag className="mr-1.5 h-4 w-4" />
                {t('combo.addBundle')}
              </Button>
            )}
            <Button
              asChild
              variant="outline"
              className="h-10 rounded-full border-2 border-primary px-4 font-bold text-primary hover:bg-primary/10 active-press"
            >
              <Link to={`/combos/${id}`} onClick={handleClick}>
                {t('combo.details')}
                <ArrowRight className="ml-1.5 h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ComboStoryCard;
