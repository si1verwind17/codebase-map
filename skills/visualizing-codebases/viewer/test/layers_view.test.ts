// Layers in the viewer (spec §15): the scene shows one extra layer at a time over a faint base, a floor change resets it to
// the base, and the button and its list name a layer by its heavily used item's map code.
import { readFileSync } from "node:fs";
import { Container, Graphics } from "pixi.js";
import { describe, expect, it, vi } from "vitest";
import { Model, SITE } from "../src/model/model";
import type { CodeMap } from "../src/model/types";
import { floorLayers, layerLabel, listEntry, type LayerId } from "../src/model/layers";
import { createState, type LayerView, type SceneState } from "../src/floor/state";
import { BASE_FADE, bundleKeysOf, layerLines, restyle, select, setLayer } from "../src/floor/selection";
import { FloorScene } from "../src/floor/scene";
import { defaultLit } from "../src/floor/lit";
import { Clearance, badgeBox, planBadge } from "../src/factory/clear";

const DEMO = new URL("../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const demo = () => new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
const DAGS = "jobs/dags::dags/", COMMON = "jobs/dags::dags._common";
const HUB: LayerId = "hub";

/** A scene state with no renderer: the canvas is a bare dataset, and the views are plain Graphics. */
function bare(): SceneState {
  const st = createState({ select: () => {}, enter: () => {}, up: () => {}, door: () => {} });
  (st as { app: unknown }).app = { canvas: { dataset: {} }, screen: { width: 1440, height: 900 } };
  return st;
}

/** Two base lines (one shared junction plate between them), two layer lines into `hub`, three machines. */
function floorWithLayer() {
  const st = bare();
  const view = () => new Graphics();
  const plate = view();
  st.lineViews.set("a|b", [view(), plate]);
  st.lineViews.set("b|c", [view(), plate]);
  st.implViews.set("a|c", view());
  const box = new Container();
  box.visible = false;
  const lv = new Map([["a|hub", [view()]], ["c|hub", [view()]]]);
  const bundle = (a: string, b: string) => ({ key: `${a}|${b}`, a, b, relations: [], kinds: {}, inferred: 0, kind: "calls" as const, flow: "both" as const, layer: HUB, into: true });
  const layer: LayerView = { box, lineViews: lv, routes: [], bundles: [bundle("a", "hub"), bundle("c", "hub")], lines: { belt: true } };
  st.layerViews.set(HUB, layer);
  st.layered = layer.bundles;
  st.floorLayers = [{ id: HUB, name: "F9", full: "hub.py", count: 2, item: HUB, usedBy: 2 }];
  st.bundles = [
    { key: "a|b", a: "a", b: "b", relations: [], kinds: {}, inferred: 0, kind: "calls", flow: "both" },
    { key: "b|c", a: "b", b: "c", relations: [], kinds: {}, inferred: 0, kind: "calls", flow: "both" },
  ];
  for (const id of ["a", "b", "c", "hub"]) { st.machineViews.set(id, new Container()); st.highlights.set(id, new Graphics()); st.hoverRings.set(id, new Graphics()); }
  return { st, layer };
}
const alphas = (m: Map<string, Container[]>) => [...m.values()].flat().map((v) => v.alpha);

describe("layer switch (selection.ts setLayer)", () => {
  it("a layer shows its lines at full strength on top, every base line at 12%, buildings unchanged; the base restores them", () => {
    const { st, layer } = floorWithLayer();
    restyle(st);
    expect(alphas(st.lineViews).every((a) => a === 1)).toBe(true);
    setLayer(st, HUB);
    expect(st.layer).toBe(HUB);
    expect(BASE_FADE).toBe(0.12);
    expect(layer.box.visible).toBe(true);
    expect(alphas(layer.lineViews)).toEqual([1, 1]);
    expect(new Set(alphas(st.lineViews))).toEqual(new Set([BASE_FADE]));
    expect(st.implViews.get("a|c")!.alpha).toBe(BASE_FADE);
    expect([...st.machineViews.values()].map((v) => v.alpha)).toEqual([1, 1, 1, 1]);
    expect(st.layers.lines.interactiveChildren, "the faint base takes no click").toBe(false);
    expect(layerLines(st)).toEqual({ belt: true });
    setLayer(st, null);
    expect(st.layer).toBeNull();
    expect(layer.box.visible).toBe(false);
    expect(alphas(st.lineViews).every((a) => a === 1)).toBe(true);
    expect(st.implViews.get("a|c")!.alpha).toBe(1);
    expect(st.layers.lines.interactiveChildren).toBe(true);
    expect(layerLines(st)).toBeNull();
  });

  it("composes with the selection: a selected layer line stays lit, the rest of the layer fades as today, the base stays faint", () => {
    const { st, layer } = floorWithLayer();
    setLayer(st, HUB);
    select(st, { type: "bundle", key: "a|hub" });
    expect(layer.lineViews.get("a|hub")![0].alpha).toBe(1);
    expect(layer.lineViews.get("c|hub")![0].alpha).toBe(0.25);
    expect(new Set(alphas(st.lineViews))).toEqual(new Set([0.25 * BASE_FADE]));
    // a selected machine: its layer lines lit, the layer's other end related (its building not dimmed)
    select(st, { type: "node", id: "hub" });
    expect(alphas(layer.lineViews)).toEqual([1, 1]);
    expect(st.machineViews.get("a")!.alpha).toBe(1);
    expect(st.machineViews.get("b")!.alpha).toBe(0.38);
    expect(bundleKeysOf(st, "hub")).toEqual(["a|hub", "c|hub"]);
    // on the base the selected node peeks its layer lines, so their far boxes stay lit; a box with no line to it dims
    setLayer(st, null);
    expect(st.machineViews.get("a")!.alpha).toBe(1);
    expect(st.machineViews.get("b")!.alpha).toBe(0.38);
  });

  it("an id this floor does not have shows the base", () => {
    const { st } = floorWithLayer();
    setLayer(st, HUB);
    setLayer(st, "other");
    expect(st.layer).toBeNull();
    expect(alphas(st.lineViews).every((a) => a === 1)).toBe(true);
  });
});

describe("a floor change resets to the base (scene.ts show)", () => {
  it("shows the dags floor with its layer, switches, then any show (another floor or the same) is back on the base", () => {
    vi.spyOn(FloorScene.prototype as unknown as { draw: () => void }, "draw").mockImplementation(() => {});
    const events: (LayerId | null)[] = [];
    const scene = new FloorScene({ select: () => {}, enter: () => {}, up: () => {}, door: () => {}, layer: (id) => events.push(id) }, () => () => {});   // no idle planning here
    const st = (scene as unknown as { s: SceneState }).s;
    (st as { app: unknown }).app = { canvas: { dataset: {} }, screen: { width: 1440, height: 900 } };
    const m = demo();
    scene.show(m, DAGS);
    expect(st.floorLayers.map((l) => l.id)).toEqual([COMMON]);
    expect(st.layered).toHaveLength(10);
    st.layerViews.set(COMMON, { box: new Container(), lineViews: new Map(), routes: [], bundles: st.layered, lines: {} });   // as drawFactory would
    scene.setLayer(COMMON);
    expect(st.layer).toBe(COMMON);
    expect(events.at(-1)).toBe(COMMON);
    scene.show(m, SITE);
    expect(st.layer).toBeNull();
    expect(st.floorLayers, "F0 has no layer: Code links is its own toggle").toEqual([]);
    scene.show(m, DAGS);
    expect(st.layer).toBeNull();
    vi.restoreAllMocks();
  });
});

describe("picking a node whose lines are all in a layer opens it (scene.ts select)", () => {
  it("_common.py on dags opens its layer; a file with base lines leaves the base; a pick while it shows keeps it", () => {
    vi.spyOn(FloorScene.prototype as unknown as { draw: () => void }, "draw").mockImplementation(() => {});
    const scene = new FloorScene({ select: () => {}, enter: () => {}, up: () => {}, door: () => {} }, () => () => {});
    const st = (scene as unknown as { s: SceneState }).s;
    (st as { app: unknown }).app = { canvas: { dataset: {} }, screen: { width: 1440, height: 900 } };
    const m = demo();
    scene.show(m, DAGS);
    st.layerViews.set(COMMON, { box: new Container(), lineViews: new Map(), routes: [], bundles: st.layered, lines: {} });   // as drawFactory would
    const other = st.bundles.flatMap((b) => [b.a, b.b]).find((id) => id !== COMMON && m.nodes.has(id))!;
    scene.select({ type: "node", id: other });
    expect(st.layer, "a node with base lines").toBeNull();
    scene.select({ type: "node", id: COMMON });
    expect(st.layer).toBe(COMMON);
    scene.select({ type: "node", id: other });
    expect(st.layer, "the shown layer is kept").toBe(COMMON);
    scene.select(null);
    expect(st.layer).toBe(COMMON);
    vi.restoreAllMocks();
  });
});

describe("a line in two layers (between two heavily used items)", () => {
  it("is one key in a machine's keys and in the default lit set", () => {
    vi.spyOn(FloorScene.prototype as unknown as { draw: () => void }, "draw").mockImplementation(() => {});
    const scene = new FloorScene({ select: () => {}, enter: () => {}, up: () => {}, door: () => {} }, () => () => {});
    const st = (scene as unknown as { s: SceneState }).s;
    (st as { app: unknown }).app = { canvas: { dataset: {} }, screen: { width: 1440, height: 900 } };
    const caller = "jobs/dags::dags.bq_bay_events_export";
    const map = JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap;
    map.layout.containers[DAGS].hubs = [COMMON, caller];
    const m = new Model(map);
    scene.show(m, DAGS);
    const shared = st.layered.filter((b) => b.layer === caller && (b.a === COMMON || b.b === COMMON)).map((b) => b.key);
    expect(shared).toHaveLength(1);
    expect(st.layered.filter((b) => b.key === shared[0])).toHaveLength(2);
    for (const id of [COMMON, caller]) {
      const keys = bundleKeysOf(st, id);
      expect(new Set(keys).size, id).toBe(keys.length);
      expect(keys.filter((k) => k === shared[0]), id).toHaveLength(1);
    }
    const lit = defaultLit(m, DAGS);
    expect(new Set(lit).size).toBe(lit.length);
    vi.restoreAllMocks();
  });
});

describe("a line in two layers, shown (selection.ts setLayer)", () => {
  it("is drawn once with either layer shown (the other layer's view hidden) and swaps with the layer; `used by N` counts only an item something uses", () => {
    vi.spyOn(FloorScene.prototype as unknown as { draw: () => void }, "draw").mockImplementation(() => {});
    const scene = new FloorScene({ select: () => {}, enter: () => {}, up: () => {}, door: () => {} }, () => () => {});
    const st = (scene as unknown as { s: SceneState }).s;
    (st as { app: unknown }).app = { canvas: { dataset: {} }, screen: { width: 1440, height: 900 } };
    const caller = "jobs/dags::dags.bq_bay_events_export";
    const map = JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap;
    map.layout.containers[DAGS].hubs = [COMMON, caller];
    scene.show(new Model(map), DAGS);
    const shared = st.layered.find((b) => b.layer === caller && (b.a === COMMON || b.b === COMMON))!.key;
    // each layer's view as drawFactory builds it: a hidden box holding a view per line of the layer
    for (const l of st.floorLayers) {
      const box = new Container(), lineViews = new Map<string, Container[]>();
      box.visible = false;
      const bundles = st.layered.filter((b) => b.layer === l.id);
      for (const b of bundles) { const v = new Graphics(); box.addChild(v); lineViews.set(b.key, [v]); }
      st.layerViews.set(l.id, { box, lineViews, routes: [], bundles, lines: {} });
    }
    const drawn = () => [...st.layerViews.values()].flatMap((lv) => (lv.box.visible ? (lv.lineViews.get(shared) ?? []) : []));
    expect(drawn(), "base: no layer's view").toHaveLength(0);
    for (const [shown, other] of [[COMMON, caller], [caller, COMMON]]) {
      setLayer(st, shown);
      expect(drawn(), `${shown} shown`).toHaveLength(1);
      expect(drawn()[0], `${shown} shown`).toBe(st.layerViews.get(shown)!.lineViews.get(shared)![0]);
      expect(st.layerViews.get(other)!.box.visible, `${other} hidden`).toBe(false);
    }
    setLayer(st, null);
    expect(drawn()).toHaveLength(0);
    // `used by N` shows for an item something uses: _common.py (used by all 10), not the caller (nothing uses it)
    expect(st.floorLayers.map((l) => [l.item, l.usedBy])).toEqual([[COMMON, 10], [caller, 0]]);
    vi.restoreAllMocks();
  });
});

describe("the `used by N` badge's spot (clear.ts planBadge)", () => {
  it("grows from the side with the most clear room, right first on a tie; the winning box joins the obstacles", () => {
    const m = { x: 240, y: 240, w: 120, h: 72 };
    const open = new Clearance([]);
    const a = planBadge(m, 60, 14, open);
    expect(a.side).toBe("right");
    expect(a.maxK).toBe(4);
    expect(open.free(badgeBox(a, 1))).toBe(false);   // taken now
    // lines just right and left of the box and a row further down: the badge goes below, as large as the room allows
    const walled = new Clearance([{ x0: 370, y0: 0, x1: 394, y1: 2000 }, { x0: 200, y0: 0, x1: 224, y1: 2000 }, { x0: 0, y0: 360, x1: 2000, y1: 384 }]);
    const b = planBadge(m, 60, 14, walled);
    expect(b.side).toBe("below");
    const box = badgeBox(b, b.maxK);
    expect(box.y1).toBeLessThanOrEqual(360);
    expect(b.maxK).toBeGreaterThan(1);
  });
  it("slides along a side when the plain spots are tight: a line just past each plain spot leaves room above the box's right end, the badge anchored there grows up", () => {
    const m = { x: 240, y: 240, w: 120, h: 72 };
    // a line crossing the right side at the box's middle, the left side open only 1x, below and above walled close
    const walls = new Clearance([{ x0: 368, y0: 264, x1: 2000, y1: 288 }, { x0: 0, y0: 0, x1: 160, y1: 2000 }, { x0: 0, y0: 324, x1: 2000, y1: 348 }, { x0: 0, y0: 180, x1: 2000, y1: 204 }]);
    const s = planBadge(m, 60, 14, walls);
    expect(s).toMatchObject({ side: "right", clear: true, ox: 0 });
    expect(s.maxK).toBeGreaterThan(2);
    const box = badgeBox(s, s.maxK);
    expect(box.x0).toBeGreaterThanOrEqual(m.x + m.w);
    expect(box.y1 <= 264 || box.y0 >= 288).toBe(true);
  });
  it("with no clear spot even at 1x, stands below at 1x and says so", () => {
    const s = planBadge({ x: 240, y: 240, w: 120, h: 72 }, 60, 14, new Clearance([{ x0: 0, y0: 0, x1: 2000, y1: 2000 }]));
    expect(s).toMatchObject({ side: "below", ax: 240, maxK: 1, clear: false });
  });
});

describe("layer names (spec §15 naming rule, revised after the demo)", () => {
  it("a layer is named by its item's map code as the floor shows it on the machine; the button shows that name, the list adds the count after a ·", () => {
    expect(layerLabel(null)).toBe("Base");
    const m = demo();
    for (const c of Object.keys(m.map.layout.containers))
      for (const l of floorLayers(m, c)) {
        expect(l.name, c).toBe(m.codes.get(l.item));   // the code tab and the big roof code (factory-draw.ts paintBox) read model.codes
        expect(l.full, c).toBe(m.itemName(l.item));
        expect(layerLabel(l)).toBe(l.name);
        expect(listEntry(l)).toBe(`${l.name} · ${l.count}`);
      }
    const dags = floorLayers(m, DAGS)[0];
    expect(dags.name).toMatch(/^S\d+·P\d+·F\d+$/);
    expect(listEntry(dags)).toBe(`${dags.name} · 10`);
    expect(dags.full).toBe("_common.py");
  });

  it("every layer line moves by default (floor/lit.ts): the dags floor's 10 lines into _common.py are in the default lit set", () => {
    const m = demo(), b = m.bundles(DAGS), lit = defaultLit(m, DAGS);
    for (const x of b.layered) expect(lit).toContain(x.key);
    expect(b.layered.every((x) => x.a === COMMON || x.b === COMMON)).toBe(true);
    expect(new Set(lit).size).toBe(lit.length);
  });
});
