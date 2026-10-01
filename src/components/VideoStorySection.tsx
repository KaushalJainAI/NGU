import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ArrowRight, Play, ShieldCheck, Timer } from "lucide-react";
import { Button } from "@/components/ui/button";
import spicesVideo from "@/assets/kitchen-story.mp4";
import spicesPoster from "@/assets/kitchen-story-poster.jpg";

const VideoStorySection = () => {
  const { t } = useTranslation();
  return (
    <section className="border-y border-border bg-card py-8 sm:py-14">
      <div className="container mx-auto px-3 sm:px-4">
        <div className="grid grid-cols-1 lg:grid-cols-[1.08fr_0.92fr] gap-5 sm:gap-8 items-center">
          <div className="relative aspect-video overflow-hidden rounded-lg border border-border">
            {/* Muted + looping, so the clip carries no audio track. The poster
                fills the frame while the video buffers instead of a black box. */}
            <video
              className="w-full h-full object-cover"
              autoPlay
              muted
              loop
              playsInline
              preload="metadata"
              poster={spicesPoster}
              aria-label={t('ourStory.eyebrow')}
              src={spicesVideo}
            />
            <div className="absolute bottom-3 left-3 flex items-center gap-2 rounded-md bg-background/95 px-3 py-1.5 text-xs font-semibold text-foreground">
              <Play className="h-3.5 w-3.5 fill-primary text-primary" />
              {t('ourStory.eyebrow')}
            </div>
          </div>

          <div className="space-y-4 sm:space-y-5">
            <div className="text-xs tracking-[0.25em] uppercase text-primary font-semibold">{t('ourStory.label')}</div>
            <h2 className="text-xl sm:text-3xl md:text-4xl font-bold text-foreground">
              {t('ourStory.heading')}
            </h2>
            <p className="text-sm sm:text-lg text-muted-foreground leading-relaxed">
              {t('ourStory.body')}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-border bg-background p-3">
                <ShieldCheck className="mb-2 h-5 w-5 text-secondary" />
                <p className="text-sm font-bold text-foreground">{t('ourStory.feature1Title')}</p>
                <p className="text-xs text-muted-foreground">{t('ourStory.feature1Desc')}</p>
              </div>
              <div className="rounded-lg border border-border bg-background p-3">
                <Timer className="mb-2 h-5 w-5 text-primary" />
                <p className="text-sm font-bold text-foreground">{t('ourStory.feature2Title')}</p>
                <p className="text-xs text-muted-foreground">{t('ourStory.feature2Desc')}</p>
              </div>
            </div>
            <Button asChild size="lg" className="group rounded-full">
              <Link to="/products" className="flex items-center">
                {t('ourStory.cta')}
                <ArrowRight className="ml-2 h-5 w-5 group-hover:translate-x-1 transition-transform" />
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
};

export default VideoStorySection;
