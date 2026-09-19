import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served from the FastAPI/NiceGUI app under vortex/observability/live.py.
// base must match the static mount point, or the built bundle 404s in prod.
export default defineConfig({
  plugins: [react()],
  base: "/wall-assets/",
  build: {
    outDir: "dist",
  },
  server: {
    proxy: {
      "/api/wall": "http://127.0.0.1:8080",
    },
  },
});
