// Painting rails (spec §6), the pure part: where yard parts, sign texts and station labels go, the rail inside a yard
// and through a station, train paths, hover lists, the rail junction op, and the keys selection uses.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import shop from "../fixtures/shop.code-map.json";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import type { TileFloor } from "../../src/factory/layout";
import { layFloor, planFloor } from "../../src/factory/plan";
import { routeTiles } from "../../src/factory/router";
import { checkRails } from "./factory_trunks";
import { Clearance, floorObstacles, labelBox, planZoneLabel, type PxRect } from "../../src/factory/clear";
import { coveredKeys, flightPaths, messagingLabels, messagingObstacles, pathRects } from "../../src/factory/flights";
import {
  boxSize, expandKeys, jobLine, lineEnds, platformList, railLabels, railLegend, railLine, railTracks, shortCode, signLines, signList,
  trainPaths, yardKey, yardLink, yardParts,
} from "../../src/factory/rail-place";
import { factoryOps } from "../../src/factory/pieces";
import { exitOf, exits, rails, RUN } from "../../src/factory/yards";
import { inside, STEP, T, type Piece } from "../../src/factory/tiles";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
const plan = (m: Model, c: string) => { const { bundles, doors } = m.bundles(c); return { ...planFloor(m, c, doors, bundles), bundles }; };
const hit = (a: PxRect, b: PxRect) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
const tile = (p: { x: number; y: number }): PxRect => ({ x0: p.x * T, y0: p.y * T, x1: (p.x + 1) * T, y1: (p.y + 1) * T });
const box = (p: { x: number; y: number; w: number; h: number }): PxRect => ({ x0: p.x, y0: p.y, x1: p.x + p.w, y1: p.y + p.h });

/** The floor's labels as the scene places them, in its order: zone names, messaging labels, then the rails'. */
function labelled(c: string) {
  const p = plan(demo, c);
  const flights = flightPaths(p.tf), covered = coveredKeys(flights, p.bundles);
  const clear = new Clearance(messagingObstacles(p.tf, p.routes, flights, covered), p.tf.cols + 8);
  const zones = p.tf.zones.map((z) => { const q = planZoneLabel({ ...z, name: z.name.toUpperCase() }, clear); return labelBox(q, q.maxK); });
  const msg = p.tf.landing ? messagingLabels(demo, p.tf, flights, clear) : { tags: [], signs: [], plates: [] };
  const rail = railLabels(demo, c, p.tf, clear);
  // line tiles (routes, yard links, sidings) and the flights' dotted paths (drones fly over yards: only labels avoid them)
  const tiles: PxRect[] = [
    ...p.routes.filter((r) => !covered.has(r.key)).flatMap((r) => r.pieces.map(tile)),
    ...railTracks(p.tf, p.routes).flatMap((t) => [...t.link, ...t.siding].map(tile)),
  ];
  const lines = [...tiles, ...flights.flatMap((f) => pathRects(f.points))];
  return { p, zones, msg, rail, lines, tiles };
}

describe("rail paint placement (demo)", () => {
  for (const c of [SITE, "svc:nightly-jobs", "jobs/dags::dags/"]) it(`${c}: the sign texts, station labels and yard words overlap no line, machine or other label`, () => {
    const { p, zones, msg, rail, lines, tiles } = labelled(c);
    const r = p.tf.rails!;
    const machines = floorObstacles(p.tf, []);   // machines with their roofs and shadows, lanes, yards, stations, signs
    const others = [...zones, ...[...msg.tags, ...msg.signs, ...msg.plates].map(box)];
    const placed = [...rail.signs, ...rail.stations].map(box);
    placed.forEach((b, i) => {
      for (const o of [...lines, ...machines, ...others]) expect(hit(b, o), `${c} rail label ${JSON.stringify(b)} on ${JSON.stringify(o)}`).toBe(false);
      placed.forEach((q, j) => { if (i !== j) expect(hit(b, q), `${c} rail labels ${i} and ${j}`).toBe(false); });
    });
    // inside each yard: the platform strips and a parked train's strip take no tile a rail runs on, and touch no other machine
    for (const y of r.yards) {
      const parts = yardParts(y), own: PxRect = { x0: y.x * T, y0: y.y * T, x1: (y.x + y.w) * T, y1: (y.y + y.h) * T };
      for (const b of [...parts.strips.map((s) => s.r), ...(parts.parked ? [parts.parked] : [])]) {
        expect(b.x0 >= own.x0 && b.x1 <= own.x1 && b.y0 >= own.y0 && b.y1 <= own.y1, `${c} ${y.source} part inside its yard`).toBe(true);
        for (const l of tiles) expect(hit(b, { x0: l.x0 + 1, y0: l.y0 + 1, x1: l.x1 - 1, y1: l.y1 - 1 }), `${c} ${y.source} part ${JSON.stringify(b)} on a rail tile ${JSON.stringify(l)}`).toBe(false);
        for (const m of p.tf.boxes.values()) expect(hit(b, { x0: m.x * T, y0: m.y * T, x1: (m.x + m.w) * T, y1: (m.y + m.h) * T }), `${c} part on ${m.id}`).toBe(false);
        for (const q of placed) expect(hit(b, q)).toBe(false);
      }
      expect(parts.strips.map((s) => s.dest)).toEqual(y.platforms.map((q) => q.dest));
    }
  });

  it("F0: two signs carry their summary beside the clock, on two lines where one does not fit; feature-store's shows on hover only", () => {
    const { rail } = labelled(SITE);
    expect(rail.signs.map((s) => [s.source, s.text])).toEqual([
      ["svc:demand-forecast", "2 jobs · 1×/day\n+ on demand"],
      ["svc:nightly-jobs", "10 jobs\n149×/day"],
    ]);
    expect(rail.stations, "F0's one station comes from one place: no source label").toEqual([]);
    // the features floor: feature-store's yard and demand-forecast's door both feed workflows.py: each station is labelled
    expect(labelled("features::features/").rail.stations.map((s) => s.text).sort()).toEqual(["S4", "S6"]);
    expect(labelled("jobs/dags::dags/").rail.stations).toEqual([]);   // ten stations, all from the one yard
    expect(signLines("daily 01:00")).toEqual(["daily\n01:00"]);
    expect(boxSize("10 jobs\n149×/day").h).toBeGreaterThan(boxSize("10 jobs").h);
  });

  it("every rail runs from its platform through the yard, along its route and through its station to the buffer stop", () => {
    for (const c of [SITE, "svc:nightly-jobs", "jobs/dags::dags/", "svc:demand-forecast", "features::features/", "features::features.workflows", "svc:feature-store"]) {
      const p = plan(demo, c), r = p.tf.rails!;
      const paths = trainPaths(p.tf, p.routes), tracks = railTracks(p.tf, p.routes);
      expect(paths.length, c).toBe(r.stations.length);
      for (const t of tracks.filter((q) => q.yard)) {
        const y = t.yard!, path = paths.find((q) => q.key === t.key)!;
        expect(t.link[0], `${c} ${t.key} starts on its own platform`).toMatchObject({ x: y.platforms[t.index].x, y: y.platforms[t.index].y });
        for (const q of t.link) expect(inside(y, q.x, q.y), `${c} ${t.key} link inside the yard`).toBe(true);
        const last = t.link[t.link.length - 1], first = t.route!.pieces[0];
        expect([last.x + STEP[last.out][0], last.y + STEP[last.out][1]], `${c} ${t.key} link meets the route`).toEqual([first.x, first.y]);
        for (const q of t.siding) expect(inside(t.station, q.x, q.y), `${c} ${t.key} siding inside its station`).toBe(true);
        const end = t.route!.pieces[t.route!.pieces.length - 1];
        expect([end.x + STEP[end.out][0], end.y + STEP[end.out][1]]).toEqual([t.siding[0].x, t.siding[0].y]);
        // the path is one orthogonal polyline, platform strip to buffer stop
        for (let i = 1; i < path.points.length; i++) {
          const a = path.points[i - 1], b = path.points[i];
          expect(a.x === b.x || a.y === b.y, `${c} ${t.key} orthogonal`).toBe(true);
        }
        expect(path).toMatchObject({ platform: `platform:${y.source}>${t.station.dest}`, station: `station:${y.source}>${t.station.dest}` });
      }
      // a yard-less rail (scheduler off the floor): no link, its train starts at the door's edge and ends at its buffer
      for (const t of tracks.filter((q) => q.door)) {
        const path = paths.find((q) => q.key === t.key)!, door = p.tf.boxes.get(t.door!)!, a = path.points[0];
        expect(t.link, `${c} ${t.key}`).toEqual([]);
        expect(a.x >= door.x * T && a.x <= (door.x + door.w) * T && a.y >= door.y * T && a.y <= (door.y + door.h) * T, `${c} ${t.key} starts at its door`).toBe(true);
        expect([path.source, path.runsPerDay]).toEqual([t.door, null]);   // the reference task: on demand
      }
      expect(r.unplaced, `${c} no yard link cut short`).toEqual([]);
    }
  });

  it("a rider leaves past another platform: its link runs along the yard's row ends to that exit; on a ladder, along its throat", () => {
    expect(yardLink({ source: "s", machine: null, x: 0, y: 0, w: 4, h: 2, side: "e", out: "e", platforms: [{ dest: "a", x: 3, y: 0 }, { dest: "b", x: 3, y: 1 }], sign: null }, 1, { x: 4, y: 0, in: "e", out: "e", under: false, hoodBefore: false, hoodAfter: false })
      .map((q) => [q.x, q.y, q.in, q.out])).toEqual([[3, 1, "e", "n"], [3, 0, "n", "e"]]);
    // a yard against an n or s side leaves by a row's west end too
    expect(yardLink({ source: "s", machine: "m", x: 5, y: 0, w: 4, h: 2, side: "n", out: "w", platforms: [{ dest: "a", x: 5, y: 0 }, { dest: "b", x: 5, y: 1 }], sign: null }, 1)
      .map((q) => [q.x, q.y, q.in, q.out])).toEqual([[5, 1, "w", "w"]]);
    // a ladder: straight off the platform tile into the throat, one switch, along the throat, out at the exit row
    const ladder = { source: "s", machine: null, x: 0, y: 0, w: 5, h: 3, side: "e" as const, out: "e" as const, platforms: [{ dest: "a", x: 3, y: 0 }, { dest: "b", x: 3, y: 1 }, { dest: "c", x: 3, y: 2 }], sign: null, ladder: [2, 2, 2] };
    expect(exits(ladder)).toEqual([{ x: 5, y: 2, d: "e" }]);
    expect(yardLink(ladder, 0, { x: 5, y: 2, in: "e", out: "e", under: false, hoodBefore: false, hoodAfter: false }).map((q) => [q.x, q.y, q.in, q.out]))
      .toEqual([[3, 0, "e", "e"], [4, 0, "e", "s"], [4, 1, "s", "s"], [4, 2, "s", "e"]]);
    expect(yardLink(ladder, 2).map((q) => [q.x, q.y, q.in, q.out])).toEqual([[3, 2, "e", "e"], [4, 2, "e", "e"]]);
  });

  it("a yard is a ladder (a throat column) exactly when some exit carries two or more platforms' rails (demo and fixture floors)", () => {
    let ladders = 0;
    for (const m of [demo, new Model(shop as unknown as CodeMap)]) for (const c of Object.keys(m.map.layout.containers)) {
      const p = plan(m, c);
      for (const y of p.tf.rails?.yards ?? []) {
        const carried = exits(y).map((e) => p.routes.filter((q) => q.kind === "rail" && !q.failed && q.pieces[0]?.x === e.x && q.pieces[0]?.y === e.y).length);
        expect([!!y.ladder, y.w], `${c} ${y.source}`).toEqual([carried.some((n) => n >= 2), y.ladder ? 5 : 4]);
        if (y.ladder) ladders++;
      }
    }
    expect(ladders, "dags/ and demand-forecast's floor").toBe(2);
  });

  it("on a ladder each platform runs straight into the throat and joins it by one switch; no rail lies on a strip or crosses another", () => {
    for (const c of ["jobs/dags::dags/", "svc:demand-forecast"]) {
      const p = plan(demo, c), y = p.tf.rails!.yards[0], tracks = railTracks(p.tf, p.routes);
      const strips = yardParts(y).strips.map((s) => s.r), throat = y.platforms[0].x + STEP[y.out][0];
      expect(tracks.filter((t) => t.yard)).toHaveLength(y.platforms.length);
      const at = new Map<string, Set<string>>();   // tile -> the pieces on it
      for (const t of tracks.filter((q) => q.yard)) {
        const own = y.platforms[t.index], e = exitOf(y, t.index), [first, ...rest] = t.link;
        expect(first, `${c} ${t.key} straight off its platform tile`).toMatchObject({ x: own.x, y: own.y, in: y.out, out: y.out });
        for (const q of rest) expect(q.x, `${c} ${t.key} along the throat`).toBe(throat);
        for (const q of t.link) for (const s of strips) expect(hit({ x0: q.x * T + 1, y0: q.y * T + 1, x1: (q.x + 1) * T - 1, y1: (q.y + 1) * T - 1 }, s), `${c} ${t.key} on a strip`).toBe(false);
        // one switch off its row (none on the exit row), then one way along the throat, turning out at its exit row
        const switches = t.link.filter((q) => q.in === y.out && q.out !== y.out), along = t.link.filter((q) => q.in !== y.out);
        expect(switches, `${c} ${t.key} one switch`).toHaveLength(own.y === e.y ? 0 : 1);
        expect(new Set(along.map((q) => q.in)).size, `${c} ${t.key} one way along the throat`).toBeLessThanOrEqual(1);
        const last = t.link[t.link.length - 1];
        expect([last.x + STEP[last.out][0], last.y, last.out], `${c} ${t.key} out by its exit`).toEqual([e.x, e.y, y.out]);
        for (const q of t.link) { const k = `${q.x},${q.y}`; at.set(k, (at.get(k) ?? new Set()).add(`${q.in}${q.out}`)); }
      }
      // no crossing: no tile holds a rail across the throat and one along it; an exit tile takes rails from one side only
      for (const [k, ps] of at) {
        const kinds = [...ps];
        expect(kinds.includes(`${y.out}${y.out}`) && kinds.some((q) => q === "nn" || q === "ss"), `${c} crossing at ${k}`).toBe(false);
        expect(kinds.filter((q) => q === `n${y.out}` || q === `s${y.out}`).length, `${c} ${k} one curve into the exit`).toBeLessThanOrEqual(1);
      }
    }
  });

  it("a yard against an n or s side lies level (demand-forecast's yard, set on its door's s side): a row per platform, read across, rails off the row ends", () => {
    // the demo's one n/s-side yard, demand-forecast's, now stands free in the in column (side e): its shape on an s side
    const p = plan(demo, "svc:demand-forecast"), placed = p.tf.rails!.yards[0], y = { ...placed, side: "s" as const };
    expect([placed.side, placed.free]).toEqual(["e", true]);
    expect([y.w, y.h]).toEqual([5, y.platforms.length]);   // both its rails leave by one exit: a ladder, its throat a tile wider
    expect(["e", "w"]).toContain(y.out);
    const parts = yardParts(y);
    expect(Object.keys(parts).sort(), "no header, nothing turned").toEqual(["parked", "signInside", "strips"]);
    expect(parts.strips).toHaveLength(y.platforms.length);
    for (const s of parts.strips) { expect(s.r.x1 - s.r.x0).toBeGreaterThan(2 * T); expect(s.r.y1 - s.r.y0).toBeLessThan(T); }
    for (const q of y.platforms) expect(q.x).toBe(y.out === "e" ? y.x + y.w - 2 : y.x + 1);   // the throat at the row ends
    // a self-only yard is a 4x1 strip with a parked train, its sign on the last tile
    const f0 = plan(demo, SITE).tf.rails!.yards.find((q) => q.source === "svc:nightly-jobs")!, fp = yardParts(f0);
    expect([fp.signInside, fp.strips.length]).toEqual([true, 0]);
    expect(fp.parked).toEqual({ x0: f0.x * T, y0: f0.y * T, x1: (f0.x + 3) * T, y1: (f0.y + 1) * T });
    // a yard with platforms has no parked train
    expect(yardParts(y).parked).toBeNull();
  });

  it("platform strips show the destination's short code on its own floor; hover lists say job, schedule and runs a day", () => {
    expect(shortCode(demo, "jobs/dags::dags/", "jobs/dags::dags.zone_utilisation_hourly")).toBe("F12");
    expect(shortCode(demo, SITE, "svc:feature-store")).toBe("S6");
    expect(shortCode(demo, "svc:demand-forecast", "door:svc:feature-store")).toBe("S6");
    const b = plan(demo, SITE).tf.rails!.batch;
    const nightly = b.yards.find((y) => y.source === "svc:nightly-jobs")!, df = b.yards.find((y) => y.source === "svc:demand-forecast")!;
    const list = signList(demo, nightly);
    expect(list.split("\n")).toHaveLength(11);   // the title and all ten jobs
    expect(list).toContain("bq_revenue_export — daily 03:45 (1×/day)");
    expect(list).toContain("bq_bay_events_export — every 15 min (96×/day)");
    expect(list).toContain("bq_tariff_snapshot — weekly Mon 01:00 (1×/week)");
    expect(signList(demo, df)).toContain("reference_task features/compute_zone_features — on demand");
    expect(platformList(demo, df.platforms[0])).toMatch(/^1 job → feature-store\nreference_task/);
    expect(jobLine({ relation: "r", job: "j", schedule: ["*/15 * * * *"], target: "t" })).toBe("j — every 15 min (96×/day)");
  });

  it("the legend's rail parts follow the floor; none on a floor without a yard", () => {
    expect(railLegend(plan(demo, SITE).tf)).toEqual({ yard: true, station: true, sign: true, train: true });
    const shopModel = new Model(shop as unknown as CodeMap);
    const noRail = Object.keys(shopModel.map.layout.containers).find((c) => !plan(shopModel, c).tf.rails)!;
    expect(railLegend(plan(shopModel, noRail).tf)).toBeNull();
  });
});

describe("rail selection keys", () => {
  it("a yard's key lights every rail of the yard; a stand-in rail has its shell's relations and ends", () => {
    const p = plan(demo, "jobs/dags::dags/"), y = p.tf.rails!.yards[0];
    const keys = expandKeys(p.tf, [yardKey(y.source)]);
    expect(keys).toHaveLength(11);
    expect(keys.slice(1).sort()).toEqual(p.tf.rails!.stations.map((s) => s.track).sort());
    expect(lineEnds(demo, p.tf, yardKey(y.source))).toEqual(["door:svc:nightly-jobs", ...y.platforms.map((q) => q.dest)]);
    expect(railLine(demo, p.tf, yardKey(y.source))!.relations).toHaveLength(10);
    expect(railLine(demo, p.tf, yardKey(y.source))!.jobs).toContain("bq_revenue_export — daily 03:45 (1×/day)");   // the inspector's schedules
    const df = plan(demo, "svc:demand-forecast"), shell = df.tf.rails!.shells[0];
    expect(railLine(demo, df.tf, shell.key)).toMatchObject({ a: shell.a, b: shell.b, relations: shell.relations });
    expect(lineEnds(demo, df.tf, shell.key)).toEqual([shell.a, shell.b]);
    expect(railLine(demo, df.tf, "a|b")).toBeUndefined();
  });
});

describe("a free-standing yard (audit row 38)", () => {
  it("dags/: the yard stands in the in column below its door, and every platform exit runs straight for at least 2 tiles", () => {
    const p = plan(demo, "jobs/dags::dags/"), y = p.tf.rails!.yards[0], door = p.tf.boxes.get(y.machine!)!;
    const col = p.tf.zones.find((z) => z.name === "in")!;
    // below the door rows, one free row between, at the column's left: its rails leave across the column's free width
    expect([door.region, y.free, y.out, y.x, y.y, y.h]).toEqual(["in", true, "e", door.x, door.y + door.h + 1, 10]);
    expect(y.x >= col.x && y.x + y.w + RUN <= col.x + col.w && y.y + y.h < col.y + col.h - 1, "inside the in column, off its name's row").toBe(true);
    // every platform exit: the rails starting on it run straight for at least RUN (2) tiles before their first turn
    const rails = p.routes.filter((r) => r.kind === "rail" && !r.failed);
    let starts = 0;
    for (const e of exits(y)) for (const r of rails.filter((q) => q.pieces[0].x === e.x && q.pieces[0].y === e.y)) {
      starts++;
      let run = 0;
      while (run < r.pieces.length && r.pieces[run].in === e.d && r.pieces[run].out === e.d) run++;
      expect(run, `${r.key} from ${e.x},${e.y}`).toBeGreaterThanOrEqual(2);
    }
    expect(starts, "every rail leaves by one of the yard's exits").toBe(10);
    // no machine's shadow falls on a free yard: its strips start 3 px in, as on a w side
    expect(yardParts(y).strips[0].r.x0, "strip inset on a free yard").toBe(y.x * T + 3);
  });
});

describe("a yard against an n or s side (synthetic: no demo floor places one)", () => {
  // the fixture's worker schedules batch jobs on `above` services over it and `below` services under it, set by hand on an
  // empty floor: the side facing more destinations takes the yard, its rails leave the row ends nearer them
  for (const [above, below, side] of [[2, 1, "n"], [1, 2, "s"]] as const) it(`${above} destinations above and ${below} below: the yard stands against the worker's ${side} side, level, its rails off the row ends`, () => {
    const map = structuredClone(shop) as unknown as CodeMap;
    const ids = Array.from({ length: above + below }, (_, i) => `svc:d${i}`);
    ids.forEach((id, i) => {
      map.nodes.push({ id, kind: "service", name: `d${i}` } as CodeMap["nodes"][number]);
      map.layout.containers.site.items[id] = { region: "line", col: i, row: 1 };
      map.relations.push({ kind: "batch", from: "svc:worker", to: id, id: `r:batch:${i}`, key: `job ${i}`, confidence: "confirmed",
        schedule: [`${i} 3 * * *`], job: `job_${i}`, data: "forward", evidence: [] } as unknown as CodeMap["relations"][number]);
    });
    const m = new Model(map);
    const { bundles, doors } = m.bundles(SITE);
    const rail = bundles.filter((b) => b.kind === "batch");
    // an empty floor with the worker in the middle and its destinations over and under it
    const empty = layFloor(m, SITE, doors, rail);
    const at: Record<string, [number, number]> = { "svc:worker": [20, 14], [ids[0]]: [8, 2], [ids[1]]: [28, 2], [ids[2]]: [18, 28] };
    if (below === 2) { at[ids[0]] = [18, 2]; at[ids[1]] = [8, 28]; at[ids[2]] = [28, 28]; }
    const tf: TileFloor = { ...empty, zones: [], lanes: [], stacks: undefined, landing: undefined, rails: undefined, cols: 40, rows: 36,
      boxes: new Map([...empty.boxes].filter(([id]) => id in at).map(([id, b]) => [id, { ...b, x: at[id][0], y: at[id][1] }])) };
    const r = rails(m, SITE, tf, rail)!;
    tf.rails = r;
    const y = r.yards[0], w = tf.boxes.get("svc:worker")!;
    expect(r.unplaced).toEqual([]);
    expect([y.side, y.free, y.machine]).toEqual([side, undefined, "svc:worker"]);
    expect([y.w, y.h], "level: 4 wide, a row per platform").toEqual([4, above + below]);
    expect(y.out === "e" || y.out === "w", "rails leave along the side").toBe(true);
    // flush against the worker's side
    expect(side === "n" ? y.y + y.h === w.y : y.y === w.y + w.h).toBe(true);
    expect(y.x < w.x + w.w && w.x < y.x + y.w, "level with the worker").toBe(true);
    // its sign stands beside it
    expect(y.sign).not.toBeNull();
    const routes = routeTiles(tf, rail);
    expect(checkRails(tf, routes, rail, `${side} side`), "a rail per destination").toBe(above + below);
  });
});

describe("rail junction", () => {
  const at = (x: number, y: number, inn: Piece["in"], out: Piece["out"], extra: Partial<Piece> = {}): Piece => ({ x, y, in: inn, out, under: false, hoodBefore: false, hoodAfter: false, ...extra });
  it("a destination peeling off a trunk is one rail tile with the straight and the curve, and no plate", () => {
    const rail = (pieces: Piece[]) => ({ pieces, kind: "rail" as const, both: false });
    const ops = factoryOps([rail([at(1, 1, "e", "e"), at(2, 1, "e", "e"), at(3, 1, "e", "e")]), rail([at(1, 1, "e", "e"), at(2, 1, "e", "s", { join: "split" }), at(2, 2, "s", "s")])], 10);
    expect(ops.filter((o) => o.layer === "plate")).toHaveLength(0);
    const j = ops.filter((o) => o.layer === "rail");
    expect(j).toHaveLength(1);
    expect(j[0].rails!.map((q) => [q.in, q.out])).toEqual([["e", "e"], ["e", "s"]]);
    expect(j[0].holders).toEqual([0, 1]);
    expect(ops.filter((o) => o.layer === "body" && o.p.x === 2 && o.p.y === 1)).toHaveLength(0);
    // a belt's split keeps its plate
    const belt = (pieces: Piece[]) => ({ pieces, kind: "belt" as const, both: false });
    expect(factoryOps([belt([at(2, 1, "e", "e")]), belt([at(2, 1, "e", "s", { join: "split" })])], 10).filter((o) => o.layer === "plate")).toHaveLength(1);
  });

  it("the demo's dags/ floor draws its rail junctions with no plate", () => {
    const p = plan(demo, "jobs/dags::dags/");
    const ops = factoryOps(p.routes.map((r) => ({ pieces: r.pieces, kind: r.kind, failed: r.failed, both: r.both })), p.tf.cols);
    const splits = new Set(p.routes.filter((r) => r.kind === "rail").flatMap((r) => r.pieces.filter((q) => q.join && !q.under).map((q) => `${q.x},${q.y}`)));
    expect(splits.size).toBeGreaterThan(0);
    for (const o of ops.filter((q) => q.layer === "plate")) expect(splits.has(`${o.p.x},${o.p.y}`)).toBe(false);
    for (const k of splits) expect(ops.some((o) => o.layer === "rail" && `${o.p.x},${o.p.y}` === k), k).toBe(true);
  });
});
