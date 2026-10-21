import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

export default defineConfig({
  plugins: [svelte(), viteSingleFile()],
  worker: { format: "iife" },   // the layout worker, inlined as a classic script (floor/spawn-plan-worker.ts)
  build: { outDir: "../skills/visualizing-codebases/viewer/dist", emptyOutDir: false, assetsInlineLimit: 100_000_000, chunkSizeWarningLimit: 4000 },
});
