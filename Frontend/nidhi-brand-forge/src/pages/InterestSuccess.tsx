import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Heart } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCart } from "@/context/CartContext";
import { useTranslation } from "react-i18next";

const InterestSuccess = () => {
  const navigate = useNavigate();
  const { fetchCartFromBackend, setCart } = useCart();
  const { t } = useTranslation();

  useEffect(() => {
    // Clear cart and sync with backend on mount
    const clearAndSyncCart = async () => {
      try {
        // Clear local cart state immediately
        setCart([]);
        localStorage.removeItem('shopping_cart');
        
        // Fetch latest cart from backend (should be empty after order)
        await fetchCartFromBackend();
      } catch (error) {
        console.error('Failed to sync cart:', error);
      }
    };

    clearAndSyncCart();
  }, [fetchCartFromBackend, setCart]);

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4 pb-20 md:pb-0">
      <div className="text-center max-w-2xl bg-card p-8 rounded-2xl shadow-xl border border-border animate-in fade-in zoom-in duration-500">
        <div className="mb-6 flex justify-center">
          <div className="bg-primary/10 p-4 rounded-full animate-pulse">
            <Heart className="h-16 w-16 text-primary" />
          </div>
        </div>
        
        <h1 className="text-3xl sm:text-4xl font-bold text-foreground mb-6">
          {t('interestSuccess.title')}
        </h1>

        <div className="space-y-4 mb-8">
          <p className="text-xl font-medium text-primary">
            {t('interestSuccess.soon')}
          </p>
          <p className="text-lg text-muted-foreground">
            {t('interestSuccess.noted')}
          </p>
          <div className="bg-destructive/10 p-4 rounded-lg border border-destructive/20">
            <p className="text-destructive font-semibold">
              {t('interestSuccess.refund')}
            </p>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <Button
            onClick={() => navigate("/products")}
            size="lg"
            className="px-8 shadow-md hover:shadow-lg transition-all"
          >
            {t('interestSuccess.continueShopping')}
          </Button>
        </div>

        <div className="mt-12 pt-6 border-t border-border flex flex-col items-center gap-2 text-muted-foreground">
          <p className="text-sm font-medium">
            {t('interestSuccess.contactSupport')}
          </p>
          <p className="text-sm italic">
            {t('interestSuccess.tagline')}
          </p>
        </div>
      </div>
    </div>
  );
};

export default InterestSuccess;
