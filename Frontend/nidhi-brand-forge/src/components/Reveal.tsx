import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

type RevealVariant = "up" | "left" | "right" | "scale";

interface RevealProps {
  children: ReactNode;
  className?: string;
  /** Direction/style the element animates in from. */
  variant?: RevealVariant;
  /** Delay before the reveal transition starts (ms) — great for staggering. */
  delay?: number;
  /** Re-trigger every time it scrolls into view instead of only once. */
  repeat?: boolean;
}

const variantClass: Record<RevealVariant, string> = {
  up: "",
  left: "reveal-left",
  right: "reveal-right",
  scale: "reveal-scale",
};

/**
 * Scroll-reveal wrapper. Adds `.is-visible` (which drives the CSS transition in
 * index.css) once the element scrolls into the viewport. Uses a single
 * IntersectionObserver per instance and respects `prefers-reduced-motion` via
 * the CSS fallback.
 */
const Reveal = ({ children, className, variant = "up", delay = 0, repeat = false }: RevealProps) => {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          if (!repeat) observer.disconnect();
        } else if (repeat) {
          setVisible(false);
        }
      },
      { threshold: 0.15, rootMargin: "0px 0px -8% 0px" }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [repeat]);

  return (
    <div
      ref={ref}
      style={{ transitionDelay: `${delay}ms` }}
      className={cn("reveal", variantClass[variant], visible && "is-visible", className)}
    >
      {children}
    </div>
  );
};

export default Reveal;
