// The Model's caches and indexes (bundles per floor, lift chains, relations by chain step and by owner, ancestor sets,
// children) give what the walks they replace gave (reference.ts: those walks as they were), over the demo, the shop
// fixture, the 17 guide maps and a copy of the demo with floor groups (range groups, a group of groups), a twin and a
// parentless table; and the walks no longer run where an index answers. A cached result is shared, so no consumer may
// write to it: the deep-freeze test runs them all over frozen maps and bundles.
import { describe, expect, it, vi } from "vitest";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap, Floor, Group } from "../../src/model/types";
import { boundaryMethods, methodsIn } from "../../src/trace/entries";
import { TRACE_KINDS } from "../../src/trace/graph";
import { planJob } from "../../src/factory/plan-job";
import { floorLayers, layersOfRelations } from "../../src/model/layers";
import { defaultLit } from "../../src/floor/lit";
import { floorNote, traceItems, traceKeys, traceMarks } from "../../src/trace/floor";
import { codeLinkCount } from "../../src/factory/conduits";
import { auditMap } from "../../src/audit/run";
import { Reference, methodsIn as refMethodsIn } from "./reference";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const SHOP = new URL("../fixtures/shop.code-map.json", import.meta.url);
const GUIDE = new URL("../../guide/maps/", import.meta.url);
const BIG = new URL("../../.profile/big.code-map.json", import.meta.url);

/** The demo with floor groups as `assemble` makes them on a crowded floor: each run of three items on a floor of four
 *  or more becomes a range group, an item on that floor whose own floor holds the three; the first floor's first two
 *  groups go inside a third (a group of groups). Plus a twin on the first service and a table with no datastore. */
function grouped(text: string): CodeMap {
  const map = JSON.parse(text) as CodeMap;
  const floors = map.layout.containers;
  const crowded = Object.keys(floors).filter((c) => c !== SITE && Object.keys(floors[c].items).length >= 4).sort();
  let nested = false;
  for (const c of crowded) {
    const f = floors[c];
    const items = Object.keys(f.items).sort();
    const groups: Group[] = [];
    for (let i = 0; i + 3 <= items.length; i += 3) {
      const id = `grp:${c}:range:${i}`, members = items.slice(i, i + 3);
      groups.push({ id, label: `range ${i}`, members, kind: "range" });
      floors[id] = { strategy: f.strategy, items: Object.fromEntries(members.map((m) => [m, f.items[m]])) } as Floor;
      f.items[id] = f.items[members[0]];
      for (const m of members) delete f.items[m];
    }
    if (!nested && groups.length >= 2) {
      nested = true;
      const outer = `grp:${c}:outer`, innerGroups = groups.splice(0, 2), inner = innerGroups.map((g) => g.id);
      groups.push({ id: outer, label: "outer", members: inner, kind: "range" });
      floors[outer] = { strategy: f.strategy, items: Object.fromEntries(inner.map((g) => [g, f.items[g]])), groups: innerGroups } as Floor;
      f.items[outer] = f.items[inner[0]];
      for (const g of inner) delete f.items[g];
    }
    f.groups = [...(f.groups ?? []), ...groups];
  }
  const service = map.nodes.find((n) => n.kind === "service" && floors[n.id])!;
  const lib = map.nodes.find((n) => n.kind === "package" && n.parent !== service.id && floors[n.parent ?? ""])!;
  service.twins = [...(service.twins ?? []), lib.id];
  floors[service.id].items[`twin:${lib.id}`] = { region: "main", col: 9, row: 9 };
  const method = map.nodes.find((n) => n.kind === "method")!;
  map.nodes.push({ id: "tbl:loose", kind: "table", name: "loose", parent: null });
  map.relations.push({ id: "r:loose", kind: "db-write", from: method.id, to: "tbl:loose", confidence: "confirmed", evidence: [] });
  return map;
}

const DEMO_TEXT = readFileSync(DEMO, "utf8");
const MAPS: [string, () => CodeMap][] = [
  ["demo", () => JSON.parse(DEMO_TEXT)],
  ["demo, grouped", () => grouped(DEMO_TEXT)],
  ["shop", () => JSON.parse(readFileSync(SHOP, "utf8"))],
  ...readdirSync(GUIDE).filter((f) => f.endsWith(".code-map.json")).sort()
    .map((f): [string, () => CodeMap] => [f, () => JSON.parse(readFileSync(new URL(f, GUIDE), "utf8"))]),
];

const floors = (m: Model) => Object.keys(m.map.layout.containers);
const twins = (m: Model) => m.map.nodes.flatMap((n) => (n.twins ?? []).map((t) => `twin:${t}`));
const ids = (m: Model) => [...m.nodes.keys(), ...m.groups.keys(), ...twins(m)];
const doorsOf = (m: Model) => floors(m).flatMap((c) => m.bundles(c).doors.map((d) => [c, d.anchor] as const));
const refBoundary = (m: Model, ref: Reference, id: string) => {
  const within = (x: string) => x === id || ref.isInside(x, id);
  const out = new Set<string>();
  for (const r of m.map.relations) {
    if (!TRACE_KINDS.includes(r.kind)) continue;
    for (const [end, other] of [[r.from, r.to], [r.to, r.from]] as const)
      if (m.nodes.get(end)?.kind === "method" && ref.isInside(end, id) && !within(other)) out.add(end);
  }
  return [...out].sort((a, b) => (m.codes.get(a) ?? a).localeCompare(m.codes.get(b) ?? b, undefined, { numeric: true }));
};

describe("Model caches equal the walks they replace", () => {
  it.each(MAPS)("%s", (_name, load) => {
    const m = new Model(load()), ref = new Reference(new Model(load()));
    for (const c of floors(m)) {
      expect(m.bundles(c), c).toEqual(ref.bundles(c));
      expect(m.bundles(c, { codeLinks: true }), c).toEqual(ref.bundles(c, { codeLinks: true }));
      for (const id of ids(m)) expect(m.liftTo(c, id), `${c} ${id}`).toBe(ref.liftTo(c, id));
    }
    for (const a of ids(m)) for (const b of ids(m)) if (m.isInside(a, b) !== ref.isInside(a, b)) expect(m.isInside(a, b), `${a} in ${b}`).toBe(ref.isInside(a, b));
    for (const id of ids(m)) {
      expect(m.relationsOf(id), id).toEqual(ref.relationsOf(id));
      expect(methodsIn(m, id), id).toEqual(refMethodsIn(m, ref, id));
      expect(boundaryMethods(m, id), id).toEqual(refBoundary(m, ref, id));
      // ids beyond nodes too: a group's members can be groups or twins
      expect(new Set(m.descendants(id)), id).toEqual(new Set(ids(m).filter((x) => ref.isInside(x, id))));
    }
    for (const [c, anchor] of doorsOf(m)) expect(m.doorLanding(c, anchor), `${c} ${anchor}`).toEqual(ref.landing(c, anchor));
  }, 300_000);

  it("the grouped demo has what the walks branch on: groups in groups, a twin, a parentless table", () => {
    const m = new Model(grouped(DEMO_TEXT));
    const nested = [...m.groups.values()].filter((g) => g.members.some((x) => m.groups.has(x)));
    expect(nested.length).toBe(1);
    expect(m.groups.size).toBeGreaterThan(3);
    expect(twins(m).length).toBeGreaterThan(0);
    expect(m.nodes.get("tbl:loose")?.parent).toBeNull();
    expect(m.isInside(m.map.nodes.find((n) => n.kind === "method" && m.path(m.floorOf(n.id)!).includes(nested[0].id))!.id, nested[0].id)).toBe(true);
  });

  it.skipIf(!existsSync(BIG))("the big map's service floor, its range groups' floors and their members' floors", () => {
    const text = readFileSync(BIG, "utf8");
    const m = new Model(JSON.parse(text)), ref = new Reference(new Model(JSON.parse(text)));
    const ranges = [...m.groups.keys()].slice(0, 3);
    const service = m.groups.get(ranges[0])!.container;
    const cs = [SITE, service, ...ranges, ...ranges.map((g) => m.groups.get(g)!.members[0])];
    for (const c of cs) expect(m.bundles(c), c).toEqual(ref.bundles(c));
    const sample = m.map.nodes.filter((_, i) => i % 97 === 0).map((n) => n.id);
    for (const a of sample) for (const b of [...cs, ...sample]) expect(m.isInside(a, b), `${a} in ${b}`).toBe(ref.isInside(a, b));
    for (const id of [service, ...ranges]) {
      expect(m.relationsOf(id), id).toEqual(ref.relationsOf(id));
      expect(methodsIn(m, id), id).toEqual(refMethodsIn(m, ref, id));
    }
  }, 300_000);
});

describe("names on demand and the search index equal the walks they replace", () => {
  /** Every query a reader's Find can type that reaches a different part of the ranking: each code, each 1–3 character
   *  prefix of each name (the map's and the floor's), and 50 seeded random substrings of names and ids. */
  const queries = (m: Model, ref: Reference): string[] => {
    const names = m.map.nodes.flatMap((n) => [n.name, ref.itemName(n.id)]);
    const out = new Set<string>(m.map.nodes.map((n) => m.codes.get(n.id) ?? ""));
    for (const x of names) for (let k = 1; k <= 3; k++) out.add(x.slice(0, k));
    let seed = 7;
    const rand = (n: number) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
    const pool = [...names, ...m.map.nodes.map((n) => n.id)];
    for (let i = 0; i < 50; i++) {
      const s = pool[rand(pool.length)], a = rand(s.length), b = a + 1 + rand(Math.min(8, s.length - a));
      out.add(i % 5 === 0 ? s.slice(a, b).toUpperCase() : s.slice(a, b));
    }
    return [...out].filter(Boolean);
  };

  it.each(MAPS)("%s", (_name, load) => {
    const m = new Model(load()), ref = new Reference(new Model(load()));
    const doors = doorsOf(m).map(([, anchor]) => m.doorId(anchor));
    for (const id of [...ids(m), ...doors]) expect(m.itemName(id), id).toBe(ref.itemName(id));
    for (const q of queries(m, ref)) {
      expect(m.search(q, 12), q).toEqual(ref.search(q, 12));
      expect(m.search(q, 30), q).toEqual(ref.search(q, 30));
    }
  }, 300_000);

  it("itemName names one site item without naming every node", () => {
    const model = new Model(JSON.parse(DEMO_TEXT));
    const spy = vi.spyOn(model, "baseName");
    const items = Object.keys(model.floor(SITE)!.items), item = items.sort()[0];
    model.itemName(item);
    // F0's names alone: one call per item, and one more for each twin (named after the package it stands for)
    const twins = items.filter((id) => model.twinOf(id)).length;
    expect(spy.mock.calls.length).toBeGreaterThan(0);
    expect(spy.mock.calls.length).toBeLessThanOrEqual(items.length + twins);
  });
});

describe("an id that is also an object key", () => {
  it("a node named `constructor` lifts as its parent does, on every floor, and bundles agree", () => {
    const map = JSON.parse(DEMO_TEXT) as CodeMap;
    const cls = map.nodes.find((n) => n.kind === "class")!, other = map.nodes.find((n) => n.kind === "method" && n.parent !== cls.id)!;
    map.nodes.push({ id: "constructor", kind: "method", name: "constructor", parent: cls.id });
    map.relations.push({ id: "r:ctor", kind: "calls", from: "constructor", to: other.id, confidence: "confirmed", evidence: [] });
    const m = new Model(map);
    for (const c of floors(m)) {
      expect(m.liftTo(c, "constructor"), c).toBe(m.liftTo(c, cls.id));
      const ends = m.bundles(c).bundles.flatMap((b) => [b.a, b.b]);
      expect(ends, c).not.toContain("constructor");
    }
    expect(m.relationsOf(cls.id).some((r) => r.id === "r:ctor")).toBe(true);
    expect(m.descendants(cls.id)).toContain("constructor");
  });
});

describe("Model caches are used", () => {
  const m = () => new Model(JSON.parse(DEMO_TEXT));
  const deepest = (model: Model) => floors(model).filter((c) => model.bundles(c).bundles.length)
    .sort((a, b) => model.path(b).length - model.path(a).length || a.localeCompare(b))[0];

  it("bundles(c) is the same object each time, one per floor and code-links flag", () => {
    const model = m();
    for (const c of floors(model)) {
      expect(model.bundles(c), c).toBe(model.bundles(c));
      expect(model.bundles(c, { codeLinks: true }), c).toBe(model.bundles(c, { codeLinks: true }));
      expect(model.bundles(c, { codeLinks: false }), c).toBe(model.bundles(c));
    }
  });

  it("bundles on a deep floor lifts fewer ends than every relation's two", () => {
    const model = m(), c = deepest(m());   // found on another model: this one has planned nothing yet
    expect(model.path(c).length).toBeGreaterThan(3);
    const spy = vi.spyOn(model, "liftTo");
    model.bundles(c);
    // every relation a floor below the site draws (all but code links), both ends: what the walk over all relations lifts
    const drawn = model.map.relations.filter((r) => r.kind !== "uses-code").length;
    expect(spy.mock.calls.length).toBeLessThan(2 * drawn);
  });

  it("relationsOf and methodsIn ask isInside nothing once indexed", () => {
    const model = m(), all = ids(model);
    for (const id of all) { model.relationsOf(id); methodsIn(model, id); }
    const spy = vi.spyOn(model, "isInside");
    for (const id of all) { model.relationsOf(id); methodsIn(model, id); }
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("no consumer writes to the map or a cached bundles result", () => {
  const deepFreeze = <T>(o: T): T => {
    if (o && typeof o === "object" && !Object.isFrozen(o)) {
      Object.freeze(o);
      for (const v of Object.values(o)) deepFreeze(v);
    }
    return o;
  };
  it.each(MAPS)("%s", (_name, load) => {
    const map = deepFreeze(load());
    const model = new Model(map);
    for (const c of floors(model)) { deepFreeze(model.bundles(c)); deepFreeze(model.bundles(c, { codeLinks: true })); }
    expect(() => {
      for (const c of floors(model)) {
        if (model.floor(c)) planJob(model, c);
        floorLayers(model, c);
        layersOfRelations(model, model.bundles(c));
        defaultLit(model, c);
        const items = traceItems(model, c, [...model.nodes.keys()]);
        traceKeys(model, c, items);
        for (const id of model.nodes.keys()) { traceMarks(model, c, id, null); floorNote(model, c, id); }
      }
      codeLinkCount(model);
      for (const id of ids(model)) { model.relationsOf(id); methodsIn(model, id); boundaryMethods(model, id); }
      for (const [c, anchor] of doorsOf(model)) model.doorShows(c, anchor);
      auditMap(map, Infinity);
    }).not.toThrow();
  }, 300_000);
});
