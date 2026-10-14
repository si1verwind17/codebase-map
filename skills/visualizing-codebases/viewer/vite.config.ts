import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

export default defineConfig({
  plugins: [svelte(), viteSingleFile()],
  build: { outDir: "dist", emptyOutDir: false, assetsInlineLimit: 100_000_000, chunkSizeWarningLimit: 4000 },
});
