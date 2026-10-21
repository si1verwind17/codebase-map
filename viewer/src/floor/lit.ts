// What moves on a floor: one rule for every place the App lights lines (spec: motion; the owner, 2026-10-06).
import type { Model } from "../model/model";

/** What moves on floor `c` while nothing is selected: every line on the floor, on every floor, every rail's train
 *  (`rails`: the floor's train path keys, stand-in `rail:` keys among them), and every line of its extra layers
 *  (they move while their layer shows). The one place this default is decided. */
export function defaultLit(model: Model, c: string, rails: readonly string[] = []): string[] {
  const b = model.bundles(c), keys = [...new Set([...b.bundles, ...b.layered].map((x) => x.key))], have = new Set(keys);   // a line in two layers once
  return keys.concat(rails.filter((k) => !have.has(k)));
}

/** What moves for a selection: a node's own lines (`ofNode`), a selected line alone, or with nothing selected the
 *  floor's default. */
export function litFor(model: Model, c: string, t: { type: "node"; id: string } | { type: "bundle"; key: string } | null,
  ofNode: (id: string) => string[], rails: readonly string[] = []): string[] {
  if (t?.type === "node") return ofNode(t.id);
  if (t?.type === "bundle") return [t.key];
  return defaultLit(model, c, rails);
}
