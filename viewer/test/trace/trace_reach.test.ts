import { describe, expect, it } from "vitest";
import { TraceGraph } from "../../src/trace/graph";
import { FOLD_AT, START_DEPTH, initialState, reach, type TraceState } from "../../src/trace/reach";
import { MapBuilder } from "./trace_fixture";

/** a → b → c → d → e across four services, each call at line 1. */
function chain() {
  const b = new MapBuilder();
  const ids = ["a", "b", "c", "d", "e"].map((n) => b.method(b.owner(`s${n}`), "C", n));
  for (let i = 0; i + 1 < ids.length; i++) b.rel("calls", ids[i], ids[i + 1]);
  return { b, ids };
}
const run = (b: MapBuilder, st: TraceState) => { const m = b.model(); return reach(m, new TraceGraph(m), st); };
const shown = (set: ReturnType<typeof reach>) => [...set.reached.keys()];

describe("reach: what a trace shows", () => {
  it("starts two hops each way; the last node shown is a frontier with its `+` count", () => {
    expect(START_DEPTH).toBe(2);
    const { b, ids } = chain();
    const set = run(b, initialState(ids[0], "downstream"));
    expect(shown(set)).toEqual(ids.slice(0, 3));
    expect(set.reached.get(ids[2])!.more).toBe(1);
    expect(set.reached.get(ids[1])!.more).toBe(0);
    expect(set.hops.map((h) => [h.from, h.to])).toEqual([[ids[0], ids[1]], [ids[1], ids[2]]]);
  });

  it("a `+` on a frontier node adds one hop beyond it", () => {
    const { b, ids } = chain();
    const st = { ...initialState(ids[0], "downstream"), expanded: new Set([ids[2]]) };
    const set = run(b, st);
    expect(shown(set)).toEqual(ids.slice(0, 4));
    expect(set.reached.get(ids[3])!.more).toBe(1);
  });

  it("follows the direction asked: upstream only, downstream only, or both", () => {
    const { b, ids } = chain();
    expect(shown(run(b, initialState(ids[2], "upstream")))).toEqual([ids[2], ids[1], ids[0]]);
    expect(shown(run(b, initialState(ids[2], "downstream")))).toEqual([ids[2], ids[3], ids[4]]);
    const both = run(b, initialState(ids[2]));
    expect(new Set(shown(both))).toEqual(new Set(ids));
    expect(both.reached.get(ids[1])!.side).toBe(-1);
    expect(both.reached.get(ids[3])!.side).toBe(1);
  });

  it("above FOLD_AT neighbours: the total first, the first FOLD_AT in call order, all after show all", () => {
    expect(FOLD_AT).toBe(5);
    const b = new MapBuilder();
    const s = b.owner("orders");
    const a = b.method(s, "Api", "place");
    const callees = [7, 6, 5, 4, 3, 2, 1].map((line) => { const m = b.method(b.owner(`t${line}`), "C", `m${line}`); b.rel("calls", a, m, { line }); return m; });
    const set = run(b, initialState(a, "downstream"));
    expect(set.reached.get(a)!.folds).toEqual([{ side: 1, total: 7, word: "callees" }]);
    expect(shown(set).slice(1)).toEqual([...callees].reverse().slice(0, 5));
    const all = run(b, { ...initialState(a, "downstream"), showAll: new Set([`${a}|1`]) });
    expect(all.reached.get(a)!.folds).toEqual([]);
    expect(all.reached.size).toBe(8);
  });

  it("names a folded upstream of calls `callers`, of a table's writes `writers`", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const a = b.method(s, "Api", "place");
    const db = b.node({ id: "db:sql:DB", kind: "datastore", name: "db" });
    const t = b.node({ id: `${db}/public.orders`, kind: "table", name: "public.orders", parent: db });
    for (let i = 1; i <= 6; i++) {
      const c = b.method(b.owner(`c${i}`), "C", `call${i}`);
      b.rel("calls", c, a, { line: i });
      b.rel("db-write", c, t, { line: i, key: "table public.orders" });
    }
    expect(run(b, initialState(a, "upstream")).reached.get(a)!.folds[0]).toEqual({ side: -1, total: 6, word: "callers" });
    expect(run(b, initialState(t, "upstream")).reached.get(t)!.folds[0]).toEqual({ side: -1, total: 6, word: "writers" });
  });

  it("folds calls into a shared library into one box per side, counted, until it is opened", () => {
    const b = new MapBuilder();
    const s = b.owner("billing"), lib = b.owner("common", "library");
    const a = b.method(s, "Api", "invoice");
    const r = b.method(lib, "Money", "round"), f = b.method(lib, "Money", "format"), deep = b.method(lib, "Money", "digits");
    b.rel("calls", a, r, { line: 2 });
    b.rel("calls", a, f, { line: 3 });
    b.rel("calls", r, deep, { line: 9 });
    const set = run(b, initialState(a, "downstream"));
    const fold = set.reached.get(`fold:${lib}|1`)!;
    expect([fold.kind, fold.node, fold.calls, fold.members]).toEqual(["library", lib, 2, [r, f]]);
    expect(set.reached.has(r) || set.reached.has(deep)).toBe(false);
    expect(set.hops.map((h) => [h.from, h.to])).toEqual([[a, `fold:${lib}|1`]]);
    const open = run(b, { ...initialState(a, "downstream"), libraries: new Set([lib]) });
    expect(shown(open)).toEqual([a, r, f, deep]);
  });

  it("does not fold the focus's own library", () => {
    const b = new MapBuilder();
    const lib = b.owner("common", "library");
    const r = b.method(lib, "Money", "round"), d = b.method(lib, "Money", "digits");
    b.rel("calls", r, d);
    expect(shown(run(b, initialState(r, "downstream")))).toEqual([r, d]);
  });

  it("draws a loop once and marks it ↺ on the node that leads back", () => {
    const b = new MapBuilder();
    const a = b.method(b.owner("x"), "C", "a"), c = b.method(b.owner("y"), "C", "b");
    b.rel("calls", a, c);
    b.rel("calls", c, a);
    b.rel("calls", a, a, { line: 5 });
    const set = run(b, initialState(a, "downstream"));
    expect(shown(set)).toEqual([a, c]);
    expect(set.reached.get(c)!.loops).toEqual([a]);
    expect(set.reached.get(a)!.loops).toEqual([a]);
    expect(set.hops.map((h) => [h.from, h.to])).toEqual([[a, c]]);
  });

  it("ends a hop known only to the service at the service, marked a gap, and goes no further", () => {
    const b = new MapBuilder();
    const svc = b.owner("worker"), up = b.owner("scheduler");
    const h = b.method(b.owner("shop"), "Api", "create");
    b.rel("request", svc, h, { key: "POST /v1/orders" });
    b.rel("batch", up, svc, { key: "job nightly" });
    const set = run(b, initialState(h, "upstream"));
    expect(set.reached.get(svc)!.kind).toBe("gap");
    expect(set.reached.has(up)).toBe(false);
  });

  it("a container focus is not shown again as a gap row inside its own trace", () => {
    const b = new MapBuilder();
    const svc = b.owner("shop"), other = b.method(b.owner("worker"), "Job", "run");
    const h = b.method(svc, "Api", "create");
    b.rel("request", svc, h, { key: "POST /v1/orders" });
    b.rel("calls", h, other);
    b.rel("batch", other, svc, { key: "job back" });
    const set = run(b, initialState(svc, "both"));
    expect(set.reached.get(svc)).toBeUndefined();
    expect([...set.reached.values()].filter((r) => r.kind === "gap" && r.node === svc)).toEqual([]);
  });

  it("orients a db-read table → reader: a reader's upstream is the table, then its writers", () => {
    const b = new MapBuilder();
    const db = b.node({ id: "db:sql:DB", kind: "datastore", name: "db" });
    const t = b.node({ id: `${db}/public.orders`, kind: "table", name: "public.orders", parent: db });
    const w = b.method(b.owner("orders"), "Repo", "save"), r = b.method(b.owner("reports"), "Daily", "load");
    b.rel("db-write", w, t);
    b.rel("db-read", r, t);
    const set = run(b, initialState(r, "upstream"));
    expect(shown(set)).toEqual([r, t, w]);
    expect(set.hops.map((h) => [h.edge.kind, h.from, h.to])).toEqual([["db-read", t, r], ["db-write", w, t]]);
    expect(shown(run(b, initialState(t, "downstream")))).toEqual([t, r]);
  });

  it("an implementation step costs no hop: a trait method leads on to its implementation at the same hop", () => {
    const b = new MapBuilder();
    const s = b.owner("pricing");
    const trait = b.cls(s, "Pricing");
    b.cls(s, "PricingLive", undefined, [trait]);
    const caller = b.method(b.owner("orders"), "Api", "place");
    const tm = b.method(s, "Pricing", "quote"), im = b.method(s, "PricingLive", "quote");
    const tariff = b.method(s, "Tariffs", "load");
    b.rel("calls", caller, tm);
    b.rel("calls", im, tariff);
    const set = run(b, initialState(caller, "downstream"));
    expect(shown(set)).toEqual([caller, tm, im, tariff]);
    expect([set.reached.get(tm)!.hop, set.reached.get(im)!.hop, set.reached.get(tariff)!.hop]).toEqual([1, 1, 2]);
  });

  it("starts a datastore's trace from each of its tables", () => {
    const b = new MapBuilder();
    const db = b.node({ id: "db:sql:DB", kind: "datastore", name: "db" });
    const t1 = b.node({ id: `${db}/public.a`, kind: "table", name: "public.a", parent: db });
    const t2 = b.node({ id: `${db}/public.b`, kind: "table", name: "public.b", parent: db });
    const w = b.method(b.owner("orders"), "Repo", "save");
    b.rel("db-write", w, t2);
    const set = run(b, initialState(db));
    expect(set.seeds).toEqual([t1, t2]);
    expect(shown(set)).toEqual([t1, t2, w]);
  });

  it("a focus busy both ways folds each side on its own", () => {
    const b = new MapBuilder();
    const f = b.method(b.owner("hub"), "C", "f");
    for (let i = 1; i <= 6; i++) {
      b.rel("calls", b.method(b.owner(`in${i}`), "C", `c${i}`), f, { line: i });
      b.rel("calls", f, b.method(b.owner(`out${i}`), "C", `d${i}`), { line: i });
    }
    const set = run(b, initialState(f));
    expect(set.reached.get(f)!.folds).toEqual([{ side: 1, total: 6, word: "callees" }, { side: -1, total: 6, word: "callers" }]);
    expect(set.reached.size).toBe(11);
    expect(run(b, { ...initialState(f), showAll: new Set([`${f}|-1`]) }).reached.size).toBe(12);
  });

  it("an unknown focus shows nothing", () => {
    const { b } = chain();
    expect(run(b, initialState("nope")).reached.size).toBe(0);
  });
  it("a node at the frontier still follows its zero-cost implementation steps", () => {
    const b = new MapBuilder();
    const s = b.owner("pricing");
    const trait = b.cls(s, "Pricing");
    b.cls(s, "PricingLive", undefined, [trait]);
    const x = b.method(b.owner("orders"), "Api", "x"), y = b.method(b.owner("mid"), "C", "y");
    const tm = b.method(s, "Pricing", "quote"), im = b.method(s, "PricingLive", "quote");
    b.rel("calls", x, y);
    b.rel("calls", y, tm);
    const set = run(b, initialState(x, "downstream"));
    expect(shown(set)).toEqual([x, y, tm, im]);
    expect(set.reached.get(im)!.hop).toBe(2);
  });

  it("draws a two-way call once in both directions: one arrow, the loop marked on the far end", () => {
    const b = new MapBuilder();
    const a = b.method(b.owner("x"), "C", "a"), c = b.method(b.owner("y"), "C", "b");
    b.rel("calls", a, c);
    b.rel("calls", c, a);
    const set = run(b, initialState(a));
    expect(set.reached.get(c)!.loops).toEqual([a]);
    expect(set.hops.map((h) => [h.from, h.to])).toEqual([[a, c]]);
  });

  it("a cycle through an implementation step, from the trait method, draws the step once", () => {
    const b = new MapBuilder();
    const s = b.owner("pricing");
    const trait = b.cls(s, "Pricing");
    b.cls(s, "PricingLive", undefined, [trait]);
    const tm = b.method(s, "Pricing", "quote"), im = b.method(s, "PricingLive", "quote");
    b.rel("calls", im, tm);
    const set = run(b, initialState(tm));
    expect(set.reached.get(im)!.loops).toEqual([tm]);
    expect(set.hops.map((h) => [h.from, h.to, h.edge.kind])).toEqual([[tm, im, "implements"]]);
  });

  it("counts distinct neighbours: three edges to one handler are one neighbour, and the total equals what show all shows", () => {
    const b = new MapBuilder();
    const x = b.method(b.owner("shop"), "Api", "create");
    const h = b.method(b.owner("hub"), "C", "handle");
    b.rel("calls", x, h, { line: 1 });
    b.rel("event", x, h, { line: 2, key: "k1" });
    b.rel("event", x, h, { line: 3, key: "k2" });
    for (let i = 1; i <= 4; i++) b.rel("event", x, b.method(b.owner(`e${i}`), "C", `m${i}`), { line: 3 + i, key: `ev${i}` });
    const set = run(b, initialState(x, "downstream"));
    expect(set.reached.get(x)!.folds).toEqual([]);
    expect(set.reached.size).toBe(6);
    expect(set.hops.length).toBe(7);
  });

  it("a library fold counts every edge on its side, also those beyond the first FOLD_AT", () => {
    const b = new MapBuilder();
    const lib = b.owner("common", "library");
    const a = b.method(b.owner("billing"), "Api", "invoice");
    const r = b.method(lib, "Money", "round"), f = b.method(lib, "Money", "format");
    b.rel("calls", a, r, { line: 1 });
    for (let i = 2; i <= 6; i++) b.rel("calls", a, b.method(b.owner(`t${i}`), "C", `m${i}`), { line: i });
    b.rel("calls", a, f, { line: 9 });
    const set = run(b, initialState(a, "downstream"));
    expect(set.reached.get(a)!.folds).toEqual([{ side: 1, total: 7, word: "callees" }]);
    const fold = set.reached.get(`fold:${lib}|1`)!;
    expect([fold.calls, fold.members]).toEqual([2, [r, f]]);
  });

  it("a plain fold and a library fold on the same side", () => {
    const b = new MapBuilder();
    const lib = b.owner("common", "library");
    const a = b.method(b.owner("billing"), "Api", "invoice");
    b.rel("calls", a, b.method(lib, "Money", "round"), { line: 1 });
    for (let i = 2; i <= 7; i++) b.rel("calls", a, b.method(b.owner(`t${i}`), "C", `m${i}`), { line: i });
    const set = run(b, initialState(a, "downstream"));
    expect(set.reached.get(a)!.folds).toEqual([{ side: 1, total: 7, word: "callees" }]);
    expect(set.reached.size).toBe(1 + 1 + 4);
    expect(set.reached.has(`fold:${lib}|1`)).toBe(true);
  });

  it("a hop that arrives at a class itself is a gap", () => {
    const b = new MapBuilder();
    const s = b.owner("shop");
    const cls = b.cls(s, "Api");
    const m = b.method(b.owner("orders"), "C", "go");
    b.rel("request", cls, m, { key: "GET /x" });
    const set = run(b, initialState(m, "upstream"));
    expect(set.reached.get(cls)!.kind).toBe("gap");
  });

  it("a datastore with no tables is its own seed", () => {
    const b = new MapBuilder();
    const db = b.node({ id: "db:sql:DB", kind: "datastore", name: "db" });
    const w = b.method(b.owner("orders"), "Repo", "save");
    b.rel("db-write", w, db);
    const set = run(b, initialState(db, "upstream"));
    expect(set.seeds).toEqual([db]);
    expect(shown(set)).toEqual([db, w]);
  });
});
