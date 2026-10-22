import { describe, expect, it } from "vitest";
import { centreLine, implementsDots } from "../../src/factory/implements";
import { cleanBreaks, fitLine, fitName, fitSignature } from "../../src/factory/fit";
import { Graphics } from "pixi.js";
import { bodyFor, factoryOps, forwardLane, forwardLaneAt, paintHousing, paintPlate, tileArms } from "../../src/factory/pieces";
import { shape } from "../../src/factory/shape";
import { FOOT, STEP, T, type Box, type Dir, type Piece } from "../../src/factory/tiles";
import { nameSpec, paintStoreArt, storeArt, storeLegend, type Store } from "../../src/factory/machines";
import { chestFit, chestSize, shownWhole } from "../../src/factory/fit";

const piece = (inn: Piece["in"], out: Piece["out"]): Piece => ({ x: 2, y: 3, in: inn, out, under: false, hoodBefore: false, hoodAfter: false });

describe("piece shape", () => {
  it("knows a straight piece's edges", () => {
    const s = shape(piece("e", "e"));
    expect(s.straight).toBe(true);
    expect(s.inEdge).toEqual([-1, 0]);
    expect(s.outEdge).toEqual([1, 0]);
    expect([s.cx, s.cy]).toEqual([2.5 * T, 3.5 * T]);
  });

  it("finds the inner corner of a turn", () => {
    const s = shape(piece("e", "s"));   // in from the west edge, out by the south edge
    expect(s.straight).toBe(false);
    expect(s.corner).toEqual([2 * T, 4 * T]);   // bottom-left corner of the tile
    expect(s.edge(s.outEdge)).toEqual([2.5 * T, 4 * T]);
  });
});

describe("fitName", () => {
  it("keeps the largest size that fits, wrapping at separators", () => {
    expect(fitName("market", 106, 2)).toEqual({ lines: ["market"], size: 14 });
    const r = fitName("pricing-engine", 106, 2);
    expect(r.size).toBe(14);
    expect(r.lines).toEqual(["pricing-", "engine"]);
  });

  it("wraps an installed library's name at underscores", () => {
    expect(fitName("common_python", 84, 4, [12, 11, 10]).lines).toEqual(["common_", "python"]);
  });

  it("shrinks a long name without separators, then keeps its front and ends with an ellipsis", () => {
    const name = "AbstractSingletonProxyFactoryBeanConfigurationRegistryProviderImpl";
    const r = fitName(name, 106, 2);
    expect(r.size).toBe(10);
    expect(r.lines).toHaveLength(2);
    expect(r.lines[0].startsWith("…")).toBe(false);
    expect(r.lines[1].endsWith("…")).toBe(true);
    expect(r.lines.join("").startsWith("AbstractSingleton")).toBe(true);
    const per = Math.floor(106 / (10 * 0.56));
    for (const l of r.lines) expect(l.length).toBeLessThanOrEqual(per);
  });

  it("takes a smaller size over a break inside a word: a hub's `reservation-events` reads `reservation-` / `events`", () => {
    const hub = nameSpec({ id: "h", kind: "topic", foot: "hub", region: "", x: 0, y: 0, w: FOOT.hub[0], h: FOOT.hub[1] });
    expect(fitName("reservation-events", hub.w, hub.maxLines, hub.sizes)).toEqual({ lines: ["reservation-", "events"], size: 10 });
    expect(fitName("reservation-events.dlq", hub.w, hub.maxLines, hub.sizes).lines).toEqual(["reservation-", "events.dlq"]);
    expect(cleanBreaks("reservation-events", ["reservatio", "n-events"])).toBe(false);
    expect(cleanBreaks("reservation-events", ["reservation", "-events"])).toBe(false);   // before the hyphen strands it
    expect(cleanBreaks("Stripe API REST (api.stripe.com)", ["Stripe API REST", "(api.stripe.com)"])).toBe(true);
    expect(cleanBreaks("DiscordNotifier", ["Discord", "Notifier"])).toBe(true);
    expect(cleanBreaks("Stripe API REST", ["Stripe API", "REST"])).toBe(true);   // at a space: the line was trimmed before it
    expect(cleanBreaks("reservation-events", ["reserv ation", "events"])).toBe(false);   // a line not in the name: not clean
  });

  it("trades at most one size for a clean break: a name clean only two sizes down keeps its old wrap", () => {
    // at the old 64 px hub room: 11 px breaks "reservatio", 10 px breaks before the hyphen, only 9 px is clean
    expect(fitName("reservation-events", 64, 2, [11, 10, 9])).toEqual({ lines: ["reservatio", "n-events"], size: 11 });
  });

  it("keeps a break inside a word only when no size breaks between words", () => {
    expect(fitName("Supercalifragilistic", 64, 2, [11, 10])).toEqual({ lines: ["Supercalif", "ragilistic"], size: 11 });
  });
});

describe("fitSignature", () => {
  it("shows every parameter when it fits at 10 px", () => {
    expect(fitSignature(["a", "b", "c"], 100)).toBe("(a, b, c)");
    expect(fitSignature([], 100)).toBe("()");
  });
  it("keeps as many leading parameters as fit, then a count; never cuts from the front", () => {
    const p = ["symbol", "interval", "start", "end", "limit"];
    expect(fitSignature(p, 120)).toBe("(symbol, interval, …)");
    expect(fitSignature(p, 40)).toBe("(5 params)");
    expect(fitSignature(["only"], 10)).toBe("(1 param)");
    for (const w of [20, 40, 60, 80, 100, 140]) expect(fitSignature(p, w).startsWith("(")).toBe(true);
  });
});

describe("fitLine", () => {
  it("keeps the largest size that fits", () => {
    expect(fitLine("3 inside", 100)).toEqual({ text: "3 inside", size: 11 });
  });
  it("drops leading path segments, keeping the verb and the specific end", () => {
    expect(fitLine("GET /v1/orders/{id}", 95).text).toBe("GET /orders/{id}");
    expect(fitLine("external · stream.stripe.com/streams", 110).text).toBe("external · streams");
  });
  it("never starts with an ellipsis", () => {
    for (const w of [20, 30, 50, 70]) expect(fitLine("a very long sub line indeed", w).text.startsWith("…")).toBe(false);
    expect(fitLine("a very long sub line indeed", 70).text.endsWith("…")).toBe(true);
  });
});

describe("two-way belt lanes", () => {
  const DS: Dir[] = ["n", "e", "s", "w"];
  const at = (x: number, y: number, inn: Dir, out: Dir): Piece => ({ ...piece(inn, out), x, y });

  it("a straight puts the forward lane on the right of travel", () => {
    // screen y points down: right of east is south, of south is west, of west is north, of north is east
    const right: Record<Dir, [number, number]> = { e: [0, 1], s: [-1, 0], w: [0, -1], n: [1, 0] };
    for (const d of DS) {
      const s = shape(piece(d, d)), [px, py] = forwardLaneAt(piece(d, d), "out"), m = s.edge(s.outEdge);
      expect(forwardLane(piece(d, d)).side).toBe("right");
      expect([px - m[0], py - m[1]]).toEqual([right[d][0] * 6, right[d][1] * 6]);
    }
  });

  it("a corner puts it on the inner arc for a right turn and the outer arc for a left turn", () => {
    const turns: [Dir, Dir, "inner" | "outer"][] = [["e", "s", "inner"], ["s", "w", "inner"], ["w", "n", "inner"], ["n", "e", "inner"],
      ["e", "n", "outer"], ["n", "w", "outer"], ["w", "s", "outer"], ["s", "e", "outer"]];
    for (const [a, b, side] of turns) expect(forwardLane(piece(a, b)).side, a + b).toBe(side);
  });

  it("the forward lane stays continuous from a straight through a corner to the next straight", () => {
    for (const a of DS) for (const b of DS) {
      if (a === b || STEP[a][0] + STEP[b][0] === 0 && STEP[a][1] + STEP[b][1] === 0) continue;
      const [dx, dy] = STEP[a], [ex, ey] = STEP[b];
      const before = at(5 - dx, 5 - dy, a, a), corner = at(5, 5, a, b), after = at(5 + ex, 5 + ey, b, b);
      const l0 = forwardLaneAt(before, "out"), l1 = forwardLaneAt(corner, "in"), l2 = forwardLaneAt(corner, "out"), l3 = forwardLaneAt(after, "in");
      expect(l1[0], a + b).toBeCloseTo(l0[0]); expect(l1[1], a + b).toBeCloseTo(l0[1]);
      expect(l3[0], a + b).toBeCloseTo(l2[0]); expect(l3[1], a + b).toBeCloseTo(l2[1]);
    }
  });
});

describe("underground housings and junction bands", () => {
  const at = (x: number, y: number, inn: Dir, out: Dir, extra: Partial<Piece> = {}): Piece => ({ ...piece(inn, out), x, y, ...extra });
  const bounds = (draw: (g: Graphics) => void) => { const g = new Graphics(); draw(g); const b = g.getLocalBounds(); return { x0: b.minX, y0: b.minY, x1: b.maxX, y1: b.maxY }; };

  it("a two-way belt's housing draws two chevrons, a one-way belt's one larger one", () => {
    const hood = at(2, 3, "e", "e", { hoodBefore: true });
    const one = bounds((g) => paintHousing(g, hood, "belt", false)), two = bounds((g) => paintHousing(g, hood, "belt", true));
    expect(two.y1 - two.y0).toBeLessThanOrEqual(one.y1 - one.y0);   // both stay inside the housing
    const g1 = new Graphics(), g2 = new Graphics();
    paintHousing(g1, hood, "belt", false); paintHousing(g2, hood, "belt", true);
    expect(g2.context.instructions.length).toBeGreaterThan(g1.context.instructions.length);
  });

  it("a junction is the whole 1x1 plate, over the tile", () => {
    const b = bounds((g) => paintPlate(g, at(2, 3, "e", "e", { join: "split" })));
    expect(b.x1 - b.x0).toBeGreaterThan(T - 2);
    expect(b.y1 - b.y0).toBeGreaterThan(T - 2);
    expect(b.x0).toBeLessThan(2 * T + 1);
  });

  const belt = (pieces: Piece[], both = false) => ({ pieces, kind: "belt" as const, both });
  const arms = (rs: ReturnType<typeof belt>[]) => tileArms(rs, 10).get(1 * 10 + 2)!;

  it("two one-way belts on one straight compose one straight with one chevron", () => {
    const a = arms([belt([at(2, 1, "e", "e")]), belt([at(2, 1, "e", "e")])]);
    const b = bodyFor(a)!;
    expect(b.both).toBe(false);
    expect(b.branches).toEqual([]);
    expect([b.p.in, b.p.out]).toEqual(["e", "e"]);
  });

  it("a one-way belt and a two-way belt on the same axis compose a two-way piece", () => {
    expect(bodyFor(arms([belt([at(2, 1, "e", "e")]), belt([at(2, 1, "w", "w")], true)]))!.both).toBe(true);
    expect(bodyFor(arms([belt([at(2, 1, "e", "e")]), belt([at(2, 1, "w", "w")])]))!.both).toBe(true);   // opposite ways on one tile
  });

  it("a split T is the trunk's straight plus a branch leaving by its edge, shown as the plate alone", () => {
    const rs = [belt([at(2, 1, "e", "e")]), belt([at(2, 1, "e", "n", { join: "split" })])];
    const b = bodyFor(arms(rs))!;
    expect([b.p.in, b.p.out, b.both]).toEqual(["e", "e", false]);
    expect(b.branches).toEqual([{ edge: "n", flow: "out" }]);
    expect(factoryOps(rs, 10).filter((o) => o.layer === "plate")).toHaveLength(1);
  });

  it("a merge T is the trunk plus a half arm entering by the branch edge", () => {
    const rs = [belt([at(2, 1, "e", "e")]), belt([at(2, 1, "n", "e", { join: "merge" })])];   // travelling north, it comes up through the south edge
    const b = bodyFor(arms(rs))!;
    expect([b.p.in, b.p.out]).toEqual(["e", "e"]);
    expect(b.branches).toEqual([{ edge: "s", flow: "in" }]);
    expect(factoryOps(rs, 10).filter((o) => o.layer === "plate")).toHaveLength(1);
  });

  it("a turn shared by two lines is one corner; four unmarked arms are no tile (a crossing goes underground)", () => {
    const b = bodyFor(arms([belt([at(2, 1, "e", "s")]), belt([at(2, 1, "e", "s")])]))!;
    expect([b.p.in, b.p.out]).toEqual(["e", "s"]);
    expect(bodyFor(arms([belt([at(2, 1, "e", "e")]), belt([at(2, 1, "s", "s")])]))).toBeNull();
  });

  it("a shared plain belt tile emits ONE tile op carrying every route and no body op; a junction is its plate alone", () => {
    const plain = [belt([at(2, 1, "e", "e")]), belt([at(2, 1, "e", "e")])];
    const ops = factoryOps(plain, 10);
    expect(ops.filter((o) => o.layer === "tile")).toHaveLength(1);
    expect(ops.filter((o) => o.layer === "body")).toHaveLength(0);
    expect(ops.find((o) => o.layer === "tile")!.holders).toEqual([0, 1]);
    const t = [belt([at(2, 1, "e", "e")]), belt([at(2, 1, "e", "n", { join: "split" }), at(2, 0, "n", "n")])];
    const jo = factoryOps(t, 10);
    expect(jo.filter((o) => o.p.x === 2 && o.p.y === 1).map((o) => o.layer)).toEqual(["plate"]);
    expect(jo.find((o) => o.layer === "plate")!.holders).toEqual([0, 1]);
  });

  it("a housing on a shared tile is drawn once", () => {
    const h = at(2, 1, "e", "e", { hoodBefore: true });
    const ops = factoryOps([belt([h]), belt([h], true)], 10);
    const hs = ops.filter((o) => o.layer === "housing");
    expect(hs).toHaveLength(1);
    expect(hs[0].both).toBe(true);
  });
});

describe("implements link", () => {
  it("is a straight row of dots from centre to centre, not routed", () => {
    const dots = implementsDots({ x: 0, y: 0, w: 48, h: 48 }, { x: 240, y: 120, w: 48, h: 48 });
    expect(dots[0]).toEqual({ x: 24, y: 24 });
    const last = dots[dots.length - 1];
    expect(Math.hypot(264 - last.x, 144 - last.y)).toBeLessThan(7);
    for (const p of dots) expect(Math.abs((p.y - 24) * 240 - (p.x - 24) * 120)).toBeLessThan(1e-6);   // on the one straight line
  });

  it("is the path a moving part follows: two points, centre to centre", () => {
    expect(centreLine({ x: 0, y: 0, w: 48, h: 48 }, { x: 240, y: 120, w: 48, h: 48 })).toEqual([{ x: 24, y: 24 }, { x: 264, y: 144 }]);
  });
});

describe("chest size", () => {
  it("is the narrowest chest that shows the whole name: a short name 2x2, a long one wider, too long for any: none", () => {
    expect(chestSize("redis")).toEqual([2, 2]);
    expect(chestSize("reservations-redis")).toEqual([4, 3]);
    expect(chestFit("reservations-redis", 4, 3)!.lines).toEqual(["reservations-", "redis"]);
    expect(chestSize("an-extraordinarily-long-cache-name-for-the-session-store")).toBeUndefined();
    expect(chestSize("sessioncachewithoutanyseparators")).toBeUndefined();   // never cut mid-word, never "…"
  });
  it("knows a whole name: every break after a hyphen, an underscore or a dot, nothing cut", () => {
    expect(shownWhole("a-b", ["a-", "b"])).toBe(true);
    expect(shownWhole("a_b.c", ["a_", "b.c"])).toBe(true);
    expect(shownWhole("reservations", ["reser", "vations"])).toBe(false);
    expect(shownWhole("reservations-redis", ["reser", "vati…"])).toBe(false);
  });
});

describe("store art", () => {
  const laneEnd: Box = { id: "db", kind: "datastore", foot: "warehouse", region: "bus", x: 2, y: 3, w: FOOT.warehouse[0], h: FOOT.warehouse[1] };
  const chest: Box = { id: "db", kind: "datastore", foot: "chest", region: "chest", x: 4, y: 5, w: FOOT.chest[0], h: FOOT.chest[1] };
  it("picks the art by store: database and warehouse as today, a cache a chest, a bucket a container yard, none a database", () => {
    const art = (s?: Store) => storeArt(laneEnd, s);
    expect([art("database"), art("warehouse"), art("cache"), art("bucket"), art(undefined)]).toEqual(["warehouse", "warehouse", "chest", "yard", "warehouse"]);
    expect(storeArt(chest, "cache")).toBe("chest");
    expect(storeArt({ ...laneEnd, kind: "service", foot: "service" }, undefined)).toBeUndefined();
  });
  it("draws each store's art without error, inside its box (the footprint is kept)", () => {
    expect(FOOT.chest).toEqual([2, 2]);
    for (const b of [laneEnd, chest]) for (const s of ["database", "cache", "bucket", "warehouse", undefined] as (Store | undefined)[]) {
      const art = storeArt(b, s)!;
      const g = new Graphics();
      expect(() => paintStoreArt(g, b, art), `${b.foot} ${s}`).not.toThrow();
      const r = g.getLocalBounds();
      expect(r.width, `${b.foot} ${s} draws something`).toBeGreaterThan(0);
      expect(r.minX, `${b.foot} ${s}`).toBeGreaterThanOrEqual(b.x * T - 1);
      expect(r.minY, `${b.foot} ${s}`).toBeGreaterThanOrEqual(b.y * T - 1);
      expect(r.maxX, `${b.foot} ${s}`).toBeLessThanOrEqual((b.x + b.w) * T + 1);
      expect(r.maxY, `${b.foot} ${s}`).toBeLessThanOrEqual((b.y + b.h) * T + 1);
    }
  });
  it("the legend lists Cache and Bucket only when the floor has one", () => {
    const store = new Map<Box, Store | undefined>([[laneEnd, "database"]]);
    expect(storeLegend(store.keys(), (b) => store.get(b))).toBeNull();
    expect(storeLegend([laneEnd, chest], (b) => (b === chest ? "cache" : "database"))).toEqual({ cache: true });
    expect(storeLegend([laneEnd], () => "bucket")).toEqual({ bucket: true });
  });
});

describe("a line drawn straight", () => {
  it("wears a small × every 36 px of its length, the first 18 px in, across its bends", async () => {
    const { crossMarks } = await import("../../src/floor/draw");
    const at: [number, number][] = [];
    const g = { moveTo(x: number, y: number) { at.push([x, y]); return g; }, lineTo() { return g; }, stroke() { return g; } };
    crossMarks(g as unknown as Graphics, [{ x: 0, y: 0 }, { x: 60, y: 0 }, { x: 60, y: 40 }], 36, 4, { width: 2, color: 0 });
    // two strokes a mark, from its top-left and its bottom-left corner: centres at 18 and 54 along, then 90 (30 down the bend)
    expect(at.filter((_, i) => i % 2 === 0).map(([x, y]) => [x + 4, y + 4])).toEqual([[18, 0], [54, 0], [60, 30]]);
  });
});
