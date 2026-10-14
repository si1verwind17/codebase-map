import { describe, expect, it } from "vitest";
import { crossings, isClick, moverSpeed } from "../src/floor/lane";

describe("lane labels", () => {
  it("finds where vertical runs cross or end on a lane", () => {
    const routes = [
      { key: "a", points: [{ x: 275, y: 0 }, { x: 275, y: 500 }] },          // passes through
      { key: "b", points: [{ x: 523, y: 0 }, { x: 523, y: 50 }], tap: "x" },  // ends on it
      { key: "c", points: [{ x: 600, y: 0 }, { x: 600, y: 30 }] },            // stops above it
      { key: "d", points: [{ x: 100, y: 50 }, { x: 900, y: 50 }] },           // runs along it: not a crossing
    ];
    expect(crossings(routes, 50, 14)).toEqual([275, 523]);
  });
});

describe("mover speed", () => {
  it("keeps belts and pipes at 60 px/s and lets a drone cross in about three seconds", () => {
    expect(moverSpeed("event", 120)).toBe(60);
    expect(moverSpeed("event", 900)).toBe(300);
    expect(moverSpeed("db-write", 900)).toBe(60);
    expect(moverSpeed("stream", 5000)).toBe(60);
  });
  it("tells a click from a drag", () => {
    expect(isClick(1, 2)).toBe(true);
    expect(isClick(3, 3)).toBe(false);
  });
});
