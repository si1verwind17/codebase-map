// `node audit.mjs <code-map.json>`: audits the map's drawing (run.ts) and prints the report as one line of JSON on
// stdout, exit 0. An unreadable or invalid map is one line on stderr, exit 2.
import { readFileSync } from "node:fs";
import { auditMap } from "./run";

const path = process.argv[2];
let map;
try {
  if (!path) throw new Error("usage: node audit.mjs <code-map.json>");
  map = JSON.parse(readFileSync(path, "utf8"));
} catch (e) {
  process.stderr.write(`audit: cannot read the map: ${String(e instanceof Error ? e.message : e).split("\n")[0]}\n`);
  process.exit(2);
}
let report;
try {
  report = auditMap(map);
} catch (e) {
  process.stderr.write(`audit: ${String(e instanceof Error ? e.message : e).split("\n")[0]}\n`);
  process.exit(2);
}
process.stdout.write(`${JSON.stringify(report)}\n`);
