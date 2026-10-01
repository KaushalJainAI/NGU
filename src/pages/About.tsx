import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Footer from "@/components/Footer";
import Reveal from "@/components/Reveal";
import { Button } from "@/components/ui/button";
import {
  Award,
  Users,
  Heart,
  Leaf,
  ArrowRight,
  ChevronDown,
} from "lucide-react";
import spicesImage from "@/assets/spices-hero.jpg";

type ValueItem = { title: string; description: string };
type FactItem = { value: string; label: string };

const About = () => {
  const { t } = useTranslation();

  // Icons stay in code; all copy comes from i18n (about.*).
  const valueIcons = [
    <Award className="h-6 w-6 sm:h-7 sm:w-7" />,
    <Users className="h-6 w-6 sm:h-7 sm:w-7" />,
    <Heart className="h-6 w-6 sm:h-7 sm:w-7" />,
    <Leaf className="h-6 w-6 sm:h-7 sm:w-7" />,
  ];
  const values = t("about.values", { returnObjects: true }) as ValueItem[];
  // AP12: static verifiable facts (licence, place, payment) — the animated
  // 50+/1.1M+/100%/30+ counters asserted things no data backs up.
  const facts = t("about.facts", { returnObjects: true }) as FactItem[];

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      {/* ===== Cinematic intro ===== */}
      <section className="relative flex min-h-[86vh] items-center justify-center overflow-hidden">
        {/* drifting warm backdrop */}
        <div
          className="absolute inset-0 animate-gradient-pan"
          style={{
            background:
              "linear-gradient(135deg, hsl(35 45% 94%) 0%, hsl(35 25% 97%) 40%, hsl(40 60% 92%) 100%)",
          }}
          aria-hidden
        />
        <div className="absolute inset-0" style={{ background: "var(--backdrop-spice)" }} aria-hidden />
        {/* decorative slow-spinning ring */}
        <div
          className="absolute left-1/2 top-1/2 h-[120vw] w-[120vw] -translate-x-1/2 -translate-y-1/2 rounded-full border border-primary/10 animate-spin-slow"
          aria-hidden
        />
        <div className="relative z-10 mx-auto max-w-3xl px-4 text-center">
          <Reveal>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-card/70 px-4 py-1.5 text-xs sm:text-sm font-bold uppercase tracking-wider text-primary backdrop-blur-sm">
              {t("about.badge")}
            </span>
          </Reveal>
          <Reveal delay={120}>
            <h1 className="mt-5 text-4xl sm:text-6xl md:text-7xl font-extrabold leading-[1.05] tracking-tight text-foreground">
              {t("about.heroPre")}
              <span className="bg-gradient-to-r from-primary via-primary to-accent bg-clip-text text-transparent">
                {t("about.heroHighlight")}
              </span>
              {/* heroPost is empty in every locale; guard against i18next
                  returning the key name itself when the value is "". */}
              {(() => {
                const post = t("about.heroPost", { defaultValue: "" });
                return post === "about.heroPost" ? "" : post;
              })()}
            </h1>
          </Reveal>
          <Reveal delay={240}>
            <p className="mx-auto mt-5 max-w-xl text-sm sm:text-lg text-muted-foreground">
              {t("about.heroSubtitle")}
            </p>
          </Reveal>
          <Reveal delay={360}>
            <div className="mt-7 flex items-center justify-center gap-3">
              <Button asChild size="lg" className="rounded-full active-press">
                <Link to="/products">
                  {t("about.heroCta")} <ArrowRight className="ml-1.5 h-4 w-4" />
                </Link>
              </Button>
            </div>
          </Reveal>
        </div>

        {/* scroll cue */}
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 text-primary/70">
          <ChevronDown className="h-6 w-6 animate-bounce" aria-hidden />
        </div>
      </section>

      {/* ===== The beginning ===== */}
      <section className="py-12 sm:py-24">
        <div className="container mx-auto px-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 sm:gap-14 items-center">
            <Reveal variant="left">
              <div className="relative">
                <div className="absolute inset-0 -rotate-6 rounded-3xl bg-gradient-to-br from-primary/25 to-accent/25" />
                <img
                  src={spicesImage}
                  alt="Traditional Indian spices"
                  className="relative w-full rounded-3xl shadow-2xl"
                />
                <div className="absolute -bottom-5 -right-2 sm:-right-5 rounded-2xl bg-card px-4 py-3 shadow-card border border-border">
                  <p className="text-2xl sm:text-3xl font-extrabold text-primary leading-none">
                    {facts[0]?.value ?? "FSSAI"}
                  </p>
                  <p className="text-[11px] sm:text-xs text-muted-foreground">{facts[0]?.label ?? ""}</p>
                </div>
              </div>
            </Reveal>
            <Reveal variant="right">
              <span className="text-xs sm:text-sm font-bold uppercase tracking-wider text-primary">
                {t("about.beginEyebrow")}
              </span>
              <h2 className="mt-1 text-2xl sm:text-4xl font-bold text-foreground">
                {t("about.beginTitle")}
              </h2>
              <div className="mt-4 space-y-4 text-sm sm:text-base text-muted-foreground">
                <p>{t("about.beginP1")}</p>
                <p>{t("about.beginP2")}</p>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* AP12: the journey timeline (1995/2005/2015) and the farm-to-kitchen
          process claims were removed — founding dates and process specifics no
          data backs up. They return when the owner supplies the real story. */}
      {/* ===== Values ===== */}
      <section className="py-12 sm:py-24 bg-muted/30">
        <div className="container mx-auto px-4">
          <Reveal className="text-center mb-10 sm:mb-16">
            <span className="text-xs sm:text-sm font-bold uppercase tracking-wider text-primary">
              {t("about.valuesEyebrow")}
            </span>
            <h2 className="mt-1 text-2xl sm:text-4xl font-bold text-foreground">{t("about.valuesTitle")}</h2>
          </Reveal>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-6">
            {values.map((value, i) => (
              <Reveal key={i} variant="scale" delay={i * 100}>
                <div className="group h-full text-center p-4 sm:p-6 bg-card rounded-2xl border border-border shadow-card active-press">
                  <div className="mx-auto mb-3 sm:mb-4 grid h-12 w-12 sm:h-16 sm:w-16 place-items-center rounded-full bg-gradient-to-br from-primary to-accent text-white shadow-[var(--shadow-elegant)] transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-3">
                    {valueIcons[i]}
                  </div>
                  <h3 className="font-semibold text-foreground mb-1 sm:mb-2 text-sm sm:text-lg">
                    {value.title}
                  </h3>
                  <p className="text-xs sm:text-sm text-muted-foreground">{value.description}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ===== Facts (static, verifiable — replaces the animated counters) ===== */}
      <section className="py-12 sm:py-20">
        <div className="container mx-auto px-4">
          <Reveal variant="scale">
            <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-primary via-primary to-accent p-6 sm:p-14 shadow-[var(--shadow-lift)]">
              <div className="absolute inset-0 opacity-20" style={{ background: "var(--backdrop-spice)" }} aria-hidden />
              <div className="relative grid grid-cols-1 md:grid-cols-3 gap-6 sm:gap-8 text-center">
                {facts.map((fact, i) => (
                  <div key={i} className="text-white">
                    <div className="text-3xl sm:text-5xl md:text-6xl font-extrabold leading-none">
                      {fact.value}
                    </div>
                    <div className="mt-2 text-white/85 text-xs sm:text-base">{fact.label}</div>
                  </div>
                ))}
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ===== Closing CTA ===== */}
      <section className="pb-12 sm:pb-20">
        <div className="container mx-auto px-4">
          <Reveal>
            <div className="flex flex-col sm:flex-row items-center justify-between gap-4 rounded-3xl border-2 border-dashed border-primary/40 bg-primary/5 p-6 sm:p-10 text-center sm:text-left">
              <div>
                <h3 className="text-xl sm:text-3xl font-bold text-foreground">
                  {t("about.ctaTitle")}
                </h3>
                <p className="mt-1 text-sm sm:text-base text-muted-foreground">
                  {t("about.ctaSubtitle")}
                </p>
              </div>
              <Button asChild size="lg" className="rounded-full active-press shrink-0">
                <Link to="/products">
                  {t("about.ctaButton")} <ArrowRight className="ml-1.5 h-4 w-4" />
                </Link>
              </Button>
            </div>
          </Reveal>
        </div>
      </section>

      <Footer />
    </div>
  );
};

export default About;
