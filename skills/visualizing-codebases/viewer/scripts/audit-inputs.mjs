// The map audit's inputs and their digest: every file under src/ (the audit bundles from there). vite.audit.config.ts
// writes the digest into dist/audit.mjs's first line; test/audit_run.test.ts recomputes it.
import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";

const ROOT = new URL("../", import.meta.url);

/** The inputs' paths, relative to the viewer folder, in digest order. */
export function auditInputs() {
  const walk = (dir) => readdirSync(new URL(dir, ROOT), { withFileTypes: true })
    .flatMap((d) => (d.isDirectory() ? walk(`${dir}${d.name}/`) : [`${dir}${d.name}`]));
  return walk("src/").sort();
}

/** sha256 over each input's path and bytes. */
export function auditDigest() {
  const h = createHash("sha256");
  for (const p of auditInputs()) h.update(`${p}\n`).update(readFileSync(new URL(p, ROOT))).update("\n");
  return h.digest("hex");
}
