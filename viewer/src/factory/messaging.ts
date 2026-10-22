// src/factory/messaging.ts
// The messaging picture of one floor, pure: airfields of hubs per broker, and who produces to, consumes
// from or fails into each hub, with the flight each one flies. Layout, painting and motion read this; nothing here
// draws. Facts come from the map: delivery and dead_letter_of on the topic, group / subscription / on_failure on the
// event relation, replicas on the consuming service. Absent facts read as a plain fan-out.
import type { Bundle, Model } from "../model/model";
import { doorAnchor, flies, SITE } from "../model/model";
import type { Relation } from "../model/types";
import type { TileFloor } from "./layout";

export type Delivery = "fan-out" | "queue";
/** What a drone does on its path. produce / enqueue: machine → hub; copy / take / push / pull: hub → consumer
 *  (pull flies out empty and back loaded); failure: machine → dead-letter hub. */
export type Flight = "produce" | "enqueue" | "copy" | "take" | "push" | "pull" | "failure";
/** The short label each flight's plate shows (owner decision: short words). */
export const FLIGHT_LABEL: Record<Flight, string> = {
  produce: "produce", enqueue: "enqueue", copy: "copy", take: "take", push: "push", pull: "pull", failure: "on failure",
};

export interface Hub {
  item: string;            // the box on this floor: the topic itself on the site, "door:<topic>" inside a building
  topic: string;           // the topic node id
  broker: string;          // "<broker>" from "topic:<broker>:<name>": the airfield (and its zone's name)
  delivery: Delivery;
  dlqOf: string | null;    // the topic whose failures land here, when that topic is in the map
  waiting: boolean;        // a queue keeps a visible waiting stack
}
export interface Airfield { broker: string; hubs: Hub[] }

export interface Producer {
  machine: string;         // item on this floor
  item: string;            // the hub's box
  topic: string;
  flight: "produce" | "enqueue";
  viaRelations: string[];  // relation ids, sorted
}
export interface Consumer {
  machine: string;
  item: string;
  topic: string;
  group?: string;
  replicas?: number;
  subscription?: "push" | "pull";
  /** The dead-letter topic this machine's failures go to, when one of them is this topic's dead-letter hub. */
  onFailureTo?: string;
  flight: "copy" | "take" | "push" | "pull";
  /** "group <name>" and "<n> replicas" (above 1 only: copies of the service, taking turns on a queue), in that order. */
  tags: string[];
  viaRelations: string[];
}
export interface Failure {
  machine: string;
  item: string;            // the dead-letter hub's box
  dlq: string;             // its topic id
  flight: "failure";
  viaRelations: string[];
}
export interface Messaging { airfields: Airfield[]; producers: Producer[]; consumers: Consumer[]; failures: Failure[] }

/** The airfield an in-process queue's hub stands on, inside its service's floor. */
export const IN_PROCESS = "in-process";
/** "kafka" from "topic:kafka:orders": the same split the layout's airfields use; an in-process queue's is IN_PROCESS. */
export const brokerOf = (topic: string): string => (topic.startsWith("inq:") ? IN_PROCESS : topic.split(":")[1] ?? "");

const byStr = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

/** The topic whose failures land on topic `id` (it is a dead-letter hub), when that topic is in the map; else null. */
export function deadLetterOf(model: Model, id: string): string | null {
  const src = model.nodes.get(id)?.dead_letter_of;
  return src && model.nodes.get(src)?.kind === "topic" ? src : null;
}

/** What a door leads to, for its marks (a top band and a corner square): a dead-letter hub (red), another topic or
 *  in-process queue (green), an outside service (yellow, as its dock on floor 0). A door to a part of the repo has none. */
export type DoorLead = "dead" | "hub" | "outside";
export function doorLead(model: Model, anchor: string): DoorLead | undefined {
  const kind = model.nodes.get(anchor)?.kind;
  if (kind === "topic" || kind === "in-process-queue") return deadLetterOf(model, anchor) ? "dead" : "hub";
  return kind === "external" ? "outside" : undefined;
}

/** Which door marks a floor has, for the legend's door entry: each only when a door there leads to one; null when none. */
export type DoorLegend = Partial<Record<DoorLead, true>>;
export function doorLegend(model: Model, anchors: Iterable<string>): DoorLegend | null {
  const out: DoorLegend = {};
  for (const a of anchors) { const lead = doorLead(model, a); if (lead) out[lead] = true; }
  return Object.keys(out).length ? out : null;
}

export function messaging(model: Model, container: string, tf: TileFloor, bundles: Bundle[]): Messaging {
  const onSite = container === SITE;
  // hubs: topic boxes on the site, doors to topics inside buildings, in-process queues on their service's floor (and
  // doors to them below it)
  const hubs = new Map<string, Hub>();
  for (const box of [...tf.boxes.values()].sort((p, q) => byStr(p.id, q.id))) {
    const topic = doorAnchor(box.id);
    const node = model.nodes.get(topic);
    if (node?.kind !== "topic" && node?.kind !== "in-process-queue") continue;
    const delivery: Delivery = node.delivery === "queue" ? "queue" : "fan-out";
    hubs.set(box.id, {
      item: box.id, topic, broker: brokerOf(topic), delivery,
      dlqOf: deadLetterOf(model, topic), waiting: delivery === "queue",
    });
  }
  const lift = (id: string) => model.liftTo(container, id) ?? (onSite ? undefined : model.doorId(model.anchorFor(container, id)));

  const produced = new Map<string, { machine: string; hub: Hub; rels: Relation[] }>();
  const consumed = new Map<string, { machine: string; hub: Hub; group?: string; rels: Relation[] }>();
  const failed = new Map<string, { machine: string; hub: Hub; rels: Relation[] }>();
  for (const b of bundles) {
    const hubEnd = hubs.get(b.a) ? b.a : hubs.get(b.b) ? b.b : null;
    if (!hubEnd) continue;
    const machine = hubEnd === b.a ? b.b : b.a;
    if (hubs.has(machine)) continue;   // hub to hub: no machine to fly from
    const hub = hubs.get(hubEnd)!;
    for (const r of b.relations) {
      if (!flies(r.kind)) continue;
      if (lift(r.to) === hubEnd) {
        const into = r.on_failure ? failed : produced;
        const k = `${machine}|${hubEnd}`;
        const e = into.get(k) ?? { machine, hub, rels: [] };
        e.rels.push(r);
        into.set(k, e);
      } else if (lift(r.from) === hubEnd) {
        const k = `${machine}|${hubEnd}|${r.group ?? ""}`;
        const e = consumed.get(k) ?? { machine, hub, group: r.group, rels: [] };
        e.rels.push(r);
        consumed.set(k, e);
      }
    }
  }

  const ids = (rels: Relation[]) => rels.map((r) => r.id).sort(byStr);
  const failures: Failure[] = [...failed.values()]
    .map(({ machine, hub, rels }) => ({ machine, item: hub.item, dlq: hub.topic, flight: "failure" as const, viaRelations: ids(rels) }))
    .sort((p, q) => byStr(p.machine, q.machine) || byStr(p.dlq, q.dlq));
  const producers: Producer[] = [...produced.values()]
    .map(({ machine, hub, rels }) => ({
      machine, item: hub.item, topic: hub.topic, flight: hub.delivery === "queue" ? "enqueue" as const : "produce" as const, viaRelations: ids(rels),
    }))
    .sort((p, q) => byStr(p.machine, q.machine) || byStr(p.topic, q.topic));

  const consumers: Consumer[] = [...consumed.values()].map(({ machine, hub, group, rels }) => {
    rels.sort((p, q) => byStr(p.id, q.id));
    const subscription = rels.find((r) => r.subscription)?.subscription;
    const reps = rels.map((r) => replicasOf(model, r.to)).filter((n): n is number => n !== undefined);
    const replicas = reps.length ? Math.max(...reps) : undefined;
    const dlqs = new Set([...hubs.values()].filter((h) => h.dlqOf === hub.topic).map((h) => h.topic));
    const onFailureTo = failures.find((f) => f.machine === machine && dlqs.has(f.dlq))?.dlq;
    const flight = subscription ?? (hub.delivery === "queue" ? "take" : "copy");
    const tags = [...(group ? [`group ${group}`] : []), ...(replicas && replicas > 1 ? [`${replicas} replicas`] : [])];
    const c: Consumer = { machine, item: hub.item, topic: hub.topic, flight, tags, viaRelations: ids(rels) };
    if (group !== undefined) c.group = group;
    if (replicas !== undefined) c.replicas = replicas;
    if (subscription) c.subscription = subscription;
    if (onFailureTo) c.onFailureTo = onFailureTo;
    return c;
  }).sort((p, q) => byStr(p.machine, q.machine) || byStr(p.topic, q.topic) || byStr(p.group ?? "", q.group ?? ""));

  const fields = new Map<string, Hub[]>();
  for (const h of hubs.values()) fields.set(h.broker, [...(fields.get(h.broker) ?? []), h]);
  const airfields = [...fields.entries()].sort(([p], [q]) => byStr(p, q))
    .map(([broker, list]) => ({ broker, hubs: list.sort((p, q) => byStr(p.topic, q.topic)) }));
  return { airfields, producers, consumers, failures };
}

/** Replicas of the service that runs `id`: the nearest service up its parents. */
function replicasOf(model: Model, id: string): number | undefined {
  let cur: string | undefined = id;
  const seen = new Set<string>();
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    const n = model.nodes.get(cur);
    if (!n) return undefined;
    if (n.kind === "service") return n.replicas;
    cur = n.parent ?? undefined;
  }
  return undefined;
}
