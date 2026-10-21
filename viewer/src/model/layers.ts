// Layers (spec §15): a floor's base layer is everything it draws by default; lines that do not fit the base go into
// extra layers shown on demand. Today that is one layer per heavily used item (`floor.hubs`, the scanner's fan-in >= 8
// items), holding every line into and out of it. A layer is named by its item's map code, exactly as the floor shows it
// on the machine (`S7·P1·F1`), with the item's full name on hover; the list adds " · <count>".
import type { Bundle, Model } from "./model";

/** A layer's id: the id of the heavily used item it shows. */
export type LayerId = string;

/** A line kept out of the base layer, with the layer it is drawn in (its heavily used item) and whether it runs into
 *  that item (some relation of the drawn kind ends on it: the `used by N` count). A line between two heavily used items
 *  is in both their layers: one entry each, with the same key, running into one item and out of the other. */
export interface LayerBundle extends Bundle { layer: LayerId; into: boolean }

/** A floor's extra layer: its id (= `item`), its name (the item's map code), the item's full name (the hover), how many
 *  lines it holds, and how many of them run into the item (`used by N`). */
export interface FloorLayer { id: LayerId; name: string; full: string; count: number; item: string; usedBy: number }

/** The floor's extra layers, one per heavily used item with a line, in `floor.hubs` order. Empty on most floors (no
 *  layers button). Pure: from the model alone. */
export function floorLayers(model: Model, container: string): FloorLayer[] {
  const hubs = model.floor(container)?.hubs ?? [];
  if (!hubs.length) return [];
  const layered = model.bundles(container).layered;
  const out: FloorLayer[] = [];
  for (const h of hubs) {
    const list = layered.filter((b) => b.layer === h);
    if (list.length) out.push({ id: h, name: model.codes.get(h) ?? h, full: model.itemName(h), count: list.length, item: h, usedBy: list.filter((b) => b.into).length });
  }
  return out;
}

/** A floor's line count: its base lines and its layer lines, a line in two layers once. */
export const floorLineCount = (b: { bundles: readonly Bundle[]; layered: readonly LayerBundle[] }): number =>
  b.bundles.length + new Set(b.layered.map((x) => x.key)).size;

/** The layers button's label: the shown layer's name exactly as the list has it, `Base` when none shows. */
export const layerLabel = (l: Pick<FloorLayer, "name"> | null | undefined): string => l?.name ?? "Base";

/** A layer's entry in the layers list: its name, then its line count after a "·" (the count is the list's only). */
export const listEntry = (l: Pick<FloorLayer, "name" | "count">): string => `${l.name} · ${l.count}`;

/** The layer lines a node selected on the base peeks over it: per layer, the keys of its lines in it (`a` or `b` is the
 *  node). A line in two layers (hub to hub) is peeked from the first layer in `order` only. */
export function peekKeys(layered: readonly Pick<LayerBundle, "key" | "a" | "b" | "layer">[], order: readonly LayerId[], id: string): Map<LayerId, Set<string>> {
  const out = new Map<LayerId, Set<string>>(), seen = new Set<string>();
  for (const layer of order) for (const x of layered) {
    if (x.layer !== layer || (x.a !== id && x.b !== id) || seen.has(x.key)) continue;
    seen.add(x.key);
    if (!out.has(layer)) out.set(layer, new Set());
    out.get(layer)!.add(x.key);
  }
  return out;
}

/** Relation id to the names (map codes) of the layers whose lines carry it, for the relations no base line carries (the
 *  inspector's "in layer" note). From one `model.bundles` result, cached and shared by the model: read, never changed. */
export function layersOfRelations(model: Model, b: { bundles: readonly Bundle[]; layered: readonly LayerBundle[] }): Map<string, string[]> {
  const onBase = new Set(b.bundles.flatMap((x) => x.relations.map((r) => r.id))), out = new Map<string, string[]>();
  for (const x of b.layered) for (const r of x.relations) {
    if (onBase.has(r.id)) continue;
    const name = model.codes.get(x.layer) ?? x.layer, list = out.get(r.id) ?? [];
    if (!list.includes(name)) out.set(r.id, [...list, name]);
  }
  return out;
}
