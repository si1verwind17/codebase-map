import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { floorNote, isFocus, ownBox, traceItems, traceKeys, traceMarks, traceSubject } from "../../src/trace/floor";
import shop from "../fixtures/shop.code-map.json";

const m = new Model(shop as unknown as CodeMap);
const RUN = "worker::worker.main#run/2", SAVE = "shop::io.demo.shop.repo.PgOrderRepo#save/2", TOPIC = "topic:kafka:orders";

describe("the trace on the floor", () => {
  it("on the site floor: the services and the topic the trace passes through", () => {
    expect(traceItems(m, SITE, [SAVE, TOPIC, RUN])).toEqual(new Set(["svc:shop", TOPIC, "svc:worker"]));
  });

  it("lights only the lines between two traced items", () => {
    const items = traceItems(m, SITE, [SAVE, TOPIC, RUN]);
    const keys = traceKeys(m, SITE, items);
    expect(keys.length).toBeGreaterThan(0);
    const all = m.bundles(SITE);
    for (const k of keys) {
      const b = [...all.bundles, ...all.layered].find((x) => x.key === k)!;
      expect(items.has(b.a) && items.has(b.b), k).toBe(true);
    }
    expect(traceKeys(m, SITE, new Set(["svc:shop"]))).toEqual([]);
  });

  it("inside a service: its own items, and a door for what is outside", () => {
    const items = traceItems(m, "svc:worker", [RUN, TOPIC]);
    expect(items.has(m.liftTo("svc:worker", RUN)!)).toBe(true);
    expect([...items].some((id) => id.startsWith("door:"))).toBe(true);
  });

  it("an unknown node is skipped", () => {
    expect(traceItems(m, SITE, ["nope"])).toEqual(new Set());
  });
});

describe("the picked mark and the floor note", () => {
  it("marks one item: the pointed node when a row is pointed, else the focus, lifted to the floor (spec A1)", () => {
    expect(traceMarks(m, SITE, SAVE, RUN)).toEqual(["svc:worker"]);
    expect(traceMarks(m, SITE, SAVE, SAVE)).toEqual(["svc:shop"]);
    expect(traceMarks(m, SITE, SAVE, null)).toEqual(["svc:shop"]);
  });

  it("marks nothing for a node with no item on the shown floor, not in the map, or a line's trace with no row pointed", () => {
    expect(m.liftTo("svc:worker", SAVE)).toBeUndefined();
    expect(traceMarks(m, "svc:worker", SAVE, RUN)).toEqual([m.liftTo("svc:worker", RUN)]);
    expect(traceMarks(m, SITE, "nope", null)).toEqual([]);
    expect(traceMarks(m, SITE, "line:svc:shop|svc:worker", null)).toEqual([]);
  });

  it("a pointed row with no mark on the shown floor leaves the ring on the focus", () => {
    expect(m.liftTo("svc:worker", SAVE)).toBeUndefined();
    expect(m.bundles("svc:worker").doors.map((d) => d.id)).not.toContain(m.doorId(m.anchorFor("svc:worker", SAVE)));
    expect(traceMarks(m, "svc:worker", RUN, SAVE)).toEqual([m.liftTo("svc:worker", RUN)]);
  });

  it("a node on another floor reached through a door of the shown floor marks that door: it's that way", () => {
    const c = m.floorOf(SAVE)!;
    expect(m.liftTo(c, TOPIC)).toBeUndefined();
    expect(m.bundles(c).doors.map((d) => d.id)).toContain("door:topic:kafka:orders");
    expect(traceMarks(m, c, SAVE, TOPIC)).toEqual(["door:topic:kafka:orders"]);
    expect(traceMarks(m, "svc:worker", TOPIC, null)).toEqual(["door:topic:kafka:orders"]);
    // no door leads there from this floor: nothing is marked for it
    expect(m.bundles("svc:worker").doors.map((d) => d.id)).not.toContain(m.doorId(m.anchorFor("svc:worker", SAVE)));
    expect(traceMarks(m, "svc:worker", SAVE, null)).toEqual([]);
  });

  it("names the node's floor when it is not the shown one, as the Floors list does", () => {
    const c = m.floorOf(SAVE)!;
    expect(floorNote(m, SITE, SAVE)).toBe(`on floor F${m.path(c).length - 1} · ${m.label(c)}`);
    expect(floorNote(m, SITE, SAVE)).toMatch(/^on floor F3 · /);
    expect(floorNote(m, c, SAVE)).toBeNull();
    expect(floorNote(m, SITE, TOPIC)).toBeNull();
    expect(floorNote(m, c, TOPIC)).toBe("on floor F0 · Whole system");
    expect(floorNote(m, SITE, "nope")).toBeNull();
  });
});

describe("the trace's own box (spec A4)", () => {
  it("is the focus lifted to the shown floor: a method's service on F0, the method itself on its own floor", () => {
    expect(ownBox(m, SITE, { focus: SAVE }, { type: "node", id: "svc:shop" })).toBe(true);
    expect(ownBox(m, SITE, { focus: SAVE }, { type: "node", id: "svc:worker" })).toBe(false);
    expect(ownBox(m, m.floorOf(SAVE)!, { focus: SAVE }, { type: "node", id: SAVE })).toBe(true);
    expect(ownBox(m, SITE, { focus: TOPIC }, { type: "node", id: TOPIC })).toBe(true);
  });

  it("for a line's trace, the same line; never a box", () => {
    const st = { focus: "line:svc:shop|svc:worker", line: { key: "svc:shop|svc:worker", title: "shop ↔ worker", ends: [] } };
    expect(ownBox(m, SITE, st, { type: "bundle", key: "svc:shop|svc:worker" })).toBe(true);
    expect(ownBox(m, SITE, st, { type: "bundle", key: "svc:shop|topic:kafka:orders" })).toBe(false);
    expect(ownBox(m, SITE, st, { type: "node", id: "svc:shop" })).toBe(false);
    expect(ownBox(m, SITE, { focus: SAVE }, { type: "bundle", key: "svc:shop|svc:worker" })).toBe(false);
  });
});

describe("a pick that is the trace's focus itself (a named pick: Find, a link)", () => {
  it("the focus's own id, a twin as the package it stands for; never its lifted box, never for a line's trace", () => {
    const tw = structuredClone(shop) as unknown as CodeMap;
    tw.nodes.find((n) => n.id === "svc:shop")!.twins = ["worker::worker/"];
    tw.layout.containers["svc:shop"].items["twin:worker::worker/"] = { region: "line", col: 5, row: 0 };
    const t = new Model(tw);
    expect(isFocus(t, { focus: SAVE }, { type: "node", id: SAVE })).toBe(true);
    expect(isFocus(t, { focus: SAVE }, { type: "node", id: "svc:shop" })).toBe(false);
    expect(isFocus(t, { focus: "worker::worker/" }, { type: "node", id: "twin:worker::worker/" })).toBe(true);
    const st = { focus: "line:svc:shop|svc:worker", line: { key: "svc:shop|svc:worker", title: "shop ↔ worker", ends: [] } };
    expect(isFocus(t, st, { type: "node", id: "svc:shop" })).toBe(false);
    expect(isFocus(t, st, { type: "bundle", key: "svc:shop|svc:worker" })).toBe(false);
    // ownBox takes the twin path too: the twin box on its floor is the package's trace's own box
    expect(ownBox(t, "svc:shop", { focus: "worker::worker/" }, { type: "node", id: "twin:worker::worker/" })).toBe(true);
  });
});

describe("what the inspector shows while the pane is open (audit row 64)", () => {
  const LINE = { key: "svc:shop|svc:worker", title: "shop ↔ worker", ends: [] };
  const has = (k: string) => k === LINE.key;
  it("the pointed row's node, else the focus: the item the blue mark is on", () => {
    expect(traceSubject(m, { focus: SAVE }, null, has)).toEqual({ type: "node", id: SAVE });
    expect(traceSubject(m, { focus: "svc:shop" }, null, has)).toEqual({ type: "node", id: "svc:shop" });
    expect(traceSubject(m, { focus: SAVE }, RUN, has)).toEqual({ type: "node", id: RUN });
  });

  it("a pointed node with no mark on the shown floor is still shown (its detail is open); a point not in the map shows the focus", () => {
    expect(traceMarks(m, "svc:worker", RUN, SAVE)).toEqual([m.liftTo("svc:worker", RUN)]);
    expect(traceSubject(m, { focus: RUN }, SAVE, has)).toEqual({ type: "node", id: SAVE });
    expect(traceSubject(m, { focus: RUN }, "nope", has)).toEqual({ type: "node", id: RUN });
  });

  it("a line's trace shows its line while the shown floor can name it, else the floor (null)", () => {
    const st = { focus: `line:${LINE.key}`, line: LINE };
    expect(traceSubject(m, st, null, has)).toEqual({ type: "bundle", key: LINE.key });
    expect(traceSubject(m, st, null, () => false)).toBeNull();
    expect(traceSubject(m, st, RUN, () => false)).toEqual({ type: "node", id: RUN });
  });

  it("a focus that is neither a map node nor a floor group shows the floor", () => {
    expect(traceSubject(m, { focus: "nope" }, null, has)).toBeNull();
  });
});
