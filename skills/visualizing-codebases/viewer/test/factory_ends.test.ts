import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model } from "../src/model/model";
import { planFloor } from "../src/factory/plan";
import { outerEnds } from "./factory_trunks";

const BIG = process.env.VIZ_BIG_MAP ?? "";

describe("plug-in points", () => {
  // a line meets a side near its middle, straight on: few ends in a side's outermost tile
  it.runIf(BIG && existsSync(BIG))("big map: ends sit mid-side", () => {
    const big = new Model(JSON.parse(readFileSync(BIG, "utf8")));
    let ends = 0, outer = 0;
    for (const c of Object.keys(big.map.layout.containers)) {
      const { bundles, doors } = big.bundles(c);
      const { tf, routes } = planFloor(big, c, doors, bundles);
      const o = outerEnds(tf, routes);
      if (/order$|market/.test(c)) process.stderr.write(`outer ${c}: ${o.outer}/${o.ends}` + "\n");
      ends += o.ends; outer += o.outer;
    }
    process.stderr.write(`outer ends, all floors: ${outer}/${ends}` + "\n");
    // before: 3544 of 5184 (68%); order.py 74/92
    expect(ends).toBeGreaterThan(0);
    expect(outer / ends).toBeLessThan(0.1);
  });
});
