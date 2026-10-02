import { useTranslation } from "react-i18next";

/**
 * Slim static strip of brand USPs shown above the navbar (AP12: the
 * auto-scrolling marquee is gone — motion without meaning). Pure
 * presentation — no state, no data.
 */
const UspRibbon = () => {
  const { t } = useTranslation();

  // Falls back to English copy when a translation key is missing.
  const items = [
    t("ribbon.freeShipping"),
    t("ribbon.pure"),
    t("ribbon.handPacked"),
    t("ribbon.trusted"),
  ];

  return (
    <div className="bg-primary text-primary-foreground text-[11px] sm:text-xs overflow-hidden">
      <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-0.5 px-4 py-1.5">
        {items.map((text, i) => (
          <span key={i} className="notranslate">
            {text}
          </span>
        ))}
      </div>
    </div>
  );
};

export default UspRibbon;
