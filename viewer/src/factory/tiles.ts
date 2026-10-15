// The factory grid: one tile is 24 px; machines have fixed footprints; lines are chains of 1×1 pieces.
export const T = 24;

export type Dir = "n" | "e" | "s" | "w";
/** n, e, s, w: index (i + 2) % 4 is the opposite direction. */
export const DIRS: Dir[] = ["n", "e", "s", "w"];
export const STEP: Record<Dir, readonly [number, number]> = { n: [0, -1], e: [1, 0], s: [0, 1], w: [-1, 0] };
export const OPP: Record<Dir, Dir> = { n: "s", s: "n", e: "w", w: "e" };

export type Footprint = "service" | "dock" | "rack" | "installed" | "package" | "warehouse" | "hub" | "door" | "chest";
/** `chest`: a cache only one machine uses, standing beside that machine on the site floor instead of on a lane. 2x2 is its
 *  smallest size; a chest grows up to a lane-end store box until its name shows whole (fit.ts `chestSize`). */
export const FOOT: Record<Footprint, readonly [number, number]> = {
  service: [5, 5], dock: [5, 5], rack: [4, 3], installed: [4, 5], package: [5, 3], warehouse: [6, 3], hub: [3, 3], door: [7, 3], chest: [2, 2],
};
/** A database lane is three tiles tall. */
export const LANE_H = 3;

/** Which footprint a map kind takes; a library is a rack on the site shelf and a wall unit inside a factory. */
export function footprintFor(kind: string, site: boolean): Footprint {
  switch (kind) {
    case "service": return "service";
    case "external": return "dock";
    case "library": return site ? "rack" : "installed";
    case "datastore": return "warehouse";
    case "topic": case "in-process-queue": return "hub";
    case "door": return "door";
    default: return "package";   // package, class, file, method, table, group: one wide 5×3 block
  }
}

export interface Rect { x: number; y: number; w: number; h: number }
export interface Box extends Rect { id: string; kind: string; foot: Footprint; region: string }

/** One line tile. `in` is the travel direction entering it and `out` the direction leaving it (a corner where
 *  they differ). `under` tiles are crossed underground; `hoodBefore`/`hoodAfter` mark the tile just before and
 *  just after an underground run, where the hood is drawn. */
export interface Piece { x: number; y: number; in: Dir; out: Dir; under: boolean; hoodBefore: boolean; hoodAfter: boolean;
  /** A shared tile of a trunk: where a line leaves it (split, same source) or joins it (merge, same target). */
  join?: "split" | "merge" }

export const inside = (r: Rect, x: number, y: number) => x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h;

/** The travel direction from tile (x, y) into the rectangle beside it, or null if it does not touch one side. */
export function dirInto(r: Rect, x: number, y: number): Dir | null {
  for (const d of DIRS) if (inside(r, x + STEP[d][0], y + STEP[d][1])) return d;
  return null;
}

/** The edge a junction piece's branch leaves by (split) or joins through (merge). */
export const joinEdge = (p: Piece): Dir => p.join === "merge" ? OPP[p.in] : p.out;
