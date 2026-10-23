// The floor checks of the map audit: drone pads on corridor tiles, trips over their time (trains 3 s, drones 5 s),
// relations lost from the floor; and the numbers it only measures (congestion, spacing, the Fit zoom against the
// names/codes switch). Each is pure. No Pixi here: the speeds, the Fit zoom and the switch come from the functions the viewer uses (lane.ts `moverSpeed`,
// fitscale.ts `fitZoom`, fit.ts `codeZoom`), never from a copy.
import { SITE, type Model } from "../model/model";
import type { FloorPlan } from "../factory/plan";
import type { TileRoute } from "../factory/router";
import { T, type Box } from "../factory/tiles";
import { codeZoom } from "../factory/fit";
import { boxNameFit, nameContext } from "../factory/boxname";
import { coveredKeys, flightPaths } from "../factory/flights";
import { FLIGHT_SECS, moverSpeed, TRAIN_SECS } from "../floor/lane";
import { fitZoom } from "../floor/fitscale";
import { STRIP_MIN } from "../factory/layout";
import type { Violation } from "./types";

/** The longest a moving item may take over one line, seconds (audit row 25): a train over its rail, a drone over its
 *  flight (drones fly slower, so a floor's flights stay readable). */
export const TRIP_MAX: Record<string, number> = { train: TRAIN_SECS, event: FLIGHT_SECS };
/** The floor area Fit is measured for (audit row 24). */
export const FIT_AREA = { w: 1440, h: 900 };

const inBox = (b: Box, x: number, y: number) => x >= b.x && x < b.x + b.w && y >= b.y && y < b.y + b.h;
const boxAt = (plan: FloorPlan) => { const boxes = [...plan.tf.boxes.values()]; return (x: number, y: number) => boxes.some((b) => inBox(b, x, y)); };
/** The base's lines and each layer's, with the suffix a violation names its view by. */
const views = (plan: FloorPlan): [string, TileRoute[]][] =>
  [["", plan.routes], ...Object.entries(plan.layers ?? {}).map(([id, l]): [string, TileRoute[]] => [` (layer ${id})`, l!.routes])];

/** Every drone pad whose tile lies outside every box: a pad stands inside its machine, never on a corridor tile. */
export function padCorridorViolations(plan: FloorPlan): Violation[] {
  const covered = boxAt(plan);
  return (plan.tf.landing?.pads ?? []).filter((p) => !covered(p.x, p.y))
    .map((p) => ({ detail: `${p.role} pad of ${p.machine} (${p.topic}) on a corridor tile`, at: { x: p.x, y: p.y } }));
}

/** The movers whose trip the audit times: a train on a rail and a drone on a drone route (an event). Belts, pipes and
 *  taps are not timed: their items run at a steady 60 px/s by design (lane.ts `moverSpeed`), so their trip grows with
 *  the line; row 25 was about drones crawling along long flight paths. A train scales its speed to its rail; every
 *  drone on a floor flies at the speed its longest flight sets, so that flight crosses in about FLIGHT_SECS. */
const TIMED: Partial<Record<TileRoute["kind"], string>> = { rail: "train", drone: "event" };
const secs = (s: number) => s.toFixed(1);

/** Every train or drone whose trip takes over its TRIP_MAX s end to end at the movers' speed (`speed`, the viewer's
 *  lane.ts `moverSpeed`; a test may pass another to prove the check sees a slow mover): a rail's length is its piece
 *  count times the tile, in the base and in each layer view; a flight's is its path's length (as drones.ts measures
 *  it). A route with no pieces (a drone route, a failed line) carries nothing along tiles. */
export function travelViolations(plan: FloorPlan, speed: (kind: string, length: number) => number = moverSpeed): Violation[] {
  const out: Violation[] = [];
  const trip = (kind: string, length: number) => length / speed(kind, length);
  for (const [view, routes] of views(plan)) for (const r of routes) {
    const kind = TIMED[r.kind];
    if (!kind || !r.pieces.length) continue;
    const t = trip(kind, r.pieces.length * T);
    if (t > TRIP_MAX[kind] + 1e-6) out.push({ detail: `${r.kind} ${r.key} takes ${secs(t)} s (${r.pieces.length} tiles)${view}`, at: { x: r.pieces[0].x, y: r.pieces[0].y } });
  }
  const flights = flightPaths(plan.tf).map((f) => {
    let len = 0;
    for (let i = 1; i < f.points.length; i++) len += Math.hypot(f.points[i].x - f.points[i - 1].x, f.points[i].y - f.points[i - 1].y);
    return { f, len };
  });
  const longest = Math.max(0, ...flights.map((x) => x.len));
  for (const { f, len } of flights) {
    const t = len / speed("event", longest);
    if (t > TRIP_MAX.event + 1e-6) out.push({ detail: `${f.flight} flight ${f.key} takes ${secs(t)} s (${Math.round(len)} px)`, at: { x: Math.floor(f.points[0].x / T), y: Math.floor(f.points[0].y / T) } });
  }
  return out;
}

/** Every relation bundle the floor holds (`model.bundles(container)`: its base bundles and each layer's) that the plan
 *  draws nowhere: its key is on no base route and no layer route, and no flight carries it. Every route the plan holds
 *  is drawn (a belt, a pipe, a tap, a rail, a dotted drone route, or a failed line dashed red), and a bundle its flights
 *  carry whole (`coveredKeys`) is drawn as them. */
export function lostViolations(model: Model, container: string, plan: FloorPlan): Violation[] {
  const { bundles, layered } = model.bundles(container);
  const drawn = new Set(views(plan).flatMap(([, routes]) => routes.map((r) => r.key)));
  for (const k of coveredKeys(flightPaths(plan.tf), [...bundles, ...layered])) drawn.add(k);
  return [...bundles.map((b) => ({ b, view: "" })), ...layered.map((b) => ({ b, view: ` (layer ${b.layer})` }))]
    .filter(({ b }) => !drawn.has(b.key))
    .map(({ b, view }) => ({ detail: `relation ${b.key} (${b.kind}) is in neither the base nor a layer${view}` }));
}

export interface FloorMeasures { congestion: number; spacing: { area: number; spread: number }; fitZoom: number; switchZoom: number }

/** The smallest machine or door name the drawing fits on the floor, px, as the scene keeps it (`minName`: 14 before
 *  any box is drawn, then each name's fitted size: factory-draw.ts `paintBox`, draw.ts `drawDoor`). */
export function minNameSize(model: Model, container: string, plan: FloorPlan): number {
  const ctx = nameContext(model, container, plan.tf.boxes.values(), model.bundles(container).doors);
  return Math.min(14, ...[...plan.tf.boxes.values()].map((b) => boxNameFit(model, ctx, b).size));
}

/** How much wider than the Fit canvas a floor may be, side to side against its height, before a row is too long. */
export const WIDE = 2;

/** The outside world (the externals, which wrap near-square from STRIP_MIN of them) laid out as a strip: its long
 *  side holds over twice the items of a near-square grid (20 externals in one row, not 5 × 4). */
export function stripViolations(plan: FloorPlan): Violation[] {
  const out: Violation[] = [];
  for (const z of plan.tf.zones) {
    if (z.name !== "outside world") continue;
    const inside = [...plan.tf.boxes.values()].filter((b) => b.kind !== "door" && b.x >= z.x && b.y >= z.y
      && b.x + b.w <= z.x + z.w && b.y + b.h <= z.y + z.h);
    const side = Math.ceil(Math.sqrt(inside.length));
    const cols = new Set(inside.map((b) => b.x)).size, rows = new Set(inside.map((b) => b.y)).size;
    if (inside.length >= STRIP_MIN && Math.max(cols, rows) > 2 * side)
      out.push({ detail: `${z.name}: ${inside.length} machines in ${cols}×${rows}, a near-square ${side}×${Math.ceil(inside.length / side)} fits`,
                 at: { x: z.x, y: z.y } });
  }
  return out;
}

/** A floor more than WIDE times as wide (for its height) as the Fit canvas whose names do not read at Fit: Fit is held
 *  back by its width, so a row of it should wrap (row 46: an airfield's hubs in one long row). Small wide floors read
 *  at Fit and pass. */
export function wideViolations(m: FloorMeasures, plan: FloorPlan): Violation[] {
  const { cols, rows } = plan.tf, aspect = cols / rows, canvas = FIT_AREA.w / FIT_AREA.h;
  if (aspect <= WIDE * canvas || m.fitZoom >= m.switchZoom) return [];
  return [{ detail: `${cols}×${rows} tiles, ${aspect.toFixed(1)}:1: at Fit (${m.fitZoom.toFixed(2)}) names need ${m.switchZoom.toFixed(2)}` }];
}

/** The floor's measured numbers (no threshold yet):
 *  - `congestion`: above-ground line tiles of the base (each tile once) divided by the tiles outside every box;
 *  - `spacing.area`: machine area (every box but the doors) divided by the floor's area; `spacing.spread`: the
 *    coefficient of variation of each machine's edge-to-edge gap to its nearest machine, tiles (0 under two machines);
 *  - `fitZoom`: the zoom the scene's Fit picks for a FIT_AREA canvas (`fitZoom`, no bottom inset);
 *  - `switchZoom`: the names/codes switch, `codeZoom` of the floor's smallest name (`minNameSize`). */
export function measure(plan: FloorPlan, model: Model, container: string): FloorMeasures {
  const { tf } = plan, boxed = boxAt(plan);
  const lines = new Set<number>();
  for (const r of plan.routes) for (const p of r.pieces) if (!p.under && !boxed(p.x, p.y)) lines.add(p.y * tf.cols + p.x);
  let free = 0;
  for (let y = 0; y < tf.rows; y++) for (let x = 0; x < tf.cols; x++) if (!boxed(x, y)) free++;
  const machines = [...tf.boxes.values()].filter((b) => b.kind !== "door");
  const area = machines.reduce((s, b) => s + b.w * b.h, 0) / Math.max(1, tf.cols * tf.rows);
  const gap = (a: Box, b: Box) => Math.hypot(Math.max(0, b.x - (a.x + a.w), a.x - (b.x + b.w)), Math.max(0, b.y - (a.y + a.h), a.y - (b.y + b.h)));
  const gaps = machines.length < 2 ? [] : machines.map((a) => Math.min(...machines.filter((b) => b !== a).map((b) => gap(a, b))));
  const mean = gaps.reduce((s, g) => s + g, 0) / Math.max(1, gaps.length);
  const sd = Math.sqrt(gaps.reduce((s, g) => s + (g - mean) ** 2, 0) / Math.max(1, gaps.length));
  return {
    congestion: free ? lines.size / free : 0,
    spacing: { area, spread: mean > 0 ? sd / mean : 0 },
    fitZoom: fitZoom(tf.cols * T, tf.rows * T, FIT_AREA.w, FIT_AREA.h, container === SITE),
    switchZoom: codeZoom(minNameSize(model, container, plan)),
  };
}
