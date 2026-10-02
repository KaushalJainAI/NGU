import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import Footer from "@/components/Footer";
import ProductCard from "@/components/ProductCard";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2 } from "lucide-react";
import { productsAPI, categoriesAPI } from "@/lib/api";
import { useTranslation } from "react-i18next";

const Products = () => {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const categoryFromUrl = searchParams.get("category");
  
  const [selectedCategory, setSelectedCategory] = useState<string>(categoryFromUrl || "all");
  const [sortBy, setSortBy] = useState("featured");
  // Swiggy-style quick filters: "all" | "offers" | "rating"
  const [quickFilter, setQuickFilter] = useState<"all" | "offers" | "rating">("all");
  const [products, setProducts] = useState<any[]>([]);
  const [categories, setCategories] = useState<{ id: number; name: string; slug: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Fetch categories on mount
  useEffect(() => {
    categoriesAPI.getAll()
      .then((data) => {
        // Categories is DRF-paginated ({ results }).
        setCategories(data.results || []);
      })
      .catch((err) => console.error("Failed to fetch categories:", err));
  }, []);

  // Fetch products when category changes
  useEffect(() => {
    setLoading(true);
    setError("");
    
    const fetchProducts = async () => {
      try {
        let data;
        if (selectedCategory && selectedCategory !== "all") {
          data = await productsAPI.getByCategory(selectedCategory);
        } else {
          data = await productsAPI.getAll();
        }
        setProducts(data.results || data || []);
      } catch (err) {
        // Never surface raw backend/validation strings to shoppers (e.g. an
        // invalid ?category= id). Log the detail, show a friendly message.
        console.error("Failed to fetch products:", err);
        setError(t('products.loadError'));
        setProducts([]);
      } finally {
        setLoading(false);
      }
    };

    fetchProducts();
  }, [selectedCategory]);

  // Sync category with URL
  useEffect(() => {
    if (categoryFromUrl) {
      setSelectedCategory(categoryFromUrl);
    }
  }, [categoryFromUrl]);

  const handleCategoryChange = (categoryId: string) => {
    setSelectedCategory(categoryId);
    if (categoryId === "all") {
      searchParams.delete("category");
    } else {
      searchParams.set("category", categoryId);
    }
    setSearchParams(searchParams);
  };

  // Quick-filter narrowing (applied before sorting).
  const filteredProducts = products.filter((p) => {
    if (quickFilter === "offers") {
      const discounted = p.discount_price || (p.final_price && p.final_price < p.price);
      if (!discounted) return false;
    }
    if (quickFilter === "rating") {
      if (!(Number(p.average_rating) >= 4)) return false;
    }
    return true;
  });

  // Sorting logic
  const sortedProducts = [...filteredProducts].sort((a, b) => {
    const priceA = a.final_price || a.discount_price || a.price;
    const priceB = b.final_price || b.discount_price || b.price;
    
    switch (sortBy) {
      case "price-low":
        return priceA - priceB;
      case "price-high":
        return priceB - priceA;
      case "name":
        return a.name.localeCompare(b.name);
      default:
        return 0;
    }
  });

  const formatProduct = (product: any) => ({
    id: Number(product.id),
    name: product.name,
    image: product.image,
    price: product.final_price || product.discount_price || product.price,
    originalPrice: product.discount_price ? product.price : undefined,
    weight: product.weight || "100g",
    badge: product.badge,
    itemType: "product" as const,
    variantCount: product.variant_count ?? 1,
  });

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      <section className="py-6 sm:py-12">
        <div className="container mx-auto px-3 sm:px-4">
          {/* Swiggy-style quick-filter chips */}
          <div className="flex gap-2 overflow-x-auto no-scrollbar pb-3 mb-2">
            {[
              { key: "all", label: t('products.filterAll') },
              { key: "offers", label: t('products.filterOffers') },
              { key: "rating", label: t('products.filterRating') },
            ].map((chip) => (
              <button
                key={chip.key}
                onClick={() => setQuickFilter(chip.key as typeof quickFilter)}
                className={`shrink-0 text-xs font-semibold px-3 py-1.5 rounded-full border transition-colors active-press ${
                  quickFilter === chip.key
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-card border-border hover:border-primary"
                }`}
              >
                {chip.label}
              </button>
            ))}
            <button
              onClick={() => setSortBy("price-low")}
              className={`shrink-0 text-xs font-semibold px-3 py-1.5 rounded-full border transition-colors active-press ${
                sortBy === "price-low" ? "bg-primary text-primary-foreground border-primary" : "bg-card border-border hover:border-primary"
              }`}
            >
              {t('products.sortPriceLow')}
            </button>
          </div>

          {/* Mobile/tablet category filter — the sidebar is desktop-only, so on
              smaller screens categories live in this scrollable chip row. */}
          <div className="lg:hidden flex gap-2 overflow-x-auto no-scrollbar pb-3 mb-2">
            <button
              onClick={() => handleCategoryChange("all")}
              className={`shrink-0 text-xs font-semibold px-3 py-1.5 rounded-full border transition-colors active-press ${
                selectedCategory === "all"
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-card border-border hover:border-primary"
              }`}
            >
              {t('category.allSpices')}
            </button>
            {categories.map((category) => (
              <button
                key={category.id}
                onClick={() => handleCategoryChange(String(category.id))}
                className={`shrink-0 text-xs font-semibold px-3 py-1.5 rounded-full border transition-colors active-press ${
                  selectedCategory === String(category.id)
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-card border-border hover:border-primary"
                }`}
              >
                {category.name}
              </button>
            ))}
          </div>

          <div className="grid lg:grid-cols-[220px_1fr] gap-6">
            {/* Desktop category sidebar */}
            <aside className="hidden lg:block">
              <div className="bg-card border border-border rounded-2xl p-4 sticky top-32">
                <h3 className="font-bold text-sm mb-3">{t('category.categories')}</h3>
                <ul className="space-y-1 text-sm">
                  <li
                    onClick={() => handleCategoryChange("all")}
                    className={`rounded-lg px-3 py-2 cursor-pointer transition-colors ${
                      selectedCategory === "all" ? "bg-primary/10 text-primary font-semibold" : "hover:bg-muted"
                    }`}
                  >
                    {t('category.allSpices')}
                  </li>
                  {categories.map((category) => (
                    <li
                      key={category.id}
                      onClick={() => handleCategoryChange(String(category.id))}
                      className={`rounded-lg px-3 py-2 cursor-pointer transition-colors ${
                        selectedCategory === String(category.id) ? "bg-primary/10 text-primary font-semibold" : "hover:bg-muted"
                      }`}
                    >
                      {category.name}
                    </li>
                  ))}
                </ul>
              </div>
            </aside>

            {/* Main column */}
            <div>
              <div className="flex items-center justify-between gap-3 mb-3 sm:mb-4">
                <h2 className="text-base sm:text-lg font-bold">
                  {loading ? t('products.loadingProducts') : (sortedProducts.length === 1 ? t('products.productCount', { count: sortedProducts.length }) : t('products.productCount_other', { count: sortedProducts.length }))}
                </h2>
                <Select value={sortBy} onValueChange={setSortBy}>
                  <SelectTrigger className="w-40 sm:w-48 h-9 text-xs sm:text-sm">
                    <SelectValue placeholder={t('products.sortBy')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="featured">{t('products.sortFeatured')}</SelectItem>
                    <SelectItem value="price-low">{t('products.sortPriceLowToHigh')}</SelectItem>
                    <SelectItem value="price-high">{t('products.sortPriceHighToLow')}</SelectItem>
                    <SelectItem value="name">{t('products.sortName')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 sm:gap-6">
                {loading ? (
                  <div className="col-span-full flex justify-center py-12">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                  </div>
                ) : error ? (
                  <div className="col-span-full text-center py-12 text-destructive">{error}</div>
                ) : sortedProducts.length === 0 ? (
                  <div className="col-span-full text-center py-12 text-muted-foreground">{t('products.noProducts')}</div>
                ) : (
                  sortedProducts.map((product) => (
                    <ProductCard key={product.id} {...formatProduct(product)} />
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </section>
      <Footer />
    </div>
  );
};

export default Products;
