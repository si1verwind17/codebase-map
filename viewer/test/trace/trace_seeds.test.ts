// Where a trace starts (spec A3, A5, A6): a container's seeds — its entry points, else its boundary methods, else itself —
// folded above FOLD_AT; a line's ends; the header's words and the pin's default name.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { TraceGraph } from "../../src/trace/graph";
import { boundaryMethods, lineFocus, lineStart, seedsFor, startFor, traceable } from "../../src/trace/entries";
import { ALL_SEEDS, FOLD_AT, initialState, reach } from "../../src/trace/reach";
import { layoutTrace, pinStartName, qualifiedName, startText, traceTitle } from "../../src/trace/layout";
import { MapBuilder } from "./trace_fixture";

const demo = new Model(JSON.parse(readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8")) as CodeMap);

/** The same expectations as scripts/tests/test_examples.py (`examples.seeds`): the agent's checklist and the viewer start
 *  a container's trace from the same seeds. */
const FEATURE_STORE = ["features::features.zone_features#zone_features/0"];
const COMMON = [
  "common::city.parking.common.Config$#env/1", "common::city.parking.common.EventProducer#publish/3",
  "common::city.parking.common.Jdbc#query/3", "common::city.parking.common.Jdbc#transaction/1",
  "common::city.parking.common.Jdbc#update/2",
];

/** A library `util` (Fmt.a called from outside, Fmt.b only from a, Idle.c linked by code only) and a service `app`. */
function shelf() {
  const b = new MapBuilder();
  const lib = b.owner("util", "library"), svc = b.owner("app");
  const a = b.method(lib, "Fmt", "a"), inner = b.method(lib, "Fmt", "b"), lone = b.method(lib, "Idle", "c");
  const run = b.method(svc, "Main", "run");
  b.rel("calls", run, a);
  b.rel("calls", a, inner);
  b.rel("uses-code", lone, run);
  return { b, lib, svc, a, inner, lone, run, pkg: "util::pkg/", idle: "util::pkg.Idle" };
}

describe("a container's seeds (spec A3)", () => {
  it("a service with entry points starts at them (demo, as the Python checklist)", () => {
    const s = seedsFor(demo, "svc:feature-store");
    expect(s.rule).toBe("entry points");
    expect([...s.ids].sort()).toEqual(FEATURE_STORE);
  });

  it("a library with none starts at its boundary methods (demo, as the Python checklist)", () => {
    const s = seedsFor(demo, "lib:common");
    expect(s.rule).toBe("boundary methods");
    expect([...s.ids].sort()).toEqual(COMMON);
  });

  it("boundary methods: a traced relation crosses the container's edge there; a call inside it or a code link does not count", () => {
    const { b, lib, svc, a, run } = shelf();
    const m = b.model();
    expect(boundaryMethods(m, lib)).toEqual([a]);
    expect(seedsFor(m, lib)).toEqual({ ids: [a], rule: "boundary methods" });
    expect(seedsFor(m, svc)).toEqual({ ids: [run], rule: "boundary methods" });
  });

  it("entry points come first when there are any", () => {
    const { b, lib, inner } = shelf();
    const t = b.node({ id: "topic:kafka:jobs", kind: "topic", name: "jobs" });
    b.rel("event", t, inner, { key: "jobs" });
    expect(seedsFor(b.model(), lib)).toEqual({ ids: [inner], rule: "entry points" });
  });

  it("a container with neither starts at itself", () => {
    const { b, idle } = shelf();
    expect(seedsFor(b.model(), idle)).toEqual({ ids: [idle], rule: "container" });
  });

  it("a floor group is a container of its members; with nothing in them it starts at its members", () => {
    const { b, a, pkg } = shelf();
    b.extra = { layout: { version: 1, containers: { site: { strategy: "main-bus", items: {}, groups: [
      { id: "group:shelf", label: "shelf", members: [pkg], kind: "family" },
      { id: "group:quiet", label: "quiet", members: ["util::pkg.Idle"], kind: "family" },
    ] } } } } as never;
    const m = b.model();
    expect(traceable(m, "group:shelf")).toBe(true);
    expect(seedsFor(m, "group:shelf")).toEqual({ ids: [a], rule: "boundary methods" });
    expect(seedsFor(m, "group:quiet")).toEqual({ ids: ["util::pkg.Idle"], rule: "container" });
  });

  it("any other node starts at itself; a datastore at its tables; an id not in the map at nothing", () => {
    const { b, a } = shelf();
    const db = b.node({ id: "db:sql:DB", kind: "datastore", name: "db" });
    const t = b.node({ id: `${db}/public.x`, kind: "table", name: "public.x", parent: db });
    const m = b.model();
    expect(seedsFor(m, a)).toEqual({ ids: [a], rule: "self" });
    expect(seedsFor(m, db)).toEqual({ ids: [t], rule: "tables" });
    expect(seedsFor(m, "nope")).toEqual({ ids: [], rule: "self" });
    expect(traceable(m, "nope")).toBe(false);
  });

  it("above FOLD_AT seeds the trace starts at the first FOLD_AT, the total kept; show all starts at every one", () => {
    const b = new MapBuilder();
    const svc = b.owner("jobs");
    const t = b.node({ id: "topic:kafka:tick", kind: "topic", name: "tick" });
    const ids = Array.from({ length: FOLD_AT + 2 }, (_, i) => b.method(svc, `Job${i}`, "run"));
    ids.forEach((id, i) => b.rel("batch", t, id, { key: `job ${i}` }));
    const m = b.model(), g = new TraceGraph(m);
    const set = reach(m, g, initialState(svc));
    expect(set.seeds.length).toBe(FOLD_AT);
    expect(set.start).toEqual({ rule: "entry points", total: FOLD_AT + 2 });
    expect(reach(m, g, { ...initialState(svc), showAll: new Set([ALL_SEEDS]) }).seeds.length).toBe(FOLD_AT + 2);
    expect(layoutTrace(m, g, initialState(svc)).start).toEqual({ rule: "entry points", total: FOLD_AT + 2, shown: FOLD_AT });
  });
});

describe("a line's ends (spec A5)", () => {
  it("the nodes at both ends of the relations it carries that a trace follows, once each; none for a code link", () => {
    const { b, a, run, lone } = shelf();
    const m = b.model();
    const rels = m.map.relations;
    const line = lineStart(m, "lib:util|svc:app", rels.filter((r) => r.kind === "calls" && r.from === run), "util ↔ app")!;
    expect(line.key).toBe("lib:util|svc:app");
    expect(line.title).toBe("util ↔ app");
    expect([...line.ends].sort()).toEqual([a, run].sort());
    expect(lineStart(m, "x|y", rels.filter((r) => r.kind === "uses-code" && r.from === lone), "x ↔ y")).toBeNull();
    expect(seedsFor(m, lineFocus(line.key), line)).toEqual({ ids: [...line.ends], rule: "ends" });
  });
});

describe("the header and the pin's name (spec A6)", () => {
  it("names the container's kind and its seed count; a single-node start has no such words", () => {
    const { b, lib, idle, a } = shelf();
    const db = b.node({ id: "db:sql:DB", kind: "datastore", name: "db" });
    b.node({ id: `${db}/public.x`, kind: "table", name: "public.x", parent: db });
    b.node({ id: `${db}/public.y`, kind: "table", name: "public.y", parent: db });
    const m = b.model(), g = new TraceGraph(m);
    const at = (focus: string) => layoutTrace(m, g, initialState(focus));
    expect(startText(m, at(lib))).toBe("library · 1 boundary method");
    expect(startText(m, at(idle))).toBe("class");
    expect(startText(m, at(db))).toBe("datastore · 2 tables");
    expect(startText(m, at(a))).toBeNull();
    expect(startText(demo, layoutTrace(demo, new TraceGraph(demo), initialState("svc:feature-store")))).toBe("service · 1 entry point");
  });

  it("titles a line's trace as the line, a group by its label, a container by its name", () => {
    const { b, a, run, lib } = shelf();
    b.extra = { layout: { version: 1, containers: { site: { strategy: "main-bus", items: {}, groups: [
      { id: "group:shelf", label: "shelf", members: ["util::pkg/"], kind: "family" },
    ] } } } } as never;
    const m = b.model(), g = new TraceGraph(m);
    const line = { key: "lib:util|svc:app", title: "util ↔ app", ends: [a, run] };
    const lv = layoutTrace(m, g, initialState(lineFocus(line.key), "both", line));
    expect(traceTitle(m, lv)).toBe("util ↔ app");
    expect(startText(m, lv)).toBe("line · 2 ends");
    expect(traceTitle(m, layoutTrace(m, g, initialState("group:shelf")))).toBe("shelf");
    expect(traceTitle(m, layoutTrace(m, g, initialState(lib)))).toBe("util");
    // a class by the name its box shows (Model.itemName), not its bare name
    const LIVE = "billing::city.parking.billing.BillingService.Live";
    expect(traceTitle(demo, layoutTrace(demo, new TraceGraph(demo), initialState(LIVE)))).toBe("BillingService.Live");
  });

  it("a container's pin is named by its qualified name; anything else by its title", () => {
    const { b, pkg, idle, a, lib } = shelf();
    const m = b.model(), g = new TraceGraph(m);
    expect(qualifiedName(m, idle)).toBe("util / pkg / Idle");
    expect(pinStartName(m, layoutTrace(m, g, initialState(pkg)))).toBe("util / pkg");
    expect(pinStartName(m, layoutTrace(m, g, initialState(lib)))).toBe("util");
    expect(pinStartName(m, layoutTrace(m, g, initialState(a)))).toBe("Fmt.a");
  });
});

describe("what a pick traces from while the pane is open (spec A2, A5)", () => {
  it("a node by its id; a twin as the package it stands for (Review Focus 2); an id not in the map, nothing", () => {
    expect(startFor(demo, SITE, { type: "node", id: "svc:billing" })).toEqual({ focus: "svc:billing" });
    expect(startFor(demo, "svc:feature-store", { type: "node", id: "twin:pipelines_shared::pipelines_shared/" }))
      .toEqual({ focus: "pipelines_shared::pipelines_shared/" });
    expect(startFor(demo, SITE, { type: "node", id: "nope" })).toBeNull();
  });

  it("a line by the ends of what it carries, titled as the inspector names it", () => {
    const key = "3p:smtp|svc:notifier";
    const s = startFor(demo, SITE, { type: "bundle", key })!;
    expect(s.focus).toBe(`line:${key}`);
    expect(s.line!.title).toBe("smtp ↔ notifier");
    expect([...s.line!.ends].sort()).toEqual(["3p:smtp", "svc:notifier"]);
  });

  it("a line that carries no traced relation starts nothing (Review Focus 1)", () => {
    expect(startFor(demo, SITE, { type: "bundle", key: "nope|nada" })).toBeNull();
    const rail = { title: "a → b", relations: demo.map.relations.filter((r) => r.kind === "uses-code").slice(0, 1) };
    expect(startFor(demo, SITE, { type: "bundle", key: "rail:x" }, () => rail)).toBeNull();
  });
});
