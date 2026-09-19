import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served from the FastAPI/NiceGUI app under vortex/observability/live.py.
// base must match the static mount point, or the built bundle 404s in prod.
export default defineConfig({
  plugins: [react()],
  base: "/wall-assets/",
  resolve: {
    alias: {
      // shadcn-style path alias (see components.json + jsconfig.json):
      // "@/lib/utils", "@/components/elevenlabs/..." inside the adopted
      // ElevenLabs UI sources.
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: "dist",
  },
  server: {
    proxy: {
      "/api/wall": "http://127.0.0.1:8080",
      "/wall/avatar2d": "http://127.0.0.1:8080",
      "/wall/vorty-face": "http://127.0.0.1:8080",
    },
  },
});
