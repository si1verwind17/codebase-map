import { describe, expect, it } from "vitest";
import { forwardToStore, packetInk } from "../../src/floor/movers";
import { C } from "../../src/floor/palette";

const pts = [{ x: 0, y: 0 }, { x: 0, y: 10 }];

describe("items on store lines (owner 2026-10-06: into the store red, out of it grey)", () => {
  it("an item travelling into a store is red, one coming out is slate, whatever the line's dominant kind", () => {
    for (const k of ["db-write", "db-read"]) {
      expect(packetInk(k, true)).toBe(C.red);
      expect(packetInk(k, false)).toBe(C.slate);
    }
  });
  it("other lines keep their yellow items", () => {
    expect(packetInk("request", true)).toBe(C.yellow);
    expect(packetInk("calls", false)).toBe(C.yellow);
  });
  it("factory taps: a read-only tap runs out of the lane, a write or two-way tap runs into it", () => {
    expect(forwardToStore({ key: "k", points: pts, tap: "db:x", kind: "tapR" }, "db-read")).toBe(false);
    expect(forwardToStore({ key: "k", points: pts, tap: "db:x", kind: "tapW" }, "db-write")).toBe(true);
    expect(forwardToStore({ key: "k", points: pts, tap: "db:x", kind: "tapRW" }, "db-write")).toBe(true);
  });
});
