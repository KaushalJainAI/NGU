import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import ProductCarousel, { type CarouselProductItem } from "@/components/ProductCarousel";

interface DealsStripProps {
  title: string;
  subtitle?: string;
  items: CarouselProductItem[];
}

/** Milliseconds remaining until local midnight — the "deal resets daily" clock. */
const msUntilEndOfDay = () => {
  const now = new Date();
  const end = new Date(now);
  end.setHours(23, 59, 59, 999);
  return end.getTime() - now.getTime();
};

const fmt = (n: number) => String(n).padStart(2, "0");

/**
 * "Deals of the Day" row: a plain heading with a live countdown beside it,
 * then a horizontally-scrolling carousel of the supplied items.
 * Renders nothing when there are no items, so it's safe to drop on any page.
 */
const DealsStrip = ({ title, subtitle, items }: DealsStripProps) => {
  const { t } = useTranslation();
  const [remaining, setRemaining] = useState(msUntilEndOfDay());

  useEffect(() => {
    const id = setInterval(() => setRemaining(msUntilEndOfDay()), 1000);
    return () => clearInterval(id);
  }, []);

  if (!items?.length) return null;

  const totalSeconds = Math.max(0, Math.floor(remaining / 1000));
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;

  // The timer runs to midnight tonight — say so, rather than showing a bare
  // clock with no date to anchor it.
  const endOfDay = new Date();
  endOfDay.setHours(23, 59, 59, 999);
  const deadlineLabel = endOfDay.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });

  return (
    <section className="py-8 sm:py-10">
      <div className="container mx-auto px-2 sm:px-4">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-4">
          <div className="min-w-0">
            <h2 className="text-xl sm:text-3xl md:text-4xl font-bold text-foreground mb-1">{title}</h2>
            {subtitle && <p className="text-xs sm:text-base text-muted-foreground">{subtitle}</p>}
          </div>
          <div className="text-right notranslate">
            <div className="text-sm text-muted-foreground">
              {t('flashSale.endsIn')}{" "}
              <span className="font-semibold tabular-nums text-foreground">
                {fmt(h)}:{fmt(m)}:{fmt(s)}
              </span>
            </div>
            {/* A bare ticking clock reads as fake urgency; name the deadline. */}
            <div className="text-[11px] text-muted-foreground sm:text-xs">
              {t('flashSale.endsOn', { date: deadlineLabel })}
            </div>
          </div>
        </div>
        <ProductCarousel items={items} />
      </div>
    </section>
  );
};

export default DealsStrip;
