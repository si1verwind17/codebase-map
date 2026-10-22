import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { drawnLines } from "../../src/floor/factory-draw";
import { factoryOps, type Op } from "../../src/factory/pieces";
import { planFloor } from "../../src/factory/plan";
import type { TileRoute } from "../../src/factory/router";
import { Model, SITE } from "../../src/model/model";
import type { Bundle } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";

const plain = (() => ({ inferred: 0, relations: [] }) as unknown as Bundle);
const route = (kind: TileRoute["kind"], extra: Partial<TileRoute> = {}) => ({ key: kind, kind, pieces: [], ...extra }) as unknown as TileRoute;

describe("the legend's two-way belt row", () => {
  it("is a belt that runs both ways, not a two-way rail or tap, nor a line drawn straight", () => {
    expect(drawnLines([route("rail", { both: true }), route("tapRW", { both: true })], plain, []).both).toBeUndefined();
    expect(drawnLines([route("belt", { both: true, failed: true })], plain, []).both).toBeUndefined();
    expect(drawnLines([route("belt", { both: true })], plain, []).both).toBe(true);
  });

  it("is a shared belt tile drawn two-way: one-way belts meeting head on", () => {
    const tile = { layer: "tile", ri: 0, tile: { both: true } } as unknown as Op;
    expect(drawnLines([route("belt"), route("belt")], plain, [tile]).both).toBe(true);
    expect(drawnLines([route("belt")], plain, [{ ...tile, tile: { both: false } } as unknown as Op]).both).toBeUndefined();
  });

  it("floor 0 of the shop fixture, whose two-way lines are a rail and a tap, has none", () => {
    const model = new Model(JSON.parse(readFileSync(new URL("../fixtures/shop.code-map.json", import.meta.url), "utf8")) as CodeMap);
    const { doors, bundles } = model.bundles(SITE), { tf, routes } = planFloor(model, SITE, doors, bundles);
    expect(routes.some((r) => r.both)).toBe(true);
    const ops = factoryOps(routes.map((r) => ({ pieces: r.pieces, kind: r.kind, failed: r.failed, both: r.both, inferred: false })), tf.cols, routes.map((_, i) => i));
    expect(drawnLines(routes, plain, ops).both).toBeUndefined();
  });
});
