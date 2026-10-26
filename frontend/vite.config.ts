import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5181,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8006",
        changeOrigin: true,
        timeout: 0,
        proxyTimeout: 0,
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 5181,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8006",
        changeOrigin: true,
      },
    },
  },
});
