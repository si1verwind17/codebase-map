import { describe, expect, it } from "vitest";
import shop from "../fixtures/shop.code-map.json";
import { Model } from "../../src/model/model";
import { needsOf, neededBy, serviceOf, splitByService } from "../../src/model/needs";
import type { CodeMap, MapNode } from "../../src/model/types";

const base = shop as unknown as CodeMap;
const API = "shop::io.demo.shop.api/";
const WORKER = "worker::worker/";
const COMMON = "common::io.demo.common.db/";
const cls = (id: string, parent: string, extra: Partial<MapNode> = {}): MapNode =>
  ({ id, kind: "class", name: id.split(".").pop()!, parent, file: `${id}.src`, line: 3, ...extra });
const method = (id: string, parent: string, name: string, params: { name: string; type: string | null; refs?: string[] }[]): MapNode =>
  ({ id, kind: "method", name, parent, file: `${parent}.src`, line: 9, signature: { params, returns: null } });

function modelWith(...nodes: MapNode[]): Model {
  return new Model({ ...structuredClone(base), nodes: [...structuredClone(base.nodes), ...nodes] });
}

describe("needsOf", () => {
  it("reads the parameters of the constructor method the fact points to", () => {
    const m = modelWith(
      cls("shop.Checkout", API, { ctor: { method: "shop.Checkout.__init__", of: 2 } }),
      method("shop.Checkout.__init__", "shop.Checkout", "__init__", [
        { name: "repo", type: "OrderRepo", refs: ["shop.OrderRepo"] },
        { name: "clock", type: "datetime.Clock" },
        { name: "retries", type: null },
      ]),
    );
    expect(needsOf(m, "shop.Checkout")).toEqual({
      needs: [
        { name: "repo", type: "OrderRepo", refs: ["shop.OrderRepo"] },
        { name: "clock", type: "datetime.Clock", refs: [] },
        { name: "retries", type: null, refs: [] },
      ],
      from: "__init__", file: "shop.Checkout.src", line: 9, of: 2,
    });
  });

  it("reads inline class parameters from the class itself", () => {
    const m = modelWith(cls("shop.Billing", API, { ctor: { params: [{ name: "repo", type: "OrderRepo", refs: ["shop.OrderRepo"] }], line: 5 } }));
    expect(needsOf(m, "shop.Billing")).toEqual({
      needs: [{ name: "repo", type: "OrderRepo", refs: ["shop.OrderRepo"] }],
      from: "class parameters", file: "shop.Billing.src", line: 5,
    });
  });

  it("is null for a class without a constructor fact", () => {
    expect(needsOf(modelWith(cls("shop.Plain", API)), "shop.Plain")).toBeNull();
  });
});

const takes = (id: string, parent: string, ...refs: string[]) =>
  cls(id, parent, { ctor: { params: refs.map((r, i) => ({ name: `p${i}`, type: r, refs: [r] })), line: 1 } });

describe("neededBy", () => {
  it("lists the classes that take it, directly or through an interface it implements", () => {
    const m = modelWith(
      cls("shop.Repo", API),
      cls("shop.PgRepo", API, { implements: ["shop.Repo"] }),
      takes("shop.A", API, "shop.PgRepo"),
      takes("shop.B", API, "shop.Repo"),
    );
    expect(neededBy(m, "shop.PgRepo")).toEqual([{ id: "shop.A", through: null }, { id: "shop.B", through: "shop.Repo" }]);
    expect(neededBy(m, "shop.Repo")).toEqual([{ id: "shop.B", through: null }]);
  });

  it("follows interfaces up their own implements, naming the nearest one the class is taken as", () => {
    const m = modelWith(
      cls("shop.Gateway", API),
      cls("shop.PaymentGateway", API, { implements: ["shop.Gateway"] }),
      cls("shop.Stripe", API, { implements: ["shop.PaymentGateway"] }),
      takes("shop.Checkout", API, "shop.Gateway"),
      takes("shop.Refunds", API, "shop.PaymentGateway"),
      takes("shop.Both", API, "shop.Gateway", "shop.PaymentGateway"),
    );
    expect(neededBy(m, "shop.Stripe")).toEqual([
      { id: "shop.Both", through: "shop.PaymentGateway" },
      { id: "shop.Checkout", through: "shop.Gateway" },
      { id: "shop.Refunds", through: "shop.PaymentGateway" },
    ]);
  });

  it("ends on a loop of implements", () => {
    const m = modelWith(
      cls("shop.P", API, { implements: ["shop.Q"] }),
      cls("shop.Q", API, { implements: ["shop.P"] }),
      cls("shop.Impl", API, { implements: ["shop.P"] }),
      takes("shop.A", API, "shop.Q"),
    );
    expect(neededBy(m, "shop.Impl")).toEqual([{ id: "shop.A", through: "shop.Q" }]);
  });

  it("lists a class once, the direct need winning over the interface", () => {
    const m = modelWith(
      cls("shop.Repo", API),
      cls("shop.PgRepo", API, { implements: ["shop.Repo"] }),
      takes("shop.A", API, "shop.Repo", "shop.PgRepo"),
    );
    expect(neededBy(m, "shop.PgRepo")).toEqual([{ id: "shop.A", through: null }]);
  });

  it("lists each of two classes that take one another once", () => {
    const m = modelWith(takes("shop.A", API, "shop.B"), takes("shop.B", API, "shop.A"));
    expect(neededBy(m, "shop.A")).toEqual([{ id: "shop.B", through: null }]);
    expect(neededBy(m, "shop.B")).toEqual([{ id: "shop.A", through: null }]);
  });

  it("leaves out a class others implement, which is never built as itself", () => {
    const m = modelWith(
      cls("shop.Repo", API),
      takes("shop.Base", API, "shop.Repo"),
      takes("shop.Orders", API, "shop.Repo"),
      cls("shop.Impl", API, { implements: ["shop.Base"] }),
    );
    expect(neededBy(m, "shop.Repo")).toEqual([{ id: "shop.Orders", through: null }]);
  });

  it("leaves out a class that takes its own kind, as a copy constructor does", () => {
    const m = modelWith(takes("shop.Money", API, "shop.Money"), takes("shop.Cart", API, "shop.Money"));
    expect(neededBy(m, "shop.Money")).toEqual([{ id: "shop.Cart", through: null }]);
  });
});

describe("a need without a type", () => {
  it("keeps the parameter name with a null type, for the viewer to show a dash", () => {
    const m = modelWith(cls("shop.Mailer", API, { ctor: { params: [{ name: "host", type: null }], line: 1 } }));
    expect(needsOf(m, "shop.Mailer")!.needs).toEqual([{ name: "host", type: null, refs: [] }]);
  });
});

describe("splitByService", () => {
  it("puts the ids of another service apart", () => {
    const m = modelWith(cls("shop.Port", API), cls("shop.ShopImpl", API), cls("worker.WorkerImpl", WORKER));
    expect(serviceOf(m, "shop.Port")).toBe("svc:shop");
    expect(splitByService(m, ["shop.ShopImpl", "worker.WorkerImpl"], "shop.Port")).toEqual({ here: ["shop.ShopImpl"], other: ["worker.WorkerImpl"] });
  });

  it("keeps everything here for an interface in a library, which has no service", () => {
    const m = modelWith(cls("common.Port", COMMON), cls("shop.ShopImpl", API), cls("worker.WorkerImpl", WORKER));
    expect(serviceOf(m, "common.Port")).toBeUndefined();
    expect(splitByService(m, ["shop.ShopImpl", "worker.WorkerImpl"], "common.Port")).toEqual({ here: ["shop.ShopImpl", "worker.WorkerImpl"], other: [] });
  });
});
