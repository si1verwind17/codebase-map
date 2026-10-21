// test/factory_webhooks.test.ts
// Inbound webhooks: on the site, a request from an outside service ends at a receiving dock on its service.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import shop from "../fixtures/shop.code-map.json";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor } from "../../src/factory/plan";
import { reservedRects, webhookDocks, webhookSign } from "../../src/factory/pads";
import { coveredKeys, dockFace, flightPaths, messagingLabels, messagingObstacles } from "../../src/factory/flights";
import { Clearance, planZoneLabel, type PxRect } from "../../src/factory/clear";
import { railLabels } from "../../src/factory/rail-place";
import { plateW } from "../../src/factory/fit";
import { STEP, T, inside, type Rect } from "../../src/factory/tiles";
import type { TileFloor } from "../../src/factory/layout";
import type { TileRoute } from "../../src/factory/router";
import { checkTrunks, plugged } from "./factory_trunks";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);

/** Does `d` stand just outside one side of `b`, along it (a 1-deep run touching the box, not overlapping it)? */
function against(d: Rect, b: Rect): boolean {
  const overlapX = d.x < b.x + b.w && b.x < d.x + d.w, overlapY = d.y < b.y + b.h && b.y < d.y + d.h;
  return (overlapX && (d.y + d.h === b.y || d.y === b.y + b.h)) || (overlapY && (d.x + d.w === b.x || d.x === b.x + b.w));
}

/** The tile past a route's last piece: where it plugs in. */
const after = (r: TileRoute) => { const l = r.pieces[r.pieces.length - 1]; return { x: l.x + STEP[l.out][0], y: l.y + STEP[l.out][1] }; };

function check(tf: TileFloor, routes: TileRoute[], label: string) {
  expect(routes.filter((r) => r.failed), `${label}: no failed line`).toHaveLength(0);
  checkTrunks(tf, routes, label);
  for (const r of routes) if (r.pieces.length) plugged(tf, r);
  for (const d of tf.webhooks ?? []) {
    for (const b of tf.boxes.values()) expect(inside(d, b.x, b.y) || inside(b, d.x, d.y), `${label}: dock on ${b.id}`).toBe(false);
    expect(reservedRects(tf).some((r) => r.x === d.x && r.y === d.y && r.w === d.w && r.h === d.h), `${label}: dock reserved`).toBe(true);
  }
}

/** No dock's words sit over a line tile or a label: they stay on the dock's face, and every label the scene places (zone
 *  names, messaging labels, rail labels, in its order) keeps off them. */
function noTextOver(model: Model, c: string, tf: TileFloor, routes: TileRoute[], label: string) {
  const hit = (a: PxRect, b: PxRect) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
  const labels: PxRect[] = [];
  let open = false;   // the constructor adds the obstacles through add(): only what is added after it is a label
  class Seen extends Clearance { add(r: PxRect) { super.add(r); if (open) labels.push(r); } }
  const { bundles: bs } = model.bundles(c);
  const flights = flightPaths(tf), clear = new Seen(messagingObstacles(tf, routes, flights, coveredKeys(flights, bs)), tf.cols + 8);
  open = true;
  for (const z of tf.zones) planZoneLabel(z, clear);
  messagingLabels(model, tf, flights, clear);
  if (tf.rails) railLabels(model, c, tf, clear);
  expect(labels.length, `${label}: labels placed`).toBeGreaterThan(0);
  for (const d of tf.webhooks ?? []) {
    const f = dockFace(d);
    const rects: PxRect[] = [{ x0: d.x * T, y0: d.y * T, x1: (d.x + d.w) * T, y1: (d.y + d.h) * T }];
    if (f) {
      expect(f.text.includes("…"), `${label}: never trimmed`).toBe(false);
      const r = { x0: f.x, y0: f.y, x1: f.x + f.w, y1: f.y + f.h };
      expect(hit(r, rects[0]) && r.x0 >= rects[0].x0 && r.x1 <= rects[0].x1 && r.y0 >= rects[0].y0 && r.y1 <= rects[0].y1, `${label}: words on the dock`).toBe(true);
      rects.push(r);
    }
    for (const r of rects) {
      for (const q of routes) for (const p of q.pieces) if (!p.under)
        expect(hit(r, { x0: p.x * T, y0: p.y * T, x1: (p.x + 1) * T, y1: (p.y + 1) * T }), `${label}: ${d.machine} text over ${q.key} at ${p.x},${p.y}`).toBe(false);
      for (const l of labels) expect(hit(r, l), `${label}: ${d.machine} text under a label`).toBe(false);
    }
  }
}

describe("inbound webhook receiving docks", () => {
  const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
  const { bundles, doors } = demo.bundles(SITE);
  const plan = planFloor(demo, SITE, doors, bundles);

  it("the demo site's payments-webhook has a 1×3 receiving dock against its box, upright on the side its belt arrives, no text over a line or label", () => {
    const tf = plan.tf, box = tf.boxes.get("svc:payments-webhook")!;
    expect(tf.webhooks, "one webhook dock on the site").toHaveLength(1);
    const d = tf.webhooks![0];
    expect(d.machine).toBe("svc:payments-webhook");
    expect([d.w, d.h].sort(), "1×3").toEqual([1, 3]);
    expect(against(d, box), "against its box").toBe(true);
    expect(d.signs).toEqual(["POST /webhooks/stripe"]);
    expect(tf.notes ?? []).not.toContainEqual(expect.stringMatching(/^webhook/));
    // the Stripe belt arrives on the east side, facing Stripe: an upright dock carries no words, its route shows on hover
    expect(d.side).toBe("e");
    expect(d.face).toBeUndefined();
    expect(dockFace(d)).toBeUndefined();
    noTextOver(demo, SITE, tf, plan.routes, "demo site");
  });

  it("the Stripe belt ends on the dock, still a dashed-edged (inferred) belt, plugged at both ends", () => {
    const tf = plan.tf, d = tf.webhooks![0];
    const r = plan.routes.find((q) => q.key.includes("3p:stripe") && q.key.includes("svc:payments-webhook"))!;
    expect(r.kind).toBe("belt");
    expect(r.pieces.length).toBeGreaterThan(0);
    expect(inside(d, after(r).x, after(r).y), "its last piece plugs into the dock").toBe(true);
    const end = r.points[r.points.length - 1];
    const px = { x0: d.x * T, y0: d.y * T, x1: (d.x + d.w) * T, y1: (d.y + d.h) * T };
    expect(end.x >= px.x0 && end.x <= px.x1 && end.y >= px.y0 && end.y <= px.y1, "its last point is on the dock").toBe(true);
    expect(d.keys).toEqual([r.key]);
    const b = bundles.find((q) => q.key === r.key)!;
    expect(b.inferred === b.relations.length, "inferred: drawn dashed-edged").toBe(true);
    check(tf, plan.routes, "demo site");
  });

  it("an inside floor has no webhook dock (the inbound arrives through a door)", () => {
    const c = "svc:payments-webhook";
    const fl = demo.bundles(c);
    expect(planFloor(demo, c, fl.doors, fl.bundles).tf.webhooks).toBeUndefined();
  });

  it("two inbound webhooks to one service share one dock, both routes listed; the face grows to carry `first +N` where the side allows", () => {
    const map = structuredClone(shop) as unknown as CodeMap;
    const to = "worker::worker.main#health/0";
    const add = (id: string, name: string, col: number, row: number, key: string | undefined) => {
      map.nodes.push({ id, kind: "external", name } as CodeMap["nodes"][number]);
      map.layout.containers.site.items[id] = { region: "line", col, row };
      map.relations.push({ kind: "request", from: id, to, id: `r:request:${id}->${to}`, ...(key ? { key } : {}), confidence: "inferred", evidence: [] } as unknown as CodeMap["relations"][number]);
    };
    add("3p:pay", "pay", 3, 0, "POST /hooks/pay");
    add("3p:mail", "mail", 0, 1, "POST /hooks/mail");
    const m = new Model(map);
    const { bundles: bs, doors: ds } = m.bundles(SITE);
    const p = planFloor(m, SITE, ds, bs);
    const docks = p.tf.webhooks ?? [];
    expect(docks, "one dock").toHaveLength(1);
    const d = docks[0];
    expect(d.machine).toBe("svc:worker");
    expect(against(d, p.tf.boxes.get("svc:worker")!)).toBe(true);
    expect(d.signs, "a sign per path").toEqual(["POST /hooks/mail", "POST /hooks/pay"]);
    for (const ext of ["3p:pay", "3p:mail"]) {
      const r = p.routes.find((q) => q.key.split("|").includes(ext))!;
      expect(inside(d, after(r).x, after(r).y), `${ext} plugs into the dock`).toBe(true);
    }
    check(p.tf, p.routes, "two webhooks");
    // level: the belts arrive on worker's north side, 5 tiles long: too short for the first route and `+1`, so the face
    // names the first route's method and `+1`
    expect(d.side, "arrives on worker's north side").toBe("n");
    expect([d.face, d.w]).toEqual(["POST +1", 3]);
    noTextOver(m, SITE, p.tf, p.routes, "two webhooks");
    expect(planFloor(m, SITE, ds, bs)).toEqual(p);
    // the arrival side held: the next side in the push dock's order; all four held: no dock, the belts keep the wall, a note
    const box = p.tf.boxes.get("svc:worker")!, ring = (sides: string[], b: Rect = box) => {
      const out: { item: string; topic: string; x: number; y: number }[] = [];
      for (let x = b.x - 1; x <= b.x + b.w; x++) for (let y = b.y - 1; y <= b.y + b.h; y++) {
        const side = y === b.y - 1 ? "n" : y === b.y + b.h ? "s" : x === b.x - 1 ? "w" : x === b.x + b.w ? "e" : "";
        if (sides.includes(side)) out.push({ item: "t", topic: "t", x, y });
      }
      return out;
    };
    const bare = { ...p.tf, webhooks: undefined };
    const other = webhookDocks(m, { ...bare, stacks: [...p.tf.stacks ?? [], ...ring([d.side])] }, bs, p.routes)!;
    expect(other.docks).toHaveLength(1);
    expect(other.docks[0].side).not.toBe(d.side);
    const none = webhookDocks(m, { ...bare, stacks: [...p.tf.stacks ?? [], ...ring(["n", "e", "s", "w"])] }, bs, p.routes)!;
    expect(none.docks).toHaveLength(0);
    expect(none.notes).toEqual(["webhook dock: svc:worker has no free side; its belts plug into its wall"]);
    // a level side long enough for the first route and `+1`: the dock grows to carry it (6 tiles of words + 1 of stripes)
    const wide = new Map(p.tf.boxes);
    const big = { ...box, w: 9 };
    wide.set("svc:worker", big);
    const level = webhookDocks(m, { ...bare, boxes: wide, stacks: [...p.tf.stacks ?? [], ...ring(["e", "w"], big)] }, bs, p.routes)!.docks[0];
    expect(level.side === "n" || level.side === "s").toBe(true);
    expect(level.face).toBe("POST /hooks/mail +1");
    expect(level.w).toBe(Math.ceil(plateW("POST /hooks/mail +1", 10) / T) + 1);
    expect(level.w).toBeLessThanOrEqual(9);
    const f = dockFace(level)!;
    expect(f.x + f.w, "the words stay on the dock").toBeLessThanOrEqual((level.x + level.w) * T);
    // a 5-wide side: too short for the route, the face names the first route's method and `+1`
    const narrow = webhookDocks(m, { ...bare, stacks: [...p.tf.stacks ?? [], ...ring(["e", "w"])] }, bs, p.routes)!.docks[0];
    expect([narrow.face, narrow.w]).toEqual(["POST +1", 3]);
  });

  it("a webhook arriving on the side of its service's cache chest leaves the chest's gap free: the tap stays one tile", () => {
    const map = structuredClone(shop) as unknown as CodeMap;
    const id = "3p:hook", to = "shop::io.demo.shop.repo.PgOrderRepo#load/2";
    map.nodes.push({ id, kind: "external", name: "hook" } as CodeMap["nodes"][number]);
    map.layout.containers.site.items[id] = { region: "line", col: 3, row: 0 };
    map.relations.push({ kind: "request", from: id, to, id: `r:request:${id}->${to}`, key: "POST /hooks/x", confidence: "inferred", evidence: [] } as unknown as CodeMap["relations"][number]);
    const m = new Model(map), { bundles: bs, doors: ds } = m.bundles(SITE);
    const p = planFloor(m, SITE, ds, bs), tf = p.tf;
    const shopBox = tf.boxes.get("svc:shop")!, chest = tf.boxes.get("db:redis:REDIS_URL")!;
    expect(chest.foot).toBe("chest");
    expect(chest.x, "the chest stands right of shop, one tile off").toBe(shopBox.x + shopBox.w + 1);
    const gap = { x: shopBox.x + shopBox.w, y: chest.y, w: 1, h: chest.h };
    expect(tf.chestGaps).toEqual([gap]);
    const hits = (a: Rect, b: Rect) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
    // the hook's first belt arrives on shop's east side, the chest's: its dock goes there only if a free run of 3 misses
    // the gap; shop's east side has none (the gap is rows 1-2 of 5), so the dock takes the next side
    const arrive = { key: `${id}|svc:shop`, pieces: [{ x: gap.x, y: shopBox.y + 4, in: "w", out: "w", under: false, hoodBefore: false, hoodAfter: false }] } as unknown as TileRoute;
    const w = webhookDocks(m, { ...tf, webhooks: undefined }, bs, [arrive])!;
    expect(w.docks).toHaveLength(1);
    expect(w.docks[0].side).not.toBe("e");
    for (const d of [...w.docks, ...tf.webhooks ?? [], ...tf.landing?.docks ?? []]) expect(hits(d, gap), `${d.machine}: dock on the chest's gap`).toBe(false);
    const tap = p.routes.find((r) => r.key === "db:redis:REDIS_URL|svc:shop")!;
    expect(tap).toMatchObject({ kind: "tapRW", failed: undefined });
    expect(tap.pieces, "the tap pair crosses the one-tile gap").toHaveLength(1);
    check(tf, p.routes, "hook beside a chest");
  });

  it("a webhook with no key is signed `webhook`", () => {
    expect(webhookSign(undefined)).toBe("webhook");
    expect(webhookSign("  ")).toBe("webhook");
    expect(webhookSign("POST /webhooks/stripe")).toBe("POST /webhooks/stripe");
  });
});
