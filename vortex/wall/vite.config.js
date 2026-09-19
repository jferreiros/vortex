import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served from the FastAPI/NiceGUI app under vortex/observability/live.py.
// base must match the static mount point, or the built bundle 404s in prod.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  // Production is mounted at /wall-assets/ by FastAPI. Dev must stay at /
  // or opening http://localhost:5173/ 404s and the dashboard looks dead.
  base: command === "build" ? "/wall-assets/" : "/",
  build: {
    outDir: "dist",
  },
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    proxy: {
      "/api/wall": "http://127.0.0.1:8080",
      "/wall/avatar2d": "http://127.0.0.1:8080",
      "/wall/vorty-face": "http://127.0.0.1:8080",
      "/wall/vorty-face-no-headphones": "http://127.0.0.1:8080",
      "/wall/accessories": "http://127.0.0.1:8080",
      "/wall/personalities": "http://127.0.0.1:8080",
    },
  },
}));
