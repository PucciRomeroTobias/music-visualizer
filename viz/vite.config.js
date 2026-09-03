import { defineConfig } from "vite";

export default defineConfig({
  root: ".",
  base: "/discover/",
  publicDir: "public",
  resolve: {
    dedupe: ["three"],
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    open: true,
  },
});
