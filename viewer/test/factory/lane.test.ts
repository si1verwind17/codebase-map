import { describe, expect, it } from "vitest";
import { crossings, isClick, laneCrossings, moverSpeed } from "../../src/floor/lane";
import { laneLabelSpot } from "../../src/factory/clear";

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

  it("keeps a lane's name off a drone or flight path over the lane, as off a line crossing it", () => {
    const lane = { y: 10 };   // rows 10-12: 240..312 px
    const path = [{ x: 0, y: 200 }, { x: 400, y: 400 }];   // over the lane from x 80 to 224
    const xs = laneCrossings(lane, [], [path]);
    expect(xs[0]).toBe(80);
    expect(xs[xs.length - 1]).toBeCloseTo(224);
    expect(xs.every((x, i) => i === 0 || x - xs[i - 1] <= 8)).toBe(true);
    // a name that would fit from the lane's start does not: it sits past the path
    expect(laneLabelSpot(48, 600, 60, xs, 1).x).toBeCloseTo(232);
    expect(laneCrossings(lane, [], [[{ x: 0, y: 0 }, { x: 400, y: 100 }]])).toEqual([]);   // a path above the lane
  });
});

describe("mover speed", () => {
  it("keeps belts and pipes at 60 px/s and lets the length it is given take 3 s (a rail) or 5 s (a floor's longest flight)", () => {
    expect(moverSpeed("event", 120)).toBe(60);
    expect(moverSpeed("event", 900)).toBe(180);   // a floor's longest flight: 5 s
    expect(moverSpeed("train", 900)).toBe(300);   // a rail: 3 s
    expect(moverSpeed("db-write", 900)).toBe(60);
    expect(moverSpeed("stream", 5000)).toBe(60);
  });
  it("tells a click from a drag", () => {
    expect(isClick(1, 2)).toBe(true);
    expect(isClick(3, 3)).toBe(false);
  });
});
