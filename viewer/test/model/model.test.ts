import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import shop from "../fixtures/shop.code-map.json";
import { MapError, Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";

const map = shop as unknown as CodeMap;

describe("Model", () => {
  it("refuses maps older than version 2", () => {
    expect(() => new Model({ ...map, meta: { ...map.meta, schema_version: 1 } })).toThrow(MapError);
    expect(() => new Model({ ...map, meta: { ...map.meta, schema_version: 3 } })).not.toThrow();
    expect(() => new Model({} as CodeMap)).toThrow(/not a code map/);
  });

  it("gives every node a short code built from its parents", () => {
    const m = new Model(map);
    expect(m.codes.get("svc:shop")).toMatch(/^S\d$/);
    const repo = m.codes.get("shop::io.demo.shop.repo.PgOrderRepo")!;
    expect(repo.startsWith(m.codes.get("shop::io.demo.shop.repo/")! + "·C")).toBe(true);
    expect(new Set(m.codes.values()).size).toBe(m.codes.size);
  });

  it("bundles site relations into one line per pair, tables rolled up to their warehouse", () => {
    const m = new Model(map);
    const { bundles } = m.bundles(SITE);
    const keys = bundles.map((b) => b.key);
    expect(new Set(keys).size).toBe(keys.length);
    const worker = bundles.find((b) => b.key === "svc:shop|svc:worker")!;
    expect(worker.kinds.request).toBe(2);
    expect(worker.inferred).toBe(1);
    expect(bundles.some((b) => b.key === "db:postgres:DB_HOST|svc:shop" && b.kind === "db-write")).toBe(true);
    expect(bundles.some((b) => b.relations.some((r) => r.kind === "calls" || r.kind === "uses-code"))).toBe(false);
  });

  it("orients data flow: a stream subscription flows from the external into the service", () => {
    const m = new Model(map);
    const feed = m.bundles(SITE).bundles.find((b) => b.key === "3p:feed|svc:worker")!;
    expect(feed.kind).toBe("stream");
    expect(feed.flow).toBe("a→b");
  });

  it("shows calls inside a service and leaves outside relations as outward stubs", () => {
    const m = new Model(map);
    const { bundles, outward } = m.bundles("worker::worker.main");
    expect(bundles.length + outward.length).toBeGreaterThan(0);
    expect(outward.some((o) => o.relations.some((r) => r.kind === "event"))).toBe(true);  // topic → run/2
  });

  it("finds the floor and path of a method", () => {
    const m = new Model(map);
    const id = "worker::worker.main#run/2";
    expect(m.floorOf(id)).toBe("worker::worker.main");
    expect(m.path("worker::worker.main")).toEqual([SITE, "svc:worker", "worker::worker/", "worker::worker.main"]);
  });

  it("searches by code and name", () => {
    const m = new Model(map);
    const code = m.codes.get("svc:worker")!;
    expect(m.search(code)[0]).toBe("svc:worker");
    expect(m.search("pgorder")).toContain("shop::io.demo.shop.repo.PgOrderRepo");
  });

  it("puts relations that leave a floor through doors on its frame", () => {
    const m = new Model(map);
    const { doors, bundles } = m.bundles("worker::worker.main");
    const topic = doors.find((d) => d.anchor === "topic:kafka:orders")!;
    expect(topic).toMatchObject({ id: "door:topic:kafka:orders", side: "in" });
    expect(bundles.some((b) => b.key.includes("door:topic:kafka:orders") && b.kind === "event")).toBe(true);
    expect(m.bundles(SITE).doors).toEqual([]);
    expect(m.anchorFor("worker::worker.main", "shop::io.demo.shop.repo.PgOrderRepo#save/2")).toBe("svc:shop");
  });

  it("leads a door to the door back on the far side, on the deepest floor that shows it", () => {
    const m = new Model(map);
    // worker.main's door to worker.util/ lands where the call ends, at helpers' door back to worker/
    expect(m.doorLanding("worker::worker.main", "worker::worker.util/")).toEqual({ floor: "worker::worker.util.helpers", door: "door:worker::worker/" });
    // and that door leads back: the same pair of doors, each the other's way in
    expect(m.doorLanding("worker::worker.util.helpers", "worker::worker/")).toEqual({ floor: "worker::worker.main", door: "door:worker::worker.util/" });
    // a door to a library goes into the library, to the floor of the code called
    expect(m.doorLanding("svc:worker", "lib:common")).toEqual({ floor: "pylib::pylib.client", door: "door:svc:worker" });
    // no floor of its own (a topic), or none inside that draws the line back (worker's requests start at the service
    // itself): the door stops at the anchor, as before
    expect(m.doorLanding("worker::worker.main", "topic:kafka:orders")).toBeUndefined();
    expect(m.doorLanding("svc:shop", "svc:worker")).toBeUndefined();
    // a door is named after the building it opens, else its anchor
    expect(m.doorShows("worker::worker.main", "worker::worker.util/")).toBe("worker::worker.util.helpers");
    expect(m.doorShows("worker::worker.main", "topic:kafka:orders")).toBe("topic:kafka:orders");
  });

  it("keeps a database's own id and name inside buildings (no door, same warehouse as on the site)", () => {
    const m = new Model(map);
    const { doors, bundles } = m.bundles("shop::io.demo.shop.repo.PgOrderRepo");
    expect(doors.find((d) => d.anchor === "db:postgres:DB_HOST")?.id).toBe("db:postgres:DB_HOST");
    expect(bundles.some((b) => b.key.includes("db:postgres:DB_HOST") && b.kind === "db-write")).toBe(true);
  });

  it("shows a warehouse as shelves: no lines, access summarised per table", () => {
    const m = new Model(map);
    expect(m.bundles("db:postgres:DB_HOST")).toMatchObject({ bundles: [], doors: [] });
    const t = m.map.nodes.find((n) => n.kind === "table")!;
    expect(m.tableAccess(t.id).writers).toEqual([m.codes.get("svc:shop")]);
  });

  it("places a group on the floor that shows it, and names doors after their anchor", () => {
    const grouped = structuredClone(map);
    const floor = grouped.layout.containers["common::io.demo.common.db/"];
    floor.groups = [{ id: "grp:db", label: "db family", members: ["common::io.demo.common.db.Db$"], kind: "family" }];
    const m = new Model(grouped);
    expect(m.floorOf("grp:db")).toBe("common::io.demo.common.db/");
    expect(m.label("door:svc:shop")).toBe(m.label("svc:shop"));
    expect(m.codes.get("svc:shop")).toBeTruthy();
  });

  it("names the real problem: a newer format, or a map with parts missing", () => {
    expect(() => new Model({ ...map, meta: { ...map.meta, schema_version: 4 } })).toThrow(/newer|version 4/);
    expect(() => new Model({ ...map, meta: { ...map.meta, schema_version: 4 } })).not.toThrow(/to get version 3/);
    expect(() => new Model({ ...map, layout: {} } as unknown as CodeMap)).toThrow(MapError);
  });

  it("draws a module two services deploy as a twin that leads to the real code", () => {
    const twinned = structuredClone(map);
    twinned.nodes.find((n) => n.id === "svc:shop")!.twins = ["worker::worker/"];
    twinned.layout.containers["svc:shop"].items["twin:worker::worker/"] = { region: "line", col: 5, row: 0 };
    const m = new Model(twinned);
    const t = "twin:worker::worker/";
    expect(m.twinOf(t)).toBe("worker::worker/");
    expect(m.twinOf("svc:shop")).toBeUndefined();
    expect(m.label(t)).toBe(m.label("worker::worker/"));
    expect(m.kindOf(t)).toBe("package");
    expect(m.codes.get(t)).toBe(m.codes.get("worker::worker/"));
    expect(m.floorOf(t)).toBe("svc:shop");
  });
});


describe("implements links", () => {
  const demo = new Model(JSON.parse(readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8")) as CodeMap);
  const trait = "billing::city.parking.billing.DeadLetters";
  const impl = "billing::city.parking.billing.DeadLetters.live$impl";
  const pkg = "billing::city.parking.billing/";

  it("finds a trait's implementers and what a class implements", () => {
    expect(demo.implementersOf(trait)).toEqual([impl]);
    expect(demo.implementedBy(impl)).toEqual([trait]);
    expect(demo.implementersOf(impl)).toEqual([]);
    expect(demo.implementedBy(trait)).toEqual([]);
  });

  it("lifts both ends to the floor's items and keeps only distinct pairs", () => {
    for (const c of Object.keys(demo.map.layout.containers)) {
      const items = demo.floor(c)!.items;
      const links = demo.implementLinks(c);
      expect(new Set(links.map((l) => l.key)).size).toBe(links.length);
      for (const l of links) {
        expect(l.trait).not.toBe(l.impl);
        expect(l.trait in items && l.impl in items, `${c}: ${l.key}`).toBe(true);
      }
    }
    expect(demo.implementLinks(pkg)).toContainEqual({ key: `${trait}|${trait}$`, trait, impl: `${trait}$` });   // the impl sits in the companion object
    expect(demo.implementLinks(SITE)).toEqual([]);   // both ends are inside one service
  });

  it("names the one implementation a trait method continues into", () => {
    const method = demo.map.nodes.find((n) => n.parent === trait && n.kind === "method")!.id;
    expect(demo.implementerOn(pkg, method)).toBe(`${trait}$`);
    expect(demo.implementerOn(pkg, trait)).toBe(`${trait}$`);
    expect(demo.implementerOn(SITE, method)).toBeUndefined();   // same item on the site floor
    expect(demo.implementerOn(pkg, "billing::city.parking.billing.Invoice")).toBeUndefined();
  });

  /** The demo with one more class implementing DeadLetters, placed under `parent`. */
  const withSecond = (parent: string) => {
    const m = structuredClone(demo.map);
    m.nodes.push({ id: "billing::extra.Impl", kind: "class", name: "ExtraImpl", parent, implements: [trait] });
    return new Model(m);
  };

  it("makes no hop unless exactly one implementer lands on the floor", () => {
    const method = demo.map.nodes.find((n) => n.parent === trait && n.kind === "method")!.id;
    expect(withSecond("billing::city.parking.billing.InvoiceRepo$").implementerOn(pkg, method)).toBeUndefined();   // two, on two items
    expect(withSecond(`${trait}$`).implementerOn(pkg, method)).toBeUndefined();   // two in one companion still count as two
    const self = structuredClone(demo.map);   // the only implementer lifts to the trait's own item
    self.nodes.find((n) => n.id === impl)!.implements = [];
    self.nodes.push({ id: "billing::inner.Impl", kind: "class", name: "InnerImpl", parent: trait, implements: [trait] });
    expect(new Model(self).implementerOn(pkg, method)).toBeUndefined();
  });
});
