import Footer from "@/components/Footer";
import { useTranslation, Trans } from "react-i18next";

const LAST_UPDATED = "9 July 2026";

const Bullets = ({ items }: { items: string[] }) => (
  <ul className="space-y-2 text-muted-foreground">
    {items.map((text, i) => (
      <li key={i} className="flex items-start">
        <span className="text-primary mr-2">•</span>
        <span>{text}</span>
      </li>
    ))}
  </ul>
);

const TermsAndConditions = () => {
  const { t } = useTranslation();
  const arr = (key: string) => t(key, { returnObjects: true }) as string[];
  const brand = <span className="notranslate font-medium text-foreground" />;

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      <section className="py-12 sm:py-16">
        <div className="container mx-auto px-4 max-w-4xl">
          <div className="mb-8">
            <h1 className="text-3xl sm:text-4xl font-extrabold text-foreground">
              {t('pages.terms.title')}
            </h1>
            <p className="text-sm text-muted-foreground mt-2">
              {t('pages.terms.lastUpdated', { date: LAST_UPDATED })}
            </p>
          </div>

          <div className="prose prose-lg max-w-none">
            <div className="space-y-8">
              <div>
                <p className="text-muted-foreground">
                  <Trans i18nKey="pages.terms.intro" components={{ brand }} />
                </p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.terms.s1.title')}</h2>
                <p className="text-muted-foreground">{t('pages.terms.s1.body')}</p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.terms.s2.title')}</h2>
                <Bullets items={arr('pages.terms.s2.items')} />
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.terms.s3.title')}</h2>
                <Bullets items={arr('pages.terms.s3.items')} />
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.terms.s4.title')}</h2>
                <Bullets items={arr('pages.terms.s4.items')} />
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.terms.s5.title')}</h2>
                <p className="text-muted-foreground">{t('pages.terms.s5.body')}</p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.terms.s6.title')}</h2>
                <p className="text-muted-foreground">
                  <Trans
                    i18nKey="pages.terms.s6.body"
                    components={{
                      shipping: <a href="/shipping-policy" className="text-primary hover:underline" />,
                      returns: <a href="/return-policy" className="text-primary hover:underline" />,
                    }}
                  />
                </p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.terms.s7.title')}</h2>
                <p className="text-muted-foreground">
                  <Trans i18nKey="pages.terms.s7.body" components={{ brand: <span className="notranslate" /> }} />
                </p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.terms.s8.title')}</h2>
                <p className="text-muted-foreground">{t('pages.terms.s8.body')}</p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.terms.s9.title')}</h2>
                <p className="text-muted-foreground">{t('pages.terms.s9.body')}</p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.terms.s10.title')}</h2>
                <p className="text-muted-foreground">{t('pages.terms.s10.body')}</p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.terms.s11.title')}</h2>
                <p className="text-muted-foreground">{t('pages.terms.s11.body')}</p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.terms.s12.title')}</h2>
                <p className="text-muted-foreground">
                  <Trans
                    i18nKey="pages.terms.s12.body"
                    components={{
                      phone: <span className="notranslate" />,
                      contact: <a href="/contact" className="text-primary hover:underline" />,
                    }}
                  />
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
};

export default TermsAndConditions;
