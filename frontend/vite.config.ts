// Vite build config for the KhetKavach frontend (React + TypeScript).
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: { port: 5173 },
  build: {
    // MapLibre (the 3D view, loaded only when picked) is about 1 MB on its own.
    chunkSizeWarningLimit: 1100,
    rollupOptions: {
      output: {
        // Split the big libraries so they cache separately.
        manualChunks: { leaflet: ["leaflet", "react-leaflet"], charts: ["recharts"] },
      },
    },
  },
});
