// The trunk hover card, pure: which tiles two or more lines share (a trunk's run, its splitter and merger
// plates), and the card's words for the lines on one. The scene draws the card (floor/trunk-hover.ts).
import { DRAW_ORDER, type Bundle } from "../model/model";
import type { RelationKind } from "../model/types";
import type { TileRoute } from "./router";

/** A kind's place in the order a line is drawn by: a row lists its kinds this way. */
const rank = (k: string) => { const i = DRAW_ORDER.indexOf(k as RelationKind); return i < 0 ? DRAW_ORDER.length : i; };
/** Short codes in reading order: S4 before S10, then X3. */
const byCode = (a: string, b: string) => a.localeCompare(b, "en", { numeric: true });

/** A line's relation kinds, in drawing order: a tap that reads and writes is both `db-write` and `db-read`. */
const kindsOf = (b: Bundle) => Object.keys(b.kinds).filter((k) => b.kinds[k as RelationKind]).sort((p, q) => rank(p) - rank(q));

export interface SharedTile { x: number; y: number; ris: number[] }

/** Every tile two or more lines hold on the surface (not crossed underground), keyed `x,y`, with the routes (indices)
 *  holding it. Drone routes and the routes `skip` names (those drawn as flights) take no part. */
export function sharedTiles(routes: Pick<TileRoute, "pieces" | "kind" | "key">[], skip: (r: Pick<TileRoute, "key">) => boolean): Map<string, SharedTile> {
  const at = new Map<string, SharedTile>();
  routes.forEach((r, i) => {
    if (r.kind === "drone" || skip(r)) return;
    for (const p of r.pieces) {
      if (p.under) continue;
      const k = `${p.x},${p.y}`;
      let t = at.get(k);
      if (!t) { t = { x: p.x, y: p.y, ris: [] }; at.set(k, t); }
      if (!t.ris.includes(i)) t.ris.push(i);
    }
  });
  for (const [k, t] of at) if (t.ris.length < 2) at.delete(k);
  return at;
}

/** The card for the lines on one shared tile: `N lines · <kinds with counts>` (how many of the lines carry each kind),
 *  then one row per branch, `→ <code> <name> · <kinds>` where the shared end sends (a split), `←` where it receives (a
 *  merge), `↔` both ways; with no end shared by every line, each row names both ends in the data's direction. Rows go by
 *  short code. Names are whole: never cut. */
export function trunkCard(bundles: Bundle[], end: (id: string) => { code: string; name: string }): string {
  const count = new Map<string, number>();
  for (const b of bundles) for (const k of kindsOf(b)) count.set(k, (count.get(k) ?? 0) + 1);
  const kinds = [...count].sort((p, q) => q[1] - p[1] || rank(p[0]) - rank(q[0])).map(([k, n]) => (n > 1 ? `${k} ×${n}` : k));
  const shared = [bundles[0].a, bundles[0].b].find((id) => bundles.every((b) => b.a === id || b.b === id));
  const named = (id: string) => { const e = end(id); return e.code ? `${e.code} ${e.name}` : e.name; };
  const rows = bundles.map((b) => {
    const ks = kindsOf(b).length ? ` · ${kindsOf(b).join(", ")}` : "";   // a line with no kinds ends at its name
    const [src, dst] = b.flow === "b→a" ? [b.b, b.a] : [b.a, b.b];
    if (shared) {
      const other = b.a === shared ? b.b : b.a;
      const arrow = b.flow === "both" ? "↔" : src === shared ? "→" : "←";
      return { code: end(other).code, text: `${arrow} ${named(other)}${ks}` };
    }
    return { code: end(src).code, text: `${named(src)} ${b.flow === "both" ? "↔" : "→"} ${named(dst)}${ks}` };
  });
  rows.sort((p, q) => byCode(p.code, q.code) || byCode(p.text, q.text));
  return [`${bundles.length} lines${kinds.length ? ` · ${kinds.join(", ")}` : ""}`, ...rows.map((r) => r.text)].join("\n");
}
