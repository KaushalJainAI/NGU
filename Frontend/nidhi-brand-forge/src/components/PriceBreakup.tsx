import { useTranslation } from "react-i18next";
import { Separator } from "@/components/ui/separator";
import type { TaxSlab } from "@/lib/api/cart";

/**
 * The customer-facing bill breakdown, shared by the cart, the checkout page and
 * the "My Orders" card so all three can never quote different numbers.
 *
 * Prices are GST-INCLUSIVE. That makes the arithmetic on screen non-obvious, so
 * the layout is deliberate:
 *
 *   Item total          ₹500.00     ← what the goods cost, GST included
 *     Taxable value     ₹480.95     ┐ indented: these EXPLAIN the line above,
 *     GST 5%             ₹19.05     ┘ they are not additional charges
 *   Delivery             ₹59.00     ← a real add-on
 *   GST on delivery 18%  ₹10.62     ← ALSO a real add-on, see below
 *   ─────────────────────────────
 *   Total to pay        ₹569.62
 *
 * Anything that adds to the total is flush-left; anything that merely breaks
 * down a figure above it is indented and muted. Getting this wrong is how a
 * customer concludes they were charged tax twice.
 *
 * ⚠ The two GST lines use OPPOSITE conventions and must be laid out
 * differently. Product prices are MRP — GST is already inside them, so the
 * goods GST is indented as an explainer. The delivery fee is quoted NET and
 * taxed at 18% on top (SAC 9968), so its GST genuinely increases the total and
 * has to sit flush-left with the other charges. Indenting it would tell the
 * customer it was already included and leave the total looking ₹10.62 wrong.
 */

export interface PriceBreakupProps {
  subtotal: number;
  total: number;
  shipping?: number;
  /**
   * GST on the delivery fee (18%), charged ON TOP of `shipping` — unlike goods
   * GST, which is already inside `subtotal`. Renders as its own charge line.
   */
  shippingTax?: number;
  discount?: number;
  tax?: number;
  taxableValue?: number | null;
  taxBreakdown?: TaxSlab[];
  /** Legacy orders had GST ADDED on top; then it must render as an addend. */
  taxInclusive?: boolean;
  /** Free-delivery threshold, for the "add ₹X more" nudge. Omit to hide it. */
  freeShippingThreshold?: number;
  className?: string;
}

const inr = (n: number) => `₹${n.toFixed(2)}`;

export const PriceBreakup = ({
  subtotal,
  total,
  shipping = 0,
  shippingTax = 0,
  discount = 0,
  tax = 0,
  taxableValue,
  taxBreakdown,
  taxInclusive = true,
  freeShippingThreshold,
  className = "",
}: PriceBreakupProps) => {
  const { t } = useTranslation();

  // Only worth breaking GST out per slab when there's tax to explain. A cart of
  // nothing but papad (0%) shows no GST rows rather than a misleading "GST ₹0".
  const slabs = (taxBreakdown ?? []).filter(s => s.tax_amount > 0);
  const showTaxDetail = taxInclusive && tax > 0;

  const shortfall =
    freeShippingThreshold !== undefined && shipping > 0
      ? freeShippingThreshold - subtotal
      : 0;

  return (
    <div className={`space-y-1.5 text-sm ${className}`}>
      <div className="flex justify-between">
        <span className="text-muted-foreground">{t("cart.subtotal")}</span>
        <span className="font-semibold">{inr(subtotal)}</span>
      </div>

      {discount > 0 && (
        <div className="flex justify-between text-green-600">
          <span>{t("cart.discount", "Discount")}</span>
          <span className="font-semibold">-{inr(discount)}</span>
        </div>
      )}

      {/* Indented explainers — components of the subtotal, not extra charges. */}
      {showTaxDetail && (
        <div className="space-y-1 pl-3 border-l-2 border-muted">
          {taxableValue != null && (
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>{t("cart.taxableValue", "Taxable value")}</span>
              <span>{inr(taxableValue)}</span>
            </div>
          )}
          {slabs.length > 0 ? (
            slabs.map(slab => (
              <div
                key={slab.rate ?? "unknown"}
                className="flex justify-between text-xs text-muted-foreground"
              >
                <span>
                  {slab.rate == null
                    ? t("cart.gst", "GST")
                    : t("cart.gstAtRate", "GST {{rate}}%", { rate: slab.rate })}
                </span>
                <span>{inr(slab.tax_amount)}</span>
              </div>
            ))
          ) : (
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>{t("cart.gst", "GST")}</span>
              <span>{inr(tax)}</span>
            </div>
          )}
        </div>
      )}

      {/* Legacy tax-exclusive orders: GST really was an addend. */}
      {!taxInclusive && tax > 0 && (
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("cart.tax")}</span>
          <span className="font-semibold">{inr(tax)}</span>
        </div>
      )}

      <div className="flex justify-between">
        <span className="text-muted-foreground">{t("cart.shipping")}</span>
        <span className="font-semibold">
          {shipping === 0 ? t("cart.free") : inr(shipping)}
        </span>
      </div>

      {/* Flush-left, NOT indented: the delivery fee is quoted net, so this tax
          really does add to what the customer pays. */}
      {shippingTax > 0 && (
        <div className="flex justify-between">
          <span className="text-muted-foreground">
            {t("cart.shippingGst", "GST on delivery (18%)")}
          </span>
          <span className="font-semibold">{inr(shippingTax)}</span>
        </div>
      )}

      {shortfall > 0 && (
        <p className="text-xs text-muted-foreground">
          {t("cart.freeShippingNudge", "Add ₹{{amount}} more for free delivery", {
            amount: shortfall.toFixed(2),
          })}
        </p>
      )}

      <Separator className="my-2" />

      <div className="flex justify-between text-base font-bold">
        <span>{t("cart.total")}</span>
        <span className="text-primary">{inr(total)}</span>
      </div>

      {showTaxDetail && (
        <p className="text-xs text-muted-foreground text-right">
          {t("cart.taxIncluded", { amount: inr(tax) })}
        </p>
      )}
    </div>
  );
};

export default PriceBreakup;
