import { describe, expect, it } from "vitest";
import { commonPrefix, doorName, nameLines, splitEndpoint } from "../../src/floor/names";

describe("machine names", () => {
  it("drops the dotted prefix every item on the floor shares", () => {
    expect(commonPrefix(["com.acme.common.db", "com.acme.common.http", "com.acme.common.db.model"])).toBe("com.acme.common.");
    expect(commonPrefix(["com.acme.order", "com.acme.order.api", "com.acme.order.repo"])).toBe("com.acme.order.");
    expect(commonPrefix(["market", "order"])).toBe("");
    expect(commonPrefix(["only.one"])).toBe("");
  });

  it("wraps at separators and keeps the specific end when it still does not fit", () => {
    expect(nameLines("db", 140, 14, 2)).toEqual(["db"]);
    const two = nameLines("pricing_engine.promotions.seasonal_rebate", 140, 14, 2);
    expect(two).toHaveLength(2);
    expect(two[0].endsWith(".") || two[0].endsWith("_")).toBe(true);
    const one = nameLines("PaymentHoldManagerLiveImplementation", 140, 13, 1);
    expect(one).toHaveLength(1);
    expect(one[0].startsWith("…")).toBe(true);
    expect(one[0].endsWith("Implementation")).toBe(true);
  });

  it("breaks prose names at spaces and before a parenthesis, never mid-word", () => {
    const lines = nameLines("Stripe API WebSocket feed (streams)", 120, 14, 2);
    expect(lines).toHaveLength(2);
    for (const l of lines) expect(["WebS", "WebSo", "WebSoc", "WebSock", "WebSocke"].some((cut) => l.endsWith(cut))).toBe(false);
    expect(lines[0]).toBe("Stripe API");
    expect(nameLines("Stripe API REST (api.stripe.com)", 150, 14, 2)).toEqual(["Stripe API REST", "(api.stripe.com)"]);
  });

  it("moves an external's parenthesised endpoint out of its title", () => {
    expect(splitEndpoint("Stripe API WebSocket (stream.stripe.com/streams)")).toEqual({ title: "Stripe API WebSocket", endpoint: "stream.stripe.com/streams" });
    expect(splitEndpoint("Stripe API REST")).toEqual({ title: "Stripe API REST", endpoint: "" });
  });

  it("names a door relative to the floors above it, keeping one segment of context", () => {
    const above = ["com.acme.market.service", "market", "Whole system"];
    expect(doorName("com.acme.market.service.stripe", above)).toBe("service.stripe");
    expect(doorName("pricing-engine", above)).toBe("pricing-engine");
    expect(doorName("Stripe API REST (api.stripe.com)", above)).toBe("Stripe API REST");
  });

  it("breaks after a hyphen rather than inside a word", () => {
    expect(nameLines("GCS orders-search bucket", 124, 15, 2)).toEqual(["GCS orders-", "search bucket"]);
  });

  it("breaks a long camelCase word at a word boundary and never strands a letter or two", () => {
    expect(nameLines("DiscordNotifier", 124, 17, 2)).toEqual(["Discord", "Notifier"]);
    for (const l of nameLines("PaymentHoldManagerLiveImpl", 124, 17, 2)) expect(l.replace("…", "").length).toBeGreaterThan(2);
    expect(nameLines("Notifier", 124, 17, 2)).toEqual(["Notifier"]);
  });
});

