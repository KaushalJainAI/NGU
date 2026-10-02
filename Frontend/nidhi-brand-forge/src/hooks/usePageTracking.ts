import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { track } from "@/lib/api/analytics";

/**
 * Fire a page_view on every route change. Auth-aware: a per-user event for
 * logged-in visitors, a coarse anonymous counter beacon otherwise. Mount once
 * inside the router.
 */
export const usePageTracking = (): void => {
  const location = useLocation();
  useEffect(() => {
    track({ event_type: "page_view" }, { metric: "page_view" });
  }, [location.pathname]);
};
