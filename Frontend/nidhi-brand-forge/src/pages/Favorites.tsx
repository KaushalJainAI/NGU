import { Link } from "react-router-dom";
import { Heart } from "lucide-react";
import Footer from "@/components/Footer";
import ProductCard from "@/components/ProductCard";
import { Button } from "@/components/ui/button";
import { useFavorites } from "@/context/FavoritesContext";
import { useTranslation } from "react-i18next";

const Favorites = () => {
  const { favorites } = useFavorites();
  const { t } = useTranslation();


  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      <div className="container mx-auto px-3 sm:px-4 py-6 sm:py-12">
        {favorites.length > 0 && (
          <div className="mb-5 sm:mb-8">
            <h1 className="text-xl sm:text-3xl font-bold text-foreground">{t('favorites.title')}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {favorites.length === 1
                ? t('favorites.count', { count: favorites.length })
                : t('favorites.count_other', { count: favorites.length })}
            </p>
          </div>
        )}
        {favorites.length > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2 sm:gap-6">
            {favorites.map((product) => (
              <ProductCard key={product.id} {...product} />
            ))}
          </div>
        ) : (
          <div className="text-center py-12 sm:py-20">
            <div className="mx-auto mb-4 h-20 w-20 rounded-full spice-backdrop grid place-items-center">
              <Heart className="h-9 w-9 text-primary" />
            </div>
            <p className="text-foreground font-semibold text-lg mb-1">{t('favorites.empty')}</p>
            <p className="text-muted-foreground text-sm mb-6">{t('favorites.emptyHint')}</p>
            <Button asChild className="rounded-full font-bold shadow-lg shadow-primary/30 active-press">
              <Link to="/products">{t('favorites.browse')}</Link>
            </Button>
          </div>
        )}
      </div>

      <Footer />
    </div>
  );
};

export default Favorites;
