// test/factory_trunk_card.test.ts
// The trunk hover card (spec §8 Hover): a tile carrying two or more lines names them, a count by kind, then one row per
// branch, ordered by the branch end's short code.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model, SITE, type Bundle } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor } from "../../src/factory/plan";
import { coveredKeys, flightPaths } from "../../src/factory/flights";
import { sharedTiles, trunkCard } from "../../src/factory/trunk-card";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);

const bundle = (a: string, b: string, kinds: Bundle["kinds"], kind: Bundle["kind"], flow: Bundle["flow"]): Bundle =>
  ({ key: [a, b].sort().join("|"), a, b, relations: [], kinds, inferred: 0, kind, flow });
const ENDS: Record<string, { code: string; name: string }> = {
  "svc:pay": { code: "S2", name: "payments" }, "3p:stripe": { code: "X3", name: "stripe" },
  "svc:res": { code: "S10", name: "reservations" }, "svc:bill": { code: "S4", name: "billing" },
  "svc:ops": { code: "S9", name: "ops" },
};
const end = (id: string) => ENDS[id];

describe("trunk card text", () => {
  it("a split: how many lines carry each kind, then one → row per branch, ordered by code (S4 before S10)", () => {
    const text = trunkCard([
      bundle("svc:pay", "svc:res", { request: 2 }, "request", "a→b"),
      bundle("3p:stripe", "svc:pay", { "ext-call": 1 }, "ext-call", "b→a"),
      bundle("svc:bill", "svc:pay", { request: 1, "db-read": 1 }, "request", "b→a"),
    ], end);
    expect(text).toBe([
      "3 lines · request ×2, ext-call, db-read",
      "→ S4 billing · request, db-read",
      "→ S10 reservations · request",
      "→ X3 stripe · ext-call",
    ].join("\n"));
  });

  it("a merge: ← rows from each source", () => {
    const text = trunkCard([
      bundle("svc:res", "svc:pay", { request: 1 }, "request", "a→b"),
      bundle("svc:bill", "svc:pay", { request: 1 }, "request", "a→b"),
    ], end);
    expect(text).toBe("2 lines · request ×2\n← S4 billing · request\n← S10 reservations · request");
  });

  it("no shared end: each row names both ends in the data's direction", () => {
    const text = trunkCard([
      bundle("svc:res", "svc:pay", { request: 1 }, "request", "a→b"),
      bundle("svc:bill", "svc:ops", { request: 1 }, "request", "b→a"),
    ], end);
    expect(text).toBe("2 lines · request ×2\nS9 ops → S4 billing · request\nS10 reservations → S2 payments · request");
  });

  it("a line with no kinds: no trailing separator", () => {
    const text = trunkCard([
      bundle("svc:pay", "svc:res", {}, "calls", "a→b"),
      bundle("svc:pay", "svc:bill", {}, "calls", "a→b"),
    ], end);
    expect(text).toBe("2 lines\n→ S4 billing\n→ S10 reservations");
  });
});

describe("shared tiles on demo F0", () => {
  it("every tile two or more surface lines hold, and no other", () => {
    const model = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    const { bundles, doors } = model.bundles(SITE);
    const { tf, routes } = planFloor(model, SITE, doors, bundles);
    const covered = coveredKeys(flightPaths(tf), bundles);
    const tiles = sharedTiles(routes, (r) => covered.has(r.key));
    expect(tiles.size).toBeGreaterThan(0);
    for (const t of tiles.values()) {
      expect(t.ris.length).toBeGreaterThanOrEqual(2);
      for (const i of t.ris) {
        expect(routes[i].kind).not.toBe("drone");
        expect(routes[i].pieces.some((p) => p.x === t.x && p.y === t.y && !p.under)).toBe(true);
      }
    }
    // a junction plate's tile is one of them
    const plate = routes.flatMap((r) => r.pieces).find((p) => p.join && !p.under)!;
    expect(tiles.has(`${plate.x},${plate.y}`)).toBe(true);
    // and the card of a shared tile reads as a split or a merge of real bundles
    const t = tiles.get(`${plate.x},${plate.y}`)!;
    const text = trunkCard(t.ris.map((i) => bundles.find((b) => b.key === routes[i].key)!), (id) => ({ code: model.codes.get(id) ?? "", name: model.label(id) }));
    expect(text.split("\n")[0]).toMatch(new RegExp(`^${t.ris.length} lines · `));
    expect(text.split("\n").slice(1).every((l) => /^[→←↔] /.test(l))).toBe(true);
  });
});
