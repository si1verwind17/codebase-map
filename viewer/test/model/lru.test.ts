// The plan cache's LRU: the least recently used entry leaves first, `get` refreshes and `has` does not.
import { describe, expect, it } from "vitest";
import { Lru } from "../../src/floor/lru";

describe("Lru", () => {
  it("evicts the least recently used entry once over max", () => {
    const l = new Lru<string, number>(2);
    l.set("a", 1); l.set("b", 2); l.set("c", 3);
    expect([l.has("a"), l.has("b"), l.has("c")]).toEqual([false, true, true]);
  });

  it("get refreshes an entry, has does not", () => {
    const l = new Lru<string, number>(2);
    l.set("a", 1); l.set("b", 2);
    expect(l.get("a")).toBe(1);
    l.set("c", 3);
    expect([l.has("a"), l.has("b"), l.has("c")]).toEqual([true, false, true]);
    expect(l.has("a")).toBe(true);
    l.set("d", 4);   // `has` left "a" the oldest
    expect([l.has("a"), l.has("c"), l.has("d")]).toEqual([false, true, true]);
    expect(l.get("missing")).toBeUndefined();
  });

  it("set of a present key replaces its value and refreshes it", () => {
    const l = new Lru<string, number>(2);
    l.set("a", 1); l.set("b", 2); l.set("a", 9); l.set("c", 3);
    expect(l.get("a")).toBe(9);
    expect(l.has("b")).toBe(false);
  });

  it("size never exceeds max; clear empties", () => {
    const l = new Lru<number, number>(5);
    for (let i = 0; i < 40; i++) { l.set(i % 13, i); if (i % 3 === 0) l.get(i % 7); expect(l.size).toBeLessThanOrEqual(5); }
    expect(l.size).toBe(5);
    l.clear();
    expect(l.size).toBe(0);
    expect(l.has(39 % 13)).toBe(false);
  });
});
