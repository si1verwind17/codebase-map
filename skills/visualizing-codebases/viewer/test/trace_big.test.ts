// The trace on the large private regression map (VIZ_BIG_MAP; read only, never copied into the repo). It predates
// fields, type links, pins and examples, so it also proves the trace works without them.
import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../src/model/model";
import type { CodeMap } from "../src/model/types";
import { TraceGraph } from "../src/trace/graph";
import { FOLD_AT, initialState } from "../src/trace/reach";
import { layoutTrace } from "../src/trace/layout";
import { traceItems, traceKeys } from "../src/trace/floor";
import { examplesFor } from "../src/trace/examples";

const BIG = process.env.VIZ_BIG_MAP ?? "";

/** One warm-up, then the median of 5 timed runs (a single run flakes under full-suite load). */
function median(f: () => unknown): number {
  f();
  const runs: number[] = [];
  for (let i = 0; i < 5; i++) {
    const t = performance.now();
    f();
    runs.push(performance.now() - t);
  }
  return runs.sort((a, b) => a - b)[2];
}

describe("traces on the large real map", () => {
  it.runIf(BIG && existsSync(BIG))("builds the graph, and lays out depth 2 from its busiest method and with every frontier opened, quickly", () => {
    const m = new Model(JSON.parse(readFileSync(BIG, "utf8")) as CodeMap);
    const g = new TraceGraph(m);
    const graphMs = median(() => new TraceGraph(m));
    const busiest = m.map.nodes.filter((n) => n.kind === "method").map((n) => n.id).sort((a, b) => g.degree(b) - g.degree(a) || a.localeCompare(b))[0];
    const v = layoutTrace(m, g, initialState(busiest));
    const layoutMs = median(() => layoutTrace(m, g, initialState(busiest)));
    expect(v.rows.size).toBeGreaterThan(1);
    const open = { ...initialState(busiest), expanded: new Set([...v.rows.values()].filter((r) => r.more).map((r) => r.id)) };
    const wider = layoutTrace(m, g, open);
    const widerMs = median(() => layoutTrace(m, g, open));
    expect(wider.rows.size).toBeGreaterThanOrEqual(v.rows.size);
    const floorMs = median(() => traceKeys(m, SITE, traceItems(m, SITE, wider.nodes)));
    console.log(`big map traces (median of 5): graph ${graphMs.toFixed(1)} ms, depth 2 ${layoutMs.toFixed(1)} ms, opened ${widerMs.toFixed(1)} ms, floor ${floorMs.toFixed(1)} ms`);
    expect(graphMs, "graph").toBeLessThan(500);
    expect(layoutMs, "layout at depth 2").toBeLessThan(100);
    expect(widerMs, "layout with every frontier opened").toBeLessThan(200);
    expect(floorMs, "the floor's items and lines").toBeLessThan(100);
    for (const r of wider.rows.values()) expect(() => examplesFor(m, r.node)).not.toThrow();
  });

  it.runIf(BIG && existsSync(BIG))("a service's or library's trace starts from its seeds as quickly as a method's", () => {
    const m = new Model(JSON.parse(readFileSync(BIG, "utf8")) as CodeMap);
    const g = new TraceGraph(m);
    const owners = m.map.nodes.filter((n) => n.kind === "service" || n.kind === "library").map((n) => n.id);
    expect(owners.length).toBeGreaterThan(0);
    let worst = 0;
    const t0 = performance.now();
    for (const id of owners) {
      const t = performance.now();
      const v = layoutTrace(m, g, initialState(id));
      worst = Math.max(worst, performance.now() - t);
      expect(v.start.shown).toBeLessThanOrEqual(FOLD_AT);
    }
    const mean = (performance.now() - t0) / owners.length;
    console.log(`big map container traces: ${owners.length}, mean ${mean.toFixed(1)} ms, worst ${worst.toFixed(1)} ms`);
    expect(mean, "mean container trace").toBeLessThan(100);
    expect(worst, "slowest container trace").toBeLessThan(400);
  });
});
