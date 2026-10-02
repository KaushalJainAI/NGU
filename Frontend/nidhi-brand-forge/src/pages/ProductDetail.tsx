import { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import Footer from "@/components/Footer";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ShoppingCart, Heart, Share2, Star, Loader2, Minus, Plus, Check, ChevronRight, MessageCircle, ShieldCheck } from "lucide-react";
import { Carousel, CarouselContent, CarouselItem, CarouselNext, CarouselPrevious } from "@/components/ui/carousel";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import ProductCard from "@/components/ProductCard";
import TrustSignalBand from "@/components/TrustSignalBand";
import { toast } from "sonner";
import { useCart } from "@/context/CartContext";
import { MAX_ITEM_QUANTITY, MAX_REVIEW_COMMENT } from "@/config/limits";
import { useFavorites } from "@/context/FavoritesContext";
import { useAuth } from "@/context/AuthContext";
import { productsAPI, reviewsAPI, Product, ProductVariant } from "@/lib/api";
import { trackEvent, track } from "@/lib/api/analytics";
import { Review } from "@/lib/api/reviews";
import CachedImage from "@/components/CachedImage";
import product1 from "@/assets/product-1.jpg";
import { useTranslation } from "react-i18next";
import { formatWeight } from "@/lib/utils";
import Seo, { SITE_URL } from "@/components/Seo";

const ProductDetail = () => {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { isLoggedIn } = useAuth();
  const [quantity, setQuantity] = useState(1);
  const [selectedImageIndex, setSelectedImageIndex] = useState(0);
  const { cart, addToCart, updateQuantity: updateCartQuantity } = useCart();
  const { isFavorite, toggleFavorite } = useFavorites();
  
  const [product, setProduct] = useState<Product | null>(null);
  const [selectedVariant, setSelectedVariant] = useState<ProductVariant | null>(null);
  const [similarProducts, setSimilarProducts] = useState<Product[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  
  // Reviews pagination state
  const [reviewsPage, setReviewsPage] = useState(1);
  const [totalReviews, setTotalReviews] = useState(0);
  const [hasMoreReviews, setHasMoreReviews] = useState(false);
  const [loadingMoreReviews, setLoadingMoreReviews] = useState(false);

  // Write-a-review form state
  const [reviewRating, setReviewRating] = useState(0);
  const [reviewHover, setReviewHover] = useState(0);
  const [reviewTitle, setReviewTitle] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const [submittingReview, setSubmittingReview] = useState(false);
  // Whether the logged-in user is eligible to review this product (backend
  // only accepts reviews from verified purchasers, one per product).
  const [canReview, setCanReview] = useState(false);
  const [canReviewReason, setCanReviewReason] = useState<'not_purchased' | 'already_reviewed' | null>(null);

  // Check if the currently-selected size is already in cart
  const itemInCart = cart.find(
    item =>
      item.itemType === "product" &&
      (selectedVariant
        ? item.variantId === selectedVariant.id
        : item.id === Number(product?.id ?? id))
  );

  useEffect(() => {
    const fetchProduct = async () => {
      if (!id) {
        setError("No product ID provided");
        setLoading(false);
        return;
      }
      
      setLoading(true);
      setError("");
      
      try {
        const productData = await productsAPI.getById(id);
        
        if (!productData) {
          throw new Error("Product not found");
        }
        
        setProduct(productData);

        // Choose the active variant: the one named by a variant-slug URL; else the
        // default size IF it is in stock; else the first size that is; else the
        // default. (Opening on a sold-out size while another is available would
        // show a disabled page for a product that can be bought.)
        const vs: ProductVariant[] = (productData.variants || []).filter((v: ProductVariant) => v.is_active);
        const defaultSize = vs.find((v) => v.is_default);
        const chosen =
          vs.find((v) => v.id === productData.selected_variant_id) ||
          (defaultSize?.in_stock ? defaultSize : undefined) ||
          vs.find((v) => v.in_stock) ||
          defaultSize ||
          vs[0] ||
          null;
        setSelectedVariant(chosen);

        // Record a product view: a per-user personalization signal when logged
        // in, or a coarse anonymous counter otherwise.
        track(
          {
            event_type: "view",
            product_id: Number(productData.id),
            category_id: productData.category ? Number(productData.category) : undefined,
          },
          { metric: "product_view", product_id: Number(productData.id) },
        );

        try {
          const reviewsData = await reviewsAPI.getByProduct(productData.id, 1);
          setReviews(reviewsData.results || []);
          setTotalReviews(reviewsData.count || 0);
          setHasMoreReviews(!!reviewsData.next);
          setReviewsPage(1);
        } catch (reviewErr) {
          setReviews([]);
          setTotalReviews(0);
          setHasMoreReviews(false);
        }
        
        if (productData.category) {
          try {
            const similarData = await productsAPI.getByCategory(String(productData.category));
            const similar = (similarData || [])
              .filter((p: Product) => p.id !== productData.id)
              .slice(0, 4);
            setSimilarProducts(similar);
          } catch (similarErr) {
            setSimilarProducts([]);
          }
        }
      } catch (err: any) {
        console.error("Error fetching product:", err);
        setError(err.message || "Failed to load product");
        setProduct(null);
      } finally {
        setLoading(false);
      }
    };

    fetchProduct();
  }, [id]);

  useEffect(() => {
    if (!isLoggedIn || !product) {
      setCanReview(false);
      setCanReviewReason(null);
      return;
    }
    let cancelled = false;
    reviewsAPI
      .canReviewProduct(product.id)
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
    return () => {
      cancelled = true;
    };
  }, [isLoggedIn, product?.id]);

  // Load more reviews function
  const loadMoreReviews = async () => {
    if (!product || loadingMoreReviews || !hasMoreReviews) return;
    
    setLoadingMoreReviews(true);
    try {
      const nextPage = reviewsPage + 1;
      const reviewsData = await reviewsAPI.getByProduct(product.id, nextPage);
      setReviews(prev => [...prev, ...(reviewsData.results || [])]);
      setHasMoreReviews(!!reviewsData.next);
      setReviewsPage(nextPage);
    } catch (err) {
      console.error("Error loading more reviews:", err);
    } finally {
      setLoadingMoreReviews(false);
    }
  };

  // Submit a new review. The backend enforces verified-purchase and one-review-
  // per-item; those rejections surface as APIError.message which we toast.
  const submitReview = async () => {
    if (!product || submittingReview) return;
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
        item_type: 'product',
        product: Number(product.id),
        rating: reviewRating,
        title: reviewTitle.trim() || undefined,
        comment: reviewComment.trim(),
      }) as Review;
      setReviews(prev => [created, ...prev]);
      setTotalReviews(prev => prev + 1);
      setReviewRating(0);
      setReviewHover(0);
      setReviewTitle("");
      setReviewComment("");
      // One review per product — retire the form now that it's been used.
      setCanReview(false);
      setCanReviewReason('already_reviewed');
      toast.success(t('product.reviewSubmitted'));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('product.reviewError'));
    } finally {
      setSubmittingReview(false);
    }
  };

  const handleAddToCart = () => {
    if (!product) return;
    
    if (!isLoggedIn) {
      toast.warning(t('product.loginRequired'));
      navigate('/login', { state: { from: '/cart' } });
      return;
    }
    
    const effPrice = selectedVariant
      ? Number(selectedVariant.final_price)
      : (product.final_price || Number(product.discount_price) || Number(product.price));
    const effOriginal = selectedVariant
      ? (selectedVariant.discount_price ? Number(selectedVariant.price) : undefined)
      : (product.discount_price ? Number(product.price) : undefined);

    addToCart({
      id: Number(product.id),
      variantId: selectedVariant ? selectedVariant.id : undefined,
      variantSlug: selectedVariant ? selectedVariant.slug : undefined,
      weight: selectedVariant ? selectedVariant.formatted_weight : undefined,
      name: product.name,
      itemType: "product" as const,
      image: product.image || product1,
      price: effPrice,
      originalPrice: effOriginal,
      quantity: quantity,
    });
    toast.success(`${quantity} ${quantity > 1 ? 'items' : 'item'} added to cart!`);
  };

  // Add the selected item, then jump straight to the cart for a fast checkout.
  const handleBuyNow = () => {
    if (!product) return;
    if (!isLoggedIn) {
      toast.warning(t('product.loginRequired'));
      navigate('/login', { state: { from: '/cart' } });
      return;
    }
    if (!itemInCart) handleAddToCart();
    navigate('/cart');
  };

  const handleToggleFavorite = () => {
    if (!product) return;
    
    const isCurrentlyFavorite = isFavorite(Number(product.id));
    
    toggleFavorite({
      id: Number(product.id),
      name: product.name,
      image: product.image || product1,
      price: product.final_price || Number(product.discount_price) || Number(product.price),
      originalPrice: product.discount_price ? Number(product.price) : undefined,
      weight: formatWeight(product.weight, product.unit),
      badge: product.badge,
    });
    
    toast.success(isCurrentlyFavorite ? t('product.removedFromFavorites') : t('product.addedToFavorites'));
  };

  const handleShare = async () => {
    if (!product) return;
    
    const shareUrl = `${window.location.origin}/products/${id}`;
    const shareTitle = product.name;
    const shareText = `Check out ${product.name} - ₹${price}${originalPrice && originalPrice > price ? ` (Save ${discountPercent}%)` : ''}`;
    
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
    if (!product) return;
    
    const shareUrl = `${window.location.origin}/products/${id}`;
    const message = `Check out ${product.name} - ₹${price}${originalPrice && originalPrice > price ? ` (Save ${discountPercent}%)` : ''}\n${shareUrl}`;
    const whatsappUrl = `https://wa.me/?text=${encodeURIComponent(message)}`;
    window.open(whatsappUrl, '_blank');
  };

  const formatSimilarProduct = (p: Product) => ({
    id: Number(p.id),
    name: p.name,
    slug: p.slug,
    image: p.image || product1,
    price: p.final_price || Number(p.discount_price) || Number(p.price),
    originalPrice: p.discount_price ? Number(p.price) : undefined,
    weight: `${p.weight || ''}${p.unit || ''}` || "100g",
    itemType: "product" as const,
    variantCount: p.variant_count ?? 1,
    inStock: p.in_stock !== false,
  });

  if (loading) {
    return (
      <div className="min-h-screen bg-background pb-20 md:pb-0">
        <div className="container mx-auto px-4 py-16 flex justify-center items-center">
          <div className="text-center">
            <Loader2 className="h-12 w-12 animate-spin text-primary mx-auto mb-4" />
            <p className="text-muted-foreground">Loading product details...</p>
          </div>
        </div>
        <Footer />
      </div>
    );
  }

  if (error || !product) {
    return (
      <div className="min-h-screen bg-background pb-20 md:pb-0">
        <div className="container mx-auto px-4 py-16 text-center">
          <div className="max-w-md mx-auto">
            <h2 className="text-2xl font-bold mb-4">Product Not Found</h2>
            <p className="text-destructive text-lg mb-6">{error || "The product you're looking for doesn't exist."}</p>
            <div className="flex gap-4 justify-center">
              <Button onClick={() => navigate(-1)} variant="outline">
                Go Back
              </Button>
              <Button asChild>
                <Link to="/products">Browse Products</Link>
              </Button>
            </div>
          </div>
        </div>
        <Footer />
      </div>
    );
  }

  const productImage = product.image || product1;
  const galleryImages = product.images?.length 
    ? [productImage, ...product.images.map((img) => img.image)]
    : [productImage];
  const rating = product.average_rating || 0;
  const reviewsCount = product.reviews_count || reviews.length;
  // Pricing/stock follow the selected packaging size when variants exist.
  const variants = (product.variants || []).filter((v) => v.is_active);
  const price = selectedVariant
    ? Number(selectedVariant.final_price)
    : (product.final_price || Number(product.discount_price) || Number(product.price));
  const originalPrice = selectedVariant
    ? (selectedVariant.discount_price ? Number(selectedVariant.price) : null)
    : (product.discount_price ? Number(product.price) : null);
  const discountPercent = (selectedVariant ? selectedVariant.discount_percentage : product.discount_percentage) ||
    (originalPrice && originalPrice > price ? Math.round(((originalPrice - price) / originalPrice) * 100) : 0);
  const savings = originalPrice && originalPrice > price ? originalPrice - price : 0;
  // AP8/S12: the catalog API no longer exposes exact stock counts to the
  // storefront (staff-only now) — availability is the boolean in_stock, and
  // quantities are capped client-side by MAX_ITEM_QUANTITY. The server still
  // enforces real stock on cart-add and checkout, so oversell is impossible.
  const effectiveStock = selectedVariant?.stock ?? product.stock ?? MAX_ITEM_QUANTITY;
  const effectiveInStock = selectedVariant ? selectedVariant.in_stock : product.in_stock;
  const effectiveWeight = selectedVariant ? selectedVariant.formatted_weight : formatWeight(product.weight, product.unit, "100g");

  // Product schema drives Google rich results (price, availability, rating).
  const productSchema: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: product.name,
    description: product.description,
    image: product.image ? [product.image] : undefined,
    sku: String(product.id),
    category: product.category_name,
    weight: effectiveWeight,
    brand: { "@type": "Brand", name: "Nidhi Grah Udyog" },
    offers: {
      "@type": "Offer",
      url: `${SITE_URL}/products/${product.slug}`,
      priceCurrency: "INR",
      price: String(price),
      availability: effectiveInStock
        ? "https://schema.org/InStock"
        : "https://schema.org/OutOfStock",
      seller: { "@type": "Organization", name: "Nidhi Grah Udyog" },
    },
  };
  if (totalReviews > 0 && product.average_rating) {
    productSchema.aggregateRating = {
      "@type": "AggregateRating",
      ratingValue: String(product.average_rating),
      reviewCount: String(totalReviews),
    };
  }

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      <Seo
        title={product.name}
        description={
          product.description?.slice(0, 160) ||
          `Buy ${product.name} online from Nidhi Grah Udyog — pure, authentic Indian spices.`
        }
        image={product.image}
        path={`/products/${product.slug}`}
        type="product"
        schema={productSchema}
      />
      <div className="container mx-auto px-3 sm:px-4 py-4 sm:py-6">
        {/* Breadcrumb */}
        <div className="flex items-center gap-1 text-xs sm:text-sm text-muted-foreground mb-4 overflow-x-auto whitespace-nowrap">
          <Link to="/" className="hover:text-primary transition-colors">Home</Link>
          <ChevronRight className="h-3 w-3" />
          <Link to="/products" className="hover:text-primary transition-colors">Products</Link>
          {product.category_name && (
            <>
              <ChevronRight className="h-3 w-3" />
              <span className="text-foreground">{product.category_name}</span>
            </>
          )}
        </div>

        {/* Main Product Section */}
        <div className="grid lg:grid-cols-2 gap-6 lg:gap-10 mb-8">
          
          {/* Image Gallery - Amazon Style */}
          <div className="flex flex-col-reverse sm:flex-row gap-3">
            {/* Thumbnails */}
            <div className="flex sm:flex-col gap-2 overflow-x-auto sm:overflow-y-auto sm:max-h-[500px] pb-2 sm:pb-0 sm:pr-2">
              {galleryImages.map((img: string, idx: number) => (
                <button
                  key={idx}
                  onClick={() => setSelectedImageIndex(idx)}
                  className={`flex-shrink-0 w-14 h-14 sm:w-16 sm:h-16 rounded-lg border-2 overflow-hidden transition-all ${
                    selectedImageIndex === idx 
                      ? "border-primary ring-2 ring-primary/20" 
                      : "border-border hover:border-primary/50"
                  }`}
                >
                  <CachedImage 
                    src={img} 
                    alt={`${product.name} view ${idx + 1}`}
                    className="w-full h-full object-contain"
                    fallbackSrc={product1}
                  />
                </button>
              ))}
            </div>
            
            {/* Main Image */}
            <div className="flex-1 relative">
              <div className="aspect-square rounded-xl border border-border overflow-hidden bg-muted group">
                <CachedImage 
                  src={galleryImages[selectedImageIndex]} 
                  alt={product.name}
                  className="w-full h-full object-contain transition-transform duration-300 group-hover:scale-105"
                  fallbackSrc={product1}
                  lazy={false}
                />
              </div>
              
              {/* Badges */}
              <div className="absolute top-3 left-3 flex flex-col gap-2">
                {product.badge && (
                  <Badge className="bg-primary text-primary-foreground">{product.badge}</Badge>
                )}
                {discountPercent > 0 && (
                  <Badge className="bg-secondary text-secondary-foreground">{discountPercent}{t('product.off')}</Badge>
                )}
              </div>
              
              {/* Favorite Button */}
              <button
                onClick={handleToggleFavorite}
                className="absolute top-3 right-3 bg-card/90 backdrop-blur-sm p-2.5 rounded-full shadow-lg hover:bg-card transition-all hover:scale-110"
                aria-label={isFavorite(Number(product.id)) ? t('product.removedFromFavorites') : t('product.addedToFavorites')}
              >
                <Heart className={`h-5 w-5 ${isFavorite(Number(product.id)) ? "fill-red-500 text-red-500" : "text-muted-foreground"}`} />
              </button>
            </div>
          </div>

          {/* Product Info */}
          <div className="space-y-4">
            {/* Title */}
            <h1 className="text-xl sm:text-2xl lg:text-3xl font-bold text-foreground leading-tight">
              {product.name}
            </h1>
            
            {/* Rating */}
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-1">
                {[...Array(5)].map((_, i) => (
                  <Star 
                    key={i} 
                    className={`h-4 w-4 ${i < Math.floor(rating) ? "fill-amber-400 text-amber-400" : "text-muted-foreground/30"}`} 
                  />
                ))}
              </div>
              <span className="text-sm text-primary font-medium">
                {rating > 0 ? rating.toFixed(1) : t('product.noRatings')}
              </span>
              <span className="text-sm text-muted-foreground">
                ({reviewsCount === 1 ? t('product.reviewsCount', { count: reviewsCount }) : t('product.reviewsCount_other', { count: reviewsCount })})
              </span>
            </div>

            <Separator />

            {/* Price Section - Amazon Style */}
            <div className="space-y-2">
              <div className="flex items-baseline gap-3 flex-wrap">
                <span className="text-3xl sm:text-4xl font-bold text-foreground">₹{price.toFixed(0)}</span>
                {originalPrice && originalPrice > price && (
                  <>
                    <span className="text-lg text-muted-foreground line-through">₹{originalPrice.toFixed(0)}</span>
                    <Badge variant="secondary" className="text-sm">
                      -{discountPercent}%
                    </Badge>
                  </>
                )}
              </div>
              {savings > 0 && (
                <p className="text-sm text-green-600 dark:text-green-400 font-medium">
                  {t('product.youSave', { amount: savings.toFixed(0) })}
                </p>
              )}
              <p className="text-xs text-muted-foreground">{t('product.inclusiveTaxes')}</p>
            </div>

            {/* Packaging / Size Selector */}
            {variants.length > 1 && (
              <div className="space-y-2">
                <span className="font-medium text-sm">{t('product.sizeLabel')}</span>
                <div className="flex flex-wrap gap-2">
                  {variants.map((v) => {
                    const isSelected = selectedVariant?.id === v.id;
                    const soldOut = !v.in_stock;
                    return (
                      <button
                        key={v.id}
                        type="button"
                        disabled={soldOut}
                        onClick={() => {
                          setSelectedVariant(v);
                          setQuantity(1);
                          // Keep the URL shareable for this size without a reload.
                          navigate(`/products/${v.slug}`, { replace: true });
                        }}
                        className={`px-4 py-2 rounded-xl border-2 text-sm font-medium transition-all active-press ${
                          isSelected
                            ? "border-primary bg-primary/5 text-primary shadow-sm shadow-primary/20"
                            : "border-border hover:border-primary/50"
                        } ${soldOut ? "opacity-40 cursor-not-allowed line-through" : ""}`}
                      >
                        {v.formatted_weight}
                        <span className="block text-xs font-normal text-muted-foreground">
                          ₹{Number(v.final_price).toFixed(0)}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Quick Info */}
            <div className="grid grid-cols-2 gap-3">
              <div className="flex items-center gap-2 text-sm">
                <span className="font-medium">{t('product.weightLabel')}</span>
                <span className="text-muted-foreground">{effectiveWeight}</span>
              </div>
              {product.spice_form && (
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-medium">{t('product.formLabel')}</span>
                  <span className="text-muted-foreground">{product.spice_form}</span>
                </div>
              )}
              {product.origin_country && (
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-medium">{t('product.originLabel')}</span>
                  <span className="text-muted-foreground">{product.origin_country}</span>
                </div>
              )}
              {product.shelf_life && (
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-medium">{t('product.shelfLifeLabel')}</span>
                  <span className="text-muted-foreground">{t('product.months', { count: product.shelf_life })}</span>
                </div>
              )}
            </div>

            {/* Stock Status */}
            <div className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg ${
              effectiveInStock
                ? "bg-green-50 dark:bg-green-950 text-green-700 dark:text-green-300"
                : "bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-300"
            }`}>
              {effectiveInStock ? (
                <>
                  <Check className="h-4 w-4" />
                  <span className="font-medium">{t('product.inStock')}</span>
                </>
              ) : (
                <span className="font-medium">{t('product.outOfStock')}</span>
              )}
            </div>

            {/* Quantity Selector */}
            {effectiveInStock && (
              <div className="flex items-center gap-4">
                <span className="font-medium">{t('product.quantityLabel')}</span>
                {itemInCart ? (
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="icon"
                      className="h-9 w-9"
                      onClick={() => updateCartQuantity(Number(product.id), itemInCart.quantity - 1, "product", selectedVariant?.id)}
                    >
                      <Minus className="h-4 w-4" />
                    </Button>
                    <span className="w-10 text-center font-semibold">{itemInCart.quantity}</span>
                    <Button
                      variant="outline"
                      size="icon"
                      className="h-9 w-9"
                      onClick={() => updateCartQuantity(Number(product.id), itemInCart.quantity + 1, "product", selectedVariant?.id)}
                      disabled={itemInCart.quantity >= effectiveStock}
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
                      onClick={() => setQuantity(Math.min(effectiveStock, MAX_ITEM_QUANTITY, quantity + 1))}
                      disabled={quantity >= Math.min(effectiveStock, MAX_ITEM_QUANTITY)}
                    >
                      <Plus className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </div>
            )}

            {/* Action Buttons */}
            <div className="flex gap-3">
              <Button
                variant="outline"
                className="flex-1 h-12 rounded-xl border-2 border-primary text-primary font-bold hover:bg-primary/10 active-press"
                onClick={handleAddToCart}
                disabled={!effectiveInStock}
              >
                <ShoppingCart className="mr-2 h-5 w-5" />
                {t('product.addToCart')}
              </Button>
              <Button
                className="flex-1 h-12 rounded-xl font-bold shadow-lg shadow-primary/30 hover:brightness-110 active-press"
                onClick={handleBuyNow}
                disabled={!effectiveInStock}
              >
                {t('product.buyNow')}
              </Button>
              <Button
                variant="outline"
                size="icon"
                className="h-12 w-12 rounded-xl"
                onClick={handleShareWhatsApp}
                title={t('footer.whatsapp')}
              >
                <MessageCircle className="h-5 w-5" />
              </Button>
              <Button
                variant="outline"
                size="icon"
                className="h-12 w-12 rounded-xl"
                onClick={handleShare}
                title={t('product.copyLink')}
              >
                <Share2 className="h-5 w-5" />
              </Button>
            </div>
            <TrustSignalBand />

            {/* FSSAI licence disclosure — required for packaged food sold online. */}
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <ShieldCheck className="h-4 w-4 text-primary flex-shrink-0" />
              <span className="notranslate">{t('product.fssai')}: 11414730000288</span>
            </div>

            {/* Organic Badge */}
            {product.organic && (
              <div className="flex items-center gap-3 p-4 bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-800 rounded-xl">
                <span className="text-2xl">🌿</span>
                <div>
                  <p className="font-semibold text-green-700 dark:text-green-300">{t('product.organicCertified')}</p>
                  <p className="text-sm text-green-600 dark:text-green-400">{t('product.naturalIngredients')}</p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Product Description */}
        <div className="max-w-4xl mb-10">
          <h2 className="text-xl font-bold mb-4">{t('product.aboutProduct')}</h2>
          <p className="text-muted-foreground leading-relaxed mb-4">{product.description}</p>
          
          {product.ingredients && (
            <div className="mt-4">
              <h3 className="font-semibold mb-2">{t('product.ingredientsLabel')}</h3>
              <p className="text-muted-foreground">{product.ingredients}</p>
            </div>
          )}

          {/* Recipe / Usage & Nutrition — collapsible so they don't crowd the
              page. Each only renders when the product actually has the data. */}
          {(product.recipe?.trim() || (product.nutrition && Object.keys(product.nutrition).length > 0)) && (
            <Accordion type="multiple" className="mt-6 space-y-3">
              {product.recipe?.trim() && (
                <AccordionItem
                  value="recipe"
                  className="rounded-xl border border-border bg-card px-4"
                >
                  <AccordionTrigger className="text-sm sm:text-base font-semibold hover:no-underline">
                    <span className="flex items-center gap-2">
                      <span aria-hidden>🍳</span>{t('product.recipeTitle')}
                    </span>
                  </AccordionTrigger>
                  <AccordionContent className="text-sm text-muted-foreground leading-relaxed whitespace-pre-line">
                    {product.recipe}
                  </AccordionContent>
                </AccordionItem>
              )}

              {product.nutrition && Object.keys(product.nutrition).length > 0 && (
                <AccordionItem
                  value="nutrition"
                  className="rounded-xl border border-border bg-card px-4"
                >
                  <AccordionTrigger className="text-sm sm:text-base font-semibold hover:no-underline">
                    <span className="flex items-center gap-2">
                      <span aria-hidden>📊</span>{t('product.nutritionTitle')}
                    </span>
                  </AccordionTrigger>
                  <AccordionContent>
                    <p className="mb-3 text-xs text-muted-foreground">{t('product.nutritionNote')}</p>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <tbody>
                          {Object.entries(product.nutrition).map(([key, value], i) => (
                            <tr
                              key={key}
                              className={i % 2 === 0 ? "bg-muted/40" : ""}
                            >
                              <th
                                scope="row"
                                className="py-2 px-3 text-left font-medium text-foreground whitespace-nowrap"
                              >
                                {t(`product.nutritionKeys.${key}`, {
                                  defaultValue: key
                                    .replace(/_/g, " ")
                                    .replace(/\b\w/g, (c) => c.toUpperCase()),
                                })}
                              </th>
                              <td className="py-2 px-3 text-right text-muted-foreground notranslate">
                                {value}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              )}
            </Accordion>
          )}
        </div>

        {/* Similar Products */}
        {similarProducts.length > 0 && (
          <section className="mb-12">
            <h2 className="text-xl font-bold mb-6">{t('product.customersAlsoBought')}</h2>
            <Carousel opts={{ align: "start", loop: false }} className="w-full">
              <CarouselContent className="-ml-4">
                {similarProducts.map((p) => (
                  <CarouselItem key={p.id} className="pl-4 basis-1/2 md:basis-1/3 lg:basis-1/4">
                    <ProductCard {...formatSimilarProduct(p)} />
                  </CarouselItem>
                ))}
              </CarouselContent>
              <CarouselPrevious className="hidden md:flex" />
              <CarouselNext className="hidden md:flex" />
            </Carousel>
          </section>
        )}

        {/* Reviews Section */}
        <section className="max-w-4xl">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-xl font-bold">{t('product.customerReviews')}</h2>
            {totalReviews > 0 && (
              <span className="text-sm text-muted-foreground">
                {t('product.showingReviews', { count: reviews.length, total: totalReviews })}
              </span>
            )}
          </div>

          {/* Write a review — only verified purchasers who haven't already
              reviewed this product get the form, mirroring the backend rule. */}
          {isLoggedIn && canReview ? (
            <Card className="mb-6">
              <CardContent className="p-4 space-y-4">
                <h3 className="font-semibold">{t('product.writeReview')}</h3>
                <div>
                  <Label className="mb-1 block text-sm">{t('product.yourRating')}</Label>
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
                </div>
                <div>
                  <Label htmlFor="review-title" className="mb-1 block text-sm">{t('product.reviewTitle')}</Label>
                  <Input
                    id="review-title"
                    value={reviewTitle}
                    onChange={(e) => setReviewTitle(e.target.value)}
                    placeholder={t('product.reviewTitlePlaceholder')}
                    maxLength={120}
                  />
                </div>
                <div>
                  <Label htmlFor="review-comment" className="mb-1 block text-sm">{t('product.reviewComment')}</Label>
                  <Textarea
                    id="review-comment"
                    value={reviewComment}
                    onChange={(e) => setReviewComment(e.target.value)}
                    placeholder={t('product.reviewCommentPlaceholder')}
                    rows={4}
                    maxLength={MAX_REVIEW_COMMENT}
                  />
                </div>
                <div className="flex justify-end">
                  <Button onClick={submitReview} disabled={submittingReview}>
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
          ) : (
            <Card className="mb-6">
              <CardContent className="p-4 flex items-center justify-between gap-3 flex-wrap">
                <p className="text-sm text-muted-foreground">{t('product.loginToReview')}</p>
                <Button variant="outline" onClick={() => navigate('/login', { state: { from: `/products/${id}` } })}>
                  {t('nav.login', 'Login')}
                </Button>
              </CardContent>
            </Card>
          )}

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
                      <span className="text-sm font-medium ml-2">{review.title || t('product.defaultReviewTitle')}</span>
                      {review.is_verified_purchase && (
                        <Badge variant="secondary" className="ml-2 text-xs">{t('product.verifiedPurchase')}</Badge>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground mb-2">{review.comment}</p>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      {review.user_name && <span>{t('product.reviewBy', { name: review.user_name })}</span>}
                      {review.created_at && (
                        <span>• {new Date(review.created_at).toLocaleDateString()}</span>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
              
              {/* Load More Button */}
              {hasMoreReviews && (
                <div className="flex justify-center pt-4">
                  <Button
                    variant="outline"
                    onClick={loadMoreReviews}
                    disabled={loadingMoreReviews}
                    className="min-w-[200px]"
                  >
                    {loadingMoreReviews ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        {t('common.loading')}
                      </>
                    ) : (
                      t('product.loadMoreReviews')
                    )}
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <div className="text-center py-8 bg-muted/50 rounded-xl">
              <p className="text-muted-foreground">{t('product.noReviews')}</p>
            </div>
          )}
        </section>
      </div>

      {/* Sticky Mobile Cart Bar — floats cleanly above the bottom nav */}
      <div className="fixed bottom-[4.5rem] left-3 right-3 bg-card/95 backdrop-blur-md border border-border rounded-2xl p-3 md:hidden z-40 shadow-xl shadow-primary/10 animate-cart-slide-up">
        <div className="flex items-center gap-3">
          <div className="flex-1">
            <div className="flex items-baseline gap-2">
              <span className="text-lg font-bold">₹{price.toFixed(0)}</span>
              {originalPrice && originalPrice > price && (
                <span className="text-sm text-muted-foreground line-through">₹{originalPrice.toFixed(0)}</span>
              )}
            </div>
            <p className={`text-xs ${effectiveInStock ? "text-green-600" : "text-red-600"}`}>
              {effectiveInStock ? t('product.inStock') : t('product.outOfStock')}
            </p>
          </div>
          <Button
            size="sm"
            onClick={handleAddToCart}
            disabled={!effectiveInStock}
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

export default ProductDetail;

