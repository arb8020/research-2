import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

export default defineConfig({
  plugins: [preact()],
  server: {
    proxy: {
      // Proxy API calls to the Python mimir server
      "/api": {
        target: "http://127.0.0.1:4141",
        changeOrigin: true,
      },
      "/preview": {
        target: "http://127.0.0.1:4141",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "../dist",
    emptyOutDir: true,
  },
});
