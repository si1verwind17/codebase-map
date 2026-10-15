// test/guide_maps.test.ts
// The field guide's tiny example maps (scripts/guide_maps.py → guide/maps): each, planned on the floor its picture shows,
// draws the pattern its page explains, and stays small and clean (no failed line, trunk rules hold, every line plugged).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { floorLayers } from "../../src/model/layers";
import { planFloor, type FloorPlan } from "../../src/factory/plan";
import { storeArt, type Store } from "../../src/factory/machines";
import type { TileRoute } from "../../src/factory/router";
import { TraceGraph } from "../../src/trace/graph";
import { layoutTrace } from "../../src/trace/layout";
import { initialState } from "../../src/trace/reach";
import { checkTrunks, flowOf, plugged } from "../factory/factory_trunks";

const MAX_MACHINES = 12;

const load = (name: string) =>
  new Model(JSON.parse(readFileSync(new URL(`../../guide/maps/${name}.code-map.json`, import.meta.url), "utf8")) as CodeMap);

/** The floor's plan with its extra layers, checked: small, nothing failed, trunk rules and plug-ins hold. */
function plan(m: Model, c: string): FloorPlan & { bundles: ReturnType<Model["bundles"]>["bundles"] } {
  const { bundles, doors, layered } = m.bundles(c);
  const p = planFloor(m, c, doors, bundles, layered);
  const label = `${m.map.meta.repo} @ ${c}`;
  expect(p.tf.boxes.size, `${label}: at most ${MAX_MACHINES} machines`).toBeLessThanOrEqual(MAX_MACHINES);
  const all = [...p.routes, ...Object.values(p.layers ?? {}).flatMap((l) => l!.routes)];
  expect(all.filter((r) => r.failed).map((r) => r.key), `${label}: no failed line`).toEqual([]);
  checkTrunks(p.tf, p.routes, label);
  for (const r of p.routes) if (r.pieces.length) plugged(p.tf, r);
  return { ...p, bundles };
}

const route = (p: { routes: TileRoute[] }, a: string, b: string) => p.routes.find((r) => r.key === [a, b].sort().join("|"));
const pieces = (p: { routes: TileRoute[] }) => p.routes.flatMap((r) => r.pieces);

describe("the field guide's examples draw their patterns", () => {
  it("belt: a one-way belt between two services, and a two-way belt", () => {
    const p = plan(load("belt"), SITE);
    const one = route(p, "svc:orders", "svc:billing")!, two = route(p, "svc:billing", "svc:payments")!;
    expect([one.kind, two.kind]).toEqual(["belt", "belt"]);
    expect(one.both).toBe(false);
    expect(flowOf(p.tf, one)).toEqual({ src: "svc:orders", dst: "svc:billing" });
    expect(two.both).toBe(true);
  });

  it("splitters: one trunk splits out of orders and one merges into reports", () => {
    const p = plan(load("splitters"), SITE);
    const joins = pieces(p).map((q) => q.join);
    expect(joins).toContain("split");
    expect(joins).toContain("merge");
  });

  it("pipe: a pipe route", () => {
    const p = plan(load("pipe"), SITE);
    expect(route(p, "svc:orders", "svc:tracking")?.kind).toBe("pipe");
  });

  it("drones: an airfield with one hub, the producer's pad and two consumer pads", () => {
    const p = plan(load("drones"), SITE);
    const l = p.landing!;
    expect(l.messaging.airfields).toHaveLength(1);
    expect(l.messaging.airfields[0].hubs).toHaveLength(1);
    expect(l.pads.filter((q) => q.role === "consume").map((q) => q.machine).sort()).toEqual(["svc:billing", "svc:reports"]);
    expect(l.pads.filter((q) => q.role === "produce").map((q) => q.machine)).toEqual(["svc:orders"]);
    expect(p.routes.every((r) => r.kind === "drone")).toBe(true);
  });

  it("queues: a waiting stack on the work queue and a dead-letter hub", () => {
    const l = plan(load("queues"), SITE).landing!;
    const hubs = l.messaging.airfields.flatMap((a) => a.hubs);
    const queue = hubs.find((h) => h.topic === "topic:events:invoices")!;
    expect(queue.waiting).toBe(true);
    expect(l.stacks.map((s) => s.topic)).toContain("topic:events:invoices");
    expect(hubs.find((h) => h.dlqOf === "topic:events:invoices")?.topic).toBe("topic:events:invoices-dead");
    expect(l.messaging.consumers.filter((c) => c.topic === queue.topic).map((c) => c.flight)).toEqual(["take", "take"]);
    expect(l.messaging.failures.map((f) => [f.machine, f.dlq])).toEqual([["svc:billing", "topic:events:invoices-dead"]]);
  });

  it("in_process: the service's own airfield holds the queue hub; the site shows no queue and no hand-off", () => {
    const m = load("in_process");
    const site = plan(m, SITE);
    expect([...site.tf.boxes.keys()].some((id) => id.startsWith("inq:"))).toBe(false);
    expect(site.bundles.filter((b) => b.kinds["hand-off"])).toEqual([]);

    const p = plan(m, "svc:orders");
    const q = "inq:orders:outbox";
    expect(p.tf.boxes.get(q)?.foot).toBe("hub");
    const field = p.tf.zones.find((z) => z.airfield)!;
    expect(field.name).toBe("in-process");
    const hub = p.tf.boxes.get(q)!;
    expect(hub.x >= field.x && hub.x + hub.w <= field.x + field.w && hub.y >= field.y && hub.y + hub.h <= field.y + field.h).toBe(true);
    const l = p.landing!;
    expect(l.messaging.airfields.map((a) => [a.broker, a.hubs.map((h) => h.topic)])).toEqual([["in-process", [q]]]);
    expect(l.stacks.map((s) => s.topic)).toEqual([q]);   // a queue keeps its waiting stack
    expect(l.messaging.producers.map((x) => x.flight)).toEqual(["enqueue"]);   // both routes' package: one machine
    expect(l.messaging.consumers.map((x) => x.flight)).toEqual(["take"]);
    expect(p.routes.filter((r) => r.key.includes(q)).every((r) => r.kind === "drone")).toBe(true);

    const pkg = plan(m, "orders::api/");   // below the service floor the queue is a door, still a hub
    const door = `door:${q}`;
    expect(pkg.tf.boxes.has(door)).toBe(true);
    expect(pkg.landing!.messaging.producers.map((x) => x.item)).toEqual([door]);   // routes.py: one machine
  });

  it("in_process: a trace from a route reaches the worker through the queue, and the call out after it", () => {
    const m = load("in_process");
    const g = new TraceGraph(m);
    const place = "orders::api.routes#place_order/1";
    const down = g.next(place, 1).map((e) => [e.kind, e.to]);
    expect(down).toContainEqual(["hand-off", "inq:orders:outbox"]);
    expect(g.next("inq:orders:outbox", 1).map((e) => e.to)).toEqual(["orders::workers.outbox#drain/0"]);
    expect(g.next("orders::workers.outbox#drain/0", 1).map((e) => e.to)).toEqual(["3p:mailer"]);
  });

  it("push_pull: a receiving dock for the push, a pull, and the puller's `3 replicas` tag", () => {
    const l = plan(load("push_pull"), SITE).landing!;
    expect(l.docks.map((d) => [d.machine, d.flight])).toEqual([["svc:billing", "push"]]);
    const pull = l.messaging.consumers.find((c) => c.subscription === "pull")!;
    expect([pull.machine, pull.flight, pull.replicas]).toEqual(["svc:reports", "pull", 3]);
    expect(pull.tags).toContain("3 replicas");
  });

  it("rail: a yard with its sign, a station, and the rail between them", () => {
    const p = plan(load("rail"), SITE);
    const rails = p.tf.rails!;
    expect(rails.yards).toHaveLength(1);
    expect(rails.yards[0].sign).not.toBeNull();
    expect(rails.stations).toHaveLength(1);
    expect(rails.unplaced).toEqual([]);
    expect(p.routes.filter((r) => r.kind === "rail" && r.pieces.length)).toHaveLength(1);
  });

  it("storage: a read-and-write tap, a read tap, a write tap to a bucket, and the sole cache as a chest (not a lane)", () => {
    const m = load("storage"), p = plan(m, SITE);
    const db = "db:sql:DB_URL", cache = "db:kv:CACHE_URL", bucket = "db:blob:RECEIPTS_BUCKET";
    expect(route(p, "svc:orders", db)?.kind).toBe("tapRW");
    expect(route(p, "svc:reports", db)?.kind).toBe("tapR");
    expect(route(p, "svc:orders", bucket)?.kind).toBe("tapW");
    const art = (id: string) => storeArt(p.tf.boxes.get(id)!, m.nodes.get(id)?.store as Store | undefined);
    expect(p.tf.boxes.get(cache)?.foot).toBe("chest");
    expect(p.tf.lanes.map((l) => l.id)).not.toContain(cache);
    expect(p.tf.notes ?? []).toEqual([]);
    expect(art(bucket)).toBe("yard");
    expect(route(p, "svc:orders", cache)?.kind).toBe("tapRW");
  });

  it("outside: an outside dock, a webhook into a receiving dock, and a utility tab on each of three services", () => {
    const m = load("outside"), p = plan(m, SITE);
    expect(p.tf.boxes.get("ext:http:TAX_API_URL")?.foot).toBe("dock");
    expect(route(p, "svc:orders", "ext:http:TAX_API_URL")?.kind).toBe("belt");
    expect(p.tf.webhooks?.map((d) => d.machine)).toEqual(["svc:billing"]);
    expect(p.tf.webhooks![0].keys).toContain(["3p:payment-provider", "svc:billing"].sort().join("|"));
    expect(m.map.layout.containers[SITE].utilities).toEqual(["3p:mail"]);
    expect([...m.badges(SITE).entries()].sort()).toEqual([["svc:billing", ["3p:mail"]], ["svc:orders", ["3p:mail"]], ["svc:reports", ["3p:mail"]]]);
    expect(p.tf.boxes.has("3p:mail")).toBe(false);
  });

  it("shared: a library reached by uses-code, on the F0 shelf and installed inside orders, and an implements pair", () => {
    const m = load("shared");
    expect(m.map.relations.filter((r) => r.kind === "uses-code").map((r) => [r.from, r.to])).toEqual([["svc:orders", "lib:common"]]);
    expect(plan(m, SITE).tf.boxes.get("lib:common")?.foot).toBe("rack");
    const inside = plan(m, "svc:orders");
    expect(inside.tf.boxes.get("door:lib:common")?.foot).toBe("installed");
    expect(inside.routes.some((r) => r.key.split("|").includes("door:lib:common") && r.pieces.length)).toBe(true);
    const file = plan(m, "orders::store.repo");
    expect(m.implementedBy("orders::store.repo.SqlOrderStore")).toEqual(["orders::store.repo.OrderStore"]);
    expect(file.tf.boxes.has("orders::store.repo.SqlOrderStore") && file.tf.boxes.has("orders::store.repo.OrderStore")).toBe(true);
  });

  it("crossings: one line passes under another, and one line is inferred", () => {
    const p = plan(load("crossings"), SITE);
    expect(pieces(p).some((q) => q.under)).toBe(true);
    const inferred = p.bundles.filter((b) => b.relations.length && b.inferred === b.relations.length);
    expect(inferred.map((b) => b.key)).toEqual([["svc:payments", "svc:reports"].sort().join("|")]);
    expect(route(p, "svc:payments", "svc:reports")?.pieces.length).toBeGreaterThan(0);
  });

  it("layers: one item used by eight, in its own layer of 8 lines", () => {
    const m = load("layers"), p = plan(m, "svc:orders");
    expect(floorLayers(m, "svc:orders").map((l) => [l.item, l.name, l.count, l.usedBy])).toEqual([["orders::audit/", "S1·P1", 8, 8]]);
    expect(p.layers?.["orders::audit/"]?.routes.filter((r) => r.pieces.length)).toHaveLength(8);
    expect(p.routes).toHaveLength(0);   // every line is the heavily used item's: the base is empty
  });

  it("trace: the pin's trace shows orders, billing, the common fold, the invoices table and payments, five boxes", () => {
    const m = load("trace");
    const pin = m.map.pins![0];
    const v = layoutTrace(m, new TraceGraph(m), initialState(pin.start, pin.direction));
    expect(v.boxes.map((b) => m.label(b.owner)).sort()).toEqual(["billing", "common", "orders", "payments", "public.invoices"]);
    expect([...v.rows.values()].find((r) => r.kind === "library")!.label).toBe("common · 2 calls");
    for (const c of Object.keys(m.map.layout.containers)) plan(m, c);
  });

  it("codes: service, package, file, class and method codes, five levels deep", () => {
    const m = load("codes");
    const codes = [...m.codes.values()];
    for (const re of [/^S\d+$/, /^S\d+·P\d+$/, /^S\d+·P\d+·F\d+$/, /^S\d+·P\d+·F\d+·C\d+$/, /^S\d+·P\d+·F\d+·C\d+·M\d+$/])
      expect(codes.some((c) => re.test(c)), String(re)).toBe(true);
    expect(m.codes.get("orders::core.service.OrderService#create/1")).toMatch(/^S1·P\d·F\d·C1·M\d$/);
    plan(m, "orders::core.service");
  });

  it("floors: two services on F0, and inside orders a few packages with the out door to billing", () => {
    const m = load("floors");
    expect(plan(m, SITE).tf.boxes.size).toBe(2);
    const p = plan(m, "svc:orders");
    expect([...p.tf.boxes.values()].filter((b) => b.kind === "package").length).toBeGreaterThanOrEqual(3);
    const out = p.routes.find((r) => r.key.split("|").includes("door:svc:billing"))!;
    expect(flowOf(p.tf, out)).toEqual({ src: "orders::clients/", dst: "door:svc:billing" });
    expect(m.bundles("svc:orders").doors.find((d) => d.anchor === "svc:billing")?.side).toBe("out");
  });
});
