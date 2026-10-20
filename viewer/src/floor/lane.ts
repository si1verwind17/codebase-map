// A lane's name sits where no line crosses it, so taps and pipes never run through the letters.
import { flies } from "../model/model";
import type { Pt } from "../route/types";

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
