import { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import Footer from "@/components/Footer";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ShoppingCart, Heart, Share2, Package, Loader2, Minus, Plus, Check, Truck, Shield, ChevronRight, Gift, MessageCircle, Star } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { reviewsAPI, Review } from "@/lib/api/reviews";
import { MAX_REVIEW_COMMENT } from "@/config/limits";
import { toast } from "sonner";
import { useCart } from "@/context/CartContext";
import { useFavorites } from "@/context/FavoritesContext";
import { combosAPI, Combo, ComboItem } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import ProductCard from "@/components/ProductCard";
import CachedImage from "@/components/CachedImage";
import product1 from "@/assets/product-1.jpg";
import { resolveImageUrl } from "@/lib/utils";
import { useTranslation } from "react-i18next";

// Resolve a backend image path with the local product placeholder as fallback.
const getImageUrl = (imagePath: string | null | undefined): string =>
  resolveImageUrl(imagePath, product1);

const ComboDetail = () => {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { isLoggedIn } = useAuth();
  const [quantity, setQuantity] = useState(1);
  const [selectedImageIndex, setSelectedImageIndex] = useState(0);
  const { cart, addToCart, updateQuantity } = useCart();
  const { isFavorite, toggleFavorite } = useFavorites();
  
  const [combo, setCombo] = useState<Combo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Combo reviews. My Orders has always offered a review dialog for combos, but
  // nothing on the storefront rendered the result — they were write-only.
  const [reviews, setReviews] = useState<Review[]>([]);
  const [totalReviews, setTotalReviews] = useState(0);
  const [canReview, setCanReview] = useState(false);
  const [canReviewReason, setCanReviewReason] = useState<'not_purchased' | 'already_reviewed' | null>(null);
  const [reviewRating, setReviewRating] = useState(0);
  const [reviewHover, setReviewHover] = useState(0);
  const [reviewComment, setReviewComment] = useState("");
  const [submittingReview, setSubmittingReview] = useState(false);

  useEffect(() => {
    const fetchCombo = async () => {
      if (!id) {
        setError("No combo ID provided");
        setLoading(false);
        return;
      }
      
      setLoading(true);
      setError("");
      
      try {
        const comboData = await combosAPI.getById(id);
        
        if (!comboData) {
          throw new Error("Combo not found");
        }
        
        setCombo(comboData);

        try {
          const reviewsData = await reviewsAPI.getByCombo(comboData.id, 1);
          setReviews(reviewsData.results || []);
          setTotalReviews(reviewsData.count || 0);
        } catch {
          setReviews([]);
          setTotalReviews(0);
        }
      } catch (err: any) {
        console.error("Error fetching combo:", err);
        setError(err.message || "Failed to load combo");
        setCombo(null);
      } finally {
        setLoading(false);
      }
    };

    fetchCombo();
  }, [id]);

  // Eligibility is a UX hint only — the POST re-checks verified purchase.
  useEffect(() => {
    if (!isLoggedIn || !combo) {
      setCanReview(false);
      setCanReviewReason(null);
      return;
    }
    let cancelled = false;
    reviewsAPI
      .canReviewCombo(combo.id)
      .then((res) => {
        if (cancelled) return;
        setCanReview(res.can_review);
        setCanReviewReason(res.reason);
      })
      .catch(() => {
        if (cancelled) return;
        setCanReview(false);
        setCanReviewReason(null);
      });
    return () => { cancelled = true; };
  }, [isLoggedIn, combo?.id]);

  const submitComboReview = async () => {
    if (!combo || submittingReview) return;
    if (reviewRating < 1) {
      toast.error(t('product.reviewSelectRating'));
      return;
    }
    if (!reviewComment.trim()) {
      toast.error(t('product.reviewCommentRequired'));
      return;
    }
    setSubmittingReview(true);
    try {
      const created = await reviewsAPI.create({
        item_type: 'combo',
        combo: Number(combo.id),
        rating: reviewRating,
        comment: reviewComment.trim(),
      }) as Review;
      setReviews(prev => [created, ...prev]);
      setTotalReviews(prev => prev + 1);
      setReviewRating(0);
      setReviewHover(0);
      setReviewComment("");
      setCanReview(false);
      setCanReviewReason('already_reviewed');
      toast.success(t('product.reviewSubmitted'));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('product.reviewError'));
    } finally {
      setSubmittingReview(false);
    }
  };

  // Check if combo is already in cart
  const itemInCart = cart.find(item => item.id === Number(id) && item.itemType === "combo");

  const handleAddToCart = () => {
    if (!combo) return;
    
    if (!isLoggedIn) {
      toast.warning(t('product.loginRequired'));
      navigate('/login', { state: { from: '/cart' } });
      return;
    }
    
    addToCart({
      id: Number(combo.id),
      name: combo.display_title || combo.name,
      itemType: "combo" as const,
      image: combo.image || product1,
      price: combo.final_price || combo.price,
      originalPrice: combo.total_original_price || combo.price,
      badge: combo.badge,
      quantity: quantity,
    });
    toast.success(quantity === 1 ? t('combo.addedToCart', { count: quantity }) : t('combo.addedToCart_other', { count: quantity }));
  };

  const handleToggleFavorite = () => {
    if (!combo) return;
    
    const isCurrentlyFavorite = isFavorite(Number(combo.id));
    
    toggleFavorite({
      id: Number(combo.id),
      name: combo.display_title || combo.name,
      image: combo.image || product1,
      price: combo.final_price || combo.price,
      originalPrice: combo.total_original_price,
      weight: combo.total_weight,
      badge: combo.badge || "Combo",
    });
    
    toast.success(isCurrentlyFavorite ? t('product.removedFromFavorites') : t('product.addedToFavorites'));
  };

  const handleShare = async () => {
    if (!combo) return;
    
    const shareUrl = `${window.location.origin}/combos/${id}`;
    const shareTitle = combo.display_title || combo.name;
    const shareText = `Check out ${shareTitle} - ₹${price}${originalPrice > price ? ` (Save ${discountPercent}%)` : ''}`;
    
    // Try native share first (works on mobile)
    if (navigator.share) {
      try {
        await navigator.share({
          title: shareTitle,
          text: shareText,
          url: shareUrl,
        });
        return;
      } catch (err) {
        // User cancelled or error, fall through to copy
      }
    }
    
    // Fallback: copy to clipboard
    try {
      await navigator.clipboard.writeText(shareUrl);
      toast.success("Link copied to clipboard!");
    } catch (err) {
      toast.error("Failed to copy link");
    }
  };

  const handleShareWhatsApp = () => {
    if (!combo) return;
    
    const shareUrl = `${window.location.origin}/combos/${id}`;
    const shareTitle = combo.display_title || combo.name;
    const message = `Check out ${shareTitle} - ₹${price}${originalPrice > price ? ` (Save ${discountPercent}%)` : ''}\n${shareUrl}`;
    const whatsappUrl = `https://wa.me/?text=${encodeURIComponent(message)}`;
    window.open(whatsappUrl, '_blank');
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-background pb-20 md:pb-0">
        <div className="container mx-auto px-4 py-16 flex justify-center items-center">
          <div className="text-center">
            <Loader2 className="h-12 w-12 animate-spin text-primary mx-auto mb-4" />
            <p className="text-muted-foreground">Loading combo details...</p>
          </div>
        </div>
        <Footer />
      </div>
    );
  }

  if (error || !combo) {
    return (
      <div className="min-h-screen bg-background pb-20 md:pb-0">
        <div className="container mx-auto px-4 py-16 text-center">
          <div className="max-w-md mx-auto">
            <Package className="h-16 w-16 text-muted-foreground mx-auto mb-4" />
            <h2 className="text-2xl font-bold mb-4">Combo Not Found</h2>
            <p className="text-destructive text-lg mb-6">{error || "The combo you're looking for doesn't exist."}</p>
            <div className="flex gap-4 justify-center">
              <Button onClick={() => navigate(-1)} variant="outline">
                Go Back
              </Button>
              <Button asChild>
                <Link to="/offer-zone">Browse Combos</Link>
              </Button>
            </div>
          </div>
        </div>
        <Footer />
      </div>
    );
  }

  const comboImage = combo.image || product1;
  const price = combo.final_price || combo.price;
  const originalPrice = combo.total_original_price || combo.price;
  const discountPercent = combo.discount_percentage || 
    (originalPrice && originalPrice > price ? Math.round(((originalPrice - price) / originalPrice) * 100) : 0);
  const savings = originalPrice > price ? originalPrice - price : 0;
  const items = combo.items || [];

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      <div className="container mx-auto px-3 sm:px-4 py-4 sm:py-6">
        {/* Breadcrumb */}
        <div className="flex items-center gap-1 text-xs sm:text-sm text-muted-foreground mb-4 overflow-x-auto whitespace-nowrap">
          <Link to="/" className="hover:text-primary transition-colors">Home</Link>
          <ChevronRight className="h-3 w-3" />
          <Link to="/offer-zone" className="hover:text-primary transition-colors">Combos</Link>
          <ChevronRight className="h-3 w-3" />
          <span className="text-foreground truncate">{combo.display_title || combo.name}</span>
        </div>

        {/* Main Content */}
        <div className="grid lg:grid-cols-2 gap-6 lg:gap-10 mb-8">
          
          {/* Image Gallery - Similar to ProductDetail */}
          <div className="flex flex-col-reverse sm:flex-row gap-3">
            {/* Thumbnails - All product images from combo */}
            <div className="flex sm:flex-col gap-2 overflow-x-auto sm:overflow-y-auto sm:max-h-[500px] pb-2 sm:pb-0 sm:pr-2">
              {/* Combo main image as first thumbnail */}
              <button
                onClick={() => setSelectedImageIndex(0)}
                className={`flex-shrink-0 w-14 h-14 sm:w-16 sm:h-16 rounded-lg border-2 overflow-hidden transition-all ${
                  selectedImageIndex === 0 
                    ? "border-primary ring-2 ring-primary/20" 
                    : "border-border hover:border-primary/50"
                }`}
              >
                <CachedImage 
                  src={getImageUrl(combo.image)} 
                  alt="Combo"
                  className="w-full h-full object-contain"
                  fallbackSrc={product1}
                />
              </button>
              {/* Product images as additional thumbnails */}
              {items.map((item: ComboItem, idx: number) => (
                <button
                  key={idx}
                  onClick={() => setSelectedImageIndex(idx + 1)}
                  className={`flex-shrink-0 w-14 h-14 sm:w-16 sm:h-16 rounded-lg border-2 overflow-hidden transition-all relative ${
                    selectedImageIndex === idx + 1 
                      ? "border-primary ring-2 ring-primary/20" 
                      : "border-border hover:border-primary/50"
                  }`}
                >
                  <CachedImage 
                    src={getImageUrl(item.product_image)} 
                    alt={item.product_name}
                    className="w-full h-full object-contain"
                    fallbackSrc={product1}
                  />
                  {/* Quantity indicator on thumbnail */}
                  <span className="absolute bottom-0.5 right-0.5 bg-primary text-primary-foreground text-[10px] px-1 rounded">
                    ×{item.quantity}
                  </span>
                </button>
              ))}
            </div>
            
            {/* Main Image Display */}
            <div className="flex-1 relative">
              <div className="aspect-square rounded-xl border border-border overflow-hidden bg-gradient-to-br from-primary/5 to-accent/10 group">
                <CachedImage 
                  src={selectedImageIndex === 0 
                    ? getImageUrl(combo.image) 
                    : getImageUrl(items[selectedImageIndex - 1]?.product_image)
                  } 
                  alt={selectedImageIndex === 0 
                    ? combo.name 
                    : items[selectedImageIndex - 1]?.product_name
                  }
                  className="w-full h-full object-contain transition-transform duration-300 group-hover:scale-105"
                  fallbackSrc={product1}
                  lazy={false}
                />
              </div>
              
              {/* Current product name indicator */}
              {selectedImageIndex > 0 && items[selectedImageIndex - 1] && (
                <div className="absolute bottom-3 left-3 right-3">
                  <div className="bg-card/95 backdrop-blur-sm rounded-lg px-3 py-2 shadow-lg">
                    <p className="text-sm font-medium truncate">
                      {items[selectedImageIndex - 1].product_name}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      ×{items[selectedImageIndex - 1].quantity} in this combo
                    </p>
                  </div>
                </div>
              )}
              
              {/* Badges */}
              <div className="absolute top-3 left-3 flex flex-col gap-2">
                <Badge className="bg-accent text-accent-foreground">
                  <Package className="h-3 w-3 mr-1" />
                  {items.length} Products
                </Badge>
                {combo.badge && (
                  <Badge className="bg-primary text-primary-foreground">{combo.badge}</Badge>
                )}
                {discountPercent > 0 && (
                  <Badge className="bg-secondary text-secondary-foreground">Save {discountPercent}%</Badge>
                )}
              </div>
              
              {/* Favorite Button */}
              <button
                onClick={handleToggleFavorite}
                className="absolute top-3 right-3 bg-card/90 backdrop-blur-sm p-2.5 rounded-full shadow-lg hover:bg-card transition-all hover:scale-110"
                aria-label={isFavorite(Number(combo.id)) ? "Remove from favorites" : "Add to favorites"}
              >
                <Heart className={`h-5 w-5 ${isFavorite(Number(combo.id)) ? "fill-red-500 text-red-500" : "text-muted-foreground"}`} />
              </button>
            </div>
          </div>

          {/* Info Section */}
          <div className="space-y-4">
            {/* Title */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Badge variant="outline" className="text-primary border-primary">
                  <Gift className="h-3 w-3 mr-1" />
                  Value Pack
                </Badge>
                {combo.is_featured && (
                  <Badge variant="secondary">Featured</Badge>
                )}
              </div>
              <h1 className="text-xl sm:text-2xl lg:text-3xl font-bold text-foreground leading-tight">
                {combo.display_title || combo.name}
              </h1>
              {combo.subtitle && (
                <p className="text-muted-foreground mt-1">{combo.subtitle}</p>
              )}
            </div>

            <Separator />

            {/* Price Section - Amazon Style */}
            <div className="space-y-2">
              <div className="flex items-baseline gap-3 flex-wrap">
                <span className="text-3xl sm:text-4xl font-bold text-foreground">₹{price}</span>
                {originalPrice > price && (
                  <>
                    <span className="text-lg text-muted-foreground line-through">₹{originalPrice}</span>
                    <Badge variant="secondary" className="text-sm">
                      -{discountPercent}%
                    </Badge>
                  </>
                )}
              </div>
              {savings > 0 && (
                <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
                  <Gift className="h-4 w-4" />
                  <p className="font-medium">{t('combo.saveWithCombo', { amount: savings.toFixed(0) })}</p>
                </div>
              )}
              <p className="text-xs text-muted-foreground">{t('product.inclusiveTaxes')}</p>
            </div>

            {/* What's Included */}
            <div className="bg-muted/50 rounded-xl p-4">
              <h2 className="font-semibold mb-3 flex items-center gap-2">
                <Package className="h-5 w-5 text-primary" />
                {t('combo.whatsIncluded', { count: items.length })}
              </h2>
              <div className="space-y-2">
                {items.map((item: ComboItem, index: number) => (
                  <div 
                    key={index} 
                    className="flex items-center gap-3 p-2 bg-background rounded-lg border border-border"
                  >
                    <div className="w-10 h-10 rounded-lg overflow-hidden bg-muted flex-shrink-0">
                      <CachedImage 
                        src={getImageUrl(item.product_image)} 
                        alt={item.product_name}
                        className="w-full h-full object-contain"
                        fallbackSrc={product1}
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm truncate">{item.product_name}</p>
                      <p className="text-xs text-muted-foreground">
                        {t('product.quantityLabel')} {item.quantity} × ₹{item.product_price}
                      </p>
                    </div>
                    <Check className="h-4 w-4 text-green-500 flex-shrink-0" />
                  </div>
                ))}
              </div>
            </div>

            {/* Total Weight */}
            {combo.total_weight && (
              <p className="text-sm">
                <span className="font-medium">{t('combo.totalWeight')}</span>{" "}
                <span className="text-muted-foreground">{combo.total_weight}</span>
              </p>
            )}

            {/* Quantity Selector */}
            <div className="flex items-center gap-4">
              <span className="font-medium">{t('product.quantityLabel')}</span>
              {itemInCart ? (
                <div className="flex items-center gap-2">
                  <Button 
                    variant="outline" 
                    size="icon" 
                    className="h-9 w-9"
                    onClick={() => updateQuantity(Number(id), itemInCart.quantity - 1, "combo")}
                  >
                    <Minus className="h-4 w-4" />
                  </Button>
                  <span className="w-10 text-center font-semibold">{itemInCart.quantity}</span>
                  <Button 
                    variant="outline" 
                    size="icon" 
                    className="h-9 w-9"
                    onClick={() => updateQuantity(Number(id), itemInCart.quantity + 1, "combo")}
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                  <span className="text-sm text-muted-foreground">{t('product.inCart')}</span>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <Button 
                    variant="outline" 
                    size="icon" 
                    className="h-9 w-9"
                    onClick={() => setQuantity(Math.max(1, quantity - 1))}
                  >
                    <Minus className="h-4 w-4" />
                  </Button>
                  <span className="w-10 text-center font-semibold">{quantity}</span>
                  <Button 
                    variant="outline" 
                    size="icon" 
                    className="h-9 w-9"
                    onClick={() => setQuantity(quantity + 1)}
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                </div>
              )}
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3">
              <Button 
                className="flex-1 h-12" 
                onClick={handleAddToCart}
              >
                <ShoppingCart className="mr-2 h-5 w-5" />
                {t('product.addToCart')}
              </Button>
              <Button 
                variant="outline" 
                size="icon" 
                className="h-12 w-12"
                onClick={handleShareWhatsApp}
                title={t('footer.whatsapp')}
              >
                <MessageCircle className="h-5 w-5" />
              </Button>
              <Button 
                variant="outline" 
                size="icon" 
                className="h-12 w-12"
                onClick={handleShare}
                title={t('product.copyLink')}
              >
                <Share2 className="h-5 w-5" />
              </Button>
            </div>

            {/* Trust Indicators */}
            <div className="grid grid-cols-2 gap-3 pt-2">
              <div className="flex flex-col items-center text-center p-3 bg-muted/50 rounded-lg">
                <Truck className="h-5 w-5 text-primary mb-1" />
                <span className="text-xs font-medium">{t('combo.freeDelivery')}</span>
                <span className="text-xs text-muted-foreground">{t('combo.ordersMin')}</span>
              </div>
              <div className="flex flex-col items-center text-center p-3 bg-muted/50 rounded-lg">
                <Shield className="h-5 w-5 text-primary mb-1" />
                <span className="text-xs font-medium">{t('combo.secure')}</span>
                <span className="text-xs text-muted-foreground">{t('combo.payment')}</span>
              </div>
            </div>

            {/* Savings Highlight */}
            {savings > 0 && (
              <Card className="bg-gradient-to-r from-green-50 to-emerald-50 dark:from-green-950 dark:to-emerald-950 border-green-200 dark:border-green-800">
                <CardContent className="p-4">
                  <div className="flex items-center gap-3">
                    <div className="bg-green-500 text-white rounded-full p-2">
                      <Gift className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="font-semibold text-green-700 dark:text-green-300">{t('combo.greatValue')}</p>
                      <p className="text-sm text-green-600 dark:text-green-400">
                        {t('combo.saveSeparately', { amount: savings.toFixed(0) })}
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>

        {/* Description Section */}
        {combo.description && (
          <section className="max-w-4xl mb-8">
            <h2 className="text-xl font-bold mb-4">{t('combo.aboutCombo')}</h2>
            <p className="text-muted-foreground leading-relaxed">{combo.description}</p>
          </section>
        )}

        {/* Why This Combo Section - Compact on mobile, spacious on desktop */}
        <section className="mb-8 md:mb-12">
          <h2 className="text-lg sm:text-xl md:text-2xl lg:text-3xl font-bold mb-4 md:mb-6 text-center">
            {t('combo.whyChoose')}
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 sm:gap-3 md:gap-6">
            <div className="flex flex-col items-center text-center p-3 sm:p-4 md:p-8 bg-card rounded-xl md:rounded-2xl border border-border hover:shadow-xl transition-all md:hover:-translate-y-1">
              <div className="bg-gradient-to-br from-primary/20 to-primary/5 rounded-xl md:rounded-2xl p-2.5 sm:p-3 md:p-5 mb-2 md:mb-4">
                <Gift className="h-5 w-5 sm:h-6 sm:w-6 md:h-10 md:w-10 text-primary" />
              </div>
              <p className="text-xs sm:text-sm md:text-lg font-bold text-foreground mb-0.5 md:mb-2">{t('combo.betterValue')}</p>
              <p className="text-[10px] sm:text-xs md:text-sm text-muted-foreground hidden sm:block">
                {t('combo.saveTogether')}
              </p>
            </div>
            <div className="flex flex-col items-center text-center p-3 sm:p-4 md:p-8 bg-card rounded-xl md:rounded-2xl border border-border hover:shadow-xl transition-all md:hover:-translate-y-1">
              <div className="bg-gradient-to-br from-accent/20 to-accent/5 rounded-xl md:rounded-2xl p-2.5 sm:p-3 md:p-5 mb-2 md:mb-4">
                <Package className="h-5 w-5 sm:h-6 sm:w-6 md:h-10 md:w-10 text-accent" />
              </div>
              <p className="text-xs sm:text-sm md:text-lg font-bold text-foreground mb-0.5 md:mb-2">{t('combo.curatedSelection')}</p>
              <p className="text-[10px] sm:text-xs md:text-sm text-muted-foreground hidden sm:block">
                {t('combo.expertlyPaired')}
              </p>
            </div>
            <div className="flex flex-col items-center text-center p-3 sm:p-4 md:p-8 bg-card rounded-xl md:rounded-2xl border border-border hover:shadow-xl transition-all md:hover:-translate-y-1">
              <div className="bg-gradient-to-br from-secondary/20 to-secondary/5 rounded-xl md:rounded-2xl p-2.5 sm:p-3 md:p-5 mb-2 md:mb-4">
                <Truck className="h-5 w-5 sm:h-6 sm:w-6 md:h-10 md:w-10 text-secondary" />
              </div>
              <p className="text-xs sm:text-sm md:text-lg font-bold text-foreground mb-0.5 md:mb-2">{t('combo.singleDelivery')}</p>
              <p className="text-[10px] sm:text-xs md:text-sm text-muted-foreground hidden sm:block">
                {t('combo.allInOne')}
              </p>
            </div>
            <div className="flex flex-col items-center text-center p-3 sm:p-4 md:p-8 bg-card rounded-xl md:rounded-2xl border border-border hover:shadow-xl transition-all md:hover:-translate-y-1">
              <div className="bg-gradient-to-br from-green-500/20 to-green-500/5 rounded-xl md:rounded-2xl p-2.5 sm:p-3 md:p-5 mb-2 md:mb-4">
                <Check className="h-5 w-5 sm:h-6 sm:w-6 md:h-10 md:w-10 text-green-600" />
              </div>
              <p className="text-xs sm:text-sm md:text-lg font-bold text-foreground mb-0.5 md:mb-2">{t('home.features.qualityTitle')}</p>
              <p className="text-[10px] sm:text-xs md:text-sm text-muted-foreground hidden sm:block">
                {t('combo.genuine')}
              </p>
            </div>
          </div>
        </section>

        {/* Products In This Combo - Enhanced layout with images */}
        {items.length > 0 && (
          <section className="mb-10">
            <h2 className="text-xl sm:text-2xl lg:text-3xl font-bold mb-6 text-center">
              {t('combo.productsInCombo')}
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 md:gap-6">
              {items.map((item: ComboItem, index: number) => (
                <div 
                  key={index}
                  onClick={() => navigate(`/products/${item.product_slug || item.product}`)}
                  className="group bg-card rounded-2xl border border-border overflow-hidden hover:shadow-xl transition-all cursor-pointer hover:-translate-y-1"
                >
                  {/* Product Image */}
                  <div className="aspect-square bg-muted relative overflow-hidden">
                    <CachedImage 
                      src={getImageUrl(item.product_image)}
                      alt={item.product_name}
                      className="w-full h-full object-contain group-hover:scale-105 transition-transform duration-300"
                      fallbackSrc={product1}
                    />
                    {/* Quantity badge */}
                    <div className="absolute top-2 right-2">
                      <Badge className="bg-primary text-primary-foreground shadow-lg">
                        ×{item.quantity}
                      </Badge>
                    </div>
                  </div>
                  {/* Product Info */}
                  <div className="p-3 md:p-4">
                    <p className="font-semibold text-sm md:text-base text-foreground line-clamp-2 group-hover:text-primary transition-colors mb-1">
                      {item.product_name}
                    </p>
                    <p className="text-primary font-bold text-base md:text-lg">
                      ₹{item.product_price}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
        {/* Combo reviews */}
        <section className="max-w-4xl mt-10">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-xl font-bold">{t('product.customerReviews')}</h2>
            {totalReviews > 0 && (
              <span className="text-sm text-muted-foreground">
                {t('product.showingReviews', { count: reviews.length, total: totalReviews })}
              </span>
            )}
          </div>

          {isLoggedIn && canReview ? (
            <Card className="mb-6">
              <CardContent className="p-4 space-y-4">
                <h3 className="font-semibold">{t('product.writeReview')}</h3>
                <div className="flex items-center gap-1">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <button
                      key={star}
                      type="button"
                      onClick={() => setReviewRating(star)}
                      onMouseEnter={() => setReviewHover(star)}
                      onMouseLeave={() => setReviewHover(0)}
                      className="p-0.5"
                      aria-label={`${star}`}
                    >
                      <Star
                        className={`h-6 w-6 transition-colors ${
                          star <= (reviewHover || reviewRating)
                            ? "fill-amber-400 text-amber-400"
                            : "text-muted-foreground/30"
                        }`}
                      />
                    </button>
                  ))}
                </div>
                <Textarea
                  value={reviewComment}
                  onChange={(e) => setReviewComment(e.target.value)}
                  placeholder={t('product.reviewCommentPlaceholder')}
                  rows={4}
                  maxLength={MAX_REVIEW_COMMENT}
                />
                <div className="flex justify-end">
                  <Button onClick={submitComboReview} disabled={submittingReview}>
                    {submittingReview ? (
                      <><Loader2 className="mr-2 h-4 w-4 animate-spin" />{t('common.loading')}</>
                    ) : (
                      t('product.submitReview')
                    )}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : isLoggedIn ? (
            canReviewReason && (
              <Card className="mb-6">
                <CardContent className="p-4">
                  <p className="text-sm text-muted-foreground">
                    {canReviewReason === 'already_reviewed'
                      ? t('product.alreadyReviewed')
                      : t('product.purchaseToReview')}
                  </p>
                </CardContent>
              </Card>
            )
          ) : null}

          {reviews.length > 0 ? (
            <div className="space-y-4">
              {reviews.map((review) => (
                <Card key={review.id}>
                  <CardContent className="p-4">
                    <div className="flex items-center gap-2 mb-2">
                      {[...Array(5)].map((_, index) => (
                        <Star
                          key={index}
                          className={`h-4 w-4 ${index < review.rating ? "fill-amber-400 text-amber-400" : "text-muted-foreground/30"}`}
                        />
                      ))}
                      {review.title && (
                        <span className="text-sm font-medium ml-2">{review.title}</span>
                      )}
                      {review.is_verified_purchase && (
                        <span className="inline-flex items-center gap-1 text-xs text-green-600 font-medium ml-2">
                          <Check className="h-3 w-3" />
                          {t('home.testimonials.verified')}
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground mb-2">{review.comment}</p>
                    <p className="text-xs text-muted-foreground">
                      {review.user_name} · {new Date(review.created_at).toLocaleDateString('en-IN')}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t('product.noReviews')}</p>
          )}
        </section>
      </div>

      {/* Sticky Mobile Cart Bar */}
      <div className="fixed bottom-16 left-0 right-0 bg-card border-t border-border p-3 md:hidden z-40 shadow-lg">
        <div className="flex items-center gap-3">
          <div className="flex-1">
            <div className="flex items-baseline gap-2">
              <span className="text-lg font-bold">₹{price}</span>
              {originalPrice > price && (
                <span className="text-sm text-muted-foreground line-through">₹{originalPrice}</span>
              )}
            </div>
            {savings > 0 && (
              <p className="text-xs text-green-600">{t('product.youSave', { amount: savings.toFixed(0) })}</p>
            )}
          </div>
          <Button 
            size="sm" 
            onClick={handleAddToCart}
            className="h-10 px-6"
          >
            <ShoppingCart className="mr-2 h-4 w-4" />
            {t('product.addToCart')}
          </Button>
          {cart.length > 0 && (
            <Button size="sm" variant="secondary" asChild className="h-10 px-4">
              <Link to="/cart">
                {t('nav.cart')} ({cart.reduce((sum, item) => sum + item.quantity, 0)})
              </Link>
            </Button>
          )}
        </div>
      </div>

      <Footer />
    </div>
  );
};

export default ComboDetail;

