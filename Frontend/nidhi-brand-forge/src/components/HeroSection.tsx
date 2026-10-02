import { Button } from "@/components/ui/button";
import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import heroImage from "@/assets/spices-hero.jpg";
import { useTranslation } from "react-i18next";

const HeroSection = () => {
  const { t } = useTranslation();
  const stats = [
    { value: "50+", label: t('hero.statsProducts') },
    { value: "100%", label: t('hero.statsPure') },
    { value: "1.1M+", label: t('hero.statsCustomers') },
  ];
  return (
    <section className="border-b border-border bg-background">
      <div className="container mx-auto px-3 sm:px-4 py-10 sm:py-16 lg:py-20">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-14 items-center">
          <div className="space-y-5 sm:space-y-6">
            <p className="text-xs sm:text-sm font-semibold text-primary">
              {t('hero.badge')}
            </p>

            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold text-foreground leading-[1.1] tracking-tight">
              {t('hero.headlineStart')}<span className="text-primary">{t('hero.headlineHighlight')}</span>{t('hero.headlineEnd')}
            </h1>

            <p className="text-sm sm:text-lg text-muted-foreground max-w-xl leading-relaxed">
              {t('hero.description')}
            </p>

            <div className="flex flex-col min-[420px]:flex-row gap-3">
              <Button size="lg" className="group rounded-full" asChild>
                <Link to="/products" className="flex items-center">
                  {t('common.shopNow')}
                  <ArrowRight className="ml-2 h-5 w-5 group-hover:translate-x-1 transition-transform duration-200" />
                </Link>
              </Button>
              <Button size="lg" variant="outline" className="rounded-full" asChild>
                <Link to="/about">{t('hero.learnMore')}</Link>
              </Button>
            </div>

            <div className="grid max-w-lg grid-cols-3 gap-4 border-t border-border pt-5 sm:pt-6">
              {stats.map((stat) => (
                <div key={stat.value}>
                  <div className="text-2xl sm:text-3xl font-bold text-foreground">{stat.value}</div>
                  <div className="text-xs sm:text-sm text-muted-foreground">{stat.label}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="relative hidden lg:block">
            <img
              src={heroImage}
              alt="Premium Indian Spices"
              className="aspect-[5/4] w-full rounded-2xl object-cover"
            />
            <div className="absolute bottom-4 left-4 rounded-md bg-background/95 px-3 py-1.5 text-sm font-medium text-foreground">
              {t('hero.since')} · {t('hero.handPackedFresh')}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

export default HeroSection;
