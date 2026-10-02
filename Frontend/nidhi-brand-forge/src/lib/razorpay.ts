// Razorpay Checkout loader + typed open helper.
//
// Loads the hosted checkout.js on demand (once, memoised) and opens the modal.
// The modal runs entirely in the customer's browser against Razorpay — our
// server is never in the money path.

const CHECKOUT_SRC = "https://checkout.razorpay.com/v1/checkout.js";

let loadPromise: Promise<boolean> | null = null;

export interface RazorpaySuccess {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

export interface OpenCheckoutOptions {
  key: string;
  amount: number; // paise
  currency: string;
  orderId: string; // razorpay_order_id
  name?: string;
  description?: string;
  prefill?: { name?: string; email?: string; contact?: string };
  onSuccess: (r: RazorpaySuccess) => void;
  onDismiss?: () => void;
}

export function loadRazorpay(): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  if ((window as any).Razorpay) return Promise.resolve(true);
  if (loadPromise) return loadPromise;

  loadPromise = new Promise<boolean>((resolve) => {
    const script = document.createElement("script");
    script.src = CHECKOUT_SRC;
    script.async = true;
    script.onload = () => resolve(true);
    script.onerror = () => {
      loadPromise = null; // allow a retry on next attempt
      resolve(false);
    };
    document.body.appendChild(script);
  });
  return loadPromise;
}

export async function openRazorpayCheckout(opts: OpenCheckoutOptions): Promise<void> {
  const ok = await loadRazorpay();
  if (!ok) throw new Error("Could not load the payment gateway. Check your connection.");

  const rzp = new (window as any).Razorpay({
    key: opts.key,
    amount: opts.amount,
    currency: opts.currency,
    order_id: opts.orderId,
    name: opts.name || "Nidhi Masala",
    description: opts.description || "Order payment",
    prefill: opts.prefill || {},
    theme: { color: "#b45309" },
    handler: (response: RazorpaySuccess) => opts.onSuccess(response),
    modal: {
      ondismiss: () => opts.onDismiss?.(),
    },
  });
  // Razorpay surfaces a failed attempt through this event.
  rzp.on("payment.failed", () => opts.onDismiss?.());
  rzp.open();
}
