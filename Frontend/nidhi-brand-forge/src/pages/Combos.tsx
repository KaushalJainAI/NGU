import { useState, useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import Footer from "@/components/Footer";
import ComboCard from "@/components/ComboCard";
import ComboStoryCard from "@/components/ComboStoryCard";
import { Button } from "@/components/ui/button";
import { Package, BadgePercent, Truck, ArrowRight } from "lucide-react";
import { combosAPI, type Combo } from "@/lib/api";
import { FREE_SHIPPING_THRESHOLD } from "@/config/limits";
import { useTranslation } from "react-i18next";

const Combos = () => {
  const { t } = useTranslation();
  const [combos, setCombos] = useState<Combo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const fetchCombos = async () => {
      setLoading(true);
      setError("");
      try {
        const data = await combosAPI.getAll();
        // Combos endpoint returns a plain array (pagination_class = None).
        setCombos(data || []);
      } catch (err: any) {
        console.error("Failed to fetch combos:", err);
        setError(err.message || t('combosPage.loadError'));
      } finally {
        setLoading(false);
      }
    };

    fetchCombos();
  }, []);

  const discountOf = (c: Combo) => {
    const price = Number(c.final_price ?? c.price);
    const mrp = c.discount_price ? Number(c.price) : Number(c.total_original_price);
    return mrp && mrp > price ? Math.round((1 - price / mrp) * 100) : 0;
  };

  // Headline savings across all bundles, for the "save up to X%" highlight.
  const maxDiscount = useMemo(
    () => combos.reduce((max, c) => Math.max(max, discountOf(c)), 0),
    [combos],
  );

  // Story spotlights: lead with featured bundles, otherwise the best-value ones.
  // These get the editorial treatment; the remainder fill the grid below.
  const { spotlight, rest } = useMemo(() => {
    const featured = combos.filter((c) => c.is_featured);
    const pool = featured.length
      ? featured
      : [...combos].sort((a, b) => discountOf(b) - discountOf(a));
    const picked = pool.slice(0, combos.length > 4 ? 2 : 1);
    const pickedIds = new Set(picked.map((c) => c.id));
    return { spotlight: picked, rest: combos.filter((c) => !pickedIds.has(c.id)) };
  }, [combos]);

  const benefits = [
    { icon: <Package className="h-4 w-4" />, label: t('combosPage.benefitCurated') },
    { icon: <BadgePercent className="h-4 w-4" />, label: t('combosPage.benefitValue') },
    { icon: <Truck className="h-4 w-4" />, label: t('combosPage.benefitShipping', { amount: FREE_SHIPPING_THRESHOLD }) },
  ];

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      {/* Clean, minimal intro */}
      <section className="border-b border-border/60 py-8 sm:py-12">
        <div className="container mx-auto px-3 sm:px-4">
          <div className="text-[10px] sm:text-xs tracking-[0.25em] uppercase text-primary font-semibold mb-1.5">
            {t('combosPage.eyebrow')}
          </div>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="text-2xl sm:text-4xl font-extrabold text-foreground leading-tight">
                {t('combosPage.title')}
              </h1>
              <p className="mt-1.5 text-sm sm:text-base text-muted-foreground max-w-xl">
                {t('combosPage.subtitle')}
              </p>
            </div>
            {!loading && maxDiscount > 0 && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-secondary/10 px-3 py-1.5 text-xs sm:text-sm font-bold text-secondary">
                <BadgePercent className="h-4 w-4" />
                {t('combosPage.saveUpTo', { percent: maxDiscount })}
              </span>
            )}
          </div>

          {/* Benefits strip */}
          <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2">
            {benefits.map((b, i) => (
              <span key={i} className="flex items-center gap-1.5 text-xs sm:text-sm text-muted-foreground">
                <span className="text-primary">{b.icon}</span>
                {b.label}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section className="py-6 sm:py-10">
        <div className="container mx-auto px-3 sm:px-4">
          {loading ? (
            // Skeleton grid keeps layout stable while combos load.
            <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 sm:gap-8 max-w-7xl mx-auto">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="overflow-hidden rounded-2xl border border-border/80 bg-card">
                  <div className="spice-backdrop aspect-square animate-pulse" />
                  <div className="space-y-2 p-3 sm:p-4">
                    <div className="h-4 w-3/4 rounded bg-muted animate-pulse" />
                    <div className="h-3 w-1/2 rounded bg-muted animate-pulse" />
                    <div className="h-9 w-full rounded-lg bg-muted animate-pulse" />
                  </div>
                </div>
              ))}
            </div>
          ) : error ? (
            <div className="text-center py-20 text-destructive">
              <p>{error}</p>
            </div>
          ) : combos.length === 0 ? (
            <div className="mx-auto max-w-md text-center py-16 sm:py-20">
              <div className="mx-auto mb-4 grid h-16 w-16 place-items-center rounded-full spice-backdrop text-primary">
                <Package className="h-8 w-8" />
              </div>
              <h2 className="text-lg font-bold text-foreground mb-1">{t('combosPage.emptyTitle')}</h2>
              <p className="text-sm text-muted-foreground mb-6">
                {t('combosPage.emptyBody')}
              </p>
              <Button asChild className="rounded-full font-bold active-press">
                <Link to="/products">
                  {t('combosPage.browseAll')}
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
            </div>
          ) : (
            <div className="max-w-7xl mx-auto space-y-10 sm:space-y-14">
              {/* Story spotlights — the narrative that sells each bundle */}
              {spotlight.length > 0 && (
                <div className="space-y-5 sm:space-y-7">
                  {spotlight.map((combo, i) => (
                    <ComboStoryCard key={combo.id} combo={combo} reverse={i % 2 === 1} />
                  ))}
                </div>
              )}

              {/* Everything else */}
              {rest.length > 0 && (
                <div>
                  {spotlight.length > 0 && (
                    <h2 className="mb-4 text-lg sm:text-xl font-bold text-foreground">
                      {t('combosPage.moreBundles')}
                    </h2>
                  )}
                  <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 sm:gap-8">
                    {rest.map((combo) => (
                      <ComboCard key={combo.id} combo={combo} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </section>
      <Footer />
    </div>
  );
};

export default Combos;
