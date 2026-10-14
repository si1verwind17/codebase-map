import { Container, Graphics } from "pixi.js";
import { describe, expect, it } from "vitest";
import { clearLayer } from "../../src/floor/clear";

describe("clearLayer", () => {
  it("destroys what it removes, so redraws do not leak GPU objects", () => {
    const layer = new Container();
    const g = new Graphics().rect(0, 0, 10, 10).fill(0);
    layer.addChild(g, new Container());
    clearLayer(layer);
    expect(layer.children).toHaveLength(0);
    expect(g.destroyed).toBe(true);
  });

  it("keeps the children it is told to keep", () => {
    const layer = new Container();
    const keep = new Graphics();
    const drop = new Graphics();
    layer.addChild(keep, drop);
    clearLayer(layer, [keep]);
    expect(layer.children).toEqual([keep]);
    expect(keep.destroyed).toBe(false);
    expect(drop.destroyed).toBe(true);
  });
});

