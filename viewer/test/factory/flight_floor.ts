// A synthetic floor for the flight path tests: machines with one pad each and hubs (or doors), placed by tile, and no
// relations. Only what `flightPaths` and the flight checks read.
import type { TileFloor } from "../../src/factory/layout";
import type { Pad } from "../../src/factory/pads";
import type { Box } from "../../src/factory/tiles";

export type Spec = { id: string; x: number; y: number; to?: string; flight?: Pad["flight"]; pads?: number[] };

/** Machines are 5×5 with a pad on the bottom row at each of `pads` (tiles from the left; default the middle) and fly
 *  to `to`; hubs are 3×3, doors (an id starting `door:`) 7×3. `machineBoxes: false` leaves the machines' boxes off the
 *  floor (open floor everywhere but the hubs). */
export function flightFloor(machines: Spec[], hubs: Spec[], cols = 60, rows = 80, machineBoxes = true): TileFloor {
  const boxes = new Map<string, Box>();
  for (const h of hubs) {
    const door = h.id.startsWith("door:");
    boxes.set(h.id, { id: h.id, kind: "topic", foot: door ? "door" : "hub", region: "airfield", x: h.x, y: h.y, w: door ? 7 : 3, h: 3 });
  }
  if (machineBoxes) for (const m of machines) boxes.set(m.id, { id: m.id, kind: "service", foot: "service", region: "work", x: m.x, y: m.y, w: 5, h: 5 });
  const pads: Pad[] = machines.flatMap((m) => (m.pads ?? [2]).map((dx): Pad => {
    const flight = m.flight ?? "produce";
    return { machine: m.id, item: m.to!, topic: m.to!, role: flight === "produce" ? "produce" : "consume", flight, x: m.x + dx, y: m.y + 4, inside: true };
  }));
  return {
    boxes, lanes: [], zones: [], cols, rows, strategy: "layered", site: true,
    landing: { messaging: { airfields: [], producers: [], consumers: [], failures: [] }, pads, docks: [], stacks: [], unplaced: [] },
  } as unknown as TileFloor;
}
