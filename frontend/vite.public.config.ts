import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { outDir: "../public_demo_site/dist", emptyOutDir: true,
    rollupOptions: { input: resolve(__dirname, "public-demo.html") } },
});
