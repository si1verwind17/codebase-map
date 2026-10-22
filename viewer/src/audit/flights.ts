// The flight path checks of the map audit: paths still on top of each other after their landings are spread (and the
// paths in line with their hub that no spread along its edge can part), and paths that pass under a box. They read the
// paths as the floor draws them (`flightPaths`). Pure; no Pixi here.
import { flightPaths, inLine, keepOffBoxes, OVERLAP_PX, OVERLAP_RUN, runTogether, visiblePart, type FlightPath } from "../factory/flights";
import type { PxRect } from "../factory/clear";
import type { TileFloor } from "../factory/layout";
import { T } from "../factory/tiles";
import type { Pt } from "../route/types";
import type { Violation } from "./types";

const name = (p: FlightPath) => `${p.flight} ${p.key}${p.group !== undefined ? ` (${p.group})` : ""}`;
const tile = (q: Pt) => ({ x: Math.floor(q.x / T), y: Math.floor(q.y / T) });
const px = (tf: TileFloor, id: string): PxRect | undefined => {
  const r = tf.boxes.get(id);
  return r ? { x0: r.x * T, y0: r.y * T, x1: (r.x + r.w) * T, y1: (r.y + r.h) * T } : undefined;
};

/** Pairs of flight paths whose seen parts (`visiblePart`: from the pad or dock to the hub's edge) run within OVERLAP_PX
 *  of each other for OVERLAP_RUN or more on open floor (outside every box's face: under a box they are hidden, which
 *  `flights.hidden` reports), each with whether its pads are in line with their one hub (`inLine`). */
function overlaps(tf: TileFloor, paths: FlightPath[]): { a: FlightPath; b: FlightPath; run: number; at: Pt; inLine: boolean }[] {
  const faces = keepOffBoxes(tf, 0).map((b) => b.r);
  const seen = paths.map((p) => { const r = px(tf, p.item); return r ? visiblePart(p, r) : [p.launch, p.hub] as [Pt, Pt]; });
  const out: { a: FlightPath; b: FlightPath; run: number; at: Pt; inLine: boolean }[] = [];
  for (let i = 0; i < paths.length; i++) for (let j = i + 1; j < paths.length; j++) {
    const run = runTogether(seen[i], seen[j], faces);
    if (run < OVERLAP_RUN) continue;
    const a = paths[i], b = paths[j], hub = px(tf, a.item);
    const line = a.item === b.item && !!hub && inLine(a.launch, b.launch, { x: (hub.x0 + hub.x1) / 2, y: (hub.y0 + hub.y1) / 2 });
    out.push({ a, b, run, at: seen[i][1], inLine: line });
  }
  return out;
}
const told = (o: { a: FlightPath; b: FlightPath; run: number; at: Pt }): Violation =>
  ({ detail: `${name(o.a)} and ${name(o.b)} run within ${OVERLAP_PX} px of each other for ${Math.round(o.run)} px on open floor`, at: tile(o.at) });

/** `flights.overlap`: two flight paths still on top of each other on open floor after their landings are spread
 *  (`spreadLandings`): a group into one hub with more paths than its edge holds, sharing landing points, or paths into
 *  different hubs. Paths whose pads are in line with their hub are `flights.in-line`'s. */
export function overlapViolations(tf: TileFloor, paths: FlightPath[] = flightPaths(tf)): Violation[] {
  return overlaps(tf, paths).filter((o) => !o.inLine).map(told);
}

/** `flights.in-line`, an advisory: two paths into one hub whose pads are in line with it (one machine straight behind
 *  another) that still run together on open floor with their landings spread over the whole edge: the far pad is too
 *  far from the hub, for the near one, for the edge's width to part them. */
export function inLineViolations(tf: TileFloor, paths: FlightPath[] = flightPaths(tf)): Violation[] {
  return overlaps(tf, paths).filter((o) => o.inLine).map(told);
}

/** A path must run this far under a box's face to count as hidden: one dot and its gap (2 px on, 6 off), so at most one
 *  dot is lost. A shorter run is the path clipping a corner. */
export const HIDDEN_MIN = 8;

/** A flight path that passes under a box it does not belong to, for HIDDEN_MIN or more of its length: one of
 *  `flightKeepOff`'s (a machine, hub, store or door, a receiving or webhook dock, a waiting stack), by its face alone
 *  (the shadow is not the box), other than its own machine's, its hub's, or theirs (the machine's docks, the hub's
 *  stack). Paths are drawn under the machines, so that stretch is hidden. An advisory, not a map limit: a known look,
 *  kept for now (format.md → Audit). */
export function hiddenViolations(tf: TileFloor, paths: FlightPath[] = flightPaths(tf)): Violation[] {
  const boxes = keepOffBoxes(tf, 0), out: Violation[] = [];
  for (const p of paths) for (const b of boxes) {
    if (b.owner === p.machine || b.owner === p.item) continue;
    let len = 0;
    for (let i = 1; i < p.points.length; i++) len += through(p.points[i - 1], p.points[i], b.r);
    if (len >= HIDDEN_MIN) out.push({ detail: `${name(p)} passes under ${b.name} for ${Math.round(len)} px`, at: tile({ x: (b.r.x0 + b.r.x1) / 2, y: (b.r.y0 + b.r.y1) / 2 }) });
  }
  return out;
}

/** How far segment a→b runs through `r`, in px (Liang–Barsky). */
function through(a: Pt, b: Pt, r: PxRect): number {
  let t0 = 0, t1 = 1;
  const dx = b.x - a.x, dy = b.y - a.y;
  for (const [p, q] of [[-dx, a.x - r.x0], [dx, r.x1 - a.x], [-dy, a.y - r.y0], [dy, r.y1 - a.y]]) {
    if (p === 0) { if (q < 0) return 0; continue; }
    const t = q / p;
    if (p < 0) { if (t > t1) return 0; if (t > t0) t0 = t; } else { if (t < t0) return 0; if (t < t1) t1 = t; }
  }
  return t1 > t0 ? (t1 - t0) * Math.hypot(dx, dy) : 0;
}
