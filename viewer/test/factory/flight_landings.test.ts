// Flight paths that would run on top of each other into one hub land apart on its edge (flights.ts `spreadLandings`);
// every other path keeps its landing, the hub's centre or a door's edge.
import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor } from "../../src/factory/plan";
import { clipInto, flightPaths, keepOffBoxes, LANDING_GAP, OVERLAP_RUN, runTogether, visiblePart, type FlightPath } from "../../src/factory/flights";
import { T } from "../../src/factory/tiles";
import { flightFloor } from "./flight_floor";

const HUB = { id: "topic:q", x: 20, y: 60 };              // a 3×3 hub: px 480..552 × 1440..1512, centre (516, 1476)
const CENTRE = { x: 516, y: 1476 };
const hubPx = { x0: 480, y0: 1440, x1: 552, y1: 1512 };
/** Machines straight above the hub, one under the other: their pads line up with the hub's centre (x 516). */
const column = (n: number, to = HUB.id) => Array.from({ length: n }, (_, i) => ({ id: `svc:m${i}`, x: 19, y: 2 + i * 7, to }));
/** Eight pads on two machines side by side, a tile apart, far above a hub centred under them: each runs on top of its
 *  neighbour, so they are one group, more than the hub's edge holds, and none is in line with another. */
const FAN_HUB = { id: "topic:q", x: 17, y: 60 };          // centre x 444
const fan = [{ id: "svc:a", x: 14, y: 2, to: FAN_HUB.id, pads: [0, 1, 2, 3] }, { id: "svc:b", x: 19, y: 2, to: FAN_HUB.id, pads: [0, 1, 2, 3] }];
const dist = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);

describe("flight landings", () => {
  it("two paths in line with the hub land apart on its top edge, at least the gap apart, spread wide enough to part on open floor", () => {
    const tf = flightFloor(column(2), [HUB]);
    const [a, b] = flightPaths(tf);
    for (const p of [a, b]) {
      expect(p.hub.y).toBe(hubPx.y0);
      expect(p.hub.x).toBeGreaterThanOrEqual(hubPx.x0);
      expect(p.hub.x).toBeLessThanOrEqual(hubPx.x1);
      expect(p.points).toEqual([p.launch, p.hub]);   // still one straight segment, pad → hub
    }
    expect(dist(a.hub, b.hub)).toBeGreaterThanOrEqual(LANDING_GAP);
    // to the centre they run on top of each other below the near machine; spread, they part there (under the near
    // machine the far path is hidden, which flights.hidden reports)
    const faces = keepOffBoxes(tf, 0).map((x) => x.r);
    expect(runTogether(visiblePart({ ...a, hub: CENTRE }, hubPx), visiblePart({ ...b, hub: CENTRE }, hubPx), faces)).toBeGreaterThan(1000);
    expect(runTogether(visiblePart(a, hubPx), visiblePart(b, hubPx), faces)).toBeLessThan(OVERLAP_RUN);
    // wider than the least gap: at 12 px apart they would still run together below the near machine
    expect(dist(a.hub, b.hub)).toBeGreaterThan(LANDING_GAP);
  });

  it("paths in line with the hub: the nearest pad takes the middle point, the farthest the outermost, and no two paths cross", () => {
    const paths = flightPaths(flightFloor(column(3), [HUB]));
    const [far, mid, near] = paths;   // m0 is the farthest from the hub, m2 the nearest
    const anchor = near.launch.x;
    expect(Math.abs(near.hub.x - anchor)).toBeLessThan(Math.abs(mid.hub.x - anchor));
    expect(Math.abs(mid.hub.x - anchor)).toBeLessThanOrEqual(Math.abs(far.hub.x - anchor));
    const cross = (p: FlightPath, q: FlightPath) => {
      const [a, b] = p.points, [c, d] = q.points;
      const s = (o: { x: number; y: number }, u: { x: number; y: number }, v: { x: number; y: number }) => Math.sign((u.x - o.x) * (v.y - o.y) - (u.y - o.y) * (v.x - o.x));
      return s(a, b, c) * s(a, b, d) < 0 && s(c, d, a) * s(c, d, b) < 0;
    };
    for (let i = 0; i < 3; i++) for (let j = i + 1; j < 3; j++) expect(cross(paths[i], paths[j]), `${i}×${j}`).toBe(false);
  });

  it("near-parallel paths land in the order they come in, so they do not cross near the hub", () => {
    // the right-hand pad's path comes in right of the other's: it lands right of it
    const tf = flightFloor([{ id: "svc:a", x: 19, y: 2, to: HUB.id }, { id: "svc:b", x: 20, y: 30, to: HUB.id }], [HUB]);
    const [a, b] = flightPaths(tf);
    expect(runTogether([a.launch, CENTRE], [b.launch, CENTRE])).toBeGreaterThanOrEqual(OVERLAP_RUN);
    expect(b.launch.x).toBeGreaterThan(a.launch.x);
    expect(b.hub.x).toBeGreaterThan(a.hub.x);
    expect(runTogether(visiblePart(a, hubPx), visiblePart(b, hubPx))).toBeLessThan(OVERLAP_RUN);
  });

  it("paths from clearly different directions keep the hub's centre", () => {
    const tf = flightFloor([{ id: "svc:n", x: 19, y: 40, to: HUB.id }, { id: "svc:w", x: 2, y: 58, to: HUB.id },
      { id: "svc:e", x: 40, y: 58, to: HUB.id }, { id: "svc:ne", x: 34, y: 44, to: HUB.id }], [HUB]);
    const paths = flightPaths(tf);
    expect(paths).toHaveLength(4);
    for (const p of paths) expect(p.hub, p.machine).toEqual(CENTRE);
  });

  it("a group too big for the edge at the gap shares landing points, in order; no path is lost", () => {
    const paths = flightPaths(flightFloor(fan, [FAN_HUB]));
    expect(paths).toHaveLength(8);
    expect(paths.map((p) => p.launch.x)).toEqual([348, 372, 396, 420, 468, 492, 516, 540]);
    const xs = paths.map((p) => p.hub.x), slots = [...new Set(xs)].sort((a, b) => a - b);
    // a 72 px edge less 6 px at each corner holds 6 points 12 px apart; the 8 paths share them, left to right
    expect(slots).toHaveLength(Math.floor((3 * T - 12) / LANDING_GAP) + 1);
    for (let i = 1; i < slots.length; i++) expect(slots[i] - slots[i - 1]).toBeCloseTo(LANDING_GAP, 6);
    expect(xs).toEqual([...xs].sort((a, b) => a - b));
    for (const p of paths) expect(p.hub.y).toBe(FAN_HUB.y * T);
  });

  it("a door hub: paths stop at its edge, and collinear ones land apart along that edge", () => {
    const door = { id: "door:topic:q", x: 18, y: 60 };     // 7×3: px 432..600 × 1440..1512, centre x 516
    const one = flightPaths(flightFloor(column(1, door.id), [door]));
    expect(one[0].hub).toEqual({ x: 516, y: 1440 });        // alone: where its line first reaches the door
    const [a, b] = flightPaths(flightFloor(column(2, door.id), [door]));
    for (const p of [a, b]) {
      expect(p.hub.y).toBe(1440);
      expect(p.hub.x).toBeGreaterThanOrEqual(432);
      expect(p.hub.x).toBeLessThanOrEqual(600);
    }
    expect(dist(a.hub, b.hub)).toBeGreaterThanOrEqual(LANDING_GAP);
  });

  it("is deterministic, whatever order the pads come in", () => {
    const specs = [...column(3), { id: "svc:w", x: 2, y: 58, to: HUB.id }, { id: "svc:n", x: 20, y: 30, to: HUB.id }];
    const landed = (ss: typeof specs) => Object.fromEntries(flightPaths(flightFloor(ss, [HUB])).map((p) => [p.machine, p.hub]));
    const once = landed(specs);
    expect(landed(specs)).toEqual(once);
    expect(landed([...specs].reverse())).toEqual(once);
    expect(landed([specs[2], specs[4], specs[0], specs[3], specs[1]])).toEqual(once);
  });

  it("a moved path that then runs on another path of the hub: the groups merge and are spread again", () => {
    // on open floor (no machine boxes): m0 and m1 run together into the hub; m2 runs on neither of them while they
    // land at the centre, but does once they are spread
    const specs = [{ id: "svc:m0", x: 18, y: 2, to: HUB.id }, { id: "svc:m1", x: 19, y: 2, to: HUB.id }, { id: "svc:m2", x: 15, y: 4, to: HUB.id }];
    const lands = (ss: typeof specs) => flightPaths(flightFloor(ss, [HUB], 60, 80, false)).map((p) => p.hub);
    expect(lands([specs[0], specs[2]])).toEqual([CENTRE, CENTRE]);
    expect(lands([specs[1], specs[2]])).toEqual([CENTRE, CENTRE]);
    const all = lands(specs);
    for (const h of all) expect(h.y).toBe(hubPx.y0);
    const xs = all.map((h) => h.x).sort((a, b) => a - b);
    for (let i = 1; i < xs.length; i++) expect(xs[i] - xs[i - 1]).toBeGreaterThanOrEqual(LANDING_GAP - 1e-9);
  });

  it("on the committed maps, only the push and pull page's site moves a landing: every other path keeps its hub's centre or its door's edge", () => {
    const root = new URL("../../../", import.meta.url);
    const maps: [string, URL][] = [["demo", new URL("demo/parking-city/docs/viz-code/code-map.json", root)],
      ["shop", new URL("viewer/test/fixtures/shop.code-map.json", root)],
      ...readdirSync(new URL("viewer/guide/maps/", root)).filter((f) => f.endsWith(".code-map.json")).sort()
        .map((f): [string, URL] => [f.replace(".code-map.json", ""), new URL(`viewer/guide/maps/${f}`, root)])];
    const moved: string[] = [];
    for (const [name, url] of maps) {
      const model = new Model(JSON.parse(readFileSync(url, "utf8")) as CodeMap);
      for (const c of Object.keys(model.map.layout.containers)) {
        if (!Object.keys(model.map.layout.containers[c].items ?? {}).length) continue;
        const { bundles, doors } = model.bundles(c);
        const { tf } = planFloor(model, c, doors, bundles);
        for (const p of flightPaths(tf)) {
          const b = tf.boxes.get(p.item)!, r = { x0: b.x * T, y0: b.y * T, x1: (b.x + b.w) * T, y1: (b.y + b.h) * T };
          const plain = [p.launch, { x: (r.x0 + r.x1) / 2, y: (r.y0 + r.y1) / 2 }];
          const end = (b.foot === "door" ? clipInto(plain, r) : plain).at(-1)!;
          if (end.x !== p.hub.x || end.y !== p.hub.y) moved.push(`${name} ${c}: ${p.flight} ${p.key}`);
        }
      }
    }
    expect(moved).toEqual(["push_pull site: produce svc:orders|topic:events:order-events", "push_pull site: push svc:billing|topic:events:order-events"]);
  });
});
