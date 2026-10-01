import Footer from "@/components/Footer";
import { useTranslation, Trans } from "react-i18next";
import {
  ShieldCheck,
  Database,
  Scale,
  CheckCircle2,
  Share2,
  Cookie,
  Lock,
  UserCheck,
  AlertCircle,
  Mail,
} from "lucide-react";

const LAST_UPDATED = "9 July 2026";

const PrivacyPolicy = () => {
  const { t } = useTranslation();

  const bold = <strong className="text-foreground" />;

  /**
   * Each section renders as its own bordered card with an icon, so the policy
   * reads as a clear, scannable structure rather than a wall of prose.
   */
  const SECTIONS = [
    {
      icon: Database,
      title: t('pages.privacy.s1.title'),
      body: (
        <ul className="space-y-2">
          {(["item1", "item2", "item3"] as const).map((k) => (
            <li key={k} className="flex items-start gap-2">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
              <span>
                <Trans i18nKey={`pages.privacy.s1.${k}`} components={{ b: bold }} />
              </span>
            </li>
          ))}
        </ul>
      ),
    },
    { icon: Scale, title: t('pages.privacy.s2.title'), body: <p>{t('pages.privacy.s2.body')}</p> },
    { icon: CheckCircle2, title: t('pages.privacy.s3.title'), body: <p>{t('pages.privacy.s3.body')}</p> },
    { icon: Share2, title: t('pages.privacy.s4.title'), body: <p>{t('pages.privacy.s4.body')}</p> },
    { icon: Cookie, title: t('pages.privacy.s5.title'), body: <p>{t('pages.privacy.s5.body')}</p> },
    { icon: Lock, title: t('pages.privacy.s6.title'), body: <p>{t('pages.privacy.s6.body')}</p> },
    { icon: UserCheck, title: t('pages.privacy.s7.title'), body: <p>{t('pages.privacy.s7.body')}</p> },
    {
      icon: AlertCircle,
      title: t('pages.privacy.s8.title'),
      body: (
        <p>
          <Trans
            i18nKey="pages.privacy.s8.body"
            components={{
              name: <span className="notranslate font-medium text-foreground" />,
              phone: <span className="notranslate" />,
              br: <br />,
            }}
          />
        </p>
      ),
    },
    {
      icon: Mail,
      title: t('pages.privacy.s9.title'),
      body: (
        <p>
          <Trans
            i18nKey="pages.privacy.s9.body"
            components={{
              brand: <span className="notranslate" />,
              email: <span className="notranslate" />,
              phone: <span className="notranslate" />,
              contact: <a href="/contact" className="text-primary font-medium hover:underline" />,
            }}
          />
        </p>
      ),
    },
  ];

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-border">
        <div className="absolute inset-0" style={{ background: "var(--backdrop-spice)" }} aria-hidden />
        <div className="relative container mx-auto px-4 max-w-4xl py-12 sm:py-16">
          <div className="flex items-center gap-3 sm:gap-4">
            <div className="grid h-12 w-12 sm:h-16 sm:w-16 place-items-center rounded-2xl bg-primary text-white shadow-[var(--shadow-elegant)]">
              <ShieldCheck className="h-6 w-6 sm:h-8 sm:w-8" />
            </div>
            <div>
              <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-foreground">
                {t('pages.privacy.title')}
              </h1>
              <p className="text-sm text-muted-foreground mt-1">
                {t('pages.privacy.lastUpdated', { date: LAST_UPDATED })}
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="py-8 sm:py-12">
        <div className="container mx-auto px-4 max-w-4xl space-y-5">
          {/* Intro */}
          <div className="rounded-2xl border border-border bg-card p-5 sm:p-6 shadow-sm">
            <p className="text-muted-foreground leading-relaxed">
              <Trans
                i18nKey="pages.privacy.intro"
                components={{ brand: <span className="notranslate font-semibold text-foreground" /> }}
              />
            </p>
          </div>

          {/* Sections */}
          {SECTIONS.map(({ icon: Icon, title, body }) => (
            <div
              key={title}
              className="rounded-2xl border border-border bg-card p-5 sm:p-6 shadow-sm transition-shadow hover:shadow-md"
            >
              <div className="mb-3 flex items-center gap-3">
                <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="h-5 w-5" />
                </div>
                <h2 className="text-lg sm:text-xl font-bold text-foreground">
                  {title}
                </h2>
              </div>
              <div className="text-muted-foreground leading-relaxed pl-0 sm:pl-12">
                {body}
              </div>
            </div>
          ))}
        </div>
      </section>

      <Footer />
    </div>
  );
};

export default PrivacyPolicy;
