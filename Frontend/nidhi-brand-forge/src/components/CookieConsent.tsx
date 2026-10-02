import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Cookie } from "lucide-react";

const STORAGE_KEY = "cookie_consent";

/**
 * Lightweight cookie / data-processing consent notice for DPDP Act, 2023
 * compliance. Shows once until the visitor makes a choice; the decision is
 * stored in localStorage under `cookie_consent` ("accepted" | "essential").
 * Non-essential analytics can gate on `localStorage.cookie_consent === "accepted"`.
 */
const CookieConsent = () => {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    try {
      if (!localStorage.getItem(STORAGE_KEY)) setVisible(true);
    } catch {
      /* private mode — show the notice, decision just won't persist */
      setVisible(true);
    }
  }, []);

  const decide = (choice: "accepted" | "essential") => {
    try {
      localStorage.setItem(STORAGE_KEY, choice);
    } catch {
      /* ignore storage failures */
    }
    setVisible(false);
    window.dispatchEvent(new CustomEvent("cookie-consent", { detail: choice }));
  };

  if (!visible) return null;

  return (
    <div className="fixed inset-x-0 bottom-0 z-[60] p-3 sm:p-4 pb-20 md:pb-4">
      <div className="mx-auto max-w-3xl rounded-2xl border border-border bg-card/95 backdrop-blur shadow-[var(--shadow-elegant)] p-4 sm:p-5">
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4">
          <div className="flex items-start gap-3 flex-1">
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primary/10 text-primary">
              <Cookie className="h-5 w-5" />
            </div>
            <p className="text-xs sm:text-sm text-muted-foreground">
              We use cookies and similar technologies to keep you signed in,
              remember your cart, and run anonymous analytics to improve your
              experience. See our{" "}
              <Link to="/privacy-policy" className="text-primary hover:underline font-medium">
                Privacy Policy
              </Link>
              .
            </p>
          </div>
          <div className="flex gap-2 shrink-0">
            <Button
              variant="outline"
              size="sm"
              className="h-9 text-xs sm:text-sm"
              onClick={() => decide("essential")}
            >
              Essential only
            </Button>
            <Button
              size="sm"
              className="h-9 text-xs sm:text-sm"
              onClick={() => decide("accepted")}
            >
              Accept all
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CookieConsent;
