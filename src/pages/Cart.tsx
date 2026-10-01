import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Trash2, AlertCircle, ShoppingCart, MapPin, CreditCard, Check, PartyPopper, Sparkles } from "lucide-react";
import { Carousel, CarouselContent, CarouselItem, CarouselNext, CarouselPrevious } from "@/components/ui/carousel";
import ProductCard from "@/components/ProductCard";
import product1 from "@/assets/product-1.jpg";
import product2 from "@/assets/product-2.jpg";
import product3 from "@/assets/product-3.jpg";
import product4 from "@/assets/product-4.jpg";
import { useCart } from "@/context/CartContext";
import { useAuth } from "@/context/AuthContext";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { cartAPI, searchAPI } from "@/lib/api";
import { FREE_SHIPPING_THRESHOLD, SHIPPING_CHARGE, DEFAULT_TAX_RATE, shippingTaxFor } from "@/config/limits";
import { formatWeight, resolveImageUrl } from "@/lib/utils";
import { PriceBreakup } from "@/components/PriceBreakup";


const Cart = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { isLoggedIn } = useAuth();
  const { cart, setCart, updateQuantity, removeFromCart, clearCart } = useCart();
  const [isLoading, setIsLoading] = useState(false);
  const [recommendations, setRecommendations] = useState<any[]>([]);

  // Fetch cart from backend on mount - only once
  useEffect(() => {
    if (!isLoggedIn) {
      toast.warning(t('product.loginRequired'));
      navigate('/login', { state: { from: '/cart' } });
      return;
    }

    const fetchCart = async () => {
      setIsLoading(true);
      try {
        const response = await cartAPI.get();

        if (response.success && response.items && Array.isArray(response.items)) {
          const backendCart = response.items.map((item: any) => ({
            id: Number(item.product_id || item.id),
            itemType: (item.item_type || "product") as "product" | "combo",
            name: item.name,
            image: item.image,
            price: item.price,
            originalPrice: item.originalPrice,
            quantity: item.quantity,
            badge: item.badge,
          }));

          setCart(backendCart);
        }
      } catch (error) {
        console.error('Failed to fetch cart:', error);
        toast.error("Failed to load cart from server.");
      } finally {
        setIsLoading(false);
      }
    };

    fetchCart();
  }, [isLoggedIn]); // Only depend on isLoggedIn

  // Filter in-stock items for checkout
  const inStockItems = cart.filter(item => item.inStock !== false);
  const outOfStockItems = cart.filter(item => item.inStock === false);
  
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

  const handleRemoveItem = async (id: number, itemType: "product" | "combo", variantId?: number | null) => {
    try {
      await removeFromCart(id, itemType, variantId);
      toast.success(t('cart.removed'));
    } catch (error) {
      console.error('Failed to remove item:', error);
      toast.error("Failed to remove item");
    }
  };

  const handleClearCart = async () => {
    try {
      await clearCart();
      toast.success(t('cart.cleared'));
    } catch (error) {
      console.error('Failed to clear cart:', error);
      toast.error("Failed to clear cart");
    }
  };

  const handleCheckout = async () => {
    if (inStockItems.length === 0) {
      toast.error(t('cart.noStock'));
      return;
    }

    setIsLoading(true);
    try {
      // Fetch the latest cart state from backend before checkout
      const response = await cartAPI.get();

      if (!response.success) {
        toast.error("Failed to verify cart");
        return;
      }
      
      if (!response.items || response.items.length === 0) {
        toast.error(t('cart.emptyToast'));
        setCart([]);
        return;
      }

      // Update cart with latest backend data
      const backendCart = response.items.map((item: any) => ({
        id: Number(item.product_id || item.id),
        itemType: (item.item_type || "product") as "product" | "combo",
        name: item.name,
        image: item.image,
        price: item.price,
        originalPrice: item.originalPrice,
        quantity: item.quantity,
        badge: item.badge,
      }));
      
      setCart(backendCart);
      
      // Navigate to billing page
      navigate('/billing');
    } catch (error) {
      console.error('Checkout error:', error);
      toast.error("Could not verify cart with server!");
    } finally {
      setIsLoading(false);
    }
  };

  // Fetch recommendations from backend
  useEffect(() => {
    const fetchRecommendations = async () => {
      try {
        const response = await searchAPI.getRecommendations(8);
        
        // Format products for ProductCard - use correct field names from search API
        const formattedProducts = (response.products || []).map((p: any) => ({
          id: Number(p.id),
          name: p.name,
          image: resolveImageUrl(p.image, product1),
          price: p.price,
          originalPrice: p.original_price > p.price ? p.original_price : undefined,
          weight: formatWeight(p.weight, p.unit, "100g"),
          itemType: "product" as const,
          badge: p.is_featured ? "Featured" : undefined,
        }));
        
        // Format combos for ProductCard
        const formattedCombos = (response.combos || []).map((c: any) => ({
          id: Number(c.id),
          name: c.name || c.display_title,
          image: resolveImageUrl(c.image, product1),
          price: c.price || c.final_price,
          originalPrice: c.original_price > c.price ? c.original_price : undefined,
          weight: "Combo",
          itemType: "combo" as const,
          badge: c.badge || "Combo",
        }));
        
        // Combine and limit to 8 items
        setRecommendations([...formattedProducts, ...formattedCombos].slice(0, 8));
      } catch (error) {
        console.error('Failed to fetch recommendations:', error);
        // Keep empty array on error (don't show recommendations section)
      }
    };

    fetchRecommendations();
  }, []);

  if (isLoading && cart.length === 0) {
    return (
      <>
        <div className="container py-4 sm:py-8 px-3 sm:px-4 pb-24 md:pb-8">
          <div className="flex items-center justify-center min-h-[400px]">
            <p className="text-lg text-muted-foreground">{t('cart.loading')}</p>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="container py-4 sm:py-8 px-3 sm:px-4 pb-24 md:pb-8">
        <h1 className="text-4xl font-bold mb-8">{t('cart.title')}</h1>
        {cart.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-16">
              <p className="text-xl text-muted-foreground mb-4">{t('cart.empty')}</p>
              <Button asChild>
                <a href="/products">{t('cart.continueShopping')}</a>
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="grid lg:grid-cols-3 gap-8">
            <div className="lg:col-span-2 space-y-4">
              {/* Free-shipping progress nudge */}
              {(() => {
                const remaining = Math.max(0, FREE_SHIPPING_THRESHOLD - subtotal);
                const pct = Math.min(100, Math.round((subtotal / FREE_SHIPPING_THRESHOLD) * 100));
                return (
                  <Card className={`border-secondary/30 transition-colors ${remaining === 0 ? "bg-secondary/5 border-secondary/50" : ""}`}>
                    <CardContent className="p-3 sm:p-4">
                      <p className="text-sm font-medium mb-2">
                        {remaining > 0 ? (
                          <>You're <span className="text-primary font-bold">₹{remaining.toFixed(0)} away</span> from FREE shipping!</>
                        ) : (
                          <><PartyPopper className="mr-1 inline h-4 w-4" /> You've unlocked <span className="text-secondary font-bold">FREE shipping!</span></>
                        )}
                      </p>
                      <div className="h-2.5 bg-muted rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all duration-700 ease-out bg-gradient-to-r from-secondary via-primary to-accent bg-[length:200%_100%] animate-shimmer"
                          style={{ width: `${Math.max(pct, 6)}%` }}
                        />
                      </div>
                    </CardContent>
                  </Card>
                );
              })()}
              {cart.map((item) => (
                <Card key={`${item.itemType}-${item.id}-${item.variantId ?? ''}`} className={item.inStock === false ? "opacity-60 border-destructive/30" : ""}>
                  <CardContent className="flex items-center gap-2 sm:gap-4 p-3 sm:p-6">
                    <Link
                      to={item.itemType === 'combo' ? `/combos/${item.id}` : `/products/${item.variantSlug || item.id}`}
                      className="flex-shrink-0"
                    >
                      <img
                        src={item.image}
                        alt={item.name}
                        className="w-16 h-16 sm:w-24 sm:h-24 bg-muted rounded-md object-contain hover:opacity-80 transition-opacity cursor-pointer"
                      />
                    </Link>
                    <div className="flex-1 min-w-0">
                      <Link
                        to={item.itemType === 'combo' ? `/combos/${item.id}` : `/products/${item.variantSlug || item.id}`}
                        className="hover:text-primary transition-colors"
                      >
                        <h3 className="font-semibold text-sm sm:text-lg truncate">{item.name}</h3>
                      </Link>
                      <div className="flex items-center gap-1 text-[10px] sm:text-xs text-muted-foreground mt-0.5">
                        <span>{item.itemType === "combo" ? "Combo" : (item.weight || "Product")}</span>
                        <span>•</span>
                        {item.inStock === false ? (
                          <span className="text-destructive font-medium">{t('product.outOfStock')}</span>
                        ) : (
                          <span className="text-green-600 font-medium">{t('product.inStock')}</span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-primary font-bold text-sm sm:text-base">₹{item.price}</span>
                        {item.originalPrice && (
                          <span className="text-[10px] sm:text-xs text-muted-foreground line-through">
                            ₹{item.originalPrice}
                          </span>
                        )}
                        {item.badge && (
                          <span className="text-[10px] bg-primary/10 text-primary px-1 py-0.5 rounded hidden sm:inline-block">
                            {item.badge}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 sm:gap-2 flex-shrink-0">
                      <Button
                        variant="outline"
                        size="icon"
                        className="h-7 w-7 sm:h-10 sm:w-10"
                        onClick={() => updateQuantity(item.id, item.quantity - 1, item.itemType, item.variantId)}
                        disabled={isLoading || item.inStock === false}
                      >
                        -
                      </Button>
                      <span className="w-6 sm:w-8 text-center text-sm sm:text-base">{item.quantity}</span>
                      <Button
                        variant="outline"
                        size="icon"
                        className="h-7 w-7 sm:h-10 sm:w-10"
                        onClick={() => updateQuantity(item.id, item.quantity + 1, item.itemType, item.variantId)}
                        disabled={isLoading || item.inStock === false}
                      >
                        +
                      </Button>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 sm:h-10 sm:w-10 flex-shrink-0"
                      onClick={() => handleRemoveItem(item.id, item.itemType, item.variantId)}
                      disabled={isLoading}
                    >
                      <Trash2 className="h-4 w-4 sm:h-5 sm:w-5 text-destructive" />
                    </Button>
                  </CardContent>
                </Card>
              ))}
              <div className="flex flex-col sm:flex-row gap-2">
                <Button asChild variant="outline" className="w-full sm:flex-1">
                  <a href="/products">← {t('cart.continueShopping')}</a>
                </Button>
                <Button
                  variant="outline"
                  onClick={handleClearCart}
                  className="w-full sm:flex-1"
                  disabled={isLoading}
                >
                  {t('cart.clearCart')}
                </Button>
              </div>
            </div>
            <div>
              <Card>
                <CardHeader className="py-3 sm:py-4">
                  <CardTitle className="text-base sm:text-lg">{t('cart.orderSummary')}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 sm:space-y-3 py-2 sm:py-4">
                  {outOfStockItems.length > 0 && (
                    <div className="bg-destructive/10 border border-destructive/30 rounded-lg p-2 sm:p-3">
                      <p className="text-xs sm:text-sm text-destructive font-medium flex items-center gap-1 sm:gap-2">
                        <AlertCircle className="h-3 w-3 sm:h-4 sm:w-4" />
                        {outOfStockItems.length} {t('product.outOfStock')}
                      </p>
                    </div>
                  )}
                  <PriceBreakup
                    subtotal={subtotal}
                    tax={tax}
                    taxableValue={subtotal - tax}
                    taxBreakdown={taxBreakdown}
                    shipping={shipping}
                    shippingTax={shippingTax}
                    total={total}
                    freeShippingThreshold={FREE_SHIPPING_THRESHOLD}
                  />
                </CardContent>
                <CardFooter className="py-3 sm:py-4">
                  <Button 
                    className="w-full h-9 sm:h-10 text-sm" 
                    onClick={handleCheckout}
                    disabled={isLoading || inStockItems.length === 0}
                  >
                    {isLoading ? t('cart.processing') : inStockItems.length === 0 ? t('cart.noItems') : t('cart.checkout')}
                  </Button>
                </CardFooter>
              </Card>

              {/* Checkout progress timeline */}
              <div className="mt-4 rounded-lg border border-border bg-card p-4">
                <div className="flex items-center justify-between">
                  {[
                    { Icon: ShoppingCart, label: t('cart.steps.cart', { defaultValue: "Cart" }), active: true },
                    { Icon: MapPin, label: t('cart.steps.address', { defaultValue: "Address" }) },
                    { Icon: CreditCard, label: t('cart.steps.payment', { defaultValue: "Payment" }) },
                    { Icon: Check, label: t('cart.steps.done', { defaultValue: "Done" }) },
                  ].map((step, i, arr) => (
                    <div key={i} className="flex flex-1 flex-col items-center text-center relative">
                      {i < arr.length - 1 && (
                        <span className="absolute top-4 left-1/2 right-[-50%] h-0.5 bg-border" />
                      )}
                      <span
                        className={`relative z-10 grid h-8 w-8 place-items-center rounded-full transition-colors ${
                          step.active
                            ? "bg-primary text-primary-foreground shadow-md shadow-primary/30"
                            : "bg-muted text-muted-foreground"
                        }`}
                      >
                        <step.Icon className="h-4 w-4" />
                      </span>
                      <span className={`mt-1.5 text-[10px] sm:text-xs font-medium ${step.active ? "text-primary" : "text-muted-foreground"}`}>
                        {step.label}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
        {cart.length > 0 && recommendations.length > 0 && (
          <section className="mt-8 sm:mt-12 rounded-xl border-2 border-dashed border-primary/40 bg-primary/[0.03] p-4 sm:p-6">
              <h2 className="text-xl sm:text-2xl font-bold mb-4 sm:mb-6 flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-primary" />{t('cart.peopleAlsoBuy')}
              </h2>
            <Carousel opts={{ align: "start" }} className="w-full">
              <CarouselContent className="-ml-2 sm:-ml-4">
                {recommendations.map((product) => (
                  <CarouselItem key={`${product.itemType}-${product.id}`} className="pl-2 sm:pl-4 basis-1/2 sm:basis-1/3 lg:basis-1/4">
                    <ProductCard {...product} />
                  </CarouselItem>
                ))}
              </CarouselContent>
              <CarouselPrevious className="hidden sm:flex" />
              <CarouselNext className="hidden sm:flex" />
            </Carousel>
          </section>
        )}
      </div>
    </>
  );
};

export default Cart;
