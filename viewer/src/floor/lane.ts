// A lane's name sits where no line crosses it, so taps and pipes never run through the letters.
import { flies } from "../model/model";
import type { Pt } from "../route/types";
import { LANE_H, T } from "../factory/tiles";

/** x positions where a vertical run crosses, or ends on, the lane band at `y` (± half its height). */
export function crossings(routes: { points: Pt[] }[], y: number, half: number): number[] {
  const xs = new Set<number>();
  for (const r of routes)
    for (let i = 1; i < r.points.length; i++) {
      const a = r.points[i - 1], b = r.points[i];
      if (a.x !== b.x) continue;
      const lo = Math.min(a.y, b.y), hi = Math.max(a.y, b.y);
      if (lo <= y + half && hi >= y - half) xs.add(a.x);
    }
  return [...xs].sort((p, q) => p - q);
}

/** The paths drawn point to point over a floor: drone lines no flight carries, and the flights. */
export function pointPaths(routes: { key: string; kind: string; points: Pt[] }[], flights: { points: Pt[] }[], covered: Set<string>): Pt[][] {
  return [...routes.filter((r) => r.kind === "drone" && !covered.has(r.key)).map((r) => r.points), ...flights.map((f) => f.points)];
}

const PATH_STEP = 8;   // px between the points a path over a lane blocks: closer than a name's gap needs (laneLabelSpot)

/** x positions a lane's name keeps off (clear.ts `laneLabelSpot`): where a vertical run crosses or ends on the lane
 *  (`crossings`), and every PATH_STEP px along where a drone or flight path (`paths`, `pointPaths`) runs over it. */
export function laneCrossings(l: { y: number }, routes: { points: Pt[] }[], paths: Pt[][]): number[] {
  const y0 = l.y * T, y1 = (l.y + LANE_H) * T;
  const xs = new Set(crossings(routes, (y0 + y1) / 2, (y1 - y0) / 2));
  for (const pts of paths) for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    // the part of the segment inside the lane's rows
    const t0 = a.y === b.y ? (a.y >= y0 && a.y <= y1 ? 0 : 1) : Math.max(0, Math.min((y0 - a.y) / (b.y - a.y), (y1 - a.y) / (b.y - a.y)));
    const t1 = a.y === b.y ? (a.y >= y0 && a.y <= y1 ? 1 : 0) : Math.min(1, Math.max((y0 - a.y) / (b.y - a.y), (y1 - a.y) / (b.y - a.y)));
    if (t1 < t0) continue;
    const xa = a.x + (b.x - a.x) * t0, xb = a.x + (b.x - a.x) * t1, lo = Math.min(xa, xb), hi = Math.max(xa, xb);
    for (let x = lo; x < hi; x += PATH_STEP) xs.add(x);
    xs.add(hi);
  }
  return [...xs].sort((p, q) => p - q);
}

/** Seconds a train takes over its rail, and a drone over its floor's longest flight, at most. */
export const TRAIN_SECS = 3;
export const FLIGHT_SECS = 5;

/** Travel speed in px/s: belts and pipes keep a steady 60; a train crosses its rail (`length`) in at most TRAIN_SECS.
 *  A drone (event) passes its floor's longest flight as `length`, so every drone on a floor flies at one speed, a
 *  short hop takes less time than a long one, and the longest crosses in at most FLIGHT_SECS. */
export function moverSpeed(kind: string, length: number): number {
  return flies(kind) ? Math.max(60, length / FLIGHT_SECS) : kind === "train" ? Math.max(60, length / TRAIN_SECS) : 60;
}

/** The floor is cleared only by a click on it: a press released within a few pixels, not a drag. */
export const CLICK_SLOP = 4;
export const isClick = (dx: number, dy: number): boolean => Math.hypot(dx, dy) < CLICK_SLOP;
