import { describe, expect, it } from "vitest";
import { TraceGraph, across, ownerOf } from "../../src/trace/graph";
import { MapBuilder } from "./trace_fixture";

describe("the trace graph", () => {
  it("follows calls and runtime relations, never uses-code", () => {
    const b = new MapBuilder();
    const s = b.owner("orders"), lib = b.owner("common", "library");
    const a = b.method(s, "Api", "place"), c = b.method(lib, "Money", "round");
    b.rel("calls", a, c, { line: 4 });
    b.rel("uses-code", s, lib);
    const g = new TraceGraph(b.model());
    expect(g.next(a, 1).map((e) => e.to)).toEqual([c]);
    expect(g.next(s, 1)).toEqual([]);
    expect(g.next(c, -1).map((e) => e.from)).toEqual([a]);
  });

  it("turns a db-read round: a table's upstream is its writers, its downstream its readers", () => {
    const b = new MapBuilder();
    const s = b.owner("billing");
    const db = b.node({ id: "db:sql:DB", kind: "datastore", name: "db" });
    const t = b.node({ id: `${db}/public.invoices`, kind: "table", name: "public.invoices", parent: db });
    const w = b.method(s, "Repo", "save"), r = b.method(s, "Repo", "load");
    b.rel("db-write", w, t, { key: "table public.invoices" });
    b.rel("db-read", r, t, { key: "table public.invoices" });
    const g = new TraceGraph(b.model());
    expect(g.next(t, -1).map((e) => e.from)).toEqual([w]);
    expect(g.next(t, 1).map((e) => e.to)).toEqual([r]);
    const read = g.next(r, -1)[0];
    expect([read.kind, read.from, read.to]).toEqual(["db-read", t, r]);
  });

  it("orders a method's callees by the evidence line of each call (call order)", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const a = b.method(s, "Api", "place"), x = b.method(s, "Api", "x"), y = b.method(s, "Api", "y"), z = b.method(s, "Api", "z");
    b.rel("calls", a, x, { line: 30 });
    b.rel("calls", a, y, { line: 7 });
    b.rel("calls", a, z, { line: 12 });
    expect(new TraceGraph(b.model()).next(a, 1).map((e) => e.to)).toEqual([y, z, x]);
  });

  it("merges relations of one kind between the same ends into one edge, confirmed when any is, at its first line", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const a = b.method(s, "Api", "place"), x = b.method(s, "Api", "x");
    b.rel("calls", a, x, { line: 9, inferred: true });
    b.relations.push({ ...b.relations[0], id: "second", confidence: "confirmed", evidence: [{ file: "f.py", line: 3 }] });
    const [e] = new TraceGraph(b.model()).next(a, 1);
    expect([e.confirmed, e.line, e.relations.length]).toEqual([true, 3, 2]);
  });

  it("leads a trait method on to each implementation's same-named method", () => {
    const b = new MapBuilder();
    const s = b.owner("pricing");
    const trait = b.cls(s, "Pricing");
    b.cls(s, "PricingLive", undefined, [trait]);
    const tm = b.method(s, "Pricing", "quote", [{ name: "zone", type: "Zone" }]);
    const im = b.method(s, "PricingLive", "quote", [{ name: "zone", type: "Zone" }]);
    const [e] = new TraceGraph(b.model()).next(tm, 1);
    expect([e.kind, e.from, e.to]).toEqual(["implements", tm, im]);
  });

  it("puts a method in its service's or library's box, and a table, topic or external in its own", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const m = b.method(s, "Api", "place");
    const t = b.node({ id: "topic:bus:orders", kind: "topic", name: "orders" });
    const db = b.node({ id: "db:sql:DB", kind: "datastore", name: "db" });
    const table = b.node({ id: `${db}/public.orders`, kind: "table", name: "public.orders", parent: db });
    const model = b.model();
    expect([ownerOf(model, m), ownerOf(model, t), ownerOf(model, table), ownerOf(model, s)]).toEqual([s, t, table, s]);
  });

  it("across: the far end of an edge seen from a side", () => {
    const e = { from: "a", to: "b" } as Parameters<typeof across>[0];
    expect([across(e, 1), across(e, -1)]).toEqual(["b", "a"]);
  });
});

describe("the trace graph, trait unfolding", () => {
  it("unfolds a trait method to every implementation, by the fold rule", () => {
    const b = new MapBuilder();
    const s = b.owner("pricing");
    const trait = b.cls(s, "Pricing");
    b.cls(s, "Live", undefined, [trait]);
    b.cls(s, "Test", undefined, [trait]);
    b.cls(s, "Odd", undefined, [trait]);
    const tm = b.method(s, "Pricing", "quote", [{ name: "zone", type: "Zone" }]);
    const live = b.method(s, "Live", "quote", [{ name: "zone", type: "Zone" }]);
    const test = b.method(s, "Test", "quote", [{ name: "zone", type: "Zone" }]);
    const odd = b.method(s, "Odd", "quote", [{ name: "zone", type: "Zone" }, { name: "x", type: null }]);
    const g = new TraceGraph(b.model());
    expect(g.next(tm, 1).map((e) => [e.kind, e.to]).sort()).toEqual([["implements", live], ["implements", odd], ["implements", test]].sort());
  });
});

describe("the trace graph, fold rule edge cases", () => {
  it("a chain A <- B <- C unfolds from the top: A->B and A->C, no B->C", () => {
    const b = new MapBuilder();
    const s = b.owner("pricing");
    const a = b.cls(s, "A"), bc = b.cls(s, "B", undefined, [a]);
    b.cls(s, "C", undefined, [bc]);
    const am = b.method(s, "A", "quote"), bm = b.method(s, "B", "quote"), cm = b.method(s, "C", "quote");
    const g = new TraceGraph(b.model());
    expect(g.next(am, 1).map((e) => e.to).sort()).toEqual([bm, cm].sort());
    expect(g.next(bm, 1)).toEqual([]);
  });

  it("two same-name, same-arity trait methods are ambiguous: no unfolding edge", () => {
    const b = new MapBuilder();
    const s = b.owner("pricing");
    const trait = b.cls(s, "Pricing");
    b.cls(s, "Live", undefined, [trait]);
    const t1 = b.method(s, "Pricing", "quote", [{ name: "z", type: null }]);
    b.node({ id: `${trait}#quote(b)/1`, kind: "method", name: "quote", parent: trait });
    b.method(s, "Live", "quote", [{ name: "z", type: null }]);
    expect(new TraceGraph(b.model()).next(t1, 1)).toEqual([]);
  });
});
