import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The React dev server runs on :5173 and proxies /api to the Python
// backend on :8000, so the frontend can call same-origin paths.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
