import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useCart } from "@/context/CartContext";
import Footer from "@/components/Footer";
import ProductCard from "@/components/ProductCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Minus, Plus, Sparkles, Loader2, ShoppingCart, Eye } from "lucide-react";
import { toast } from "sonner";
import { productsAPI, combosAPI } from "@/lib/api";
import product1 from "@/assets/product-1.jpg";
import product2 from "@/assets/product-2.jpg";
import product3 from "@/assets/product-3.jpg";
import product4 from "@/assets/product-4.jpg";
import heroVideo from "@/assets/grok-video-2e290515-947f-4dd0-baca-4581ae53774a (1).mp4";
import { useTranslation } from "react-i18next";
import { formatWeight } from "@/lib/utils";

const comboImages = [product1, product2, product3, product4];

const OfferZone = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { cart, addToCart, updateQuantity } = useCart();
  const [loading, setLoading] = useState(true);
  const [hotDeals, setHotDeals] = useState<any[]>([]);
  const [comboOffers, setComboOffers] = useState<any[]>([]);

  useEffect(() => {
    const fetchOfferData = async () => {
      setLoading(true);
      try {
        // Both list endpoints have `pagination_class = None` and return a plain
        // array, so a failure falls back to an empty one. The old fallback was
        // `{ results: [] }`, which forced every read through a `.results ||`
        // dance for a paginated shape neither endpoint has ever returned.
        const [products, combos] = await Promise.all([
          productsAPI.getAll().catch(() => []),
          combosAPI.getAll().catch(() => []),
        ]);

        // Filter products that have discounts for Hot Deals
        const discountedProducts = products
          .filter((p: any) => p.discount_price || p.final_price < p.price || p.badge)
          .map((p: any) => ({
            id: Number(p.id),
            name: p.name,
            image: p.image || product1,
            price: p.final_price || p.discount_price || p.price,
            originalPrice: p.price,
            badge: p.badge || `${Math.round(((p.price - (p.final_price || p.discount_price || p.price)) / p.price) * 100)}${t('product.off')}`,
            weight: formatWeight(p.weight, p.unit, "100g"),
            itemType: "product" as const,
            inStock: p.in_stock !== false,
          }));

        // Format combos with images
        const formattedCombos = combos.map((c: any, index: number) => ({
          id: Number(c.id),
          slug: c.slug || c.id,
          title: c.display_title || c.name,
          description: c.subtitle || c.description || t('combo.productBundle', { count: c.products?.length || 0 }),
          price: c.final_price || c.price,
          originalPrice: c.total_original_price || c.price,
          badge: c.badge || t('combo.comboDeal'),
          image: c.image || comboImages[index % comboImages.length],
          productCount: c.products?.length || 0,
          inStock: c.in_stock !== false,
        }));

        setHotDeals(discountedProducts);
        setComboOffers(formattedCombos);
      } catch (error) {
        console.error("Failed to fetch offer data:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchOfferData();
  }, []);

  const handleComboClick = (combo: any) => {
    navigate(`/combos/${combo.slug}`);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex flex-col pb-20 md:pb-0">
        <main className="flex-grow flex items-center justify-center">
          <Loader2 className="h-12 w-12 animate-spin text-primary" />
        </main>
        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-24">
      {/* Video Hero Section */}
      <section className="relative h-[280px] sm:h-[400px] md:h-[500px] overflow-hidden">
        <video
          autoPlay
          muted
          loop
          playsInline
          className="absolute inset-0 w-full h-full object-cover"
        >
          <source src={heroVideo} type="video/mp4" />
        </video>
        {/* Gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-background via-background/60 to-transparent" />
        <div className="absolute inset-0 bg-gradient-to-r from-primary/30 via-transparent to-accent/30" />
        
        {/* Content */}
        <div className="relative h-full container mx-auto px-4 flex flex-col items-center justify-center text-center">
          <div className="flex items-center justify-center mb-3 sm:mb-4">
            <Sparkles className="h-8 w-8 sm:h-12 sm:w-12 text-accent animate-pulse" />
          </div>
          <h1 className="text-3xl sm:text-5xl md:text-6xl font-bold text-foreground mb-2 sm:mb-4 drop-shadow-lg">
            {t('offerZone.heroTitle')}
          </h1>
          <p className="text-base sm:text-xl text-foreground/90 max-w-2xl mx-auto drop-shadow-md">
            {t('offerZone.heroSubtitle')}
          </p>
          <Badge variant="default" className="mt-4 text-sm sm:text-base px-4 py-2 animate-bounce">
            {t('offerZone.heroBadge')}
          </Badge>
        </div>
      </section>

      {/* Combo Offers */}
      <section className="py-8 sm:py-16">
        <div className="container mx-auto px-3 sm:px-4">
          {comboOffers.length > 0 && (
            <>
              <div className="text-center mb-6 sm:mb-10">
                <h2 className="text-2xl sm:text-4xl font-bold mb-2">
                  <span className="text-primary">
                    {t('offerZone.comboOffersTitle')}
                  </span>
                </h2>
                <p className="text-muted-foreground text-sm sm:text-base">{t('offerZone.comboOffersSubtitle')}</p>
              </div>
              
              <div className="grid md:grid-cols-2 gap-4 sm:gap-6 max-w-5xl mx-auto mb-12 sm:mb-20">
                {comboOffers.map((combo) => {
                  const itemInCart = cart.find(item => item.id === combo.id && item.itemType === "combo");
                  const savings = combo.originalPrice > combo.price 
                    ? Math.round(((combo.originalPrice - combo.price) / combo.originalPrice) * 100)
                    : 0;
                  
                  return (
                    <div 
                      key={combo.id} 
                      className="group bg-card border border-border rounded-2xl overflow-hidden hover:shadow-2xl transition-all duration-300 hover:-translate-y-1 cursor-pointer"
                      onClick={() => handleComboClick(combo)}
                    >
                      {/* Combo Image */}
                      <div className="relative h-40 sm:h-52 overflow-hidden">
                        <img 
                          src={combo.image} 
                          alt={combo.title}
                          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                        />
                        {/* Gradient overlay on image */}
                        <div className="absolute inset-0 bg-gradient-to-t from-card/80 to-transparent" />
                        
                        {/* Badge */}
                        <div className="absolute top-3 left-3">
                          <Badge className="text-xs px-2 py-1 bg-primary text-primary-foreground shadow-lg">
                            {combo.badge}
                          </Badge>
                        </div>
                        
                        {/* Savings badge */}
                        {savings > 0 && (
                          <div className="absolute top-3 right-3">
                            <Badge variant="destructive" className="text-xs px-2 py-1 shadow-lg">
                              {t('combo.savePercent', { percent: savings })}
                            </Badge>
                          </div>
                        )}

                        {/* View details overlay */}
                        <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/20">
                          <div className="bg-white/90 backdrop-blur-sm rounded-full px-4 py-2 flex items-center gap-2 shadow-lg">
                            <Eye className="h-4 w-4" />
                            <span className="text-sm font-medium">{t('offerZone.viewDetails')}</span>
                          </div>
                        </div>
                      </div>
                      
                      {/* Content */}
                      <div className="p-4 sm:p-6">
                        <h3 className="text-lg sm:text-xl font-bold text-foreground mb-1 group-hover:text-primary transition-colors line-clamp-2 min-h-[3.5rem] leading-snug">
                          {combo.title}
                        </h3>
                        <p className="text-muted-foreground text-xs sm:text-sm mb-4 line-clamp-2">
                          {combo.description}
                        </p>
                        
                        {/* Price */}
                        <div className="flex items-center gap-2 mb-4">
                          <span className="text-2xl sm:text-3xl font-bold text-primary">₹{combo.price}</span>
                          {combo.originalPrice > combo.price && (
                            <span className="text-sm sm:text-base text-muted-foreground line-through">
                              ₹{combo.originalPrice}
                            </span>
                          )}
                        </div>
                        
                        {/* Add to cart button */}
                        <div onClick={(e) => e.stopPropagation()}>
                          {itemInCart ? (
                            <div className="flex items-center justify-center gap-4 bg-muted rounded-lg p-2">
                              <Button
                                variant="outline"
                                size="icon"
                                className="h-8 w-8"
                                onClick={() => updateQuantity(combo.id, itemInCart.quantity - 1, "combo")}
                              >
                                <Minus className="h-4 w-4" />
                              </Button>
                              <span className="font-bold text-lg min-w-[2rem] text-center">
                                {itemInCart.quantity}
                              </span>
                              <Button
                                variant="outline"
                                size="icon"
                                className="h-8 w-8"
                                onClick={() => updateQuantity(combo.id, itemInCart.quantity + 1, "combo")}
                              >
                                <Plus className="h-4 w-4" />
                              </Button>
                            </div>
                          ) : combo.inStock === false ? (
                            <Button disabled variant="outline" className="w-full py-3 font-semibold">
                              {t('product.outOfStock')}
                            </Button>
                          ) : (
                            <Button
                              onClick={() => {
                                 addToCart({
                                   id: combo.id,
                                   name: combo.title,
                                   image: combo.image,
                                   price: combo.price,
                                   originalPrice: combo.originalPrice,
                                   badge: combo.badge,
                                   itemType: "combo",
                                 });
                                 toast.success(t('product.addedToCart'));
                               }}
                               className="w-full py-3 font-semibold gap-2"
                             >
                               <ShoppingCart className="h-4 w-4" />
                               {t('product.addToCart')}
                             </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {/* Hot Deals */}
          {hotDeals.length > 0 && (
            <>
               <div className="text-center mb-6 sm:mb-10">
                <h2 className="text-2xl sm:text-4xl font-bold mb-2">
                  <span className="text-primary">
                    {t('offerZone.hotDealsTitle')}
                  </span>
                </h2>
                <p className="text-muted-foreground text-sm sm:text-base">{t('offerZone.hotDealsSubtitle')}</p>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 sm:gap-6">
                {hotDeals.map((product) => (
                  <ProductCard key={`product-${product.id}`} {...product} />
                ))}
              </div>
            </>
          )}

          {/* Empty state */}
          {hotDeals.length === 0 && comboOffers.length === 0 && (
            <div className="text-center py-10 sm:py-16">
              <Sparkles className="h-16 w-16 mx-auto text-muted-foreground mb-4" />
              <p className="text-base sm:text-xl text-muted-foreground">{t('offerZone.noOffers')}</p>
              <p className="text-muted-foreground text-sm sm:text-base">{t('offerZone.checkBack')}</p>
            </div>
          )}
        </div>
      </section>
      <Footer />
    </div>
  );
};

export default OfferZone;
