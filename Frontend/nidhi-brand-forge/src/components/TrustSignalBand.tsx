import { Award, Leaf, RotateCcw, ShieldCheck, Truck } from "lucide-react";
import { useTranslation } from "react-i18next";

interface TrustSignalBandProps {
  variant?: "soft" | "solid";
}

const TrustSignalBand = ({ variant = "soft" }: TrustSignalBandProps) => {
  const { t } = useTranslation();
  const solid = variant === "solid";

  const items = [
    { icon: Leaf, title: t('trustBand.pureBlends'), text: t('trustBand.noFillers') },
    { icon: ShieldCheck, title: t('trustBand.qualityChecked'), text: t('trustBand.batchTested') },
    { icon: Truck, title: t('trustBand.fastDelivery'), text: t('trustBand.packedFresh') },
    { icon: RotateCcw, title: t('trustBand.easySupport'), text: t('trustBand.simpleHelp') },
  ];

  return (
    <div
      className={`rounded-lg border px-3 py-3 sm:px-4 ${
        solid
          ? "border-primary/20 bg-primary text-primary-foreground"
          : "border-border/80 bg-card"
      }`}
    >
      <div className="grid grid-cols-2 gap-y-4 sm:grid-cols-4 sm:gap-y-0">
        {items.map((item, i) => {
          const Icon = item.icon;
          return (
            <div
              key={item.title}
              className={`flex items-center gap-2.5 px-1 sm:px-3 ${
                i > 0
                  ? solid
                    ? "sm:border-l sm:border-white/15"
                    : "sm:border-l sm:border-border"
                  : ""
              }`}
            >
              <Icon className={`h-5 w-5 shrink-0 ${solid ? "text-primary-foreground" : "text-primary"}`} />
              <span className="min-w-0">
                <span className="block text-xs font-semibold leading-tight sm:text-sm">{item.title}</span>
                <span className={`block text-[11px] leading-tight ${solid ? "text-primary-foreground/75" : "text-muted-foreground"}`}>{item.text}</span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default TrustSignalBand;
