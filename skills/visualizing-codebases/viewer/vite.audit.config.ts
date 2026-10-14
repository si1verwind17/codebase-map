// The map audit's plain-Node build: src/audit/cli.ts bundled whole (no runtime dependency) into dist/audit.mjs, its
// first line the digest of src/ (scripts/audit-inputs.mjs) that test/audit_run.test.ts checks for freshness.
import { defineConfig } from "vite";
import { auditDigest } from "./scripts/audit-inputs.mjs";

export default defineConfig({
  build: {
    ssr: "src/audit/cli.ts",
    outDir: "dist",
    emptyOutDir: false,
    target: "node18",
    rollupOptions: { output: { entryFileNames: "audit.mjs", format: "es", banner: `// audit-inputs: ${auditDigest()}` } },
  },
  ssr: { noExternal: true },
});
