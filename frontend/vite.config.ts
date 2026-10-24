import { defineConfig } from "vite";

// The backend owns /api, /ws and /stats; proxying them keeps the dev server on
// the same origin as the API, so no CORS and no absolute URLs in the client.
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  server: {
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/stats": { target: backend, changeOrigin: true },
      "/ws": { target: backend, changeOrigin: true, ws: true },
    },
  },
  build: { outDir: "dist" },
});
