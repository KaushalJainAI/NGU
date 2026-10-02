/**
 * Runtime configuration bridge.
 *
 * Vite inlines `import.meta.env.VITE_*` at BUILD time, so those values are frozen
 * into the bundle. To let one image be reconfigured per deployment WITHOUT a
 * rebuild, the container entrypoint (docker-entrypoint.d/40-runtime-config.sh)
 * writes `window.APP_CONFIG` from its env vars on every start (see public/config.js
 * for the local-dev stub). This helper prefers that runtime value and falls back
 * to the build-time Vite value, so `npm run dev` keeps working unchanged.
 *
 * APP_CONFIG keys are the VITE_ name without the prefix (VITE_API_URL -> API_URL),
 * matching the admin panel's window.APP_CONFIG convention.
 */
const runtime = (typeof window !== "undefined"
  ? (window as unknown as { APP_CONFIG?: Record<string, string | undefined> }).APP_CONFIG
  : undefined);

/** Runtime override wins; falls back to build-time Vite env. `undefined` when neither is set. */
export function readEnv(viteName: string): string | undefined {
  const key = viteName.replace(/^VITE_/, "");
  const r = runtime?.[key];
  if (r != null && r !== "") return r;
  const b = (import.meta.env as Record<string, string | undefined>)[viteName];
  return b != null && b !== "" ? b : undefined;
}
