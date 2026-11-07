import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api (including the chat WebSocket) is proxied to the FastAPI backend.
export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 800 },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true, ws: true },
    },
  },
});
