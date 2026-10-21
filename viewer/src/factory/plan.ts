// src/factory/plan.ts
// A floor and its lines together: wide corridors for busy floors, crowded corridors widened to fit their lines,
// and every corridor widened once more if a line still fails.
import { flies, type Bundle, type Door, type Model } from "../model/model";
import type { LayerBundle, LayerId } from "../model/layers";
import { laneGaps, layoutTiles, type LaneGap, type LayoutOpts, type TileFloor } from "./layout";
import { hasWebhooks, landing, reservedRects, webhookDocks, type Landing } from "./pads";
import { routeTiles, type TileRoute } from "./router";
import { inYardRows, rails, yardLadders, type Ladders } from "./yards";
import { inside, type Piece, type Rect } from "./tiles";

const WIDEN = 2;       // tiles added to every corridor on the one retry
const MAX_START = 3;
const MAX_EXTRA = 6;   // a guard: counting belts (not lines), a full corridor gains at most two, so this never binds

/** Starting corridor gap from demand: lines at the busiest box beyond what its sides carry comfortably. The base
 *  corridors are already 6 across and 4 down (they were 4 and 3), so one extra tile per six lines past eight. */
export function startGap(bundles: Bundle[]): number {
  const load = new Map<string, number>();
  for (const b of bundles) {
    if (flies(b.kind)) continue;   // drones fly
    load.set(b.a, (load.get(b.a) ?? 0) + 1);
    load.set(b.b, (load.get(b.b) ?? 0) + 1);
  }
  const busiest = Math.max(0, ...load.values());
  return Math.min(MAX_START, Math.max(0, Math.ceil((busiest - 8) / 6)));
}

/** Belts side by side in a corridor: the most on-top tiles travelling along it (down a column corridor, across a row
 *  corridor) in any one cross-section. A trunk tile is one belt however many lines ride it. Cross-sections where the
 *  corridor meets a crossing one (`cross`) are not counted: lines turn there. */
export function corridorLoad(r: Rect, routes: TileRoute[], along: "down" | "across", cross: Rect[] = [], held: Rect[] = []): number {
  if (r.w <= 0 || r.h <= 0) return 0;
  const axis = along === "down" ? ["n", "s"] : ["e", "w"];
  const span = along === "down" ? r.h : r.w;
  const seen = Array.from({ length: span }, () => new Set<number>());
  for (const q of routes) if (!q.failed) for (const p of q.pieces) {
    if (p.under || !inside(r, p.x, p.y) || !(axis.includes(p.in) || axis.includes(p.out))) continue;
    if (along === "down") seen[p.y - r.y].add(p.x); else seen[p.x - r.x].add(p.y);
  }
  // a dock, waiting stack, rail yard, sign or station in the corridor takes its tiles from every cross-section it spans, as a belt would
  for (const h of held) for (let y = h.y; y < h.y + h.h; y++) for (let x = h.x; x < h.x + h.w; x++) {
    if (!inside(r, x, y)) continue;
    if (along === "down") seen[y - r.y].add(x); else seen[x - r.x].add(y);
  }
  const crossed = (i: number) => cross.some((c) => (along === "down" ? i + r.y >= c.y && i + r.y < c.y + c.h : i + r.x >= c.x && i + r.x < c.x + c.w));
  return Math.max(0, ...seen.filter((_, i) => !crossed(i)).map((s) => s.size));
}

/** Extra tiles per corridor: a corridor whose load reaches its width minus one is full and gets one tile per belt
 *  past width minus two (so one or two: belts on top never outnumber tiles), at most MAX_EXTRA; undefined when no
 *  corridor is full. Belts, not lines: lines riding one trunk share its tile, and widening for them measured worse
 *  (the large real map: +6% floor area, one file floor at 78% of its baseline tiles, against +1% and 73%). */
export function trafficGaps(tf: TileFloor, routes: TileRoute[]): { colGaps: number[]; rowGaps: number[] } | undefined {
  const cols = tf.aisles?.cols ?? [], rows = tf.aisles?.rows ?? [], held = reservedRects(tf);
  const extra = (r: Rect, along: "down" | "across") => {
    const width = along === "down" ? r.w : r.h, load = corridorLoad(r, routes, along, along === "down" ? rows : cols, held);
    return width > 0 && load >= width - 1 ? Math.min(MAX_EXTRA, load - (width - 2)) : 0;
  };
  const colGaps = cols.map((r) => extra(r, "down"));
  const rowGaps = rows.map((r) => extra(r, "across"));
  return [...colGaps, ...rowGaps].some((g) => g > 0) ? { colGaps, rowGaps } : undefined;
}

/** Lane gaps whose lines run along more rows than the gap has inner rows (rows next to no lane): a line then runs along
 *  a row next to a lane, where the lanes' taps end and their underground runs come up, so it passes those stubs as if it
 *  touched them. A gap of two rows has no inner row. Each with the first line along it and where. */
export function crowdedLaneGaps(tf: TileFloor, routes: TileRoute[]): { gap: LaneGap; key: string; at: { x: number; y: number } }[] {
  const out: { gap: LaneGap; key: string; at: { x: number; y: number } }[] = [];
  for (const g of laneGaps(tf)) {
    const rect = { x: g.x0, y: g.y0, w: g.x1 - g.x0, h: g.y1 - g.y0 };
    const along = routes.flatMap((r) => r.pieces.filter((p) => !p.under && alongRow(p) && inside(rect, p.x, p.y)).map((p) => ({ key: r.key, at: { x: p.x, y: p.y } })));
    if (new Set(along.map((a) => a.at.y)).size > g.y1 - g.y0 - 2) out.push({ gap: g, ...along[0] });
  }
  return out;
}

/** A piece that enters or leaves its tile sideways: its line runs along the row there. */
export const alongRow = (p: Piece) => p.in === "e" || p.in === "w" || p.out === "e" || p.out === "w";

const failures = (routes: TileRoute[]) => routes.filter((r) => r.failed).length;

/** Crossings as drawn: underground runs, a trunk going under counted once however many lines ride it. */
export function crossings(routes: TileRoute[]): number {
  const runs = new Set<string>();
  for (const r of routes) r.pieces.forEach((p, i) => {
    if (!p.under || i === 0 || r.pieces[i - 1].under) return;
    let e = i;
    while (e < r.pieces.length - 1 && r.pieces[e].under) e++;   // a route never ends underground
    const a = r.pieces[i - 1], b = r.pieces[e];
    runs.add(`${a.x},${a.y}>${b.x},${b.y}`);
  });
  return runs.size;
}

/** The floor laid out with its messaging, rails and webhook docks placed (tf.landing, tf.rails, tf.webhooks) before
 *  any routing: pads inside their machines, receiving docks reserved outside them; rail yards, their signs and stations
 *  reserved after the docks; then the site's inbound webhook docks, where a first routing's belts arrive. A floor with a
 *  free-standing yard is laid out again with rows kept for it in the in column. A floor with no hub and no yard is exactly layoutTiles.
 *  `ladders`: the yards that stand as ladders (a throat column), planned from a first routing (`planFloor`). */
export function layFloor(model: Model, container: string, doors: Door[], bundles: Bundle[], opts: LayoutOpts = {}, ladders?: Ladders): TileFloor {
  let tf = layoutTiles(model, container, doors, opts);
  const inYard = inYardRows(model, container, tf, bundles);   // a free-standing yard: the in column keeps its rows
  if (inYard) tf = layoutTiles(model, container, doors, { ...opts, inYard });
  const l = landing(model, container, tf, bundles);
  if (l) tf.landing = l;
  const r = rails(model, container, tf, bundles, ladders);
  if (r) tf.rails = r;
  // the site's inbound webhooks: route once with no dock to see where each belt arrives, and stand its dock there
  if (hasWebhooks(model, tf, bundles)) {
    const w = webhookDocks(model, tf, bundles, routeTiles(tf, bundles));
    if (w?.docks.length) tf.webhooks = w.docks;
    if (w?.notes.length) tf.notes = [...tf.notes ?? [], ...w.notes];
  }
  return tf;
}

/** `layers`: each extra layer's lines (spec §15), routed after the base on the same floor; present only when the floor
 *  has one. The base (`tf`, `routes`, `gap`, `landing`) is exactly the plan without them. */
export interface FloorPlan { tf: TileFloor; routes: TileRoute[]; gap: number; landing?: Landing; layers?: Partial<Record<LayerId, { routes: TileRoute[] }>> }

/** The floor's base plan (`planBase`), then each extra layer's lines (`layered`, from `Model.bundles`) routed over it. */
export function planFloor(model: Model, container: string, doors: Door[], bundles: Bundle[], layered: LayerBundle[] = []): FloorPlan {
  const base = planBase(model, container, doors, bundles);
  return layered.length ? { ...base, layers: routeLayers(base, layered) } : base;
}

/** Each layer's lines routed on the base's floor over its lines (`routeTiles`' `base`): the base plan is never touched,
 *  and no layer sees another's lines (one layer shows at a time), so a line in two layers is routed in each. Planned
 *  in item-id order, which changes nothing (each layer is independent); the list's order is `floor.hubs` (layers.ts). */
function routeLayers(base: FloorPlan, layered: LayerBundle[]): NonNullable<FloorPlan["layers"]> {
  const by = new Map<LayerId, LayerBundle[]>();
  for (const b of layered) by.set(b.layer, [...(by.get(b.layer) ?? []), b]);
  const out: NonNullable<FloorPlan["layers"]> = {};
  for (const id of [...by.keys()].sort()) out[id] = { routes: routeTiles(base.tf, by.get(id)!, base.routes) };
  return out;
}

/** Route once; widen the crowded corridors and route a second time, kept only if no more lines fail and it crosses
 *  strictly less. Only a floor with no crowded corridor, whose lines still fail, gets the old retry (every corridor
 *  GAP + WIDEN, taken if no more lines fail): a floor never routes a third time, but for a full lane gap's one more row
 *  (`roomierLanes`). When the traffic pass already routed, its answer stands, failures included. A floor where some
 *  yard sends more than one platform's rail out by one exit is planned once more with that yard a ladder (`yardLadders`;
 *  twice when an exit leaves from a group's middle row: its top end, or its bottom end when that crosses strictly
 *  less), kept if no more lines fail and no more rails go unplaced. */
function planBase(model: Model, container: string, doors: Door[], bundles: Bundle[]): FloorPlan {
  let best = routeFloor(model, container, doors, bundles);
  const top = yardLadders(best.tf, best.routes, "top");
  if (top) {
    // an exit from a group's middle row moves to its top end, or to its bottom end when that crosses strictly less
    const bottom = yardLadders(best.tf, best.routes, "bottom")!;
    const same = JSON.stringify([...top]) === JSON.stringify([...bottom]);
    const unplaced = (q: FloorPlan) => q.tf.rails?.unplaced.length ?? 0;
    const ok = (q: FloorPlan) => failures(q.routes) <= failures(best.routes) && unplaced(q) <= unplaced(best);
    let laddered: FloorPlan | undefined;
    for (const l of same ? [top] : [top, bottom]) {
      const q = routeFloor(model, container, doors, bundles, l);
      if (ok(q) && (!laddered || crossings(q.routes) < crossings(laddered.routes))) laddered = q;
    }
    if (laddered) best = laddered;
  }
  return best.tf.landing ? { ...best, landing: best.tf.landing } : best;
}

function routeFloor(model: Model, container: string, doors: Door[], bundles: Bundle[], ladders?: Ladders): FloorPlan {
  const gap = startGap(bundles);
  let opts: LayoutOpts = { gap };
  const tf = layFloor(model, container, doors, bundles, opts, ladders);
  let best = { tf, routes: routeTiles(tf, bundles), gap };
  const widths = trafficGaps(best.tf, best.routes);
  if (widths) {
    const tf2 = layFloor(model, container, doors, bundles, { gap, ...widths }, ladders);
    const routes2 = routeTiles(tf2, bundles);
    if (failures(routes2) <= failures(best.routes) && crossings(routes2) < crossings(best.routes)) { best = { tf: tf2, routes: routes2, gap }; opts = { gap, ...widths }; }
  }
  if (!widths && failures(best.routes)) {   // the traffic pass routed: no wider retry
    const wider = layFloor(model, container, doors, bundles, { gap: gap + WIDEN }, ladders);
    const routes3 = routeTiles(wider, bundles);
    if (failures(routes3) <= failures(best.routes)) { best = { tf: wider, routes: routes3, gap: gap + WIDEN }; opts = { gap: gap + WIDEN }; }
  }
  return roomierLanes(model, container, doors, bundles, ladders, best, opts);
}

/** A plan whose lane gaps are full (`crowdedLaneGaps`) laid out once more with one more row in each, kept if no more
 *  lines fail and fewer gaps are full: the owner's 2026-10-21 comment, lanes too close where lines crowd the gap. */
function roomierLanes(model: Model, container: string, doors: Door[], bundles: Bundle[], ladders: Ladders | undefined, best: FloorPlan, opts: LayoutOpts): FloorPlan {
  const full = crowdedLaneGaps(best.tf, best.routes);
  if (!full.length) return best;
  const laneGaps = best.tf.lanes.map((_, i) => (full.some((f) => f.gap.above === i) ? 1 : 0));
  const tf = layFloor(model, container, doors, bundles, { ...opts, laneGaps }, ladders);
  const routes = routeTiles(tf, bundles);
  return failures(routes) <= failures(best.routes) && crowdedLaneGaps(tf, routes).length < full.length ? { ...best, tf, routes } : best;
}
