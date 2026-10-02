import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { CheckCircle, Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCart } from "@/context/CartContext";
import { toast } from "sonner";
import { track } from "@/lib/api/analytics";
import { ordersAPI } from "@/lib/api/orders";
import { useTranslation } from "react-i18next";

const OrderSuccess = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { fetchCartFromBackend, setCart } = useCart();
  const { t } = useTranslation();

  // The checkout flow passes the freshly-placed order via router state so we can
  // show a REAL confirmation (order number + invoice), not a generic thank-you.
  const { orderId, orderNumber } = (location.state || {}) as {
    orderId?: number;
    orderNumber?: string;
  };
  const [downloading, setDownloading] = useState(false);

  // Funnel signal: checkout completed. (The authoritative purchase event is
  // recorded server-side from the order; this closes the client-side funnel.)
  useEffect(() => {
    track({ event_type: "checkout_completed" }, { metric: "checkout_completed" });
  }, []);

  useEffect(() => {
    // Clear cart and sync with backend on mount
    const clearAndSyncCart = async () => {
      try {
        setCart([]);
        localStorage.removeItem("shopping_cart");
        await fetchCartFromBackend();
      } catch (error) {
        console.error("Failed to sync cart after order:", error);
        // Don't show error toast - order was successful
      }
    };

    clearAndSyncCart();
    // No auto-redirect: this is the order confirmation, the customer should
    // stay until they choose to leave (and can grab their invoice first).
  }, [fetchCartFromBackend, setCart]);

  const handleDownloadInvoice = async () => {
    if (!orderId) return;
    setDownloading(true);
    try {
      await ordersAPI.downloadInvoice(orderId, orderNumber);
    } catch {
      toast.error(t("orderSuccess.invoiceFailed", "Could not download the invoice. You can get it from My Orders."));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4 pb-20 md:pb-0">
      <div className="text-center max-w-md">
        <div className="mb-8 flex justify-center animate-bounce">
          <CheckCircle className="h-24 w-24 text-green-500" />
        </div>

        <h1 className="text-4xl font-bold text-foreground mb-4 animate-fade-in">
          {t("orderSuccess.title")}
        </h1>

        <p className="text-lg text-muted-foreground mb-4 animate-fade-in">
          {t("orderSuccess.subtitle")}
        </p>

        {orderNumber && (
          <div className="mb-8 inline-block rounded-lg border border-border bg-card px-6 py-3">
            <p className="text-sm text-muted-foreground">
              {t("orderSuccess.orderNumber", "Order number")}
            </p>
            <p className="text-xl font-bold tracking-wide">{orderNumber}</p>
          </div>
        )}

        <div className="space-y-4 animate-fade-in">
          {orderId && (
            <Button
              onClick={handleDownloadInvoice}
              variant="secondary"
              size="lg"
              className="w-full"
              disabled={downloading}
            >
              {downloading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Download className="mr-2 h-4 w-4" />
              )}
              {t("orderSuccess.downloadInvoice", "Download invoice")}
            </Button>
          )}

          <Button
            onClick={() => navigate("/my-orders")}
            size="lg"
            className="w-full"
          >
            {t("orderSuccess.viewOrders")}
          </Button>

          <Button
            onClick={() => navigate("/products")}
            variant="outline"
            size="lg"
            className="w-full"
          >
            {t("orderSuccess.continueShopping")}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default OrderSuccess;
