// Long rows wrap (audit row 46): a service's airfield of many in-process queues, and a long shelf, take rows instead
// of stretching the floor so wide that its names no longer read at Fit; `floor.wide` reports a floor that still does.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor, type FloorPlan } from "../../src/factory/plan";
import { measure, stripViolations, wideViolations, type FloorMeasures } from "../../src/audit/floor";
import { SITE } from "../../src/model/model";

const IN_PROCESS = new URL("../../guide/maps/in_process.code-map.json", import.meta.url);
const SVC = "svc:orders";

/** The guide's in-process map with `n` more of `make`'s items on the orders service floor, in `region`, one row. */
function withMore(n: number, region: string, make: (i: number) => CodeMap["nodes"][number]): Model {
  const map = JSON.parse(readFileSync(IN_PROCESS, "utf8")) as CodeMap;
  const items = map.layout.containers[SVC].items;
  const start = Object.values(items).filter((c) => c.region === region).length;
  for (let i = 0; i < n; i++) {
    const node = make(i);
    map.nodes.push(node);
    items[node.id] = { region, col: start + i, row: 0 };
  }
  return new Model(map);
}
const plan = (m: Model) => { const b = m.bundles(SVC); return planFloor(m, SVC, b.doors, b.bundles, b.layered); };
const rowsOf = (p: FloorPlan, region: string) => new Set([...p.tf.boxes.values()].filter((b) => b.region === region).map((b) => b.y)).size;

describe("long rows wrap", () => {
  it("a service's airfield of 12 in-process queues takes rows as wide as its work area, at least 4 hubs each", () => {
    const base = JSON.parse(readFileSync(IN_PROCESS, "utf8")) as CodeMap;
    const q = base.nodes.find((x) => x.kind === "in-process-queue")!;
    const model = withMore(11, "airfield", (i) => ({ ...q, id: `inq:orders:q${i}`, name: `q${i}` })), p = plan(model);
    const hubs = [...p.tf.boxes.values()].filter((b) => b.region === "airfield");
    expect(hubs).toHaveLength(12);
    const perRow = Math.max(...[...new Set(hubs.map((b) => b.y))].map((y) => hubs.filter((b) => b.y === y).length));
    expect(rowsOf(p, "airfield")).toBe(Math.ceil(12 / perRow));
    expect(perRow).toBeGreaterThanOrEqual(4);
    expect(perRow).toBeLessThan(12);
    expect(wideViolations(measure(p, model, SVC), p)).toEqual([]);
  });

  it("a shelf of 14 packages wraps into rows near 1.6:1, filled left to right", () => {
    const p = plan(withMore(14, "shelf", (i) => ({ id: `orders::model${String(i).padStart(2, "0")}/`, kind: "package", name: `model${i}`,
      parent: SVC } as CodeMap["nodes"][number])));
    const shelf = [...p.tf.boxes.values()].filter((b) => b.region === "shelf");
    expect(shelf).toHaveLength(14);
    expect(rowsOf(p, "shelf")).toBeGreaterThan(1);
    const first = shelf.find((b) => b.id === "orders::model00/")!, second = shelf.find((b) => b.id === "orders::model01/")!;
    expect([second.y, second.x > first.x]).toEqual([first.y, true]);   // the next item sits to the right, on the same row
  });

  it("floor.wide: a wide floor whose names do not read at Fit, never a small wide one or a tall one", () => {
    const tf = (cols: number, rows: number) => ({ tf: { cols, rows } }) as unknown as FloorPlan;
    const m = (fitZoom: number, switchZoom: number) => ({ fitZoom, switchZoom }) as FloorMeasures;
    expect(wideViolations(m(0.3, 0.6), tf(168, 15))).toEqual([{ detail: "168×15 tiles, 11.2:1: at Fit (0.30) names need 0.60" }]);
    expect(wideViolations(m(0.9, 0.6), tf(43, 8))).toEqual([]);     // wide, but it reads at Fit
    expect(wideViolations(m(0.3, 0.6), tf(80, 60))).toEqual([]);    // too big to read, but not because of its width
  });

  it("zone.strip: 20 externals beside a short production line wrap near-square (5 × 4), never one long row", () => {
    const map = JSON.parse(readFileSync(IN_PROCESS, "utf8")) as CodeMap;   // a small site
    const items = map.layout.containers[SITE].items;
    for (let i = 0; i < 20; i++) {
      const id = `ext:http:vendor${i}`;
      map.nodes.push({ id, kind: "external", name: `vendor${i}` } as CodeMap["nodes"][number]);
      items[id] = { region: "line", col: 100 + i, row: 0 };
    }
    const model = new Model(map), b = model.bundles(SITE), p = planFloor(model, SITE, b.doors, b.bundles, b.layered);
    const outside = [...p.tf.boxes.values()].filter((x) => x.region === "outside");
    const cols = new Set(outside.map((x) => x.x)).size, rows = new Set(outside.map((x) => x.y)).size;
    expect(outside.length).toBeGreaterThanOrEqual(20);
    expect(Math.max(cols, rows)).toBeLessThanOrEqual(2 * Math.ceil(Math.sqrt(outside.length)));
    expect(stripViolations(p)).toEqual([]);
  });
});
