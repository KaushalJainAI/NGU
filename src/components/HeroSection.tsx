import { Button } from "@/components/ui/button";
import { ArrowRight, CheckCircle2, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import heroImage from "@/assets/spices-hero.jpg";
import { useTranslation } from "react-i18next";

const HeroSection = () => {
  const { t } = useTranslation();
  return (
    <section className="relative overflow-hidden border-b border-border/70 bg-[radial-gradient(ellipse_at_top_left,hsl(var(--accent)/0.16),transparent_34%),linear-gradient(115deg,hsl(var(--background))_0%,hsl(var(--muted)/0.55)_54%,hsl(var(--secondary)/0.08)_100%)]">
      <svg
        className="pointer-events-none absolute left-0 top-0 h-full w-full text-primary/10"
        viewBox="0 0 1200 640"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path d="M-90 438 C 164 250 322 555 562 337 S 1002 154 1296 306" fill="none" stroke="currentColor" strokeWidth="18" strokeLinecap="round" />
        <path d="M819 50 C 858 104 913 112 971 79 C 949 140 967 191 1019 229 C 954 224 908 254 884 313 C 868 249 830 213 764 204 C 823 171 842 118 819 50Z" fill="currentColor" opacity=".42" />
        <path d="M158 94 C 191 133 237 139 285 114 C 268 164 284 208 328 239 C 273 238 234 263 214 313 C 199 260 166 231 111 225 C 160 196 177 153 158 94Z" fill="currentColor" opacity=".28" />
      </svg>

      <div className="container relative mx-auto px-3 sm:px-4 py-8 sm:py-16 lg:py-24">
        <div className="grid grid-cols-1 lg:grid-cols-[0.94fr_1.06fr] gap-7 sm:gap-12 items-center">
          <div className="relative z-10 space-y-4 sm:space-y-6 animate-fade-in-up">
            <div className="inline-flex items-center gap-2 px-3 py-1.5 sm:px-4 sm:py-2 bg-card/85 border border-primary/15 rounded-full text-primary font-semibold text-xs sm:text-sm shadow-sm transition-all duration-300 hover:bg-primary/10">
              <Sparkles className="h-3.5 w-3.5" />
              {t('hero.badge')}
            </div>

            <h1 className="text-3xl sm:text-5xl lg:text-6xl font-extrabold text-foreground leading-tight tracking-normal">
              {t('hero.headlineStart')}<span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">{t('hero.headlineHighlight')}</span>{t('hero.headlineEnd')}
            </h1>

            <p className="text-sm sm:text-lg text-muted-foreground max-w-xl leading-relaxed">
              {t('hero.description')}
            </p>

            <div className="flex flex-col min-[420px]:flex-row gap-3">
              <Button size="lg" className="group rounded-full shadow-lg shadow-primary/30 transition-all duration-300 hover:shadow-xl hover:brightness-110 active:scale-95" asChild>
                <Link to="/products" className="flex items-center">
                  {t('common.shopNow')}
                  <ArrowRight className="ml-2 h-5 w-5 group-hover:translate-x-1 transition-transform duration-200" />
                </Link>
              </Button>
              <Button size="lg" variant="outline" className="rounded-full border-2 border-primary text-primary transition-all duration-300 hover:bg-primary/5 active:scale-95" asChild>
                <Link to="/about">{t('hero.learnMore')}</Link>
              </Button>
            </div>

            {/* AP12: every figure here is verifiable (licence, place, payment
                mode) — the old 50+/100%/1.1M+ counters asserted things no data
                backs up. */}
            <div className="grid grid-cols-3 gap-2 sm:gap-4 pt-2 sm:pt-5">
              <div className="rounded-lg border border-border/80 bg-card/80 p-3 shadow-sm">
                <div className="text-xl sm:text-3xl font-bold text-primary">FSSAI</div>
                <div className="text-xs sm:text-sm text-muted-foreground">{t('hero.statsLicensed')}</div>
              </div>
              <div className="rounded-lg border border-border/80 bg-card/80 p-3 shadow-sm">
                <div className="text-xl sm:text-3xl font-bold text-primary">Barnagar</div>
                <div className="text-xs sm:text-sm text-muted-foreground">{t('hero.statsMadeIn')}</div>
              </div>
              <div className="rounded-lg border border-border/80 bg-card/80 p-3 shadow-sm">
                <div className="text-xl sm:text-3xl font-bold text-primary">COD</div>
                <div className="text-xs sm:text-sm text-muted-foreground">{t('hero.statsCod')}</div>
              </div>
            </div>
          </div>

          <div className="relative animate-slide-in-right hidden lg:block">
            <div className="absolute -inset-2 sm:-inset-4 rounded-[2rem] border border-primary/20 bg-accent/10 rotate-3"></div>
            <div className="absolute -bottom-4 left-4 z-10 hidden sm:flex items-center gap-2 rounded-full border border-border bg-card/95 px-4 py-2 text-sm font-semibold text-foreground shadow-lg">
              <CheckCircle2 className="h-4 w-4 text-secondary" />
              {t('hero.handPackedFresh')}
            </div>
            <img 
              src={heroImage} 
              alt="Premium Indian Spices"
              className="relative aspect-[4/3] w-full rounded-2xl object-cover shadow-2xl transition-transform duration-500 hover:scale-[1.015] sm:rounded-[1.75rem] lg:aspect-[5/4]"
            />
          </div>
        </div>
      </div>
    </section>
  );
};

export default HeroSection;
