import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api -> FastAPI agent on :8000 (contract §5).
// SSE (/api/stream, contract §4) streams through http-proxy unbuffered.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: false,
        // keep the /api prefix — FastAPI routes are mounted under /api
      },
    },
  },
  preview: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
