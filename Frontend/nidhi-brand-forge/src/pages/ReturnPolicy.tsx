import Footer from "@/components/Footer";
import { useTranslation } from "react-i18next";

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

const ReturnPolicy = () => {
  const { t } = useTranslation();
  const arr = (key: string) => t(key, { returnObjects: true }) as string[];

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      <section className="py-16">
        <div className="container mx-auto px-4 max-w-4xl">
          <div className="prose prose-lg max-w-none">
            <div className="space-y-8">
              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.returns.eligibility.title')}</h2>
                <p className="text-muted-foreground mb-4">
                  {t('pages.returns.eligibility.intro')}
                </p>
                <Bullets items={arr('pages.returns.eligibility.items')} />
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.returns.video.title')}</h2>
                <p className="text-muted-foreground mb-4">
                  {t('pages.returns.video.intro')}
                </p>
                <Bullets items={arr('pages.returns.video.items')} />
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.returns.nonReturnable.title')}</h2>
                <p className="text-muted-foreground mb-4">
                  {t('pages.returns.nonReturnable.intro')}
                </p>
                <Bullets items={arr('pages.returns.nonReturnable.items')} />
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.returns.process.title')}</h2>
                <ol className="space-y-3 text-muted-foreground list-decimal list-inside">
                  {arr('pages.returns.process.items').map((text, i) => (
                    <li key={i}>{text}</li>
                  ))}
                </ol>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.returns.refund.title')}</h2>
                <p className="text-muted-foreground mb-4">
                  {t('pages.returns.refund.intro')}
                </p>
                <Bullets items={arr('pages.returns.refund.items')} />
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.returns.replacement.title')}</h2>
                <p className="text-muted-foreground">
                  {t('pages.returns.replacement.body')}
                </p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.returns.cancellation.title')}</h2>
                <p className="text-muted-foreground">
                  {t('pages.returns.cancellation.body')}
                </p>
              </div>

              <div>
                <h2 className="text-2xl font-bold text-foreground mb-4">{t('pages.returns.contact.title')}</h2>
                <p className="text-muted-foreground">
                  {t('pages.returns.contact.body')}
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

export default ReturnPolicy;
