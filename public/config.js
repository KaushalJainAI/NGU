// Runtime config placeholder for local dev (vite serves /public as-is).
// In production this file is overwritten at container start by
// docker-entrypoint.d/40-runtime-config.sh from the API_URL env var.
// An empty API_URL makes the app fall back to VITE_API_URL / the localhost default.
window.APP_CONFIG = {
  API_URL: "",
  GOOGLE_CLIENT_ID: ""
};
