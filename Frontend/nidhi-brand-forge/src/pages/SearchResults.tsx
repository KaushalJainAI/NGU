import { useState, useEffect } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { Search as SearchIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import Footer from "@/components/Footer";
import ProductCard from "@/components/ProductCard";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { matchPages } from "@/lib/searchablePages";
import { searchAPI } from "@/lib/api/search";
import { API_BASE_URL } from "@/lib/api/config";
import { trackEvent, track } from "@/lib/api/analytics";
import { useTranslation } from "react-i18next";
import { formatWeight } from "@/lib/utils";

interface SearchProduct {
  id: number;
  name: string;
  slug: string;
  type: string;
  category: string;
  spice_form: string;
  price: number;
  original_price: number;
  discount: number;
  weight: number;
  unit: string;
  image: string;
  score: number;
  score_type: string;
  in_stock: number;
  is_featured: boolean;
}

interface SearchResponse {
  query: string;
  total_results: number;
  products: SearchProduct[];
  combos: any[];
  stats: {
    direct_matches: number;
    other_recs: number;
  };
}

const SearchResults = () => {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const searchQuery = searchParams.get("search") || searchParams.get("q") || "";
  const [sortBy, setSortBy] = useState("relevance");
  const [loading, setLoading] = useState(false);
  const [searchData, setSearchData] = useState<SearchResponse | null>(null);

  useEffect(() => {
    if (searchQuery) {
      fetchSearchResults(searchQuery);
    } else {
      setSearchData(null);
    }
  }, [searchQuery]);

  const fetchSearchResults = async (query: string) => {
    setLoading(true);
    try {
      const response = await searchAPI.search(query);
      // Type assertion to match interface
      setSearchData(response as SearchResponse);
      const resultCount = response?.total_results ?? 0;
      track(
        {
          event_type: "search",
          query,
          metadata: { results: resultCount, zero: resultCount === 0 },
        },
        { metric: "search", query, zero: resultCount === 0 },
      );
    } catch (error) {
      console.error("Error fetching search results:", error);
      setSearchData(null);
    } finally {
      setLoading(false);
    }
  };

  // Use backend ranking with frontend sorting overlay
  const getSortedProducts = () => {
    if (!searchData?.products) return [];
    
    return [...searchData.products].sort((a, b) => {
      switch (sortBy) {
        case "price-low":
          return a.price - b.price;
        case "price-high":
          return b.price - a.price;
        case "name":
          return a.name.localeCompare(b.name);
        case "featured":
          return (b.is_featured ? 1 : 0) - (a.is_featured ? 1 : 0);
        case "relevance":
        default:
          // Use backend score as primary sort (maintains backend ranking)
          return b.score - a.score;
      }
    });
  };

  const sortedProducts = getSortedProducts();
  const totalResults = searchData?.total_results || 0;
  // Pages (cart, policies, orders, …) that match the query, shown alongside products.
  const pageMatches = matchPages(searchQuery, 6);

  if (loading) {
    return (
      <div className="min-h-screen bg-background pb-20 md:pb-0">
        <div className="container mx-auto px-4 py-20 text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto mb-4"></div>
          <p className="text-lg text-muted-foreground">{t('search.searching')}</p>
        </div>
        <Footer />
      </div>
    );
  }

  // /search with no query: there is nothing to render below, so without this
  // the page is blank. Prompt instead, and offer a way back into the catalog.
  if (!searchQuery.trim()) {
    return (
      <div className="min-h-screen bg-background pb-20 md:pb-0">
        <div className="container mx-auto px-4 py-20 text-center">
          <SearchIcon className="mx-auto mb-4 h-12 w-12 text-muted-foreground" />
          <h1 className="mb-2 text-xl font-bold text-foreground sm:text-2xl">
            {t('search.emptyTitle')}
          </h1>
          <p className="mb-6 text-muted-foreground">{t('search.emptyBody')}</p>
          <Button asChild>
            <Link to="/products">{t('search.browseAll')}</Link>
          </Button>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      {/* Results & Products */}
      <section className="py-6 sm:py-12">
        <div className="container mx-auto px-3 sm:px-4">
          {/* Result heading + count */}
          {searchQuery && (
            <div className="mb-5 sm:mb-8">
              <h1 className="text-lg sm:text-2xl font-bold text-foreground">
                {t('search.resultsFor', { query: searchQuery })}
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {t('search.resultsCount', { count: totalResults })}
              </p>
            </div>
          )}

          {/* Pages that match — quick links to cart, policies, orders, etc. */}
          {pageMatches.length > 0 && (
            <div className="mb-6 sm:mb-8">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                {t('search.pages', 'Pages')}
              </h2>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {pageMatches.map((p) => (
                  <Link
                    key={p.path}
                    to={p.path}
                    className="flex items-center gap-3 rounded-xl border border-border bg-card p-3 shadow-sm transition-colors hover:border-primary/40 hover:bg-accent/5"
                  >
                    <span className="grid h-10 w-10 flex-shrink-0 place-items-center rounded-full bg-primary/10 text-primary">
                      <p.icon className="h-5 w-5" />
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-foreground">{p.title}</span>
                      <span className="block truncate text-xs text-muted-foreground">{p.description}</span>
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {/* Sort */}
          {sortedProducts.length > 0 && (
            <div className="flex justify-end items-center mb-4 sm:mb-8">
              <Select value={sortBy} onValueChange={setSortBy}>
                <SelectTrigger className="w-36 sm:w-48">
                  <SelectValue placeholder={t('products.sortBy')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="relevance">{t('search.sortRelevance')}</SelectItem>
                  <SelectItem value="featured">{t('products.sortFeatured')}</SelectItem>
                  <SelectItem value="price-low">{t('products.sortPriceLowToHigh')}</SelectItem>
                  <SelectItem value="price-high">{t('products.sortPriceHighToLow')}</SelectItem>
                  <SelectItem value="name">{t('products.sortName')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Products Grid */}
          {sortedProducts.length > 0 ? (
            <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 sm:gap-6">
              {sortedProducts.map((product) => (
                <ProductCard 
                  key={product.id}
                  id={Number(product.id)}
                  name={product.name}
                  image={product.image.startsWith('/') ? `${API_BASE_URL.replace(/\/api\/?$/, '')}${product.image}` : product.image}
                  price={product.price}
                  originalPrice={product.original_price}
                  weight={formatWeight(product.weight, product.unit, "100g")}
                  badge={product.is_featured ? t('product.featured') : product.discount > 0 ? `${product.discount}${t('product.off')}` : undefined}
                />
              ))}
            </div>
          ) : pageMatches.length === 0 ? (
            <div className="text-center py-16">
              <p className="text-xl text-muted-foreground mb-4">{t('search.noResults')}</p>
              <p className="text-muted-foreground">{t('search.tryDifferent')}</p>
            </div>
          ) : null}
        </div>
      </section>

      <Footer />
    </div>
  );
};

export default SearchResults;
