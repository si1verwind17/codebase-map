import { describe, expect, it } from "vitest";
import type { CodeMap, Pin } from "../../src/model/types";
import { Pins, defaultTitle, pinTitle, slug } from "../../src/trace/pins";
import { clampSplit, loadSplit, saveSplit, SPLIT_DEFAULT } from "../../src/ui/viewpref";

const memory = () => { const m = new Map<string, string>(); return { m, getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }; };
const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
const NODES = new Set(["a#run/0", "b#pay/1", "t/public.orders"]);
const has = (id: string) => NODES.has(id);
const mapWith = (pins: Pin[], unpinned: string[] = []) =>
  ({ meta: { schema_version: 2, repo: "r", commit: "0".repeat(40), scanned_at: "", languages: [] }, nodes: [], relations: [], problems: [],
     layout: { version: 1, containers: {} }, pins, unpinned }) as unknown as CodeMap;
const AGENT: Pin = { id: "driver-reserves-a-bay", title: "driver reserves a bay", start: "a#run/0", direction: "downstream", by: "agent" };
const USER: Pin = { id: "billing-pays", title: "billing pays", start: "b#pay/1", direction: "both", by: "user" };
const GONE: Pin = { id: "old", title: "old path", start: "nope#x/0", direction: "upstream", by: "agent" };

describe("pinned traces", () => {
  it("shows the map's pins, flags one whose start is not in this map", () => {
    const p = new Pins(mapWith([AGENT, USER, GONE]), has, memory());
    expect(p.list().map((x) => [x.id, x.local, x.missing])).toEqual([[AGENT.id, false, false], [USER.id, false, false], ["old", false, true]]);
    expect(p.changes()).toBe(0);
    expect(p.toMarkdown()).toBe("");
  });

  it("pins and unpins at once: map pins minus removals, plus additions, in the export's exact lines", () => {
    const p = new Pins(mapWith([AGENT, USER]), has, memory());
    p.remove(AGENT.id);
    const added = p.add("orders | totals", "t/public.orders", "upstream");
    expect(added).toMatchObject({ id: "orders-totals", title: "orders / totals", by: "user", local: true });
    expect(p.list().map((x) => x.id)).toEqual([USER.id, "orders-totals"]);
    expect(p.changes()).toBe(2);
    expect(p.toMarkdown()).toBe(
      "## Pins\n- pin: orders / totals | start: t/public.orders | direction: upstream\n- unpin: driver-reserves-a-bay\n");
    expect(p.find("t/public.orders", "upstream")?.id).toBe("orders-totals");
    expect(p.find("t/public.orders", "both")).toBeUndefined();
  });

  it("unpinning a pin made here forgets it: no line goes out", () => {
    const p = new Pins(mapWith([]), has, memory());
    const a = p.add("x", "a#run/0", "both");
    p.remove(a.id);
    expect([p.changes(), p.toMarkdown()]).toEqual([0, ""]);
  });

  it("a taken slug (map pin, local pin, unpinned id) gets -2, -3", () => {
    const p = new Pins(mapWith([USER], ["gone"]), has, memory());
    expect(p.add("Billing pays!", "a#run/0", "both").id).toBe("billing-pays-2");
    expect(p.add("billing  pays", "a#run/0", "upstream").id).toBe("billing-pays-3");
    expect(p.add("Gone", "a#run/0", "both").id).toBe("gone-2");
  });

  it("ids follow Plan 2's slug rule", () => {
    expect([slug("Driver reserves a bay, billing charges it"), slug("Pay v2 / 3DS"), slug(""), slug("|| ·")])
      .toEqual(["driver-reserves-a-bay-billing-charges-it", "pay-v2-3ds", "pin", "pin"]);
  });

  it("gives a repeated title its own id", () => {
    const p = new Pins(mapWith([]), has, memory());
    expect([p.add("same", "a#run/0", "both").id, p.add("same", "b#pay/1", "both").id]).toEqual(["same", "same-2"]);
  });

  it("keeps changes across a reload, and drops the ones the agent applied (round trip)", () => {
    const store = memory();
    const p = new Pins(mapWith([AGENT, USER]), has, store);
    p.remove(AGENT.id);
    p.add("orders | totals", "t/public.orders", "upstream");
    expect(new Pins(mapWith([AGENT, USER]), has, store).changes()).toBe(2);   // reloaded, same map
    // the agent applied the export: the agent pin moved to `unpinned`, the new pin is a user pin with a slug id
    const next = mapWith([USER, { id: "orders-totals", title: "orders / totals", start: "t/public.orders", direction: "upstream", by: "user" }], [AGENT.id]);
    const after = new Pins(next, has, store);
    expect(after.changes()).toBe(0);
    expect(after.list().map((x) => [x.id, x.local])).toEqual([[USER.id, false], ["orders-totals", false]]);
    expect(JSON.parse(store.m.get("viz-code:pins:r")!)).toEqual({ added: [], removed: [] });
  });

  it("works without storage, and ignores junk in it", () => {
    const p = new Pins(mapWith([AGENT]), has, broken);
    p.remove(AGENT.id);
    expect(p.list()).toEqual([]);
    const junk = memory();
    junk.setItem("viz-code:pins:r", '{"added": [{"id": 3}], "removed": "x"}');
    expect(new Pins(mapWith([AGENT]), has, junk).changes()).toBe(0);
    junk.setItem("viz-code:pins:r", "not json");
    expect(new Pins(mapWith([AGENT]), has, junk).list()).toHaveLength(1);
  });

  it("a map with no pins (an older map) shows none", () => {
    const old = mapWith([]);
    delete (old as Partial<CodeMap>).pins;
    expect(new Pins(old, has, null).list()).toEqual([]);
  });

  it("unpin then re-pin the same trace restores it, also after a reload", () => {
    const store = memory();
    const p = new Pins(mapWith([AGENT]), has, store);
    p.remove(AGENT.id);
    const back = p.add(AGENT.title, AGENT.start, AGENT.direction);
    expect([back.id, back.local]).toEqual([AGENT.id, false]);
    expect(p.changes()).toBe(0);
    const again = new Pins(mapWith([AGENT]), has, store);
    expect(again.list().map((x) => x.id)).toEqual([AGENT.id]);
  });

  it("an empty title takes the fallback or the default, never an empty pin line", () => {
    const p = new Pins(mapWith([]), has, memory());
    expect(p.add(" | ", "a#run/0", "both", "run").title).toBe("run");
    expect(p.add("", "b#pay/1", "upstream").title).toBe("b#pay/1");
    expect(p.toMarkdown()).not.toMatch(/pin:\s+\|/);
  });

  it("clear drops every change", () => {
    const p = new Pins(mapWith([AGENT]), has, memory());
    p.remove(AGENT.id);
    p.add("x", "a#run/0", "both");
    p.clear();
    expect(p.changes()).toBe(0);
  });

  it("titles: one line, `|` replaced; the default names the start alone (the rail shows the direction)", () => {
    expect(pinTitle("  a |\n b ")).toBe("a / b");
    expect(defaultTitle("charge")).toBe("charge");
  });

  it("the default title adds the direction when a pin already has that title, so two pins of one start differ", () => {
    expect(defaultTitle("charge", "upstream", [{ title: "charge" }])).toBe("charge · upstream");
    expect(defaultTitle("charge", "upstream", [{ title: "other" }])).toBe("charge");
    expect(defaultTitle("charge", "both", [])).toBe("charge");
  });
});

describe("the divider's place", () => {
  it("starts at the default, remembers a drag, and stays within its bounds", () => {
    const s = memory();
    expect(loadSplit(s)).toBe(SPLIT_DEFAULT);
    saveSplit(s, 0.6);
    expect(loadSplit(s)).toBe(0.6);
    saveSplit(s, 0.99);
    expect(loadSplit(s)).toBe(0.8);
    expect(clampSplit(0.01)).toBe(0.2);
    const bad = memory();
    for (const v of ["0", "-0.3", "1.5", "0.1"]) { bad.setItem("code-map.trace-split", v); expect(loadSplit(bad)).toBe(SPLIT_DEFAULT); }
    saveSplit(bad, NaN);
    expect(bad.m.get("code-map.trace-split")).toBe("0.1");
  });

  it("falls back to the default when storage is missing, blocked or holds junk", () => {
    expect(loadSplit(null)).toBe(SPLIT_DEFAULT);
    expect(loadSplit(broken)).toBe(SPLIT_DEFAULT);
    expect(() => saveSplit(broken, 0.5)).not.toThrow();
    const s = memory();
    s.setItem("code-map.trace-split", "wide");
    expect(loadSplit(s)).toBe(SPLIT_DEFAULT);
  });
});

describe("the export's pin lines", () => {
  it("each line fits the grammar the agent reads (SKILL.md, Review comments)", () => {
    const p = new Pins(mapWith([AGENT, USER]), has, memory());
    p.remove(AGENT.id);
    p.add("a | b | c", "a#run/0", "both");
    p.add("orders", "t/public.orders", "downstream");
    const lines = p.toMarkdown().split("\n").filter(Boolean);
    expect(lines[0]).toBe("## Pins");
    expect(lines.length).toBe(4);
    for (const l of lines.slice(1)) expect(l).toMatch(/^(- pin: [^|]+ \| start: \S+ \| direction: (downstream|upstream|both)|- unpin: \S+)$/);
  });
});
