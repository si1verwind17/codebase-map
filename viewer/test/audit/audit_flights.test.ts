// The flight path checks: `flights.overlap` (paths still on top of each other after their landings are spread),
// `flights.in-line` (paths in line with their hub the edge cannot part) and `flights.hidden` (a path under a box not its
// own), on synthetic floors, firing and not.
import { describe, expect, it } from "vitest";
import { hiddenViolations, inLineViolations, overlapViolations } from "../../src/audit/flights";
import { flightPaths } from "../../src/factory/flights";
import { flightFloor } from "../factory/flight_floor";

const HUB = { id: "topic:q", x: 20, y: 60 };
const column = (n: number, x = 19) => Array.from({ length: n }, (_, i) => ({ id: `svc:m${i}`, x, y: 2 + i * 7, to: HUB.id }));

describe("flights.overlap", () => {
  it("fires on paths into one hub that outgrew its edge and share landing points, naming both", () => {
    // eight pads a tile apart, none in line with another, into one hub whose edge holds six points
    const fan = [{ id: "svc:a", x: 14, y: 2, to: "topic:f", pads: [0, 1, 2, 3] }, { id: "svc:b", x: 19, y: 2, to: "topic:f", pads: [0, 1, 2, 3] }];
    const tf = flightFloor(fan, [{ id: "topic:f", x: 17, y: 60 }]);
    const v = overlapViolations(tf);
    expect(v.length).toBeGreaterThan(0);
    expect(v[0].detail).toMatch(/^produce svc:[ab]\|topic:f and produce svc:[ab]\|topic:f run within 3 px of each other for \d+ px on open floor$/);
    expect(inLineViolations(tf)).toEqual([]);
    // seven fit: no point is shared, and nothing fires
    expect(overlapViolations(flightFloor([fan[0], { ...fan[1], pads: [0, 1] }], [{ id: "topic:f", x: 16, y: 60 }]))).toEqual([]);
  });

  it("fires on paths into different hubs that run on top of each other (no spread between hubs)", () => {
    // two hubs in one column, each fed by a pad above them on the column's line: a's path runs down over b's
    const tf = flightFloor([{ id: "svc:a", x: 19, y: 2, to: "topic:a" }, { id: "svc:b", x: 19, y: 9, to: "topic:b" }],
      [{ id: "topic:a", x: 20, y: 60 }, { id: "topic:b", x: 20, y: 40 }]);
    expect(overlapViolations(tf).map((v) => v.detail)).toEqual([expect.stringMatching(/^produce svc:a\|topic:a and produce svc:b\|topic:b run within 3 px/)]);
  });

  it("is quiet on paths that came apart at the hub and on paths from different directions", () => {
    const parted = flightFloor([{ id: "svc:a", x: 19, y: 2, to: HUB.id }, { id: "svc:b", x: 20, y: 30, to: HUB.id }], [HUB]);
    expect(overlapViolations(parted)).toEqual([]);
    const round = flightFloor([{ id: "svc:n", x: 19, y: 40, to: HUB.id }, { id: "svc:w", x: 2, y: 58, to: HUB.id },
      { id: "svc:e", x: 40, y: 58, to: HUB.id }], [HUB]);
    expect(overlapViolations(round)).toEqual([]);
  });

  it("does not count a stretch under a box: the paths there are hidden, not on top of each other", () => {
    // two pads in line, close enough to the hub that the spread parts them below the near machine; above it, the far
    // path runs under the near machine, over the near pad
    const tf = flightFloor(column(2), [HUB]);
    expect(overlapViolations(tf)).toEqual([]);
    expect(inLineViolations(tf)).toEqual([]);
    expect(hiddenViolations(tf)).toHaveLength(1);
  });

  it("reads the paths as drawn: the same paths given or worked out", () => {
    const tf = flightFloor(column(8), [HUB], 60, 120);
    expect(overlapViolations(tf, flightPaths(tf))).toEqual(overlapViolations(tf));
  });
});

describe("flights.in-line", () => {
  it("fires, not flights.overlap, on two pads in line with a hub too far off for its edge to part them", () => {
    // the pads 5 tiles apart, the hub 90 tiles below: spread over the whole edge they are still within 3 px below the near machine
    const tf = flightFloor([{ id: "svc:m0", x: 19, y: 2, to: HUB.id }, { id: "svc:m1", x: 19, y: 7, to: HUB.id }], [{ ...HUB, y: 100 }], 60, 110);
    expect(inLineViolations(tf).map((v) => v.detail)).toEqual([expect.stringMatching(/^produce svc:m0\|topic:q and produce svc:m1\|topic:q run within 3 px of each other for \d+ px on open floor$/)]);
    expect(overlapViolations(tf)).toEqual([]);
  });
});

describe("flights.hidden", () => {
  it("fires on a path under another machine, naming the path and the box, at the box's tile", () => {
    const tf = flightFloor(column(2), [HUB]);   // svc:m0's path runs down through svc:m1 below it
    expect(hiddenViolations(tf)).toEqual([{ detail: expect.stringMatching(/^produce svc:m0\|topic:q passes under svc:m1 for \d+ px$/), at: { x: 21, y: 11 } }]);
  });

  it("counts a box's face, not its shadow, and not a corner clipped by less than a dot and its gap", () => {
    // svc:b's face is px 240..360 × 480..600; its shadow reaches 5 px further right and down
    const tf = flightFloor([{ id: "svc:b", x: 10, y: 20, to: HUB.id, pads: [] }], [HUB]);
    const path = (a: { x: number; y: number }, b: { x: number; y: number }) => [{ ...flightPaths(flightFloor(column(1), [HUB]))[0], points: [a, b] }];
    expect(hiddenViolations(tf, path({ x: 363, y: 300 }, { x: 363, y: 900 }))).toEqual([]);    // in the shadow, off the face
    expect(hiddenViolations(tf, path({ x: 355, y: 300 }, { x: 355, y: 900 }))).toHaveLength(1);   // 5 px into the face, down its whole height
    expect(hiddenViolations(tf, path({ x: 352, y: 470 }, { x: 372, y: 500 }))).toEqual([]);    // clips the corner: about 2 px inside
    expect(hiddenViolations(tf, path({ x: 340, y: 470 }, { x: 370, y: 500 }))).toHaveLength(1);   // about 14 px inside
  });

  it("is quiet on a path over open floor: its own machine and its hub do not count", () => {
    const tf = flightFloor([{ id: "svc:n", x: 19, y: 40, to: HUB.id }, { id: "svc:w", x: 2, y: 58, to: HUB.id }], [HUB]);
    expect(hiddenViolations(tf)).toEqual([]);
  });

  it("a door hub is the path's own: a path into a door is not under it", () => {
    const door = { id: "door:topic:q", x: 18, y: 60 };
    expect(hiddenViolations(flightFloor([{ id: "svc:a", x: 19, y: 30, to: door.id }], [door]))).toEqual([]);
  });
});
