// What moves (floor/lit.ts): one rule for nothing selected, a node, and a line.
import { describe, expect, it } from "vitest";
import shop from "./fixtures/shop.code-map.json";
import { defaultLit, litFor } from "../src/floor/lit";
import { Model } from "../src/model/model";
import type { CodeMap } from "../src/model/types";

describe("what moves (floor/lit.ts)", () => {
  it("nothing selected: every line on the floor; a node: its lines; a line: that line alone", () => {
    const model = new Model(shop as unknown as CodeMap);
    const c = Object.keys(model.map.layout.containers)[0];
    const all = model.bundles(c).bundles.map((b) => b.key);
    expect(all.length).toBeGreaterThan(1);
    expect(defaultLit(model, c)).toEqual(all);
    const ofNode = (id: string) => all.filter((k) => k.split("|").includes(id));
    expect(litFor(model, c, null, ofNode)).toEqual(all);
    expect(litFor(model, c, { type: "bundle", key: all[0] }, ofNode)).toEqual([all[0]]);
    const node = all[0].split("|")[0];
    expect(litFor(model, c, { type: "node", id: node }, ofNode)).toEqual(ofNode(node));
  });
});
