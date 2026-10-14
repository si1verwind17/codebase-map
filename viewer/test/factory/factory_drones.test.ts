import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor } from "../../src/factory/plan";
import { flightPaths, type FlightPath } from "../../src/factory/flights";
import { droneSchedule, FAIL_EVERY, PULSE, type DroneFloor, type Trip } from "../../src/factory/drones";
import type { Messaging } from "../../src/factory/messaging";
import type { Flight } from "../../src/factory/messaging";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);

/** A flight 300 px long (a drone takes 3 s at most: here 300 / max(60, 100) = 3 s), or `len` px. */
function fl(flight: Flight, machine: string, item: string, opts: { group?: string; len?: number; topic?: string } = {}): FlightPath {
  const len = opts.len ?? 300;
  const launch = { x: 0, y: 0 }, hub = { x: len, y: 0 };
  const out = flight === "produce" || flight === "enqueue" || flight === "failure" || flight === "pull";
  return {
    key: [machine, item].sort().join("|"), flight, role: flight === "produce" || flight === "enqueue" ? "produce" : flight === "failure" ? "failure" : "consume",
    machine, item, topic: opts.topic ?? item, ...(opts.group !== undefined ? { group: opts.group } : {}), dock: flight === "push", dead: flight === "failure",
    launch, hub, outbound: out, points: out ? [launch, hub] : [hub, launch], relations: [`r:${machine}:${item}:${flight}`],
  };
}

/** Fan-out hub `orders` (producer `shop`; groups `billing` and `mail`; `stats` pulls; `dash` takes a push), queue `jobs`
 *  (`api` enqueues; `worker` ×3 takes; `worker` fails into `jobs.dlq`, which `ops` reads). */
function world(): DroneFloor {
  const flights = [
    fl("produce", "shop", "orders"),
    fl("copy", "billing", "orders", { group: "billing" }),
    fl("copy", "mail", "orders", { group: "mail", len: 120 }),
    fl("pull", "stats", "orders", { len: 90 }),
    fl("push", "dash", "orders"),
    fl("enqueue", "api", "jobs", { len: 150 }),
    fl("take", "worker", "jobs"),
    fl("failure", "worker", "jobs.dlq"),
    fl("copy", "ops", "jobs.dlq"),
  ];
  const messaging: Messaging = {
    airfields: [{ broker: "b", hubs: [
      { item: "orders", topic: "orders", broker: "b", delivery: "fan-out", dlqOf: null, waiting: false },
      { item: "jobs", topic: "jobs", broker: "b", delivery: "queue", dlqOf: null, waiting: true },
      { item: "jobs.dlq", topic: "jobs.dlq", broker: "b", delivery: "fan-out", dlqOf: "jobs", waiting: false },
    ] }],
    producers: [],
    consumers: [
      { machine: "worker", item: "jobs", topic: "jobs", replicas: 3, flight: "take", tags: ["3 replicas"], viaRelations: [] },
    ],
    failures: [],
  };
  return { flights, messaging, stacks: [{ item: "jobs", topic: "jobs", x: 20, y: 0 }] };
}
const all = (f: DroneFloor) => new Set(f.flights.map((x) => x.key));
const of = (f: DroneFloor, trips: Trip[], flight: Flight) => trips.filter((t) => f.flights[t.flight].flight === flight);
const end = (t: Trip) => t.start + t.dur;

describe("drone schedule", () => {
  it("a produce lands, then one copy leaves the hub for every lit consumer group", () => {
    const f = world();
    const s = droneSchedule(f, all(f));
    const trips = s.cycle(0);
    const produce = of(f, trips, "produce");
    expect(produce).toHaveLength(1);
    expect(produce[0]).toMatchObject({ start: 0, dur: 3, loaded: true, red: false });
    expect(produce[0].points).toEqual(f.flights[0].points);
    const copies = trips.filter((t) => f.flights[t.flight].item === "orders" && f.flights[t.flight].flight === "copy");
    expect(copies).toHaveLength(2);   // copies equal the group count
    for (const c of copies) { expect(c.start).toBe(end(produce[0])); expect(c.loaded).toBe(true); }
    expect(copies.map((c) => c.dur).sort()).toEqual([2, 3]);   // 120 px at 60 px/s; 300 px in 3 s
    const push = of(f, trips, "push");
    expect(push).toHaveLength(1);
    expect(push[0].start).toBe(3);
    expect(push[0].points.at(-1)).toEqual(f.flights[4].launch);   // delivered to the dock
  });

  it("copies go only to groups whose flight is lit", () => {
    const f = world();
    const lit = new Set([f.flights[0].key, f.flights[2].key]);   // shop's produce and mail's copy
    const trips = droneSchedule(f, lit).cycle(0);
    expect(trips.map((t) => f.flights[t.flight].machine).sort()).toEqual(["mail", "shop"]);
    expect(droneSchedule(f, new Set()).cycle(0)).toEqual([]);
    expect(droneSchedule(f, new Set()).period).toBe(0);
  });

  it("a queue's take turns round-robin across the worker's replicas, a crate from the waiting stack", () => {
    const f = world();
    const s = droneSchedule(f, all(f));
    const takes = [0, 1, 2, 3, 4].map((n) => of(f, s.cycle(n), "take"));
    for (const t of takes) expect(t).toHaveLength(1);   // one crate, one worker at a time
    expect(takes.map((t) => t[0].receiver)).toEqual([0, 1, 2, 0, 1].map((replica) => ({ machine: "worker", replica, of: 3 })));
    const enq = of(f, s.cycle(0), "enqueue")[0];
    expect(takes[0][0].start).toBe(end(enq));
    expect(takes[0][0].points[0]).toEqual({ x: 20 * 24 + 12, y: 12 });   // leaves the waiting stack
    expect(takes[0][0].points.slice(1)).toEqual(f.flights[6].points);
  });

  it("two take flights on one queue share the turns: one crate per cycle, each worker in turn", () => {
    const f = world();
    f.flights.push(fl("take", "auditor", "jobs", { group: "audit" }));
    const s = droneSchedule(f, all(f));
    const got = [0, 1, 2, 3, 4].map((n) => of(f, s.cycle(n), "take").map((t) => `${t.receiver!.machine}#${t.receiver!.replica}`));
    expect(got).toEqual([["worker#0"], ["worker#1"], ["worker#2"], ["auditor#0"], ["worker#0"]]);
  });

  it("a pull flies out empty and comes back loaded once the message is in", () => {
    const f = world();
    const trips = of(f, droneSchedule(f, all(f)).cycle(0), "pull");
    expect(trips).toHaveLength(2);
    const [out, back] = trips;
    expect(out.loaded).toBe(false);
    expect(out.points).toEqual(f.flights[3].points);          // pad → hub
    expect(back.loaded).toBe(true);
    expect(back.points).toEqual([...f.flights[3].points].reverse());   // hub → pad
    expect(out.dur).toBe(1.5);                                // 90 px at 60 px/s
    expect(end(out)).toBe(3);                                 // reaches the hub as the produce lands
    expect(back.start).toBe(3);
  });

  it("a failure is a red drone from the worker's failure pad to the dead-letter hub, after its crate arrives, every few cycles", () => {
    const f = world();
    const s = droneSchedule(f, all(f));
    for (let n = 0; n < 2 * FAIL_EVERY; n++) {
      const trips = s.cycle(n);
      const fail = of(f, trips, "failure");
      const dlqCopy = trips.filter((t) => f.flights[t.flight].item === "jobs.dlq" && f.flights[t.flight].flight === "copy");
      if (n % FAIL_EVERY !== FAIL_EVERY - 1) { expect(fail, `cycle ${n}`).toEqual([]); expect(dlqCopy).toEqual([]); continue; }
      expect(fail).toHaveLength(1);
      expect(fail[0]).toMatchObject({ red: true, loaded: true });
      expect(fail[0].points).toEqual(f.flights[7].points);   // pad → dead-letter hub
      expect(fail[0].start).toBe(end(of(f, trips, "take")[0]));
      expect(dlqCopy).toHaveLength(1);                         // the dead-letter hub hands it on
      expect(dlqCopy[0].start).toBe(end(fail[0]));
    }
  });

  it("on a queue shared by several takers, each machine's failures fly on its own every FAIL_EVERY-th crate", () => {
    const f = world();
    f.messaging.consumers[0].replicas = 2;                                  // worker ×2
    f.flights.push(fl("take", "auditor", "jobs", { group: "audit" }));      // auditor ×1: slots w0, w1, a0
    f.flights.push(fl("failure", "auditor", "jobs.dlq"));
    const s = droneSchedule(f, all(f));
    const fails: Record<string, number[]> = { worker: [], auditor: [] };
    for (let n = 0; n < 12; n++) for (const t of of(f, s.cycle(n), "failure")) fails[f.flights[t.flight].machine].push(n);
    // worker receives in cycles 0, 1, 3, 4, 6, 7, 9, 10: its 3rd and 6th crates are cycles 3 and 7;
    // auditor receives in 2, 5, 8, 11: its 3rd is cycle 8
    expect(fails).toEqual({ worker: [3, 7], auditor: [8] });
    for (const n of [3, 7, 8]) {
      const fail = of(f, s.cycle(n), "failure")[0];
      expect(fail.start).toBe(end(of(f, s.cycle(n), "take")[0]));            // after its own crate lands
    }
  });

  it("a dead-letter hub with no lit inbound hands on only every FAIL_EVERY-th cycle", () => {
    const f = world();
    const lit = new Set([f.flights[8].key]);                                  // ops' copy from jobs.dlq alone
    const s = droneSchedule(f, lit);
    const flies = [0, 1, 2, 3, 4, 5].map((n) => s.cycle(n).length);
    expect(flies).toEqual([0, 0, 1, 0, 0, 1]);
    expect(s.cycle(2)[0].start).toBe(0);
    const plain = droneSchedule(f, new Set([f.flights[2].key]));             // a plain hub with no lit inbound: every cycle
    expect([0, 1, 2].map((n) => plain.cycle(n).length)).toEqual([1, 1, 1]);
  });

  it("at() can fill a caller's scratch result, reusing its objects", () => {
    const f = world();
    const s = droneSchedule(f, all(f));
    const out = { drones: [], pulses: [] } as ReturnType<typeof s.at>;
    const first = s.at(1.5, out);
    expect(first).toBe(out);
    const d0 = out.drones[0];
    s.at(1.6, out);
    expect(out.drones[0]).toBe(d0);                                          // the same object, moved
    expect(out.drones).toEqual(s.at(1.6).drones);
    s.at(s.period - 0.01, out);                                               // the pause: nothing in flight
    expect(out.drones).toEqual([]);
  });

  it("the period holds the longest cycle and a pause; positions and pulses come from the time alone", () => {
    const f = world();
    const s = droneSchedule(f, all(f));
    // enqueue 2.5 s, take 3 s (+ stack hop), failure 3 s, copy 3 s, then the pause
    const longest = Math.max(...[0, 1, 2].flatMap((n) => s.cycle(n).map(end)));
    expect(s.period).toBeGreaterThanOrEqual(longest + PULSE);
    const a = s.at(1.5), b = s.at(1.5);
    expect(a).toEqual(b);
    const produce = a.drones.find((d) => f.flights[d.flight].flight === "produce")!;
    expect(produce).toMatchObject({ x: 150, y: 0, loaded: true, red: false });
    expect(s.at(1.5 + s.period).drones.length).toBe(a.drones.length);
    // the take's receiver pulses just after its crate lands, with which replica it was
    const take = of(f, s.cycle(1), "take")[0];
    const p = s.at(s.period + end(take) + 0.1).pulses;
    expect(p).toEqual([{ flight: 6, machine: "worker", replica: 1, of: 3, age: expect.closeTo(0.1 / PULSE, 5) }]);
    expect(s.at(s.period + end(take) + PULSE + 0.01).pulses).toEqual([]);
  });

  it("demo site: a schedule for every hub floor, no randomness, every lit flight flown within a few cycles", () => {
    const model = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    const { bundles, doors } = model.bundles(SITE);
    const tf = planFloor(model, SITE, doors, bundles).tf;
    const flights = flightPaths(tf);
    const floor: DroneFloor = { flights, messaging: tf.landing!.messaging, stacks: tf.landing!.stacks };
    const s = droneSchedule(floor, new Set(flights.map((x) => x.key)));
    const flown = new Set<number>();
    for (let n = 0; n < 12; n++) for (const t of s.cycle(n)) { flown.add(t.flight); expect(end(t)).toBeLessThanOrEqual(s.period - PULSE + 1e-9); }
    expect([...flown].sort((a, b) => a - b)).toEqual(flights.map((_, i) => i));
    expect(JSON.stringify(droneSchedule(floor, new Set(flights.map((x) => x.key))).at(7.3))).toBe(JSON.stringify(s.at(7.3)));
    expect(s.cycle(0).filter((t) => t.red).length).toBe(0);
    expect(s.cycle(FAIL_EVERY - 1).some((t) => t.red)).toBe(true);
  });
});

describe("drones to a door", () => {
  it("demo inner floors: every drone to or from a door hub starts or lands where its path meets the door's edge", () => {
    const model = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    let checked = 0;
    for (const c of Object.keys(model.map.layout.containers)) {
      if (c === SITE) continue;
      const { bundles, doors } = model.bundles(c);
      const tf = planFloor(model, c, doors, bundles).tf;
      if (!tf.landing) continue;
      const flights = flightPaths(tf);
      const floor: DroneFloor = { flights, messaging: tf.landing.messaging, stacks: tf.landing.stacks };
      const trips = droneSchedule(floor, new Set(flights.map((f) => f.key))).cycle(0);
      for (const t of trips) {
        const f = flights[t.flight];
        if (tf.boxes.get(f.item)?.foot !== "door") continue;
        checked++;
        // a take leaves its queue's waiting stack first, then flies on from the door's edge
        const stack = f.flight === "take" ? tf.landing.stacks.find((s) => s.item === f.item) : undefined;
        if (stack) expect(t.points[0], `${c} ${f.key} leaves the stack`).toEqual({ x: stack.x * 24 + 12, y: stack.y * 24 + 12 });
        const ends = [t.points[stack ? 1 : 0], t.points[t.points.length - 1]];
        expect(ends, `${c} ${f.flight} ${f.key}`).toContainEqual(f.hub);   // the door end of the trip is the edge point
        expect(ends, `${c} ${f.flight} ${f.key}`).toContainEqual(f.launch);
      }
    }
    expect(checked).toBeGreaterThan(0);
  });
});

describe("items on lit lines (the owner, 2026-10-06: every line moves while nothing is selected)", () => {
  it("factory: one item on a belt or rail, about three evenly spaced blobs in a pipe", async () => {
    const { itemSpacing, PIPE_BLOBS } = await import("../../src/floor/movers");
    expect(PIPE_BLOBS).toBe(3);
    for (const total of [48, 300, 1200]) {
      // items sit `spacing` apart over a cycle of the line plus a pause: how many fit on the line at once
      const on = (kind: string) => Math.ceil(total / itemSpacing(kind, total));
      expect(on("request"), `belt ${total}`).toBe(1);
      expect(on("batch"), `rail ${total}`).toBe(1);
      expect(on("stream"), `pipe ${total}`).toBeLessThanOrEqual(3);
      expect(on("stream"), `pipe ${total}`).toBeGreaterThanOrEqual(2);
      expect(itemSpacing("stream", total) * PIPE_BLOBS).toBeCloseTo(itemSpacing("request", total), 6);   // evenly spaced
    }
  });
});
