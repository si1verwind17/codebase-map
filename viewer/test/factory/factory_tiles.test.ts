import { describe, expect, it } from "vitest";
import { DIRS, FOOT, OPP, STEP, dirInto, footprintFor, inside } from "../../src/factory/tiles";

describe("tiles", () => {
  it("gives every map kind its footprint; libraries are racks outside and wall units inside", () => {
    expect(footprintFor("service", true)).toBe("service");
    expect(footprintFor("external", true)).toBe("dock");
    expect(footprintFor("library", true)).toBe("rack");
    expect(footprintFor("library", false)).toBe("installed");
    expect(footprintFor("datastore", false)).toBe("warehouse");
    expect(footprintFor("topic", true)).toBe("hub");
    for (const k of ["package", "class", "file", "method", "table", "group"]) expect(footprintFor(k, false)).toBe("package");
    expect(FOOT.service).toEqual([5, 5]);
    expect(FOOT.installed).toEqual([4, 5]);
    expect(FOOT.package).toEqual([5, 3]);
    expect(FOOT.door).toEqual([7, 3]);   // wide enough for a door name in two lines at 12.5 px
  });

  it("knows directions, opposites and which side of a tile touches a box", () => {
    expect(DIRS.map((d) => OPP[d])).toEqual(["s", "w", "n", "e"]);
    for (let i = 0; i < 4; i++) expect(DIRS[(i + 2) % 4]).toBe(OPP[DIRS[i]]);
    expect(STEP.e).toEqual([1, 0]);
    const box = { x: 4, y: 4, w: 2, h: 2 };
    expect(inside(box, 5, 5)).toBe(true);
    expect(inside(box, 6, 5)).toBe(false);
    expect(dirInto(box, 3, 4)).toBe("e");    // left of the box: travelling east enters it
    expect(dirInto(box, 4, 6)).toBe("n");    // below it
    expect(dirInto(box, 3, 3)).toBe(null);   // diagonal: not touching
  });
});
