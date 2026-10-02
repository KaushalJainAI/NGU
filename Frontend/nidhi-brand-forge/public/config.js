// Runtime config placeholder for local dev (vite serves /public as-is).
// In production this file is OVERWRITTEN at container start by
// docker-entrypoint.d/40-runtime-config.sh from the container's env vars, so
// these values can change without rebuilding the image.
// Empty values make the app fall back to the build-time VITE_* baked by Vite.
window.APP_CONFIG = {
  API_URL: "",
  GOOGLE_CLIENT_ID: "",
  SHIPPING_CHARGE_NET: "",
  SHIPPING_TAX_RATE: "",
  FREE_SHIPPING_THRESHOLD: "",
  DEFAULT_TAX_RATE: "",
  MAX_ONLINE_ORDER_TOTAL: "",
  MAX_ITEM_QUANTITY: "",
  MAX_CART_ITEMS: "",
  MAX_REVIEW_COMMENT: ""
};
