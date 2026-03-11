import { defineConfig } from "vite";

export default defineConfig({
  root: ".",
  base: "/discover/",
  publicDir: "public",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    open: true,
  },
});
