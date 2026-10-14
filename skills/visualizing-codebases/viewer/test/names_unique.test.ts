import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { floorPrefix, shownName } from "../src/floor/names";
import { Model } from "../src/model/model";
import type { CodeMap } from "../src/model/types";

const DEMO = new URL("../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const SHOP = new URL("./fixtures/shop.code-map.json", import.meta.url);
const BIG = process.env.VIZ_BIG_MAP ?? "";
const load = (p: URL | string) => new Model(JSON.parse(readFileSync(p, "utf8")) as CodeMap);

/** What a floor's boxes and its "On this floor" list show: the floor-unique name, less the prefix the floor shares. */
function shown(model: Model, container: string): Map<string, string> {
  const items = Object.keys(model.floor(container)?.items ?? {});
  const prefix = floorPrefix(model, items);
  return new Map(items.map((id) => [id, shownName(model, id, prefix)]));
}

/** Items on one floor that show a name another item there shows too. */
function clashes(model: Model, name: (container: string) => Map<string, string>): string[] {
  const out: string[] = [];
  for (const c of Object.keys(model.map.layout.containers)) {
    const seen = new Map<string, string[]>();
    for (const [id, n] of name(c)) seen.set(n, [...(seen.get(n) ?? []), id]);
    for (const [n, ids] of seen) if (ids.length > 1) out.push(`${c}: "${n}" × ${ids.join(", ")}`);
  }
  return out;
}

const PKG = "billing::city.parking.billing/";
const B = "billing::city.parking.billing.";

describe("names on a floor never repeat", () => {
  it("every demo and fixture floor shows each name once (boxes, list, full-name tag)", () => {
    for (const model of [load(DEMO), load(SHOP)]) {
      expect(clashes(model, (c) => shown(model, c))).toEqual([]);
      const full = (c: string) => new Map(Object.keys(model.floor(c)?.items ?? {}).map((id) => [id, model.itemName(id)]));
      expect(clashes(model, full)).toEqual([]);
    }
  });

  it("billing's package floor tells a trait from its companion object", () => {
    const names = shown(load(DEMO), PKG);
    expect(names.get(`${B}DeadLetters`)).toBe("DeadLetters");
    expect(names.get(`${B}DeadLetters$`)).toBe("DeadLetters (object)");
    expect(names.get(`${B}BillingService`)).toBe("BillingService");
    expect(names.get(`${B}BillingService$`)).toBe("BillingService (object)");
    expect(names.get(`${B}Main$`)).toBe("Main");   // no clash, no tag
  });

  it("an implementation reads as one: qualified, and an anonymous one says (impl)", () => {
    const model = load(DEMO);
    expect(model.itemName(`${B}BillingService.Live`)).toBe("BillingService.Live");
    expect(model.itemName(`${B}DeadLetters.live$impl`)).toBe("DeadLetters.live (impl)");
    expect(shown(model, `${B}DeadLetters$`).get(`${B}DeadLetters.live$impl`)).toBe("DeadLetters.live (impl)");
    expect(shown(model, `${B}BillingService$`).get(`${B}BillingService.Live`)).toBe("BillingService.Live");
    expect(model.label(`${B}DeadLetters.live$impl`)).toBe("new DeadLetters");   // the map's own name is unchanged
  });

  it("any other clash takes the shortest parent segment that tells them apart", () => {
    const map = JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap;
    const floor = map.layout.containers[PKG];
    for (const id of ["billing::city.parking.billing.a.Twin", "billing::city.parking.billing.b.Twin"]) {
      map.nodes.push({ id, kind: "class", parent: PKG, name: "Twin" } as CodeMap["nodes"][number]);
      floor.items[id] = { ...Object.values(floor.items)[0] };
    }
    const model = new Model(map);
    expect(model.itemName("billing::city.parking.billing.a.Twin")).toBe("a.Twin");
    expect(model.itemName("billing::city.parking.billing.b.Twin")).toBe("b.Twin");
  });

  it.skipIf(!BIG || !existsSync(BIG))("the big map's floors show each name once", () => {
    const model = load(BIG);
    expect(clashes(model, (c) => shown(model, c))).toEqual([]);
  });
});

describe("a disambiguated name keeps its own name", () => {
  const maps: [string, URL | string][] = [["demo", DEMO], ["fixture", SHOP]];
  if (BIG && existsSync(BIG)) maps.push(["big", BIG]);
  it.each(maps)("%s: every shown name that gained a tag still contains the item's own name", (_what, p) => {
    const model = load(p);
    const lost: string[] = [];
    for (const c of Object.keys(model.map.layout.containers))
      for (const [id, s] of shown(model, c)) {
        const base = model.baseName(id);
        if (base.length < model.itemName(id).length && !s.includes(base)) lost.push(`${c}: ${id} shows "${s}"`);
      }
    expect(lost).toEqual([]);
  });

  it("overloads keep their method name (a config layer's config/1, config/2 shape)", () => {
    const map = JSON.parse(readFileSync(SHOP, "utf8")) as CodeMap;
    const [floor, f] = Object.entries(map.layout.containers).find(([, f]) => Object.keys(f.items).some((id) => id.endsWith("#run/2")))!;
    for (const id of Object.keys(f.items)) if (!/#run\/[12]$/.test(id)) delete f.items[id];   // a floor of overloads only
    const names = shown(new Model(map), floor);
    expect(names.get("worker::worker.main#run/1")).toBe("run/1");
    expect(names.get("worker::worker.main#run/2")).toBe("run/2");
  });
});

describe("search finds what it shows", () => {
  it("matches the floor-unique names too", () => {
    const model = load(DEMO);
    expect(model.search("DeadLetters.live")).toContain(`${B}DeadLetters.live$impl`);
    expect(model.search("DeadLetters (object)")[0]).toBe(`${B}DeadLetters$`);
    expect(model.search("object")).toContain(`${B}DeadLetters$`);
    expect(model.search("BillingService.Live")[0]).toBe(`${B}BillingService.Live`);
  });
});
