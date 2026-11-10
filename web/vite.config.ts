import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy the demo API to the FastAPI server. Build: emit into the Python package,
// which serves the console from the same origin (no CORS, no browser credentials).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/demo": "http://localhost:8000", "/health": "http://localhost:8000" },
  },
  build: { outDir: "../app/static", emptyOutDir: true, sourcemap: false },
});
