import Footer from "@/components/Footer";
import { useTranslation, Trans } from "react-i18next";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

const FAQ = () => {
  const { t } = useTranslation();
  const faqs = t('pages.faq.items', { returnObjects: true }) as { q: string; a: string }[];

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-24">
      <section className="py-12 sm:py-16">
        <div className="container mx-auto px-4 max-w-3xl">
          <div className="mb-8 text-center">
            <h1 className="text-3xl sm:text-4xl font-extrabold text-foreground">
              {t('pages.faq.title')}
            </h1>
            <p className="text-sm sm:text-base text-muted-foreground mt-2">
              {t('pages.faq.subtitle')}
            </p>
          </div>

          <Accordion type="single" collapsible className="w-full">
            {faqs.map((item, i) => (
              <AccordionItem key={i} value={`faq-${i}`}>
                <AccordionTrigger className="text-left text-sm sm:text-base font-semibold">
                  {item.q}
                </AccordionTrigger>
                <AccordionContent className="text-sm sm:text-base text-muted-foreground">
                  {item.a}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>

          <div className="mt-10 text-center text-sm text-muted-foreground">
            <Trans
              i18nKey="pages.faq.still"
              components={{
                a: <a href="/contact" className="text-primary hover:underline font-medium" />,
              }}
            />
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
};

export default FAQ;
