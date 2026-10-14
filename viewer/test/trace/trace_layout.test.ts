import { describe, expect, it } from "vitest";
import { TraceGraph } from "../../src/trace/graph";
import { initialState, type TraceState } from "../../src/trace/reach";
import { BOX_W, COL_GAP, GUTTER, HEAD_H, INDENT, INDENT_LEVELS, ROW_H, arrowTitle, dataText, layoutTrace, traceTitle } from "../../src/trace/layout";
import { MapBuilder } from "./trace_fixture";

const view = (b: MapBuilder, st: TraceState) => { const m = b.model(); return layoutTrace(m, new TraceGraph(m), st); };

/** reservations.reserve → (request POST /v1/charges) billing.charge → billing.Repo.save (same box) → payments.pay;
 *  an upstream caller api.submit → reservations.reserve. */
function shop() {
  const b = new MapBuilder();
  const res = b.owner("reservations"), bill = b.owner("billing"), pay = b.owner("payments"), api = b.owner("api");
  const reservation = b.cls(res, "Reservation", [{ name: "bay", type: "str" }]);
  const submit = b.method(api, "Gate", "submit");
  const reserve = b.method(res, "Service", "reserve", [{ name: "bay", type: "BayId" }], "Reservation", [reservation]);
  const charge = b.method(bill, "Api", "charge", [{ name: "r", type: "Reservation", refs: [reservation] }], "ChargeId");
  const save = b.method(bill, "Repo", "save", [{ name: "charge", type: null }], "None");
  const payIt = b.method(pay, "Api", "pay", [{ name: "amount", type: "Money" }]);
  b.rel("calls", submit, reserve, { line: 3 });
  b.rel("request", reserve, charge, { key: "POST /v1/charges", line: 8 });
  b.rel("calls", charge, save, { line: 4 });
  b.rel("request", save, payIt, { key: "POST /v1/pay", line: 6, inferred: true });
  return { b, ids: { submit, reserve, charge, save, payIt, res, bill, pay, api } };
}

describe("layoutTrace: boxes, rows and arrows", () => {
  it("puts upstream boxes left of the focus and downstream boxes right, one column per box hop", () => {
    const { b, ids } = shop();
    const v = view(b, initialState(ids.reserve));
    const col = (owner: string) => v.boxes.find((x) => x.owner === owner)!.col;
    expect([col(ids.api), col(ids.res), col(ids.bill)]).toEqual([-1, 0, 1]);
    const x = (owner: string) => v.boxes.find((x) => x.owner === owner)!.x;
    expect(x(ids.api)).toBeLessThan(x(ids.res));
    expect(x(ids.res)).toBeLessThan(x(ids.bill));
    expect(v.rows.get(ids.reserve)!.focus).toBe(true);
    expect(v.boxes.some((x) => x.owner === ids.pay)).toBe(false);   // three hops from the focus
  });

  it("keeps a call within a service in its box, going down; a `+` shows on the frontier", () => {
    const { b, ids } = shop();
    const v = view(b, initialState(ids.reserve, "downstream"));
    const billing = v.boxes.find((x) => x.owner === ids.bill)!;
    expect(billing.rows.map((r) => r.id)).toEqual([ids.charge, ids.save]);
    expect(billing.rows[1].y).toBe(billing.rows[0].y + ROW_H);
    expect(billing.rows[0].y).toBe(billing.y + HEAD_H);
    expect(v.rows.get(ids.save)!.more).toBe(1);
    // an elbow down the caller's trunk into the callee, indented one level under it
    const inBox = v.arrows.find((a) => a.from === ids.charge && a.to === ids.save)!;
    const trunk = billing.x + GUTTER / 2, into = billing.x + GUTTER + INDENT, y = billing.rows[1].y + ROW_H / 2;
    expect(inBox.path).toBe(`M ${trunk} ${billing.rows[0].y + ROW_H - 6} V ${y} H ${into}`);
    expect(inBox.hit).toBe(`M ${trunk} ${y} H ${into}`);
  });

  it("orders rows in a box upstream first, then the focus, then downstream, each in call order", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const caller = b.method(s, "Api", "submit"), focus = b.method(s, "Api", "place");
    const late = b.method(s, "Repo", "save"), early = b.method(s, "Repo", "check");
    b.rel("calls", caller, focus);
    b.rel("calls", focus, late, { line: 20 });
    b.rel("calls", focus, early, { line: 5 });
    const v = view(b, initialState(focus));
    expect(v.boxes).toHaveLength(1);
    expect(v.boxes[0].rows.map((r) => r.id)).toEqual([caller, focus, early, late]);
  });

  it("draws an arrow across a gap from the right edge of one box to the left edge of the next, dashed when inferred", () => {
    const { b, ids } = shop();
    const v = view(b, { ...initialState(ids.charge, "downstream"), expanded: new Set() });
    const a = v.arrows.find((x) => x.to === ids.payIt)!;
    const from = v.rows.get(ids.save)!, to = v.rows.get(ids.payIt)!;
    expect(a.dashed).toBe(true);
    expect(a.path.startsWith(`M ${from.x + BOX_W} ${from.y + ROW_H / 2} H `)).toBe(true);
    expect(a.path.endsWith(`V ${to.y + ROW_H / 2} H ${to.x}`)).toBe(true);
    expect(v.arrows.find((x) => x.to === ids.save)!.dashed).toBe(false);
  });

  it("writes what arrives on each row: a request's key, then the parameter types in and the return type back", () => {
    const { b, ids } = shop();
    const v = view(b, initialState(ids.reserve, "downstream"));
    expect(v.rows.get(ids.charge)!.sub).toBe("POST /v1/charges · Reservation →  ← ChargeId");
    expect(v.rows.get(ids.save)!.sub).toBe("charge →");   // untyped: the parameter's name; None carries nothing back
  });

  it("dataText: types in, return back, nothing for a non-method", () => {
    const { b, ids } = shop();
    const m = b.model();
    expect(dataText(m, ids.reserve)).toBe("BayId →  ← Reservation");
    expect(dataText(m, ids.res)).toBe("");
  });

  it("names a library fold `common · 2 calls` with its methods below", () => {
    const b = new MapBuilder();
    const s = b.owner("billing"), lib = b.owner("common", "library");
    const a = b.method(s, "Api", "invoice");
    b.rel("calls", a, b.method(lib, "Money", "round"), { line: 2 });
    b.rel("calls", a, b.method(lib, "Money", "format"), { line: 3 });
    const v = view(b, initialState(a, "downstream"));
    const fold = v.rows.get(`fold:${lib}|1`)!;
    expect([fold.label, fold.sub]).toEqual(["common · 2 calls", "round, format"]);
    expect(v.boxes.find((x) => x.owner === lib)!.col).toBe(1);
    expect(v.nodes).toEqual([a, lib]);
  });

  it("marks a gap row `entry method not known` in its service's box", () => {
    const b = new MapBuilder();
    const svc = b.owner("worker");
    const h = b.method(b.owner("shop"), "Api", "create");
    b.rel("request", svc, h, { key: "POST /v1/orders" });
    const v = view(b, initialState(h, "upstream"));
    const row = v.rows.get(svc)!;
    expect([row.kind, row.sub, row.label]).toEqual(["gap", "entry method not known", "worker"]);
    expect(v.boxes.find((x) => x.owner === svc)!.col).toBe(-1);
  });

  it("draws a loop once: no arrow back, the row carries ↺", () => {
    const b = new MapBuilder();
    const a = b.method(b.owner("x"), "C", "a"), c = b.method(b.owner("y"), "C", "b");
    b.rel("calls", a, c);
    b.rel("calls", c, a);
    const v = view(b, initialState(a, "downstream"));
    expect(v.arrows.map((x) => [x.from, x.to])).toEqual([[a, c]]);
    expect(v.rows.get(c)!.loops).toEqual([a]);
  });

  it("puts a table in its own box: a reader's upstream reads the table, a writer's downstream writes it", () => {
    const b = new MapBuilder();
    const db = b.node({ id: "db:sql:DB", kind: "datastore", name: "db" });
    const t = b.node({ id: `${db}/public.orders`, kind: "table", name: "public.orders", parent: db });
    const w = b.method(b.owner("orders"), "Repo", "save"), r = b.method(b.owner("reports"), "Daily", "load");
    b.rel("db-write", w, t);
    b.rel("db-read", r, t);
    const v = view(b, initialState(t));
    const col = (id: string) => v.boxes.find((x) => x.rows.some((row) => row.id === id))!.col;
    expect([col(w), col(t), col(r)]).toEqual([-1, 0, 1]);
    expect(v.rows.get(t)!.sub).toBe("table");
  });

  it("titles a trace after its focus: a method's row label; a datastore by its own name, not its first table", () => {
    const b = new MapBuilder();
    const db = b.node({ id: "db:sql:DB", kind: "datastore", name: "billing-db" });
    const t1 = b.node({ id: `${db}/public.charges`, kind: "table", name: "public.charges", parent: db });
    b.node({ id: `${db}/public.invoices`, kind: "table", name: "public.invoices", parent: db });
    const w = b.method(b.owner("billing"), "Repo", "save");
    b.rel("db-write", w, t1);
    const m = b.model(), g = new TraceGraph(m);
    const ds = layoutTrace(m, g, initialState(db));
    expect(ds.rows.has(db)).toBe(false);   // its tables are the seeds
    expect(traceTitle(m, ds)).toBe(m.label(db));
    expect(traceTitle(m, layoutTrace(m, g, initialState(w)))).toBe("Repo.save");
  });

  it("counts methods and sizes the sheet to its columns", () => {
    const { b, ids } = shop();
    const v = view(b, initialState(ids.reserve));
    expect(v.methods).toBe(4);
    expect(v.width).toBe(16 * 2 + 3 * BOX_W + 2 * 120);
    expect(v.height).toBeGreaterThan(0);
  });

  it("arrowTitle says the kind, key, data, confidence and evidence", () => {
    const { b, ids } = shop();
    const m = b.model();
    const e = new TraceGraph(m).next(ids.reserve, 1)[0];
    expect(arrowTitle(m, e)).toBe("request · POST /v1/charges · Reservation →  ← ChargeId · confirmed · f.py:8");
  });
});

type Seg = { x1: number; y1: number; x2: number; y2: number };
/** The straight segments of an orthogonal `M x y H x V y …` path. */
function segments(path: string): Seg[] {
  const t = path.split(" "), out: Seg[] = [];
  let x = 0, y = 0;
  for (let i = 0; i < t.length;) {
    const c = t[i];
    if (c === "M") { x = +t[i + 1]; y = +t[i + 2]; i += 3; continue; }
    const n = +t[i + 1];
    out.push(c === "H" ? { x1: x, y1: y, x2: n, y2: y } : { x1: x, y1: y, x2: x, y2: n });
    if (c === "H") x = n; else y = n;
    i += 2;
  }
  return out;
}
const hits = (s: Seg, b: { x: number; y: number; w: number; h: number }) =>
  Math.max(s.x1, s.x2) > b.x && Math.min(s.x1, s.x2) < b.x + b.w && Math.max(s.y1, s.y2) > b.y && Math.min(s.y1, s.y2) < b.y + b.h;
/** Arrows that cross a box they neither start nor end in. */
function crossings(v: ReturnType<typeof view>) {
  const own = (id: string) => v.boxes.find((b) => b.rows.some((r) => r.id === id))!;
  return v.arrows.filter((a) => v.boxes.some((b) => b !== own(a.from) && b !== own(a.to) && segments(a.path).some((s) => hits(s, b))));
}
/** Pairs of arrows whose vertical segments lie on the same x and overlap in y. */
function sharedVerticals(v: ReturnType<typeof view>) {
  const out: string[] = [];
  const vs = v.arrows.map((a) => segments(a.path).filter((s) => s.x1 === s.x2));
  for (let i = 0; i < vs.length; i++) for (let j = i + 1; j < vs.length; j++)
    for (const p of vs[i]) for (const q of vs[j])
      if (p.x1 === q.x1 && Math.max(Math.min(p.y1, p.y2), Math.min(q.y1, q.y2)) < Math.min(Math.max(p.y1, p.y2), Math.max(q.y1, q.y2))) out.push(`${i}/${j}`);
  return out;
}

/** Pairs of in-box arrows whose hit segments (8 px tall strokes) touch: a click there could pick the wrong one. */
function overlappingHits(arrows: ReturnType<typeof view>["arrows"]) {
  const out: string[] = [];
  const hs = arrows.map((a) => segments(a.hit)[0]);
  for (let i = 0; i < hs.length; i++) for (let j = i + 1; j < hs.length; j++) {
    const p = hs[i], q = hs[j];
    if (p.y1 !== p.y2 || q.y1 !== q.y2) continue;
    const xo = Math.max(Math.min(p.x1, p.x2), Math.min(q.x1, q.x2)) < Math.min(Math.max(p.x1, p.x2), Math.max(q.x1, q.x2));
    if (xo && Math.abs(p.y1 - q.y1) < 8) out.push(`${arrows[i].id} / ${arrows[j].id}`);
  }
  return out;
}

describe("layoutTrace: routing and order", () => {
  it("routes a two-column arrow round the boxes between (diamond)", () => {
    const b = new MapBuilder();
    const A = b.owner("a"), B = b.owner("b"), D = b.owner("d");
    const f = b.method(A, "C", "f"), x = b.method(A, "C", "x"), bb = b.method(B, "C", "b"), d = b.method(D, "C", "d");
    b.rel("calls", f, bb, { line: 1 });
    b.rel("calls", f, x, { line: 2 });
    b.rel("calls", bb, d, { line: 1 });
    b.rel("calls", x, d, { line: 1 });
    const v = view(b, initialState(f, "downstream"));
    expect(v.arrows).toHaveLength(4);
    expect(v.boxes.find((q) => q.owner === D)!.col).toBe(2);
    expect(crossings(v)).toEqual([]);
    expect(sharedVerticals(v)).toEqual([]);
    expect(Math.max(...v.arrows.flatMap((a) => segments(a.path).map((s) => Math.max(s.y1, s.y2)))) + 16).toBeLessThanOrEqual(v.height);
  });

  it("routes a backward arrow from the left edge, and a two-column backward one round the boxes between", () => {
    const b = new MapBuilder();
    const A = b.owner("a"), B = b.owner("b"), C = b.owner("c");
    const f = b.method(A, "C", "f"), x = b.method(A, "C", "x"), g = b.method(B, "C", "g"), h = b.method(C, "C", "h");
    b.rel("calls", f, g, { line: 1 });
    b.rel("calls", f, x, { line: 2 });
    b.rel("calls", g, x, { line: 1 });       // back to column 0 from column 1
    b.rel("calls", g, h, { line: 2 });
    b.rel("calls", h, x, { line: 1 });       // back across column 1 from column 2
    const v = view(b, { ...initialState(f, "downstream"), expanded: new Set([h]) });
    const back = v.arrows.find((a) => a.from === g && a.to === x)!;
    const from = v.rows.get(g)!, to = v.rows.get(x)!;
    expect(back.path.startsWith(`M ${from.x} ${from.y + 20} H `)).toBe(true);
    expect(back.path.endsWith(`V ${to.y + 20} H ${to.x + BOX_W}`)).toBe(true);
    const far = v.arrows.find((a) => a.from === h && a.to === x)!;
    expect(far).toBeDefined();
    expect(crossings(v)).toEqual([]);
    expect(sharedVerticals(v)).toEqual([]);
  });

  it("keeps a hop between two boxes of one column off the forward lanes", () => {
    const b = new MapBuilder();
    const A = b.owner("a"), B = b.owner("b"), C = b.owner("c");
    const f = b.method(A, "C", "f"), g = b.method(B, "C", "g"), h = b.method(C, "C", "h");
    b.rel("calls", f, g, { line: 1 });
    b.rel("calls", f, h, { line: 2 });
    b.rel("calls", g, h, { line: 1 });
    const v = view(b, initialState(f, "downstream"));
    const side = v.arrows.find((a) => a.from === g && a.to === h)!;
    const right = v.rows.get(g)!.x + BOX_W;
    const vx = segments(side.path).find((s) => s.x1 === s.x2)!.x1 - right;
    expect(vx).toBeGreaterThan(0);
    expect(vx).toBeLessThan(10);
    expect(crossings(v)).toEqual([]);
    expect(sharedVerticals(v)).toEqual([]);
  });

  it("gives calls from one caller to several callees in another box a lane each (wrapping after 14), in its own box one trunk", () => {
    const b = new MapBuilder();
    const A = b.owner("a"), B = b.owner("b");
    const f = b.method(A, "C", "f");
    const ids: string[] = [];
    for (let i = 0; i < 15; i++) { const g = b.method(B, "C", `g${String(i).padStart(2, "0")}`); ids.push(g); b.rel("calls", f, g, { line: i + 1 }); }
    const w = b.method(A, "C", "w"), u = b.method(A, "C", "u"), t = b.method(A, "C", "t");
    b.rel("calls", f, w, { line: 20 });
    b.rel("calls", f, u, { line: 21 });
    b.rel("calls", f, t, { line: 22 });
    const st = { ...initialState(f, "downstream"), showAll: new Set([`${f}|1`]) };
    const v = view(b, st);
    const gap = v.arrows.filter((a) => ids.includes(a.to));
    const xs = gap.map((a) => segments(a.path).find((s) => s.x1 === s.x2)!.x1);
    expect(new Set(xs).size).toBe(14);
    expect(xs[14]).toBe(xs[0]);
    expect(Math.max(...xs) - (v.rows.get(f)!.x + BOX_W)).toBeLessThan(COL_GAP);
    // in the box: one trunk at the caller's indent, an elbow into each callee
    const inBox = v.arrows.filter((a) => [w, u, t].includes(a.to));
    expect(new Set(inBox.map((a) => segments(a.path)[0].x1)).size).toBe(1);
    expect(overlappingHits(inBox)).toEqual([]);
  });

  it("indents rows in a box by their call depth, capped at INDENT_LEVELS levels", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const chain = Array.from({ length: INDENT_LEVELS + 3 }, (_, i) => b.method(s, "Api", `m${i}`));
    for (let i = 1; i < chain.length; i++) b.rel("calls", chain[i - 1], chain[i]);
    const st = { ...initialState(chain[0], "downstream"), expanded: new Set(chain) };
    const v = view(b, st);
    const rows = v.boxes[0].rows;
    expect(rows.map((r) => r.id)).toEqual(chain);
    expect(rows.map((r) => r.depth)).toEqual(chain.map((_, i) => i));
    expect(rows.map((r) => r.indent)).toEqual(chain.map((_, i) => Math.min(i, INDENT_LEVELS) * INDENT));
    // past the cap the callee sits level with its caller: the elbow is still its own, a short step right of the trunk
    const last = v.arrows.find((a) => a.to === chain[chain.length - 1])!;
    const box = v.boxes[0], cap = INDENT_LEVELS * INDENT;
    expect(last.hit).toBe(`M ${box.x + GUTTER / 2 + cap} ${rows[rows.length - 1].y + ROW_H / 2} H ${box.x + GUTTER + cap}`);
    expect(overlappingHits(v.arrows)).toEqual([]);
  });

  it("draws a call tree in a box: siblings share their caller's trunk, each callee its own elbow", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const f = b.method(s, "Api", "f"), a = b.method(s, "Api", "a"), a1 = b.method(s, "Api", "a1"), c = b.method(s, "Api", "b");
    b.rel("calls", f, a, { line: 1 });
    b.rel("calls", f, c, { line: 2 });
    b.rel("calls", a, a1, { line: 1 });
    const v = view(b, initialState(f, "downstream"));
    const box = v.boxes[0], row = (id: string) => v.rows.get(id)!;
    expect([f, a, a1, c].map((id) => row(id).depth)).toEqual([0, 1, 2, 1]);
    const arrow = (to: string) => v.arrows.find((x) => x.to === to)!;
    const trunkF = box.x + GUTTER / 2, trunkA = trunkF + INDENT;
    expect(segments(arrow(a).path)[0]).toEqual({ x1: trunkF, y1: row(f).y + ROW_H - 6, x2: trunkF, y2: row(a).y + ROW_H / 2 });
    expect(segments(arrow(c).path)[0].x1).toBe(trunkF);
    expect(segments(arrow(a1).path)[0].x1).toBe(trunkA);
    expect(arrow(a1).hit).toBe(`M ${trunkA} ${row(a1).y + ROW_H / 2} H ${box.x + GUTTER + 2 * INDENT}`);
    expect(overlappingHits(v.arrows)).toEqual([]);
  });

  it("mirrors the tree for callers in a box: a caller above its callee, one level in, the elbow pointing back up the trunk", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const focus = b.method(s, "Api", "place"), u1 = b.method(s, "Api", "submit"), u2 = b.method(s, "Api", "route");
    const v1 = b.method(s, "Api", "retry");
    b.rel("calls", u1, focus);
    b.rel("calls", u2, u1);
    b.rel("calls", v1, focus);
    const v = view(b, initialState(focus, "upstream"));
    const box = v.boxes[0], row = (id: string) => v.rows.get(id)!;
    const order = box.rows.map((r) => r.id);
    expect(order).toHaveLength(4);
    expect(order.indexOf(u2)).toBe(order.indexOf(u1) - 1);   // each caller's own callers just above it
    expect(order[3]).toBe(focus);
    expect([u2, u1, v1, focus].map((id) => row(id).depth)).toEqual([2, 1, 1, 0]);
    const up = v.arrows.find((x) => x.from === u1 && x.to === focus)!;
    const trunk = box.x + GUTTER / 2, y = row(u1).y + ROW_H / 2;
    expect(up.path).toBe(`M ${box.x + GUTTER + INDENT} ${y} H ${trunk} V ${row(focus).y + 6}`);
    expect(up.hit).toBe(`M ${trunk} ${y} H ${box.x + GUTTER + INDENT}`);
    expect(overlappingHits(v.arrows)).toEqual([]);
  });

  it("gives a second arrow into a row in a box its own elbow, off the row's middle", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const f = b.method(s, "Api", "f"), a = b.method(s, "Api", "a"), c = b.method(s, "Api", "c");
    b.rel("calls", f, a, { line: 1 });
    b.rel("calls", f, c, { line: 2 });
    b.rel("calls", a, c, { line: 3 });
    const v = view(b, initialState(f, "downstream"));
    const into = v.arrows.filter((x) => x.to === c);
    expect(into).toHaveLength(2);
    expect(new Set(into.map((x) => segments(x.hit)[0].y1)).size).toBe(2);
    expect(overlappingHits(v.arrows)).toEqual([]);
  });

  it("lists downstream rows depth-first in a box: a callee's callees before its next sibling", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const f = b.method(s, "Api", "f"), a = b.method(s, "Api", "a"), a1 = b.method(s, "Api", "a1"), c = b.method(s, "Api", "b");
    b.rel("calls", f, a, { line: 1 });
    b.rel("calls", f, c, { line: 2 });
    b.rel("calls", a, a1, { line: 1 });
    const v = view(b, initialState(f, "downstream"));
    expect(v.boxes[0].rows.map((r) => r.id)).toEqual([f, a, a1, c]);
  });

  it("shows nothing back for wrapped void returns", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const rets = ["Promise<void>", "Task[Unit]", "UIO[Unit]", "IO[Unit]", "Future[Unit]", "Mono<Void>", "( )", "()",
      "ZIO[Any, Throwable, Unit]", "IO[Throwable, Unit]", "URIO[R, Unit]", "RIO[R, Unit]", "Task", "ValueTask"];
    const ids = rets.map((r, i) => b.method(s, "Api", `m${i}`, [{ name: "q", type: "Q" }], r));
    const keep = b.method(s, "Api", "keep", [], "Promise<Order>");
    const m = b.model();
    for (const id of ids) expect(dataText(m, id)).toBe("Q →");
    expect(dataText(m, keep)).toBe("← Promise<Order>");
    const zk = b.method(s, "Api", "zkeep", [], "ZIO[Any, Throwable, Map[String, Order]]");
    expect(dataText(b.model(), zk)).toBe("← ZIO[Any, Throwable, Map[String, Order]]");
  });

  it("shows a library fold on each side as two boxes of the one library", () => {
    const b = new MapBuilder();
    const s = b.owner("billing"), lib = b.owner("common", "library");
    const f = b.method(s, "Api", "run");
    b.rel("calls", f, b.method(lib, "Money", "round"), { line: 1 });
    b.rel("calls", b.method(lib, "Hooks", "tick"), f, { line: 1 });
    const v = view(b, initialState(f));
    expect(v.boxes.filter((x) => x.owner === lib).map((x) => x.col).sort()).toEqual([-1, 1]);
    expect([v.rows.has(`fold:${lib}|1`), v.rows.has(`fold:${lib}|-1`)]).toEqual([true, true]);
    expect(v.nodes.filter((n) => n === lib)).toHaveLength(1);
    expect(crossings(v)).toEqual([]);
  });
});
