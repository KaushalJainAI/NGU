// MyOrders.tsx

import { useState, useEffect, useCallback, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import Footer from "@/components/Footer";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Package,
  Download,
  Repeat,
  ChevronDown,
  ChevronUp,
  XCircle,
  MessageCircle,
  Star,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { ordersAPI, Order } from "@/lib/api/orders";
import { razorpayAPI } from "@/lib/api/payments";
import { openRazorpayCheckout } from "@/lib/razorpay";
import { reviewsAPI } from "@/lib/api/reviews";
import { MAX_REVIEW_COMMENT } from "@/config/limits";
import { useCart } from "@/context/CartContext";
import { useAuth } from "@/context/AuthContext";
import { useTranslation, Trans } from "react-i18next";
import { PriceBreakup } from "@/components/PriceBreakup";

import product1 from "@/assets/product-1.jpg";

const MyOrders = () => {
  const { t } = useTranslation();
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const { isLoggedIn, isLoading: authLoading } = useAuth();

  // Redirect to login if not logged in
  useEffect(() => {
    if (!authLoading && !isLoggedIn) {
      navigate('/login', { state: { from: '/my-orders' } });
    }
  }, [isLoggedIn, authLoading, navigate]);

  // Per-product/combo review dialog
  const [productReviewDialog, setProductReviewDialog] = useState<{
    open: boolean;
    itemType: 'product' | 'combo';
    itemId: number | null;
    itemName: string;
    orderId: number | null;
  }>({
    open: false,
    itemType: 'product',
    itemId: null,
    itemName: "",
    orderId: null,
  });

  const [currentRating, setCurrentRating] = useState(0);
  const [currentReview, setCurrentReview] = useState("");
  // Which of the open order's items the customer may still review, keyed
  // "<item_type>:<id>". The dialog used to open on items[0] unconditionally and
  // offer no hint that it had already been reviewed, so the only feedback was a
  // failed submit.
  const [itemEligibility, setItemEligibility] = useState<Record<string, boolean>>({});
  const eligibilityKey = (itemType: 'product' | 'combo', itemId: number) => `${itemType}:${itemId}`;

  const [expandedOrderId, setExpandedOrderId] = useState<number | null>(null);

  const [cancelDialog, setCancelDialog] = useState<{
    open: boolean;
    orderId: number | null;
  }>({
    open: false,
    orderId: null,
  });
  const [cancelLoading, setCancelLoading] = useState(false);

  const { addToCart } = useCart();



  const formatDate = (dateString: string) =>
    new Date(dateString).toLocaleDateString("en-IN", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });

  const formatStatus = (status: string) => {
    const map: Record<string, string> = {
      pending: t('myOrders.statusPending'),
      confirmed: t('myOrders.statusConfirmed', 'Confirmed'),
      processing: t('myOrders.statusProcessing', 'Processing'),
      shipped: t('myOrders.statusShipped', 'Shipped'),
      delivering: t('myOrders.statusDelivering', 'Out for delivery'),
      in_transit: t('myOrders.statusInTransit'),
      delivered: t('myOrders.statusDelivered'),
      cancelled: t('myOrders.statusCancelled'),
      refunded: t('myOrders.statusRefunded', 'Refunded'),
    };
    const key = status.toLowerCase();
    // Title-case fallback for any status without an explicit label.
    return map[key] ?? key.charAt(0).toUpperCase() + key.slice(1);
  };

  const formatCurrency = (v: number) =>
    new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 2,
    }).format(v);

  // reusable fetch function so we can call it after cancel as well
  const fetchOrders = useCallback(async () => {
    try {
      setLoading(true);
      const data = await ordersAPI.getAll();
      if (Array.isArray(data)) {
        setOrders(data);
      } else {
        setOrders([]);
      }
    } catch (err: any) {
      console.error(err);
      // Check if it's an authentication error (401 or 403)
      const status = err?.response?.status || err?.status;
      if (status === 401 || status === 403) {
        toast.error(t('myOrders.loginRequired'));
      } else {
        toast.error(t('myOrders.loadFailed'));
      }
      setOrders([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOrders();
  }, [fetchOrders]);

  // Refs for order cards to scroll into view
  const orderRefs = useRef<{ [key: number]: HTMLDivElement | null }>({});

  const toggleExpanded = (orderId: number) => {
    setExpandedOrderId((prev) => (prev === orderId ? null : orderId));
  };

  const handleReorder = async (order: Order) => {
    if (!order.items || order.items.length === 0) {
      toast.error(t('myOrders.noItemsReorder'));
      return;
    }

    try {
      for (const item of order.items) {
        await addToCart({
          id: item.product_id,
          itemType: "product",
          name: item.product_name,
          image: item.image || product1,
          price: item.price,
          originalPrice: item.price,
          badge: "Reorder",
          quantity: item.quantity,
        });
      }

      toast.success(t('myOrders.reorderAdded'));
    } catch (error) {
      console.error("Failed to reorder:", error);
      toast.error(t('myOrders.reorderFailed'));
    }
  };

  const handleDownloadBill = async (order: Order) => {
    try {
      await ordersAPI.downloadInvoice(order.id, order.order_number);
      toast.success(t('myOrders.billDownloaded', { order: order.order_number }));
    } catch (error) {
      console.error("Failed to download bill:", error);
      // The API explains WHY when no invoice exists yet; a generic failure
      // message would send the customer to support over a normal state.
      const reason = error instanceof Error ? error.message : "";
      toast.error(reason || t('myOrders.billFailed'));
    }
  };

  const handleChatSupport = (order: Order) => {
    // Open the unified assistant widget, pre-seeded with the order context.
    // (Order-scoped chat now lives in the same thread as the AI assistant.)
    window.dispatchEvent(
      new CustomEvent("assistant:open", {
        detail: { seed: t('myOrders.supportSeed', { order: order.order_number }) },
      })
    );
  };

  const openProductReviewDialog = (itemType: 'product' | 'combo', itemId: number, itemName: string, orderId: number) => {
    setProductReviewDialog({
      open: true,
      itemType,
      itemId,
      itemName,
      orderId,
    });
    setCurrentRating(0);
    setCurrentReview("");
  };

  /**
   * Open the review dialog for an order, landing on the first item the customer
   * can actually review rather than always on items[0] — otherwise an order
   * whose first item is already reviewed opens onto a guaranteed failure.
   * Eligibility for every item is fetched in the background to grey out the
   * ones already done.
   */
  const openOrderReviewDialog = async (order: Order) => {
    const items = (order.items || []).filter(
      (it) => (it.item_type === 'combo' ? it.combo_id : it.product_id),
    );
    if (items.length === 0) return;

    const idOf = (it: typeof items[number]) =>
      (it.item_type === 'combo' ? it.combo_id : it.product_id) as number;

    // Open immediately on items[0] so the dialog never feels laggy; the
    // eligibility results below move the selection if that one is spent.
    openProductReviewDialog(items[0].item_type, idOf(items[0]), items[0].product_name, order.id);

    const results = await Promise.all(
      items.map(async (it) => {
        const id = idOf(it);
        try {
          const res = it.item_type === 'combo'
            ? await reviewsAPI.canReviewCombo(id)
            : await reviewsAPI.canReviewProduct(id);
          return [eligibilityKey(it.item_type, id), res.can_review] as const;
        } catch {
          // Treat an unknown as reviewable: the POST re-checks anyway, and
          // wrongly greying out a valid item is worse than a clear error.
          return [eligibilityKey(it.item_type, id), true] as const;
        }
      }),
    );
    setItemEligibility(Object.fromEntries(results));

    const firstOpen = items.find((it) => {
      const entry = results.find(([k]) => k === eligibilityKey(it.item_type, idOf(it)));
      return entry?.[1];
    });
    if (firstOpen && idOf(firstOpen) !== idOf(items[0])) {
      setProductReviewDialog((prev) => prev.orderId === order.id ? {
        ...prev,
        itemType: firstOpen.item_type,
        itemId: idOf(firstOpen),
        itemName: firstOpen.product_name,
      } : prev);
    }
  };

  const [reviewLoading, setReviewLoading] = useState(false);

  const handleSubmitProductReview = async () => {
    if (currentRating === 0) {
      toast.error(t('myOrders.selectRating'));
      return;
    }
    if (!productReviewDialog.itemId) {
      toast.error(t('myOrders.noItemSelected'));
      return;
    }

    try {
      setReviewLoading(true);
      const reviewData = {
        item_type: productReviewDialog.itemType,
        rating: currentRating,
        // This dialog has no title input. It used to send the item's own name,
        // which then displayed as the review's headline — every review titled
        // after the product. The title is optional server-side, so leave it
        // blank and let the card fall back to its default heading.
        title: "",
        comment: currentReview || "",
        ...(productReviewDialog.itemType === 'product' 
          ? { product: productReviewDialog.itemId }
          : { combo: productReviewDialog.itemId }
        ),
      };
      await reviewsAPI.create(reviewData);
      // One review per item — retire it from the selector immediately.
      setItemEligibility(prev => ({
        ...prev,
        [eligibilityKey(productReviewDialog.itemType, productReviewDialog.itemId as number)]: false,
      }));
      toast.success(t('myOrders.reviewSubmitted', { name: productReviewDialog.itemName }));
      setProductReviewDialog({ open: false, itemType: 'product', itemId: null, itemName: "", orderId: null });
      setCurrentRating(0);
      setCurrentReview("");
    } catch (error: any) {
      console.error("Failed to submit review:", error);

      
      const message = error?.message && error.message !== "Bad Request"
        ? error.message
        : t('myOrders.reviewFailed');

      toast.error(message);
    } finally {
      setReviewLoading(false);
    }
  };

  const openCancelDialog = (orderId: number) => {
    setCancelDialog({ open: true, orderId });
  };

  const handleConfirmCancel = async () => {
    if (!cancelDialog.orderId) return;
    try {
      setCancelLoading(true);
      await ordersAPI.cancel(cancelDialog.orderId);
      toast.success(t('myOrders.cancelSuccess'));

      // auto-refresh list from backend
      await fetchOrders();

      setCancelDialog({ open: false, orderId: null });
    } catch (err: any) {
      console.error("Failed to cancel order:", err);
      const msg =
        err?.data?.error || t('myOrders.cancelFailed');
      toast.error(msg);
    } finally {
      setCancelLoading(false);
    }
  };

  const isCancellable = (status: string) => {
    // Mirror the backend: a customer may cancel until the parcel is out for
    // delivery or already delivered/cancelled.
    const s = status.toLowerCase();
    return !["delivering", "delivered", "cancelled", "refunded"].includes(s);
  };

  // A payable ONLINE order that hasn't been paid yet can be retried. The cart is
  // already gone, so retry re-uses the SAME order (never re-adds to cart) —
  // PAYMENT_INTEGRATION_PLAN.md §6.6.
  const [retryingId, setRetryingId] = useState<number | null>(null);

  const canRetryPayment = (order: Order) => {
    const method = (order.payment_method || "").toUpperCase();
    const ps = (order.payment_status || "").toLowerCase();
    const s = order.status.toLowerCase();
    return method === "ONLINE" &&
      ["pending", "processing", "failed"].includes(ps) &&
      !["cancelled", "delivered", "delivering", "refunded"].includes(s);
  };

  const handleRetryPayment = async (order: Order) => {
    try {
      setRetryingId(order.id);
      const rzp = await razorpayAPI.createOrder(order.id);
      await openRazorpayCheckout({
        key: rzp.razorpay_key_id,
        amount: rzp.amount,
        currency: rzp.currency,
        orderId: rzp.razorpay_order_id,
        name: "Nidhi Masala",
        description: `Order ${order.order_number}`,
        onSuccess: async (r) => {
          try {
            await razorpayAPI.verify({
              razorpay_order_id: r.razorpay_order_id,
              razorpay_payment_id: r.razorpay_payment_id,
              razorpay_signature: r.razorpay_signature,
            });
            toast.success(t('myOrders.paymentSuccess', 'Payment received!'));
          } catch {
            toast.message(t('myOrders.paymentConfirming', 'Confirming your payment…'));
          } finally {
            setRetryingId(null);
            fetchOrders();
          }
        },
        onDismiss: () => setRetryingId(null),
      });
    } catch (err: any) {
      toast.error(err?.data?.error || t('myOrders.retryFailed', 'Could not start payment. Please try again.'));
      setRetryingId(null);
    }
  };

  const isDelivered = (status: string) => {
    return status.toLowerCase() === "delivered";
  };

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0" style={{ background: "var(--backdrop-spice)" }} aria-hidden />
        <div className="relative container mx-auto px-4 py-8 sm:py-14 max-w-5xl animate-fade-in-up">
          <div className="flex items-center gap-3 sm:gap-4">
            <div className="grid h-12 w-12 sm:h-16 sm:w-16 place-items-center rounded-full bg-gradient-to-br from-primary to-accent text-white shadow-[var(--shadow-elegant)]">
              <Package className="h-6 w-6 sm:h-8 sm:w-8" />
            </div>
            <div>
              <h1 className="text-2xl sm:text-4xl font-extrabold tracking-tight text-foreground">
                {t('myOrders.titleLead')}{" "}
                <span className="bg-gradient-to-r from-primary via-primary to-accent bg-clip-text text-transparent">
                  {t('myOrders.titleAccent')}
                </span>
              </h1>
              <p className="text-sm sm:text-base text-muted-foreground mt-0.5">
                {loading
                  ? t('myOrders.fetching')
                  : orders.length > 0
                  ? t('myOrders.placedCount', { count: orders.length })
                  : t('myOrders.trackSubtitle')}
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="py-6 sm:py-10">
        <div className="container mx-auto px-3 sm:px-4 max-w-5xl">
          {loading ? (
            <p className="text-center text-muted-foreground">
              {t('myOrders.loadingOrders')}
            </p>
          ) : orders.length > 0 ? (
              <div className="space-y-4 sm:space-y-6">
              {orders.map((order) => {
                const isExpanded = expandedOrderId === order.id;
                const cancellable = isCancellable(order.status);
                const delivered = isDelivered(order.status);

                return (
                  <Card
                    key={order.id}
                    ref={(el) => { orderRefs.current[order.id] = el; }}
                    className="overflow-hidden rounded-2xl border-border shadow-card"
                  >
                    <CardContent className="p-3 sm:p-6">
                      {/* Header */}
                      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-3 sm:mb-4 gap-2 sm:gap-4">
                        <div>
                          <h3 className="font-semibold text-sm sm:text-lg mb-0.5 sm:mb-1">
                            {t('myOrders.orderLabel', { number: order.order_number })}
                          </h3>
                          <p className="text-xs sm:text-sm text-muted-foreground">
                            {t('myOrders.placedOn', { date: formatDate(order.created_at) })}
                          </p>
                        </div>
                        <div className="flex items-center gap-2">
                          <Badge
                            variant={
                              order.status === "delivered"
                                ? "default"
                                : order.status === "cancelled"
                                ? "destructive"
                                : "secondary"
                            }
                            className="w-fit"
                          >
                            {formatStatus(order.status)}
                          </Badge>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 sm:h-10 sm:w-10"
                            onClick={() => toggleExpanded(order.id)}
                            aria-label={isExpanded ? t('myOrders.showLess') : t('myOrders.showMore')}
                          >
                            {isExpanded ? (
                              <ChevronUp className="h-4 w-4 sm:h-5 sm:w-5" />
                            ) : (
                              <ChevronDown className="h-4 w-4 sm:h-5 sm:w-5" />
                            )}
                          </Button>
                        </div>
                      </div>

                      {/* Always-visible total row */}
                      <div className="flex justify-between items-center mb-3 sm:mb-4 pb-3 sm:pb-4 border-b">
                        <span className="font-semibold text-sm sm:text-base">{t('myOrders.total')}</span>
                        <span className="text-lg sm:text-xl font-bold text-primary">
                          {formatCurrency(order.total)}
                        </span>
                      </div>

                      {/* Refund — the customer's own money coming back, so it sits
                          OUTSIDE the "show more" fold: never make someone expand a
                          section to find out how much they were refunded.
                          A refund can be partial, so the amount is always shown;
                          the "Refunded" status alone would imply the whole order. */}
                      {Number(order.refunded_amount ?? 0) > 0 && (
                        <div className="mb-3 sm:mb-4 pb-3 sm:pb-4 border-b">
                          <div className="flex justify-between items-center">
                            <span className="font-semibold text-sm sm:text-base text-orange-700 dark:text-orange-400">
                              {t('myOrders.refunded', 'Refunded')}
                            </span>
                            <span className="text-base sm:text-lg font-bold text-orange-700 dark:text-orange-400">
                              {formatCurrency(Number(order.refunded_amount))}
                            </span>
                          </div>
                          {Number(order.refunded_amount) < Number(order.total ?? 0) - 0.005 && (
                            <p className="text-xs text-muted-foreground mt-1">
                              {t('myOrders.refundedPartial',
                                 'Partial refund of your {{total}} order.',
                                 { total: formatCurrency(order.total) })}
                            </p>
                          )}
                          {(order.refunds ?? []).length > 1 && (
                            <div className="mt-2 space-y-0.5">
                              {(order.refunds ?? []).map(r => (
                                <div key={r.id} className="flex justify-between text-xs text-muted-foreground">
                                  <span>{new Date(r.created_at).toLocaleDateString()}</span>
                                  <span>{formatCurrency(Number(r.amount))}</span>
                                </div>
                              ))}
                            </div>
                          )}
                          <p className="text-xs text-muted-foreground mt-1">
                            {t('myOrders.refundedNote',
                               'Refunds usually reach your account in 5–7 business days.')}
                          </p>
                        </div>
                      )}

                      {/* SHOW MORE section with smooth transition */}
                      <div
                        className={`overflow-hidden transition-all duration-300 ease-in-out ${
                          isExpanded
                            ? "max-h-[800px] opacity-100"
                            : "max-h-0 opacity-0"
                        }`}
                      >
                        {isExpanded && (
                          <>
                            {/* Items */}
                            <div className="space-y-3 sm:space-y-4 mb-4 sm:mb-6 mt-2">
                              {order.items.map((item) => (
                                <div
                                  key={item.id}
                                  className="flex items-center gap-3 sm:gap-4"
                                >
                                  <img
                                    src={item.image || product1}
                                    alt={item.product_name}
                                    className="w-12 h-12 sm:w-16 sm:h-16 rounded-md object-contain"
                                  />
                                  <div className="flex-1 min-w-0">
                                    <h4 className="font-medium text-sm sm:text-base truncate">
                                      {item.product_name}
                                    </h4>
                                    <p className="text-xs sm:text-sm text-muted-foreground">
                                      {t('myOrders.qtyPrice', { qty: item.quantity, price: item.price })}
                                    </p>
                                    <p className="text-xs sm:text-sm text-muted-foreground">
                                      {formatCurrency(item.total)}
                                    </p>
                                  </div>
                                </div>
                              ))}
                            </div>

                            {/* Summary — same breakup the customer saw at checkout,
                                rebuilt from the order's own stored GST slabs. */}
                            <div className="mb-4 pb-4 border-b">
                              <PriceBreakup
                                subtotal={Number(order.subtotal ?? 0)}
                                discount={Number(order.discount ?? 0)}
                                tax={Number(order.tax ?? 0)}
                                taxableValue={
                                  order.taxable_value != null ? Number(order.taxable_value) : undefined
                                }
                                taxBreakdown={order.tax_breakdown}
                                taxInclusive={order.tax_inclusive !== false}
                                shipping={Number(order.shipping_charge ?? 0)}
                                shippingTax={Number(order.shipping_tax ?? 0)}
                                total={Number(order.total ?? 0)}
                              />
                            </div>
                            {/* Address */}
                            <p className="text-sm text-muted-foreground mb-4">
                              {t('myOrders.shippingTo', { address: order.shipping_address })}
                            </p>

                            {/* Tracking number (shown once the admin dispatches) */}
                            {order.tracking_number || order.tracking_url ? (
                              <div className="mb-4 rounded-xl border border-primary/20 bg-primary/5 px-3 py-2.5">
                                {order.courier_name ? (
                                  <p className="text-xs text-muted-foreground">
                                    {t('myOrders.shippedWith', 'Shipped with {{courier}}', { courier: order.courier_name })}
                                  </p>
                                ) : null}
                                {order.tracking_number ? (
                                  <>
                                    <p className="text-xs font-semibold text-primary">
                                      {t('myOrders.trackingNumber', 'Tracking number')}
                                    </p>
                                    <p className="text-sm font-mono font-medium break-all">
                                      {order.tracking_number}
                                    </p>
                                  </>
                                ) : null}
                                {order.tracking_url && (order.tracking_url.startsWith('http://') || order.tracking_url.startsWith('https://')) ? (
                                  <a
                                    href={order.tracking_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-sm font-medium text-primary underline"
                                  >
                                    {t('myOrders.trackParcel', 'Track parcel')}
                                  </a>
                                ) : null}
                              </div>
                            ) : null}
                          </>
                        )}
                      </div>

                      {/* Actions */}
                      <div className="flex flex-wrap gap-2 mt-2">
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-xs sm:text-sm h-8 sm:h-9 px-2 sm:px-3"
                          onClick={() => handleReorder(order)}
                          disabled={order.status.toLowerCase() === "cancelled"}
                        >
                          <Repeat className="h-3 w-3 sm:h-4 sm:w-4 mr-1 sm:mr-2" />
                          {t('myOrders.reorder')}
                        </Button>

                        {/* Chat Support Button */}
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-xs sm:text-sm h-8 sm:h-9 px-2 sm:px-3"
                          onClick={() => handleChatSupport(order)}
                        >
                          <MessageCircle className="h-3 w-3 sm:h-4 sm:w-4 mr-1 sm:mr-2" />
                          {t('myOrders.support')}
                        </Button>

                        {/* Only once a tax invoice has actually been issued —
                            at payment confirmation, or at dispatch for COD.
                            Before that there is no document to download. */}
                        {order.invoice && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="text-xs sm:text-sm h-8 sm:h-9 px-2 sm:px-3"
                            onClick={() => handleDownloadBill(order)}
                          >
                            <Download className="h-3 w-3 sm:h-4 sm:w-4 mr-1 sm:mr-2" />
                            {t('myOrders.bill')}
                          </Button>
                        )}

                        {/* Retry payment for an unpaid ONLINE order (reuses the
                            same order — the cart is already gone). */}
                        {canRetryPayment(order) && (
                          <Button
                            size="sm"
                            className="text-xs sm:text-sm h-8 sm:h-9 px-2 sm:px-3"
                            onClick={() => handleRetryPayment(order)}
                            disabled={retryingId === order.id}
                          >
                            {retryingId === order.id
                              ? t('myOrders.processing', 'Processing…')
                              : t('myOrders.retryPayment', 'Complete payment')}
                          </Button>
                        )}

                        {/* Cancel for pending/in_transit OR Review for delivered */}
                        {cancellable ? (
                          <Dialog
                            open={
                              cancelDialog.open &&
                              cancelDialog.orderId === order.id
                            }
                            onOpenChange={(open) => {
                              if (!open) {
                                setCancelDialog({ open: false, orderId: null });
                              } else {
                                openCancelDialog(order.id);
                              }
                            }}
                          >
                            <DialogTrigger asChild>
                              <Button
                                variant="destructive"
                                size="sm"
                                className="text-xs sm:text-sm h-8 sm:h-9 px-2 sm:px-3"
                                onClick={() => openCancelDialog(order.id)}
                              >
                                <XCircle className="h-3 w-3 sm:h-4 sm:w-4 mr-1 sm:mr-2" />
                                {t('myOrders.cancel')}
                              </Button>
                            </DialogTrigger>
                            <DialogContent>
                              <DialogHeader>
                                <DialogTitle>{t('myOrders.cancelTitle')}</DialogTitle>
                                <DialogDescription>
                                  <Trans i18nKey="myOrders.cancelConfirm" values={{ number: order.order_number }} components={{ b: <span className="font-semibold" /> }} />
                                </DialogDescription>
                              </DialogHeader>
                              <div className="mt-4 flex justify-end gap-2">
                                <Button
                                  variant="outline"
                                  onClick={() =>
                                    setCancelDialog({
                                      open: false,
                                      orderId: null,
                                    })
                                  }
                                  disabled={cancelLoading}
                                >
                                  {t('myOrders.keepOrder')}
                                </Button>
                                <Button
                                  variant="destructive"
                                  onClick={handleConfirmCancel}
                                  disabled={cancelLoading}
                                >
                                  {cancelLoading ? t('myOrders.cancelling') : t('myOrders.confirmCancel')}
                                </Button>
                              </div>
                            </DialogContent>
                          </Dialog>
                        ) : delivered ? (
                          <Dialog
                            open={
                              productReviewDialog.open &&
                              productReviewDialog.orderId === order.id
                            }
                            onOpenChange={(open) => {
                              if (!open) {
                                setProductReviewDialog({ open: false, itemType: 'product', itemId: null, itemName: "", orderId: null });
                                setCurrentRating(0);
                                setCurrentReview("");
                              }
                            }}
                          >
                            <DialogTrigger asChild>
                              <Button
                                variant="outline"
                                size="sm"
                                className="text-xs sm:text-sm h-8 sm:h-9 px-2 sm:px-3"
                                onClick={() => { void openOrderReviewDialog(order); }}
                              >
                                <Star className="h-3 w-3 sm:h-4 sm:w-4 mr-1 sm:mr-2" />
                                {t('myOrders.review')}
                              </Button>
                            </DialogTrigger>
                            <DialogContent>
                              <DialogHeader>
                                <DialogTitle>{t('myOrders.reviewTitle', { name: productReviewDialog.itemName })}</DialogTitle>
                                <DialogDescription>
                                  {t('myOrders.reviewDesc', { itemType: t(productReviewDialog.itemType === 'combo' ? 'myOrders.typeCombo' : 'myOrders.typeProduct') })}
                                </DialogDescription>
                              </DialogHeader>

                              {/* Product/Combo selector if multiple items */}
                              {order.items.length > 1 && (
                                <div className="mb-4">
                                  <p className="text-sm font-medium mb-2">{t('myOrders.selectItem')}</p>
                                  <div className="flex flex-wrap gap-2">
                                    {order.items.map((item) => {
                                      const itemId = item.item_type === 'combo' ? item.combo_id : item.product_id;
                                      // undefined = not looked up yet; treat as
                                      // reviewable so the buttons stay usable.
                                      const eligible = itemId
                                        ? itemEligibility[eligibilityKey(item.item_type, itemId)] !== false
                                        : false;
                                      return (
                                        <Button
                                          key={item.id}
                                          variant={productReviewDialog.itemId === itemId ? "default" : "outline"}
                                          size="sm"
                                          disabled={!eligible}
                                          title={eligible ? undefined : t('myOrders.alreadyReviewed')}
                                          onClick={() => {
                                            if (itemId) {
                                              setProductReviewDialog(prev => ({
                                                ...prev,
                                                itemType: item.item_type,
                                                itemId: itemId,
                                                itemName: item.product_name,
                                              }));
                                              setCurrentRating(0);
                                              setCurrentReview("");
                                            }
                                          }}
                                        >
                                          {item.product_name}
                                          {!eligible && ` — ${t('myOrders.alreadyReviewed')}`}
                                        </Button>
                                      );
                                    })}
                                  </div>
                                </div>
                              )}
                              
                              <div className="space-y-4">
                                {/* Star Rating */}
                                <div>
                                  <p className="text-sm font-medium mb-2">{t('myOrders.rating')}</p>
                                  <div className="flex gap-1">
                                    {[1, 2, 3, 4, 5].map((star) => (
                                      <button
                                        key={star}
                                        onClick={() => setCurrentRating(star)}
                                        className="focus:outline-none"
                                      >
                                        <Star
                                          className={`h-8 w-8 transition-colors ${
                                            star <= currentRating
                                              ? "fill-yellow-400 text-yellow-400"
                                              : "text-gray-300"
                                          }`}
                                        />
                                      </button>
                                    ))}
                                  </div>
                                </div>
                                
                                {/* Review Text */}
                                <div>
                                  <p className="text-sm font-medium mb-2">{t('myOrders.yourReview')}</p>
                                  <Textarea
                                    placeholder={t('myOrders.reviewPlaceholder')}
                                    value={currentReview}
                                    onChange={(e) => setCurrentReview(e.target.value.slice(0, MAX_REVIEW_COMMENT))}
                                    maxLength={MAX_REVIEW_COMMENT}
                                    rows={4}
                                  />
                                  <p className="text-xs text-muted-foreground text-right mt-1">
                                    {currentReview.length}/{MAX_REVIEW_COMMENT}
                                  </p>
                                </div>
                                
                                {/* Submit Button */}
                                <div className="flex justify-end gap-2">
                                  <Button
                                    variant="outline"
                                    disabled={reviewLoading}
                                    onClick={() => {
                                      setProductReviewDialog({ open: false, itemType: 'product', itemId: null, itemName: "", orderId: null });
                                      setCurrentRating(0);
                                      setCurrentReview("");
                                    }}
                                  >
                                    {t('myOrders.cancel')}
                                  </Button>
                                  <Button onClick={handleSubmitProductReview} disabled={reviewLoading}>
                                    {reviewLoading ? t('myOrders.submitting') : t('myOrders.submitReview')}
                                  </Button>
                                </div>
                              </div>
                            </DialogContent>
                          </Dialog>
                        ) : null}
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          ) : (
            <Card className="rounded-2xl border-border shadow-card">
              <CardContent className="flex flex-col items-center justify-center py-12 sm:py-20">
                <div className="grid h-20 w-20 sm:h-24 sm:w-24 place-items-center rounded-full bg-gradient-to-br from-primary/15 to-accent/15 mb-4 sm:mb-5">
                  <Package className="h-10 w-10 sm:h-12 sm:w-12 text-primary" />
                </div>
                <h3 className="text-lg sm:text-2xl font-bold mb-2">{t('myOrders.emptyTitle')}</h3>
                <p className="text-sm sm:text-base text-muted-foreground mb-5 text-center max-w-md">
                  {t('myOrders.emptyBody')}
                </p>
                <Link to="/products">
                  <Button size="lg" className="rounded-full text-sm sm:text-base active-press">
                    {t('myOrders.continueShopping')}
                  </Button>
                </Link>
              </CardContent>
            </Card>
          )}
        </div>
      </section>

      <Footer />
    </div>
  );
};

export default MyOrders;

