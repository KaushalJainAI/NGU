import Footer from "@/components/Footer";
import { useTranslation, Trans } from "react-i18next";

const ShippingPolicy = () => {
  const { t } = useTranslation();
  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      <section className="py-16">
        <div className="container mx-auto px-4 max-w-4xl">
          <div className="prose prose-lg max-w-none">
            <div className="space-y-8">
              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.shipping.areas.title')}</h2>
                <p className="text-muted-foreground">
                  {t('pages.shipping.areas.body')}
                </p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.shipping.timeline.title')}</h2>
                <ul className="space-y-2 text-muted-foreground">
                  {(["metro", "cities", "remote"] as const).map((k) => (
                    <li key={k} className="flex items-start">
                      <span className="text-primary mr-2">•</span>
                      <span><Trans i18nKey={`pages.shipping.timeline.${k}`} components={{ b: <strong /> }} /></span>
                    </li>
                  ))}
                </ul>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.shipping.charges.title')}</h2>
                <p className="text-muted-foreground mb-4">
                  {t('pages.shipping.charges.intro')}
                </p>
                <ul className="space-y-2 text-muted-foreground">
                  <li className="flex items-start">
                    <span className="text-primary mr-2">•</span>
                    <span><Trans i18nKey="pages.shipping.charges.free" components={{ b: <strong /> }} /></span>
                  </li>
                  <li className="flex items-start">
                    <span className="text-primary mr-2">•</span>
                    <span>{t('pages.shipping.charges.upto')}</span>
                  </li>
                </ul>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.shipping.tracking.title')}</h2>
                <p className="text-muted-foreground">
                  {t('pages.shipping.tracking.body')}
                </p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.shipping.processing.title')}</h2>
                <p className="text-muted-foreground">
                  {t('pages.shipping.processing.body')}
                </p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.shipping.attempts.title')}</h2>
                <p className="text-muted-foreground">
                  {t('pages.shipping.attempts.body')}
                </p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.shipping.address.title')}</h2>
                <p className="text-muted-foreground mb-4">
                  {t('pages.shipping.address.body1')}
                </p>
                <p className="text-muted-foreground">
                  <Trans
                    i18nKey="pages.shipping.address.body2"
                    components={{
                      a: (
                        <a
                          href="https://wa.me/919300005040"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary hover:underline notranslate"
                        />
                      ),
                      b: <strong />,
                    }}
                  />
                </p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.shipping.contact.title')}</h2>
                <p className="text-muted-foreground">
                  {t('pages.shipping.contact.body')}
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

export default ShippingPolicy;
