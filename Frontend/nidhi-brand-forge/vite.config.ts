import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import checker from "vite-plugin-checker";
import path from "path";

// https://vitejs.dev/config/
export default defineConfig(({ command }) => ({
  server: {
    host: "::",
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
      },
      '/media': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
      },
      '/s3-media': {
        target: 'https://ngu-static-files0.s3.ap-south-1.amazonaws.com',
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/s3-media/, ''),
        headers: {
          'Access-Control-Allow-Origin': '*',
        }
      }
    }
  },
  plugins: [
    react(),
    // Live TypeScript error overlay during `npm run dev` only. Never runs during
    // `vite build`, so production builds stay fast and are never blocked by types.
    ...(command === "serve"
      ? [checker({ typescript: true })]
      : []),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
}));

