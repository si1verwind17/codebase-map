import { describe, expect, it } from "vitest";
import { Model } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { EXAMPLE_LABEL, examplesFor, pretty } from "../../src/trace/examples";
import { entryPoints, methodsIn, traceable } from "../../src/trace/entries";
import { MapBuilder } from "./trace_fixture";
import { readFileSync } from "node:fs";
import shop from "../fixtures/shop.code-map.json";

function billing() {
  const b = new MapBuilder();
  const s = b.owner("billing");
  const charge = b.cls(s, "Charge", [{ name: "id", type: "str" }, { name: "amount", type: "int" }]);
  const receipt = b.cls(s, "Receipt", [{ name: "id", type: "str" }]);
  const plain = b.cls(s, "Plain");
  const h = b.method(s, "Api", "create", [{ name: "c", type: "Charge", refs: [charge] }], "Receipt", [receipt]);
  const inner = b.method(s, "Svc", "settle", [{ name: "c", type: "Charge", refs: [charge, plain] }], "Receipt", [receipt]);
  b.extra = { examples: {
    types: { [charge]: { value: { id: "ch-1", amount: 2400 }, fingerprint: "x" } },
    entries: [{ node: h, key: "POST /v1/charges", request: { id: "ch-1" }, response: { id: "rc-9" }, fingerprint: "y" },
              { node: h, key: "POST /v2/charges", request: { id: "ch-2" }, fingerprint: "z" }],
  } };
  return { b, h, inner, charge, receipt };
}

describe("examples for the detail panel", () => {
  it("are labelled as examples", () => expect(EXAMPLE_LABEL).toBe("example values, not computed"));

  it("an entry point shows its own example; an arrow's key picks that one", () => {
    const { b, h } = billing();
    const m = b.model();
    expect(examplesFor(m, h).map((x) => x.title)).toEqual(["POST /v1/charges", "POST /v2/charges"]);
    expect(examplesFor(m, h, "POST /v2/charges")).toEqual([{ kind: "entry", title: "POST /v2/charges", request: { id: "ch-2" } }]);
  });

  it("any other method shows its types' examples, a type without one its fields, a class without fields nothing", () => {
    const { b, inner, charge, receipt } = billing();
    expect(examplesFor(b.model(), inner)).toEqual([
      { kind: "type", title: "Charge", cls: charge, value: { id: "ch-1", amount: 2400 } },
      { kind: "fields", title: "Receipt", cls: receipt, fields: [{ name: "id", type: "str" }] },
    ]);
  });

  it("a map without examples, fields or refs (an older map) shows nothing and does not throw", () => {
    const old = structuredClone(shop) as unknown as Record<string, unknown>;   // the fixture now carries schema 3 facts: strip them
    delete old.examples; delete old.files; delete old.pins;
    for (const n of old.nodes as { fields?: unknown; signature?: { returns_refs?: unknown; params: { refs?: unknown }[] } }[]) {
      delete n.fields;
      if (n.signature) { delete n.signature.returns_refs; for (const p of n.signature.params) delete p.refs; }
    }
    const m = new Model(old as unknown as CodeMap);
    expect(examplesFor(m, "worker::worker.main#run/2")).toEqual([]);
    expect(entryPoints(m, "svc:worker")).toEqual([{ node: "worker::worker.main#run/2", keys: ["orders"] }]);
  });

  it("pretty prints a value in full, a JSON string too", () => {
    expect(pretty({ a: 1 })).toBe('{\n  "a": 1\n}');
    expect(pretty('{"a":1}')).toBe('{\n  "a": 1\n}');
    expect(pretty("plain")).toBe("plain");
    expect(pretty(undefined)).toBe("—");
  });
});

describe("where a trace starts", () => {
  const m = new Model(shop as unknown as CodeMap);

  it("every map node can be traced (spec A2); an id not in the map cannot", () => {
    const ids = ["worker::worker.main#run/2", "db:postgres:DB_HOST/public.orders", "topic:kafka:orders", "3p:feed", "db:redis:REDIS_URL",
      "svc:worker", "worker::worker/", "worker::worker.main", "worker::worker.main.Job"];
    expect(ids.map((id) => traceable(m, id))).toEqual(ids.map(() => true));
    expect(traceable(m, "nope")).toBe(false);
  });

  it("a service lists the methods requests, events, streams and jobs arrive at, with their keys", () => {
    expect(entryPoints(m, "svc:worker")).toEqual([{ node: "worker::worker.main#run/2", keys: ["orders"] }]);
    expect(entryPoints(m, "svc:shop").map((e) => e.node)).toEqual(["shop::io.demo.shop.api.OrderApi$#getEndpoint/0", "shop::io.demo.shop.api.OrderApi$#createEndpoint/0"]);   // GET … before POST …
  });

  it("a route's handler (files[].routes) is an entry point, keyed by method and path; a file-level handler is not", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const h = b.method(s, "Api", "list");
    b.extra = { files: { "orders/Api.py": { routes: [{ method: "GET", path: "/v1/orders", handler: h, line: 3 }, { method: "GET", path: "/health", handler: "orders::pkg.Api", line: 9 }] } } } as never;
    expect(entryPoints(b.model(), s)).toEqual([{ node: h, keys: ["GET /v1/orders"] }]);
  });

  it("a route is one key whatever its spelling: the relation's, mount prefix included (the Python checklist's rule)", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const h = b.method(s, "Api", "create");
    b.rel("request", s, h, { key: "POST /v1/orders" });
    b.extra = { files: { "orders/Api.py": { routes: [{ method: "POST", path: "/orders", handler: h, line: 3 }, { method: "GET", path: "/orders", handler: h, line: 5 }] } } } as never;
    expect(entryPoints(b.model(), s)).toEqual([{ node: h, keys: ["GET /orders", "POST /v1/orders"] }]);
  });

  it("an entry example's node is not an entry point by itself (the Python checklist's rule)", () => {
    const { b } = billing();
    expect(entryPoints(b.model(), "svc:billing")).toEqual([]);
  });

  it("a package, file or class lists every method inside it", () => {
    expect(new Set(methodsIn(m, "worker::worker.main.Job"))).toEqual(new Set(["worker::worker.main.Job#__init__/1", "worker::worker.main.Job#_secret/0", "worker::worker.main.Job#store/3"]));
    expect(methodsIn(m, "worker::worker/").length).toBeGreaterThanOrEqual(6);
  });
});

describe("entry points agree with the Python checklist", () => {
  it("a route has two spellings; its example is found by node, not by key", () => {
    const b = new MapBuilder();
    const s = b.owner("orders");
    const h = b.method(s, "Api", "list");
    b.extra = { files: { "orders/Api.py": { routes: [{ method: "GET", path: "/orders", handler: h, line: 3 }] } },
      examples: { types: {}, entries: [{ node: h, key: "GET /v1/orders", request: [1, 2], response: "ok" }] } } as never;
    const m = b.model();
    expect(entryPoints(m, s).map((e) => e.node)).toEqual([h]);
    expect(examplesFor(m, h, "GET /orders")).toEqual([{ kind: "entry", title: "GET /v1/orders", request: [1, 2], response: "ok" }]);
  });

  it("the demo map has the 27 entry points the Python checklist reports", () => {
    const demo = JSON.parse(readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8")) as CodeMap;
    const dm = new Model(demo);
    const nodes = new Set<string>();
    for (const n of demo.nodes) if (n.kind === "service" || n.kind === "library") for (const e of entryPoints(dm, n.id)) nodes.add(e.node);
    expect(nodes.size).toBe(27);
  });
});
