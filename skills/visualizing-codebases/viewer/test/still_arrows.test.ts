// test/still_arrows.test.ts
// Still motion's arrows on a lit flight: heads at the flight's true angle, only on the open part of its path (never on a
// machine, hub or dock), one direction per flight (a pull its loaded leg), and no opposed heads side by side.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../src/model/model";
import type { CodeMap } from "../src/model/types";
import { planFloor } from "../src/factory/plan";
import { flightKeepOff, flightPaths } from "../src/factory/flights";
import { T } from "../src/factory/tiles";
import { arrowHead, flightArrows, stillFlightArrows } from "../src/floor/movers";

const close = (a: number, b: number) => expect(Math.abs(a - b)).toBeLessThan(1e-9);

/** A head's tip, the middle of its base, and its unit direction (base middle → tip). */
function shape(h: number[]) {
  const tip = { x: h[0], y: h[1] }, base = { x: (h[2] + h[4]) / 2, y: (h[3] + h[5]) / 2 };
  const len = Math.hypot(tip.x - base.x, tip.y - base.y);
  return { tip, base, len, dir: { x: (tip.x - base.x) / len, y: (tip.y - base.y) / len } };
}

describe("arrowHead", () => {
  it("a diagonal head is a symmetric triangle along the true direction", () => {
    const from = { x: 444, y: 181.5 }, to = { x: 108, y: 564 };   // push_pull's pull flight: steeper than 45°
    const h = arrowHead(from, to, 5);
    const { tip, base, len, dir } = shape(h);
    expect(tip).toEqual(to);
    close(len, 5);
    const L = Math.hypot(to.x - from.x, to.y - from.y);
    close(dir.x, (to.x - from.x) / L);
    close(dir.y, (to.y - from.y) / L);
    // the wings: equally far from the tip, each 3 px off the axis, at right angles to it
    const w1 = { x: h[2], y: h[3] }, w2 = { x: h[4], y: h[5] };
    close(Math.hypot(w1.x - tip.x, w1.y - tip.y), Math.hypot(w2.x - tip.x, w2.y - tip.y));
    close(Math.hypot(w1.x - base.x, w1.y - base.y), 3);
    close((w1.x - base.x) * dir.x + (w1.y - base.y) * dir.y, 0);
  });

  it("an axis-aligned head is the one belts and rails always had", () => {
    const old = (from: { x: number; y: number }, to: { x: number; y: number }, size: number) => {
      const dx = Math.sign(to.x - from.x), dy = Math.sign(to.y - from.y);
      const bx = to.x - dx * size, by = to.y - dy * size;
      return [to.x, to.y, bx - dy * size * 0.6, by + dx * size * 0.6, bx + dy * size * 0.6, by - dx * size * 0.6];
    };
    for (const [from, to] of [[{ x: 10, y: 5 }, { x: 11, y: 5 }], [{ x: 10, y: 5 }, { x: 9, y: 5 }], [{ x: 3, y: 8 }, { x: 3, y: 9 }], [{ x: 3, y: 8 }, { x: 3, y: 7 }]])
      expect(arrowHead(from, to, 5)).toEqual(old(from, to, 5));
  });
});

describe("push_pull F0: still flight arrows", () => {
  const m = new Model(JSON.parse(readFileSync(new URL("../guide/maps/push_pull.code-map.json", import.meta.url), "utf8")) as CodeMap);
  const { bundles, doors, layered } = m.bundles(SITE);
  const tf = planFloor(m, SITE, doors, bundles, layered).tf;
  const flights = flightPaths(tf), keepOff = flightKeepOff(tf);
  // the boxes drawn on the floor: machines and the hub (as painted, no shadow), and the receiving dock
  const boxes = [
    ...[...tf.boxes.entries()].map(([id, r]) => ({ id, x0: r.x * T, y0: r.y * T, x1: (r.x + r.w) * T, y1: (r.y + r.h) * T })),
    ...tf.landing!.docks.map((d) => ({ id: `dock:${d.machine}`, x0: d.x * T, y0: d.y * T, x1: (d.x + d.w) * T, y1: (d.y + d.h) * T })),
  ];

  it("has its produce, pull and push flights, each one straight segment (the pull's path does not double)", () => {
    expect(flights.map((f) => f.flight).sort()).toEqual(["produce", "pull", "push"]);
    for (const f of flights) expect(f.points).toHaveLength(2);
  });

  const drawn = stillFlightArrows(flights, keepOff);   // every flight lit, as Still motion draws them

  it("no still arrow point lies inside a machine, hub or dock box, and every flight keeps a head", () => {
    for (const [i, f] of flights.entries()) {
      const heads = drawn[i];
      expect(heads.length, `${f.flight} has arrows`).toBeGreaterThan(0);
      for (const h of heads) for (let k = 0; k < h.length; k += 2) {
        const x = h[k], y = h[k + 1];
        const inside = boxes.filter((b) => x >= b.x0 && x <= b.x1 && y >= b.y0 && y <= b.y1).map((b) => b.id);
        expect(inside, `${f.flight} head point (${x.toFixed(1)}, ${y.toFixed(1)})`).toEqual([]);
      }
    }
  });

  it("each flight shows one direction, on its line: the way its drone flies, and a pull its loaded leg (hub → consumer)", () => {
    for (const [i, f] of flights.entries()) {
      const [a, b] = f.points, L = Math.hypot(b.x - a.x, b.y - a.y);
      const way = f.flight === "pull" ? -1 : 1;   // a pull's points run pad → hub; its loaded leg flies back
      const u = { x: (way * (b.x - a.x)) / L, y: (way * (b.y - a.y)) / L };
      for (const h of drawn[i]) {
        const sh = shape(h);
        expect(sh.dir.x * u.x + sh.dir.y * u.y, `${f.flight} head along its flight`).toBeGreaterThan(0.999);
        // on the line: the tip's distance from the path is (all but) nil
        expect(Math.abs((sh.tip.x - a.x) * u.y - (sh.tip.y - a.y) * u.x), `${f.flight} head on the line`).toBeLessThan(1e-6);
        // slender: deeper than it is wide, so a slanted head still reads one way
        expect(Math.hypot(h[2] - h[4], h[3] - h[5])).toBeLessThan(sh.len);
      }
    }
  });

  it("no two heads within 8 px point opposite ways (produce into the hub and the push out of it nearly share a line)", () => {
    const all = drawn.flat().map(shape);
    for (let i = 0; i < all.length; i++) for (let j = i + 1; j < all.length; j++) {
      const p = all[i], q = all[j];
      if (Math.hypot(p.tip.x - q.tip.x, p.tip.y - q.tip.y) <= 8) expect(p.dir.x * q.dir.x + p.dir.y * q.dir.y).toBeGreaterThan(0);
    }
    // without the rule they would: the opposed pair is real, not a lucky miss
    const raw = flights.flatMap((f) => flightArrows(f, keepOff)).map(shape);
    expect(raw.some((p) => raw.some((q) => Math.hypot(p.tip.x - q.tip.x, p.tip.y - q.tip.y) <= 8 && p.dir.x * q.dir.x + p.dir.y * q.dir.y < 0))).toBe(true);
  });
});

describe("a still flight never goes headless", () => {
  it("two opposed flights with one head each both keep it", () => {
    // two 30 px flights on one line, opposite ways, each squeezed to a single head at the same middle
    const keepOff = [{ x0: -20, y0: -20, x1: 5, y1: 20 }, { x0: 25, y0: -20, x1: 50, y1: 20 }];
    const there = { flight: "produce" as const, points: [{ x: 0, y: 0 }, { x: 30, y: 0 }] };
    const back = { flight: "push" as const, points: [{ x: 30, y: 0 }, { x: 0, y: 0 }] };
    expect(flightArrows(there, keepOff)).toHaveLength(1);
    expect(flightArrows(back, keepOff)).toHaveLength(1);
    const [a, b] = stillFlightArrows([there, back], keepOff);
    expect([a.length, b.length]).toEqual([1, 1]);
    expect(shape(a[0]).dir.x).toBeGreaterThan(0.999);
    expect(shape(b[0]).dir.x).toBeLessThan(-0.999);
  });

  it("a flight too short for a clear stretch still gets one head", () => {
    // a 30 px flight between two boxes that leave no stretch long enough for a head
    const f = { flight: "produce" as const, points: [{ x: 0, y: 0 }, { x: 30, y: 0 }] };
    const keepOff = [{ x0: -20, y0: -20, x1: 5, y1: 20 }, { x0: 25, y0: -20, x1: 50, y1: 20 }];
    const heads = flightArrows(f, keepOff);
    expect(heads).toHaveLength(1);
    expect(shape(heads[0]).dir.x).toBeGreaterThan(0.999);
  });
});
