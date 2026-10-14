import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import shop from "./fixtures/shop.code-map.json";
import { Model, SITE } from "../src/model/model";
import type { CodeMap } from "../src/model/types";
import { planFloor } from "../src/factory/plan";
import { Clearance, floorObstacles, planZoneLabel, labelBox, type PxRect } from "../src/factory/clear";
import { clipInto, consumerTags, coveredKeys, dockSign, flightPaths, legendKinds, messagingLabels, messagingObstacles, replicaPulse, tagKey, type FlightPath, type Placed } from "../src/factory/flights";
import { padCentre, reservedRects } from "../src/factory/pads";
import { doorText, freeBand } from "../src/factory/machines";
import { T } from "../src/factory/tiles";
import type { Pt } from "../src/route/types";

const DEMO = new URL("../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const demo = () => new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);

/** Everything the scene builds before painting labels: the plan, flight paths, replaced routes, obstacles, zone names. */
function floor(model: Model, c: string) {
  const { bundles, doors } = model.bundles(c);
  const plan = planFloor(model, c, doors, bundles);
  const paths = flightPaths(plan.tf);
  const covered = coveredKeys(paths, bundles);
  const clear = new Clearance(messagingObstacles(plan.tf, plan.routes, paths, covered), plan.tf.cols + 8);
  const zoneBoxes = plan.tf.zones.map((z) => { const p = planZoneLabel({ ...z, name: z.name.toUpperCase() }, clear); return labelBox(p, p.maxK); });
  // the band the scene passes (it names machines by their short name; on these floors that is their label)
  const band = (id: string) => { const b = plan.tf.boxes.get(id); return b ? freeBand(b, model.label(id)) : undefined; };
  const labels = messagingLabels(model, plan.tf, paths, clear, band);
  return { ...plan, bundles, paths, covered, labels, zoneBoxes };
}

const box = (p: Placed): PxRect => ({ x0: p.x, y0: p.y, x1: p.x + p.w, y1: p.y + p.h });
const hit = (a: PxRect, b: PxRect) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
const within = (a: PxRect, b: PxRect) => a.x0 >= b.x0 && a.x1 <= b.x1 && a.y0 >= b.y0 && a.y1 <= b.y1;
/** Does segment a→b pass through the interior of `r`? (Liang–Barsky; touching an edge is not passing under.) */
function crosses(a: Pt, b: Pt, r: PxRect): boolean {
  const e = 0.5, q0 = { x0: r.x0 + e, y0: r.y0 + e, x1: r.x1 - e, y1: r.y1 - e };
  let t0 = 0, t1 = 1;
  const dx = b.x - a.x, dy = b.y - a.y;
  for (const [p, q] of [[-dx, a.x - q0.x0], [dx, q0.x1 - a.x], [-dy, a.y - q0.y0], [dy, q0.y1 - a.y]]) {
    if (p === 0) { if (q < 0) return false; continue; }
    const t = q / p;
    if (p < 0) { if (t > t1) return false; if (t > t0) t0 = t; } else { if (t < t0) return false; if (t < t1) t1 = t; }
  }
  return t1 - t0 > 1e-9;
}
/** Does segment a→b come within `pad` px of rect r (Liang–Barsky on the grown rect)? */
function segHits(a: Pt, b: Pt, r: PxRect, pad = 2): boolean {
  let t0 = 0, t1 = 1;
  const dx = b.x - a.x, dy = b.y - a.y;
  for (const [p, q] of [[-dx, a.x - (r.x0 - pad)], [dx, r.x1 + pad - a.x], [-dy, a.y - (r.y0 - pad)], [dy, r.y1 + pad - a.y]]) {
    if (p === 0) { if (q < 0) return false; continue; }
    const t = q / p;
    if (p < 0) { if (t > t1) return false; if (t > t0) t0 = t; } else { if (t < t0) return false; if (t < t1) t1 = t; }
  }
  return true;
}

describe("flight paths", () => {
  it("demo site: one path per pad and dock, pad to hub or hub to pad, and they replace every machine→hub drone route", () => {
    const f = floor(demo(), SITE);
    const land = f.tf.landing!;
    expect(f.paths).toHaveLength(land.pads.length + land.docks.length);
    expect(land.unplaced).toHaveLength(0);
    for (const p of f.paths) {
      expect(p.relations.length, p.key).toBeGreaterThan(0);
      const out = ["produce", "enqueue", "failure", "pull"].includes(p.flight);
      expect([p.points[0], p.points[p.points.length - 1]], p.key).toEqual(out ? [p.launch, p.hub] : [p.hub, p.launch]);
      expect(p.dead).toBe(p.flight === "failure");
      expect(f.routes.some((r) => r.key === p.key), `${p.key} rides a bundle`).toBe(true);
    }
    // every event bundle to a hub is drawn only as flight paths; no other route is touched
    const hubs = new Set(land.messaging.airfields.flatMap((a) => a.hubs.map((h) => h.item)));
    for (const r of f.routes) {
      const toHub = r.key.split("|").some((id) => hubs.has(id));
      if (r.kind === "drone" && toHub) expect(f.covered.has(r.key), r.key).toBe(true);
      if (r.kind !== "drone") expect(f.covered.has(r.key), r.key).toBe(false);
    }
    const flights = f.paths.map((p) => p.flight).sort();
    expect(flights).toEqual(expect.arrayContaining(["copy", "enqueue", "failure", "produce", "pull", "push", "take"]));
  });

  it("a bundle only partly carried by flights stays uncovered, and its flights keep their key", () => {
    const model = demo();
    const f = floor(model, SITE);
    const some = f.paths[0];
    const extra = f.bundles.map((b) => (b.key === some.key ? { ...b, relations: [...b.relations, { ...b.relations[0], id: "r:not-carried" }] } : b));
    const covered = coveredKeys(f.paths, extra);
    expect(covered.has(some.key)).toBe(false);
    expect(f.paths.filter((p) => p.key === some.key).length).toBeGreaterThan(0);   // drawn as its flights and its old route
    expect(covered.size).toBe(f.covered.size - 1);
  });

  it("a want with no pad keeps its old drone route", () => {
    const f = floor(demo(), SITE);
    const some = f.paths[0];
    const fewer = f.paths.filter((p) => p.key !== some.key);
    expect(coveredKeys(fewer, f.bundles).has(some.key)).toBe(false);
    expect(coveredKeys(f.paths, f.bundles).has(some.key)).toBe(true);
  });

  it("a floor with no hub has no paths and exactly the obstacles it had", () => {
    const model = new Model(shop as unknown as CodeMap);
    for (const c of Object.keys(model.map.layout.containers)) {
      const { bundles, doors } = model.bundles(c);
      const plan = planFloor(model, c, doors, bundles);
      if (plan.tf.landing) continue;
      const paths = flightPaths(plan.tf);
      expect(paths, c).toEqual([]);
      expect(messagingObstacles(plan.tf, plan.routes, paths, coveredKeys(paths, bundles)), c).toEqual(floorObstacles(plan.tf, plan.routes));
    }
  });
});

describe("flight paths fly straight", () => {
  // the owner (2026-10-06): a drone line crosses directly, over whatever is in its way (the toggle hides the paths)
  const check = (model: Model, name: string) => {
    let flights = 0;
    for (const c of Object.keys(model.map.layout.containers)) {
      const { bundles, doors } = model.bundles(c);
      const tf = planFloor(model, c, doors, bundles).tf;
      const land = tf.landing;
      for (const p of flightPaths(tf)) {
        flights++;
        const what = `${name} ${c} ${p.flight} ${p.key}`;
        expect(p.points, `${what}: one straight segment`).toHaveLength(2);
        // from the pad's mark inside its machine, or the dock's centre
        const pad = land!.pads.find((q) => !p.dock && q.machine === p.machine && q.item === p.item && q.role === p.role && q.group === p.group);
        const dock = land!.docks.find((d) => p.dock && d.machine === p.machine && d.item === p.item && d.group === p.group);
        expect(p.launch, `${what}: launches from its pad or dock`).toEqual(pad ? padCentre(pad) : { x: (dock!.x + dock!.w / 2) * T, y: (dock!.y + dock!.h / 2) * T });
        const hub = tf.boxes.get(p.item)!, centre = { x: (hub.x + hub.w / 2) * T, y: (hub.y + hub.h / 2) * T };
        // to the hub's centre, or on the line to it, cut at a door's edge
        if (hub.foot !== "door") expect(p.hub, what).toEqual(centre);
        else expect(Math.abs((p.hub.x - p.launch.x) * (centre.y - p.launch.y) - (p.hub.y - p.launch.y) * (centre.x - p.launch.x)), `${what}: on the line to the door's centre`).toBeLessThan(1e-6);
      }
    }
    return flights;
  };
  it("demo: every flight is one straight segment from its pad or dock to its hub", () => { expect(check(demo(), "demo")).toBe(38); });
  it("fixture: the same", () => { expect(check(new Model(shop as unknown as CodeMap), "fixture")).toBeGreaterThan(0); });
});

describe("plates, tags and dock signs", () => {
  it("demo floor 0: no plate, tag or sign overlaps a line, a machine, a pad, a zone name or another label", () => {
    const demoModel = demo();
    const f = floor(demoModel, SITE);
    const all = [...f.labels.tags, ...f.labels.signs, ...f.labels.plates];
    expect(f.labels.plates.length, "most flights find room for their plate").toBeGreaterThanOrEqual(Math.ceil(f.paths.length * 0.75));
    const machines = [...f.tf.boxes.values()].map((b) => ({ id: b.id, x0: b.x * T, y0: b.y * T - (b.foot === "door" ? 0 : 20), x1: (b.x + b.w) * T + 5, y1: (b.y + b.h) * T + 5 }));
    const reserved = reservedRects(f.tf).map((r) => ({ x0: r.x * T, y0: r.y * T, x1: (r.x + r.w) * T, y1: (r.y + r.h) * T }));
    const tiles = f.routes.flatMap((r) => r.pieces).map((p) => ({ x0: p.x * T, y0: p.y * T, x1: (p.x + 1) * T, y1: (p.y + 1) * T }));
    const lines: [Pt, Pt, string][] = [
      ...f.paths.flatMap((p: FlightPath) => p.points.slice(1).map((q, i) => [p.points[i], q, p.dock ? p.key : ""] as [Pt, Pt, string])),
      ...f.routes.filter((r) => !r.pieces.length && !f.covered.has(r.key)).flatMap((r) => r.points.slice(1).map((q, i) => [r.points[i], q, ""] as [Pt, Pt, string])),
    ];
    for (const [i, l] of all.entries()) {
      const b = box(l), what = `${l.text} (${l.key})`;
      expect(b.x0 >= 0 && b.y0 >= 0 && b.x1 <= f.tf.cols * T && b.y1 <= f.tf.rows * T, `${what} on the floor`).toBe(true);
      // a tag inside its own machine sits in that machine's free band, under the name and over the sub line
      const tag = f.labels.tags.find((t) => t === l);
      const home = tag?.inside ? tag.machine : undefined;
      if (home) expect(within(b, freeBand(f.tf.boxes.get(home)!, demoModel.label(home))!), `${what} inside its band`).toBe(true);
      for (const m of machines) if (m.id !== home) expect(hit(b, m), `${what} over a machine`).toBe(false);
      // a dock sign with no room round it stands on its own dock
      const own = f.labels.signs.includes(l) && reserved.some((r) => within(b, r));
      for (const r of reserved) if (!(own && within(b, r))) expect(hit(b, r), `${what} over a pad, dock or stack`).toBe(false);
      for (const t of tiles) expect(hit(b, t), `${what} over a line tile`).toBe(false);
      // a sign standing on its own dock is over the end of the dock's flight, which the dock covers
      for (const [a, c, dockKey] of lines) if (!(own && dockKey === l.key)) expect(segHits(a, c, b), `${what} on a flight path`).toBe(false);
      for (const z of f.zoneBoxes) expect(hit(b, z), `${what} over a zone name`).toBe(false);
      for (const o of all.slice(i + 1)) expect(hit(b, box(o)), `${what} over ${o.text}`).toBe(false);
    }
  });

  it("demo floor 0 draws no consumer tags (too detailed for the overview); its push dock's sign says push; plates say the flight", () => {
    const model = demo();
    const f = floor(model, SITE);
    expect(consumerTags(f.tf)).toEqual([]);
    expect(f.labels.tags).toEqual([]);
    expect(legendKinds(f.tf, f.paths)?.replicas).toBeUndefined();
    expect(f.labels.signs.map((s) => s.text)).toEqual(["push"]);
    for (const p of f.labels.plates) expect(p.text).toBe({ failure: "on failure" }[f.paths[p.of!].flight as string] ?? f.paths[p.of!].flight);
  });

  it("inner floors: tags say the group and the replicas, sized for the take's pulse; the legend has a replicas entry only where a tag is drawn", () => {
    const model = demo();
    const tagOn = (c: string) => { const f = floor(model, c); return { f, t: consumerTags(f.tf) }; };
    const worker = tagOn("enforcement_worker/app::app.main"), notifier = tagOn("notifier/app::app.main"), billing = tagOn("svc:billing");
    expect(worker.t.map((t) => [t.text, t.wide])).toEqual([["3 replicas", "replica 3 of 3"]]);
    expect(notifier.t.map((t) => [t.text, t.wide])).toEqual([["group notifier · 2 replicas", "group notifier · 2 replicas"]]);   // a copy: no pulse
    expect(billing.t.map((t) => t.text)).toEqual(["group billing"]);
    expect(replicaPulse("3 replicas", 1, 3)).toBe("replica 1 of 3");
    expect(replicaPulse("group workers · 2 replicas", 2, 2)).toBe("group workers · replica 2 of 2");
    // the placed tag's box holds the longer text
    const placed = worker.f.labels.tags[0];
    expect(placed.text).toBe("3 replicas");
    expect(placed.w).toBeGreaterThanOrEqual(Math.ceil("replica 3 of 3".length * 10.5 * 0.56) + 8);
    const wm = worker.t[0].machine;
    expect(legendKinds(worker.f.tf, worker.f.paths)?.replicas).toBe(true);
    expect(legendKinds(billing.f.tf, billing.f.paths)?.replicas).toBeUndefined();
  });

  it("a tag with no room round its machine goes into the machine's free band", () => {
    const model = demo();
    const c = "enforcement_worker/app::app.main";
    const { bundles, doors } = model.bundles(c);
    const plan = planFloor(model, c, doors, bundles);
    const paths = flightPaths(plan.tf);
    const clear = new Clearance(messagingObstacles(plan.tf, plan.routes, paths, coveredKeys(paths, bundles)), plan.tf.cols + 8);
    const [t0] = consumerTags(plan.tf), b = plan.tf.boxes.get(t0.machine)!;
    const r = { x0: b.x * T, y0: b.y * T, x1: (b.x + b.w) * T, y1: (b.y + b.h) * T }, W = plan.tf.cols * T, H = plan.tf.rows * T;
    // fill every spot under and beside the machine
    for (const o of [{ x0: 0, y0: r.y1, x1: W, y1: H }, { x0: 0, y0: 0, x1: r.x0, y1: H }, { x0: r.x1, y0: 0, x1: W, y1: H }]) clear.add(o);
    const band = () => ({ x0: r.x0 + 5, y0: r.y0 + 22, x1: r.x1 - 5, y1: r.y0 + 40 });
    const { tags } = messagingLabels(model, plan.tf, paths, clear, band);
    expect(tags).toHaveLength(1);
    expect(tags[0].inside).toBe(true);
    expect(within(box(tags[0]), band()), "inside its band").toBe(true);
  });

  it("deterministic", () => {
    const a = floor(demo(), SITE), b = floor(demo(), SITE);
    expect(a.labels).toEqual(b.labels);
    expect(a.paths).toEqual(b.paths);
  });

  it("a dock's sign names the endpoint when the relation key or a request into the handler gives its path", () => {
    const model = demo();
    const push = model.map.relations.find((r) => r.subscription === "push")!;
    expect(dockSign(model, [push.id])).toBe("push");
    const keyed = { ...push, id: "r:keyed", key: "/pubsub/bay-status" };
    const viaRequest = { id: "r:req", kind: "request" as const, from: "x", to: push.to, key: "POST /pubsub/bay-status", confidence: "confirmed" as const };
    const m2 = new Model({ ...model.map, relations: [...model.map.relations, keyed] } as CodeMap);
    expect(dockSign(m2, ["r:keyed"])).toBe("POST /pubsub/bay-status");
    const m3 = new Model({ ...model.map, relations: [...model.map.relations, viaRequest] } as CodeMap);
    expect(dockSign(m3, [push.id])).toBe("POST /pubsub/bay-status");
  });
});

describe("flights to a door keep off door names", () => {
  const px = (r: { x: number; y: number; w: number; h: number }): PxRect => ({ x0: r.x * T, y0: r.y * T, x1: (r.x + r.w) * T, y1: (r.y + r.h) * T });
  /** Every inner floor with a topic door: no segment of any flight path enters any door's name band, and a flight to a
   *  door ends on the door's edge (where the drone lands), never inside it. */
  const check = (model: Model, name: string) => {
    let floors = 0, toDoors = 0;
    for (const c of Object.keys(model.map.layout.containers)) {
      if (c === SITE) continue;
      const { bundles, doors } = model.bundles(c);
      const tf = planFloor(model, c, doors, bundles).tf;
      const topicDoors = doors.filter((d) => model.kindOf(d.anchor) === "topic" && tf.boxes.has(d.id));
      if (!topicDoors.length) continue;
      floors++;
      const bands = doors.filter((d) => tf.boxes.has(d.id)).map((d) => {
        const b = tf.boxes.get(d.id)!;
        return [d.id, doorText({ x: b.x * T, y: b.y * T, w: b.w * T, h: b.h * T }, d.side).band] as const;
      });
      for (const p of flightPaths(tf)) {
        for (let i = 1; i < p.points.length; i++) for (const [id, band] of bands)
          expect(crosses(p.points[i - 1], p.points[i], band), `${name} ${c} ${p.flight} ${p.key} runs under ${id}'s name`).toBe(false);
        const hub = tf.boxes.get(p.item)!;
        if (hub.foot !== "door") continue;
        toDoors++;
        const r = px(hub), end = p.outbound ? p.points[p.points.length - 1] : p.points[0];
        expect(end, `${name} ${c} ${p.key} ends where it meets the door`).toEqual(p.hub);
        const onEdge = (Math.abs(end.x - r.x0) < 1e-6 || Math.abs(end.x - r.x1) < 1e-6) && end.y >= r.y0 && end.y <= r.y1
          || (Math.abs(end.y - r.y0) < 1e-6 || Math.abs(end.y - r.y1) < 1e-6) && end.x >= r.x0 && end.x <= r.x1;
        expect(onEdge, `${name} ${c} ${p.key} ends on the door's edge (${end.x}, ${end.y})`).toBe(true);
      }
    }
    return { floors, toDoors };
  };
  it("demo", () => {
    const r = check(demo(), "demo");
    expect(r.floors).toBeGreaterThan(0);
    expect(r.toDoors).toBeGreaterThan(0);
  });
  it("fixture", () => { check(new Model(shop as unknown as CodeMap), "fixture"); });
  it("clipInto cuts a path where it first reaches the box, and leaves one that never does", () => {
    const r = { x0: 100, y0: 100, x1: 200, y1: 160 };
    expect(clipInto([{ x: 0, y: 130 }, { x: 150, y: 130 }], r)).toEqual([{ x: 0, y: 130 }, { x: 100, y: 130 }]);
    expect(clipInto([{ x: 150, y: 0 }, { x: 150, y: 50 }, { x: 150, y: 130 }], r)).toEqual([{ x: 150, y: 0 }, { x: 150, y: 50 }, { x: 150, y: 100 }]);
    expect(clipInto([{ x: 0, y: 0 }, { x: 150, y: 130 }], r)).toEqual([{ x: 0, y: 0 }, { x: 150 * (100 / 130), y: 100 }]);
    expect(clipInto([{ x: 0, y: 0 }, { x: 50, y: 0 }], r)).toEqual([{ x: 0, y: 0 }, { x: 50, y: 0 }]);
  });
});

describe("consumer tag keys", () => {
  it("a machine taking one hub in two groups wears two tags with their own keys", () => {
    const map = JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap;
    const rel = map.relations.find((r) => r.group === "notifier")!;
    map.relations.push({ ...rel, id: `${rel.id}:audit`, group: "audit" });
    const model = new Model(map);
    const c = "notifier/app::app.main";   // tags are drawn on the consumer's own floor, not on the site
    const { bundles, doors } = model.bundles(c);
    const tf = planFloor(model, c, doors, bundles).tf;
    const tags = consumerTags(tf);
    expect(tags.map((t) => t.text).sort()).toEqual(["group audit · 2 replicas", "group notifier · 2 replicas"]);
    expect(new Set(tags.map((t) => t.key)).size).toBe(2);   // keyed alike, one would replace the other
    // each copy flight finds its own group's tag, as the movers look it up
    const flights = flightPaths(tf).filter((f) => f.group);
    expect(flights.map((f) => f.group).sort()).toEqual(["audit", "notifier"]);
    for (const f of flights) expect(tags.find((t) => t.key === tagKey(f.machine, f.item, f.group))?.text).toBe(`group ${f.group} · 2 replicas`);
  });
});
