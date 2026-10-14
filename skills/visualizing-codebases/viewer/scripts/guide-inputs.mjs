// The field guide's inputs and their digest: the example maps and the demo map (Welcome's picture), the page template,
// the renderer and its viewer helpers, and the built viewer the pictures were rendered with. scripts/guide.mjs writes
// the digest into dist/field-guide.html; test/guide.test.ts recomputes it.
import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";

const ROOT = new URL("../", import.meta.url);

/** The inputs' paths, relative to the viewer folder, in digest order. */
export function guideInputs() {
  const maps = readdirSync(new URL("guide/maps/", ROOT)).filter((f) => f.endsWith(".code-map.json")).sort();
  return [...maps.map((f) => `guide/maps/${f}`), "../demo/parking-city/docs/viz-code/code-map.json", "guide/pages.html",
    "scripts/guide.mjs", "scripts/viewer-page.mjs", "dist/viewer.html"];
}

/** sha256 over each input's path and bytes. */
export function guideDigest() {
  const h = createHash("sha256");
  for (const p of guideInputs()) h.update(`${p}\n`).update(readFileSync(new URL(p, ROOT))).update("\n");
  return h.digest("hex");
}
