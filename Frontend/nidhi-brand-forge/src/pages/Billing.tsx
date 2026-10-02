// Billing.tsx — checkout with Razorpay online payment.
//
// Flow (PAYMENT_INTEGRATION_PLAN.md §6):
//   1. Place the order (payment_method='ONLINE'). A full-coupon ZERO-TOTAL order
//      comes back already paid → straight to success, no gateway.
//   2. Otherwise ask the backend to create a Razorpay order, open Checkout.
//   3. On success → verify (L1) → poll status → success. If the customer closes
//      the modal, the order stays pending and can be retried from "My Orders".
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { toast } from "sonner";
import { authAPI, cartAPI, ordersAPI, geoAPI } from "@/lib/api.ts";
import { razorpayAPI } from "@/lib/api/payments";
import { openRazorpayCheckout } from "@/lib/razorpay";
import { useGeolocation } from "@/hooks/useGeolocation";
import { MapPin, Loader2, ShieldCheck } from "lucide-react";
import { track } from "@/lib/api/analytics";
import { FREE_SHIPPING_THRESHOLD, SHIPPING_CHARGE, DEFAULT_TAX_RATE, MAX_ONLINE_ORDER_TOTAL, shippingTaxFor } from "@/config/limits";
import { useTranslation } from "react-i18next";
import { PriceBreakup } from "@/components/PriceBreakup";

// Normalise the backend cart summary into the shape the UI renders. The backend
// is authoritative for tax/shipping/total (per-line GST). Prices are
// GST-INCLUSIVE: `tax` is the portion already contained in `subtotal`, shown for
// disclosure and never added into `total`. We only fall back to a browser
// estimate if the summary is somehow absent, and even then we default an unknown
// tax_rate to the backend default (5%) so the split we show matches the invoice.
const summaryFromBackend = (summary: any, items: any[]) => {
  if (summary && typeof summary.total === "number") {
    return {
      subtotal: summary.subtotal ?? 0,
      discount: summary.discount ?? 0,
      shipping: summary.shipping ?? 0,
      tax: summary.tax ?? 0,
      // MUST be carried through. It is the one GST that ADDS to the total (the
      // fee is quoted net), so dropping it leaves the rows summing ₹10.62 short
      // of the backend's `total` with nothing on screen to explain the gap.
      shipping_tax: summary.shipping_tax ?? 0,
      tax_breakdown: summary.tax_breakdown ?? [],
      taxable_value: summary.taxable_value ?? (summary.subtotal ?? 0) - (summary.tax ?? 0),
      total: summary.total,
    };
  }
  const subtotal = items.reduce((acc, item) => acc + item.price * item.quantity, 0);
  const shipping = subtotal >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_CHARGE;
  const tax = items.reduce((acc, item) => {
    const rate = item.tax_rate ?? DEFAULT_TAX_RATE;
    return acc + (item.price * item.quantity * rate) / (100 + rate);
  }, 0);
  // Delivery is billed NET + 18% (SAC 9968), so its GST is a real addend here —
  // unlike the goods `tax` above, which is already inside `subtotal`. Omitting it
  // would quote the customer less than they are actually charged.
  const shippingTax = shippingTaxFor(shipping);
  // No per-slab detail in the fallback — the backend is the only place that
  // knows each line's real rate. PriceBreakup degrades to a single GST row.
  return {
    subtotal, discount: 0, shipping, tax,
    shipping_tax: shippingTax,
    tax_breakdown: [], taxable_value: subtotal - tax,
    total: subtotal + shipping + shippingTax,
  };
};

const Billing = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();

  // Funnel signal: the visitor reached checkout.
  useEffect(() => {
    track({ event_type: "checkout_started" }, { metric: "checkout_started" });
  }, []);

  const [isLoading, setIsLoading] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [cartItems, setCartItems] = useState<any[]>([]);
  const [cartSummary, setCartSummary] = useState<any>(null);

  const [formData, setFormData] = useState({
    fullName: "",
    email: "",
    phone: "",
    address: "",
    city: "",
    state: "",
    zipCode: "",
  });

  // Coupon state
  const [couponCode, setCouponCode] = useState("");
  const [appliedCoupon, setAppliedCoupon] = useState<any>(null);

  // Location detection: offer to auto-fill the address when the user has no
  // saved default address on their profile.
  const geo = useGeolocation();
  const [detectingLocation, setDetectingLocation] = useState(false);
  const [hasDefaultAddress, setHasDefaultAddress] = useState(true);

  useEffect(() => {
    const loadData = async () => {
      try {
        // 1. Load user profile
        const profile = await authAPI.getProfile();
        setHasDefaultAddress(Boolean(profile.address && profile.city));
        setFormData((prev) => ({
          ...prev,
          fullName: profile.first_name && profile.last_name
            ? `${profile.first_name} ${profile.last_name}`
            : profile.username || prev.fullName,
          email: profile.email || prev.email,
          phone: profile.phone || prev.phone,
          address: profile.address || prev.address,
          city: profile.city || prev.city,
          state: profile.state || prev.state,
          zipCode: profile.pincode || prev.zipCode,
        }));

        // 2. Load cart
        const cartResp = await cartAPI.get();
        const items = cartResp.items || [];

        if (items.length === 0) {
          toast.error(t('billing.cartEmpty'));
          navigate("/cart");
          return;
        }

        setCartItems(items);

        // 3. Use the backend's authoritative summary (per-line GST, shipping,
        //    total). Never recompute tax in the browser: line-level tax_rate can
        //    be missing here, and a `?? 0` fallback would misstate the GST split
        //    on the breakdown (the backend defaults to 5%).
        setCartSummary(summaryFromBackend(cartResp.summary, items));
      } catch (err: any) {
        console.error('Failed to load billing info:', err);
        const errorMsg = err.data?.error || err.message || t('billing.loadError');
        toast.error(errorMsg);
      }
    };

    loadData();
  }, []);

  const handleApplyCoupon = async () => {
    if (!couponCode.trim()) {
      toast.error(t('billing.enterCoupon'));
      return;
    }
    if (!cartSummary) {
      toast.error(t('billing.paymentNotInitialized'));
      return;
    }

    try {
      const response = await ordersAPI.validateCoupon(couponCode.trim());

      if (!response.valid) {
        toast.error(response.message || response.error || t('billing.invalidCoupon'));
        return;
      }

      // Routed through summaryFromBackend rather than hand-built, so the coupon
      // path can't quietly lose the fields the breakdown needs — `shipping_tax`
      // above all, without which the rows stop summing to `total`.
      setCartSummary(summaryFromBackend({
        subtotal: response.subtotal,
        discount: response.discount_amount,
        shipping: response.shipping_charge,
        shipping_tax: response.shipping_tax,
        tax: response.tax,
        total: response.total_amount,
      }, cartItems));

      setAppliedCoupon({
        code: response.coupon_code,
        discount_type: response.discount_type,
        is_zero_total: response.total_amount === 0,
      });

      toast.success(t('billing.couponApplied', { amount: (response.savings ?? 0).toFixed(2) }));
    } catch (error: any) {
      console.error('Coupon application error:', error);
      const errorMsg = error.data?.error || error.data?.message || t('billing.couponFailed');
      toast.error(errorMsg);
    }
  };

  const handleRemoveCoupon = async () => {
    if (!cartSummary) return;
    setCouponCode("");
    setAppliedCoupon(null);

    // Re-fetch the backend's authoritative (no-coupon) summary rather than
    // recomputing tax in the browser, which could under-quote it.
    try {
      const cartResp = await cartAPI.get();
      setCartSummary(summaryFromBackend(cartResp.summary, cartResp.items || cartItems));
    } catch {
      // Network hiccup: fall back to a safe local estimate (5% default rate).
      setCartSummary(summaryFromBackend(undefined, cartItems));
    }
    toast.success(t('billing.couponRemoved'));
  };

  const handleDetectLocation = async () => {
    setDetectingLocation(true);
    try {
      const coords = await geo.request();
      if (!coords) {
        toast.error(geo.error || t('billing.locationDenied'));
        return;
      }

      const addr = await geoAPI.reverseGeocode(coords.lat, coords.lng);
      setFormData((prev) => ({
        ...prev,
        address: addr.address_line || prev.address,
        city: addr.city || prev.city,
        state: addr.state || prev.state,
        zipCode: addr.pincode || prev.zipCode,
      }));

      geoAPI
        .update({ lat: coords.lat, lng: coords.lng, city: addr.city, state: addr.state, pincode: addr.pincode })
        .catch(() => { /* recommendation signal is non-critical */ });

      toast.success(t('billing.addressFilled'));
    } catch (err) {
      toast.error(t('billing.addressFailed'));
    } finally {
      setDetectingLocation(false);
    }
  };

  const validateForm = () => {
    const newErrors: Record<string, string> = {};
    if (!formData.fullName.trim()) newErrors.fullName = t('billing.errNameRequired');
    if (!formData.email.trim()) {
      newErrors.email = t('billing.errEmailRequired');
    } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
      newErrors.email = t('billing.errEmailInvalid');
    }
    if (!formData.phone.trim()) {
      newErrors.phone = t('billing.errPhoneRequired');
    } else if (!/^\d{10}$/.test(formData.phone.replace(/\D/g, ''))) {
      newErrors.phone = t('billing.errPhoneInvalid');
    }
    if (!formData.address.trim()) newErrors.address = t('billing.errAddressRequired');
    if (!formData.city.trim()) newErrors.city = t('billing.errCityRequired');
    if (!formData.state.trim()) newErrors.state = t('billing.errStateRequired');
    if (!formData.zipCode.trim()) newErrors.zipCode = t('billing.errZipRequired');

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Poll the honest payment status until it settles (or a bounded number of
  // tries), so a "paid but /verify/ lagging" order still lands on success.
  const waitForPaid = async (orderId: number, tries = 6): Promise<boolean> => {
    for (let i = 0; i < tries; i++) {
      try {
        const s = await razorpayAPI.getStatus(orderId);
        if (s.payment_status === "paid") return true;
        if (s.payment_status === "failed") return false;
      } catch { /* transient — keep polling */ }
      await new Promise((r) => setTimeout(r, 1500));
    }
    return false;
  };

  // Land the customer on a REAL order confirmation — with the order number and a
  // link to download the invoice — not the old "thanks for your interest" page.
  const finishSuccess = (orderId: number, orderNumber: string) => {
    toast.success(t('billing.orderPlaced'));
    navigate("/order-success", { state: { orderId, orderNumber } });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateForm()) {
      toast.error(t('billing.fillAllFields'));
      return;
    }
    // Online gateway (incl. UPI) caps a transaction at ₹1,00,000. Guard here too
    // in case the button was somehow submitted; backend rejects it regardless.
    if (cartSummary && cartSummary.total > MAX_ONLINE_ORDER_TOTAL) {
      toast.error(t('billing.onlineCap', {
        amount: MAX_ONLINE_ORDER_TOTAL.toLocaleString('en-IN'),
        defaultValue: `Online payment is limited to ₹${MAX_ONLINE_ORDER_TOTAL.toLocaleString('en-IN')} per order. Please reduce your order to continue.`,
      }));
      return;
    }

    setIsLoading(true);
    try {
      const fullAddress = `${formData.address}, ${formData.city}, ${formData.state} - ${formData.zipCode}`;

      // 1. Place the order. For ONLINE the backend keeps the cart until the
      //    payment is captured (a re-checkout supersedes this pending order), so
      //    an abandoned payment leaves the cart intact to retry.
      const placed = await ordersAPI.create({
        shipping_address: fullAddress,
        // State and PIN also go up UNFLATTENED. `fullAddress` is a courier
        // label; the GST place of supply needs the state as its own value to
        // decide CGST+SGST vs IGST, and the form has always collected it.
        shipping_state: formData.state,
        shipping_pincode: formData.zipCode,
        phone_number: formData.phone,
        payment_method: 'ONLINE',
        coupon_code: appliedCoupon?.code || undefined,
      });

      const orderId = placed.order_id;

      // 2. Zero-total (full-coupon) order → already paid, no gateway needed.
      if (Number(placed.total_amount) <= 0) {
        finishSuccess(orderId, placed.order_number);
        return;
      }

      // 3. Create the Razorpay order and open Checkout.
      const rzp = await razorpayAPI.createOrder(orderId);

      await openRazorpayCheckout({
        key: rzp.razorpay_key_id,
        amount: rzp.amount,
        currency: rzp.currency,
        orderId: rzp.razorpay_order_id,
        name: "Nidhi Masala",
        description: `Order ${placed.order_number}`,
        prefill: { name: formData.fullName, email: formData.email, contact: formData.phone },
        onSuccess: async (r) => {
          try {
            const res = await razorpayAPI.verify({
              razorpay_order_id: r.razorpay_order_id,
              razorpay_payment_id: r.razorpay_payment_id,
              razorpay_signature: r.razorpay_signature,
            });
            // Order was cancelled before the capture landed — don't show a false
            // success; the charge is refunded automatically.
            if (res && res.success === false) {
              toast.message(res.message
                || "This order was cancelled. If you were charged, it will be refunded automatically.");
              navigate("/my-orders");
              setIsLoading(false);
              return;
            }
            finishSuccess(orderId, placed.order_number);
          } catch {
            // Signature/verify hiccup: the webhook (L2) will reconcile. Show a
            // non-alarming "confirming" message and let the poll settle it.
            const paid = await waitForPaid(orderId);
            if (paid) finishSuccess(orderId, placed.order_number);
            else {
              toast.message(t('billing.confirmingPayment'));
              navigate("/my-orders");
            }
            setIsLoading(false);
          }
        },
        onDismiss: () => {
          // Modal closed / payment abandoned: the order stays pending. The cart
          // was NOT emptied (ONLINE keeps it until capture), so the customer can
          // retry from My Orders OR just check out again — a fresh checkout
          // supersedes this pending order. Nothing to restore here.
          toast.message(t('billing.paymentIncomplete'));
          navigate("/my-orders");
          setIsLoading(false);
        },
      });
      // Do NOT clear isLoading here — the modal is open; the callbacks own it.
    } catch (err: any) {
      console.error('Checkout error:', err);
      const errorMsg = err.data?.error || err.data?.message || err.message || t('billing.orderFailed');
      toast.error(errorMsg);
      setIsLoading(false);
    }
  };

  if (!cartSummary) {
    return (
      <div className="container py-8 max-w-6xl flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-900 mx-auto mb-4"></div>
          <p className="text-muted-foreground">{t('billing.loadingCheckout')}</p>
        </div>
      </div>
    );
  }

  const isZeroTotal = cartSummary.total <= 0;
  // Online gateway (UPI included) caps a single transaction at ₹1,00,000. Above
  // that we block online checkout up-front rather than failing at the gateway.
  const overOnlineCap = cartSummary.total > MAX_ONLINE_ORDER_TOTAL;

  return (
    <div className="container py-4 sm:py-8 px-3 sm:px-4 max-w-6xl pb-24 md:pb-8">
      <h1 className="text-2xl sm:text-4xl font-bold mb-4 sm:mb-8">{t('billing.checkout')}</h1>
      <form onSubmit={handleSubmit}>
        <div className="grid lg:grid-cols-3 gap-4 sm:gap-10">
          {/* SHIPPING */}
          <div className="lg:col-span-2 space-y-4 sm:space-y-8">
            <Card>
              <CardHeader className="p-3 sm:p-6">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle className="text-base sm:text-lg">{t('billing.shippingInfo')}</CardTitle>
                  {geo.supported && (
                    <Button
                      type="button"
                      variant={hasDefaultAddress ? "outline" : "default"}
                      size="sm"
                      onClick={handleDetectLocation}
                      disabled={detectingLocation}
                      className="h-8 text-xs sm:text-sm"
                    >
                      {detectingLocation ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <MapPin className="h-3.5 w-3.5" />
                      )}
                      <span className="ml-1.5">{t('billing.useLocation')}</span>
                    </Button>
                  )}
                </div>
                {!hasDefaultAddress && (
                  <p className="text-xs text-muted-foreground mt-1">
                    {t('billing.noSavedAddress')}
                  </p>
                )}
              </CardHeader>
              <CardContent className="p-3 sm:p-6 pt-0 sm:pt-0 space-y-3 sm:space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 sm:gap-x-6 gap-y-3 sm:gap-y-4">
                  {Object.entries({
                    fullName: t('billing.fullName'),
                    email: t('billing.email'),
                    phone: t('billing.phone'),
                    address: t('billing.address'),
                    city: t('billing.city'),
                    state: t('billing.state'),
                    zipCode: t('billing.zipCode')
                  }).map(([key, label]) => (
                    <div key={key} className={key === 'address' ? 'sm:col-span-2' : ''}>
                      <Label htmlFor={key} className="text-xs sm:text-sm font-medium">
                        {label} <span className="text-red-500">*</span>
                      </Label>
                      <Input
                        id={key}
                        value={(formData as any)[key]}
                        onChange={e =>
                          setFormData(prev => ({ ...prev, [key]: e.target.value }))
                        }
                        required
                        className={`mt-1 h-9 sm:h-10 text-sm ${errors[key] ? "border-red-500" : ""}`}
                      />
                      {errors[key] && (
                        <p className="text-xs text-red-500 mt-1">{errors[key]}</p>
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* SUMMARY + PAY */}
          <div>
            <Card>
              <CardHeader className="p-3 sm:p-6">
                <CardTitle className="text-base sm:text-lg">{t('billing.orderSummary')}</CardTitle>
              </CardHeader>
              <CardContent className="p-3 sm:p-6 pt-0 sm:pt-0">
                {/* Cart Items */}
                <div className="divide-y divide-muted space-y-2 sm:space-y-3 text-sm sm:text-base">
                  {cartItems.map((item: any) => (
                    <div className="py-2 sm:py-3 flex flex-col" key={`${item.item_type || 'product'}-${item.product_id || item.id}`}>
                      <div className="flex justify-between items-baseline">
                        <span className="font-medium text-sm sm:text-base truncate max-w-[150px] sm:max-w-none">{item.name}</span>
                        <span className="font-semibold text-sm sm:text-base">
                          ₹{(item.price * item.quantity).toFixed(2)}
                        </span>
                      </div>
                      <div className="flex justify-between text-xs text-muted-foreground mt-0.5 sm:mt-1">
                        <span>{t('billing.qty', { count: item.quantity })}</span>
                        <span>{t('billing.perUnit', { price: item.price.toFixed(2) })}</span>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Coupon UI */}
                <Separator className="my-3 sm:my-4" />
                <div className="space-y-2">
                  <Label htmlFor="coupon" className="text-xs sm:text-sm font-medium">
                    {t('billing.haveCoupon')}
                  </Label>
                  {!appliedCoupon ? (
                    <div className="flex gap-2">
                      <Input
                        id="coupon"
                        placeholder={t('billing.enterCode')}
                        className="flex-1 h-9 sm:h-10 text-sm"
                        value={couponCode}
                        onChange={e => setCouponCode(e.target.value.toUpperCase())}
                      />
                      <Button
                        type="button"
                        variant="outline"
                        className="h-9 sm:h-10 text-xs sm:text-sm px-2 sm:px-3"
                        onClick={handleApplyCoupon}
                        disabled={!couponCode.trim()}
                      >
                        {t('billing.apply')}
                      </Button>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between bg-green-50 p-2 sm:p-3 rounded-md border border-green-200">
                      <span className="text-xs sm:text-sm text-green-700 font-medium">
                        {t('billing.couponAppliedTag', { code: appliedCoupon.code })}
                      </span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 sm:h-8 text-xs text-red-600 hover:text-red-700 hover:bg-red-50"
                        onClick={handleRemoveCoupon}
                      >
                        {t('billing.remove')}
                      </Button>
                    </div>
                  )}
                </div>

                {/* Summary */}
                <Separator className="my-3 sm:my-4" />
                <PriceBreakup
                  subtotal={cartSummary.subtotal}
                  discount={cartSummary.discount}
                  tax={cartSummary.tax}
                  taxableValue={cartSummary.taxable_value}
                  taxBreakdown={cartSummary.tax_breakdown}
                  shipping={cartSummary.shipping}
                  shippingTax={cartSummary.shipping_tax}
                  total={cartSummary.total}
                />

                {/* Secure-pay note */}
                <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground mt-4 mb-2">
                  <ShieldCheck className="h-4 w-4 text-green-600" />
                  <span>{t('billing.securePay', 'Secure payment via Razorpay — UPI, cards, netbanking & wallets')}</span>
                </div>

                {overOnlineCap && (
                  <div className="rounded-md bg-destructive/10 text-destructive text-xs sm:text-sm p-3 mb-2 text-center">
                    {t('billing.onlineCap', {
                      amount: MAX_ONLINE_ORDER_TOTAL.toLocaleString('en-IN'),
                      defaultValue: `Online payment is limited to ₹${MAX_ONLINE_ORDER_TOTAL.toLocaleString('en-IN')} per order. Please reduce your order to continue.`,
                    })}
                  </div>
                )}

                <Button
                  type="submit"
                  className="w-full mt-2 h-10 sm:h-12 text-sm sm:text-base font-semibold"
                  disabled={isLoading || (overOnlineCap && !isZeroTotal)}
                >
                  {isLoading ? (
                    <span className="flex items-center gap-2">
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                      {t('billing.processing')}
                    </span>
                  ) : isZeroTotal ? (
                    t('billing.placeFreeOrder', 'Place order')
                  ) : (
                    t('billing.payAmount', { amount: cartSummary.total.toFixed(2), defaultValue: `Pay ₹${cartSummary.total.toFixed(2)}` })
                  )}
                </Button>
              </CardContent>
            </Card>
          </div>
        </div>
      </form>
    </div>
  );
};

export default Billing;
