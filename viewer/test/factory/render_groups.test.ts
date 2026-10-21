// Render groups (state.ts createLayers, factory-draw.ts): the moving parts and the smoke, redrawn every frame, sit in
// their own render groups so a frame re-uploads only their transforms, not the whole floor's. Draw order is unchanged:
// the smoke's group takes the smoke's old place, the last of the tags.
import { readFileSync } from "node:fs";
import { CanvasTextMetrics } from "pixi.js";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { createLayers, type SceneState } from "../../src/floor/state";
import { FloorScene } from "../../src/floor/scene";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const demo = () => new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);

/** A scene with no renderer, and node's missing text measuring stood in for (fixed width: sizes do not matter here). */
function bareScene() {
  vi.spyOn(CanvasTextMetrics, "measureText").mockImplementation((text = " ") => {
    const w = text.length * 7;
    return { text, width: w, height: 14, lines: [text], lineWidths: [w], lineHeight: 14, maxLineWidth: w, fontProperties: { ascent: 11, descent: 3, fontSize: 14 } } as unknown as CanvasTextMetrics;
  });
  const scene = new FloorScene({ select: () => {}, enter: () => {}, up: () => {}, door: () => {} }, () => () => {});   // no idle planning here
  const st = (scene as unknown as { s: SceneState }).s;
  (st as { app: unknown }).app = { canvas: { dataset: {} }, screen: { width: 1440, height: 900 } };
  return { scene, st };
}
const wrappers = (st: SceneState) => st.layers.tags.children.filter((c) => c.isRenderGroup);

describe("render groups", () => {
  afterEach(() => vi.restoreAllMocks());

  it("the moving parts' layer is a render group that takes no click", () => {
    const layers = createLayers();
    expect(layers.motion.isRenderGroup).toBe(true);
    expect(layers.motion.eventMode).toBe("none");
  });

  it("the smoke sits in its own render group, the last child of the tags where the smoke was, and takes no click", () => {
    const { scene, st } = bareScene();
    scene.show(demo(), SITE);
    const smoke = st.smoke!;
    expect(smoke).toBeTruthy();
    const wrap = smoke.parent!;
    expect(wrap.isRenderGroup).toBe(true);
    expect(wrap.eventMode).toBe("none");
    expect(wrap.children).toEqual([smoke]);
    expect(wrap.parent).toBe(st.layers.tags);
    expect(st.layers.tags.children.at(-1)).toBe(wrap);
  });

  it("a second show leaves exactly one smoke wrapper in the tags, and the old one is destroyed", () => {
    const { scene, st } = bareScene();
    const m = demo();
    scene.show(m, SITE);
    const [old] = wrappers(st);
    expect(wrappers(st)).toHaveLength(1);
    scene.show(m, SITE);
    expect(wrappers(st)).toHaveLength(1);
    expect(wrappers(st)[0]).not.toBe(old);
    expect(old.destroyed).toBe(true);
    expect(st.layers.tags.children.at(-1)).toBe(st.smoke!.parent);
  });
});
