import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import shop from "../fixtures/shop.code-map.json";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { layoutTiles } from "../../src/factory/layout";
import { doorLead, doorLegend, messaging, type Messaging } from "../../src/factory/messaging";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const demoMap = (): CodeMap => JSON.parse(readFileSync(DEMO, "utf8"));

const RES = "topic:kafka:reservation-events", RES_DLQ = "topic:kafka:reservation-events.dlq";
const VIO = "topic:sqs:violations.fifo", VIO_DEAD = "topic:sqs:violations-dead.fifo";
const BAY = "topic:pubsub:bay-status";

function on(model: Model, container: string): Messaging {
  const { bundles, doors } = model.bundles(container);
  return messaging(model, container, layoutTiles(model, container, doors), bundles);
}
const hub = (m: Messaging, topic: string) => m.airfields.flatMap((a) => a.hubs).find((h) => h.topic === topic);

describe("what a door leads to", () => {
  const demo = new Model(demoMap());
  it("a dead-letter hub, another topic, an outside service; nothing for a part of the repo", () => {
    expect(doorLead(demo, RES_DLQ)).toBe("dead");
    expect(doorLead(demo, RES)).toBe("hub");
    expect(doorLead(demo, "3p:stripe")).toBe("outside");
    for (const plain of ["svc:nightly-jobs", "lib:common", "db:postgres:DB_HOST"]) expect(doorLead(demo, plain), plain).toBeUndefined();
  });
  it("the legend lists only the kinds a floor's doors lead to", () => {
    const anchors = (c: string) => demo.bundles(c).doors.map((d) => d.anchor);
    expect(doorLegend(demo, anchors("billing::city.parking.billing/"))).toEqual({ outside: true, hub: true, dead: true });
    expect(doorLegend(demo, anchors("billing::city.parking.billing.StripeCharger.live$impl"))).toEqual({ outside: true });
    expect(doorLegend(demo, ["svc:nightly-jobs", "lib:common"])).toBeNull();
  });
});

describe("messaging model", () => {
  const demo = new Model(demoMap());
  const site = on(demo, SITE);

  it("groups hubs into one airfield per broker, named like the layout's zones", () => {
    expect(site.airfields.map((a) => a.broker)).toEqual(["kafka", "pubsub", "sqs"]);
    const zones = layoutTiles(demo, SITE).zones.filter((z) => z.airfield).map((z) => z.name).sort();
    expect(site.airfields.map((a) => a.broker)).toEqual(zones);
    expect(site.airfields.find((a) => a.broker === "kafka")!.hubs.map((h) => h.topic)).toEqual([RES, RES_DLQ]);
  });

  it("kafka reservation-events is a fan-out with two consumer groups, notifier, 2 replicas", () => {
    expect(hub(site, RES)).toEqual({ item: RES, topic: RES, broker: "kafka", delivery: "fan-out", dlqOf: null, waiting: false });
    const cs = site.consumers.filter((c) => c.topic === RES);
    expect(cs.map((c) => [c.machine, c.group, c.flight])).toEqual([["svc:billing", "billing", "copy"], ["svc:notifier", "notifier", "copy"]]);
    const notifier = cs.find((c) => c.group === "notifier")!;
    expect(notifier.replicas).toBe(2);
    expect(notifier.tags).toEqual(["group notifier", "2 replicas"]);
    expect(cs.find((c) => c.group === "billing")!.tags).toEqual(["group billing"]);
    const prod = site.producers.filter((p) => p.topic === RES);
    expect(prod.map((p) => [p.machine, p.flight])).toEqual([["svc:reservations", "produce"]]);
    expect(prod[0].viaRelations.length).toBeGreaterThan(0);
  });

  it("reservation-events.dlq is its dead-letter hub, and billing's on_failure goes there", () => {
    expect(hub(site, RES_DLQ)).toMatchObject({ dlqOf: RES, delivery: "fan-out", waiting: false });
    expect(site.failures).toContainEqual(expect.objectContaining({ machine: "svc:billing", dlq: RES_DLQ, item: RES_DLQ, flight: "failure" }));
    expect(site.consumers.find((c) => c.group === "billing")!.onFailureTo).toBe(RES_DLQ);
    expect(site.consumers.find((c) => c.group === "notifier")!.onFailureTo).toBeUndefined();
    expect(site.producers.some((p) => p.topic === RES_DLQ)).toBe(false);   // a failure is not a produce
  });

  it("sqs violations is a queue taken by enforcement-worker, 3 replicas; its dead hub is a queue too", () => {
    expect(hub(site, VIO)).toMatchObject({ delivery: "queue", waiting: true, dlqOf: null, broker: "sqs" });
    expect(hub(site, VIO_DEAD)).toMatchObject({ delivery: "queue", waiting: true, dlqOf: VIO });
    const cs = site.consumers.filter((c) => c.topic === VIO);
    expect(cs).toHaveLength(1);
    expect(cs[0]).toMatchObject({ machine: "svc:enforcement-worker", replicas: 3, flight: "take", tags: ["3 replicas"] });
    expect(cs[0].group).toBeUndefined();
    expect(site.producers.filter((p) => p.topic === VIO).map((p) => p.flight)).toEqual(["enqueue"]);
  });

  it("pubsub bay-status has one push consumer and one pull consumer", () => {
    const cs = site.consumers.filter((c) => c.topic === BAY);
    expect(cs.map((c) => [c.machine, c.subscription, c.flight, c.group])).toEqual([
      ["svc:analytics-loader", "pull", "pull", "bay-status-analytics"],
      ["svc:city-dashboard", "push", "push", "bay-status-dashboard"],
    ]);
  });

  it("on an inner floor, a door to a topic counts as that hub", () => {
    const billing = on(demo, "svc:billing");
    expect(hub(billing, RES)).toMatchObject({ item: `door:${RES}`, broker: "kafka", delivery: "fan-out" });
    expect(hub(billing, RES_DLQ)).toMatchObject({ item: `door:${RES_DLQ}`, dlqOf: RES });
    const c = billing.consumers.find((x) => x.topic === RES)!;
    expect(c).toMatchObject({ item: `door:${RES}`, group: "billing", flight: "copy", onFailureTo: RES_DLQ });
    expect(demo.kindOf(c.machine)).not.toBe("topic");
    expect(billing.failures.map((f) => f.dlq)).toEqual([RES_DLQ]);
    const notifier = on(demo, "svc:notifier").consumers;
    expect(notifier.map((x) => [x.topic, x.replicas])).toEqual([[RES, 2]]);
  });

  it("is deterministic", () => {
    expect(on(demo, SITE)).toEqual(site);
    expect(JSON.stringify(on(demo, "svc:billing"))).toBe(JSON.stringify(on(demo, "svc:billing")));
  });

  it("the fixture: orders is a fan-out and orders.dlq its dead-letter hub", () => {
    const m = on(new Model(shop as unknown as CodeMap), SITE);
    expect(hub(m, "topic:kafka:orders")).toMatchObject({ delivery: "fan-out", dlqOf: null, waiting: false });
    expect(hub(m, "topic:kafka:orders.dlq")).toMatchObject({ delivery: "fan-out", dlqOf: "topic:kafka:orders" });
    expect(m.consumers.map((c) => [c.machine, c.group, c.flight, c.onFailureTo, c.tags])).toEqual([
      ["svc:worker", "worker", "copy", "topic:kafka:orders.dlq", ["group worker", "2 replicas"]],
    ]);
  });

  it("a map without the facts is a plain fan-out", () => {
    const raw = demoMap();
    for (const n of raw.nodes) { delete n.delivery; delete n.dead_letter_of; delete n.replicas; }
    for (const r of raw.relations) { delete r.group; delete r.subscription; delete r.on_failure; }
    const m = on(new Model(raw), SITE);
    const hubs = m.airfields.flatMap((a) => a.hubs);
    expect(hubs.length).toBe(5);
    for (const h of hubs) expect(h).toMatchObject({ delivery: "fan-out", dlqOf: null, waiting: false });
    expect(m.failures).toEqual([]);
    expect(new Set(m.producers.map((p) => p.flight))).toEqual(new Set(["produce"]));
    expect(new Set(m.consumers.map((c) => c.flight))).toEqual(new Set(["copy"]));
    for (const c of m.consumers) expect(c).toMatchObject({ tags: [] });
    expect(m.consumers.every((c) => c.group === undefined && c.replicas === undefined && c.subscription === undefined)).toBe(true);
    // one consumer per machine and topic once groups are gone; billing now produces to the dlq
    expect(m.producers.some((p) => p.machine === "svc:billing" && p.topic === RES_DLQ)).toBe(true);
  });
});
