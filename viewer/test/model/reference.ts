// The Model's walks as they were before its caches and indexes (commit 694efe3), copied verbatim as the reference the
// cached ones must equal (model_cache.test.ts). `this` is a Reference: its own copies of the walks, and the Model's
// unchanged methods for the rest.
import { DRAW_ORDER, RUNTIME, SITE, type Bundle, type Door, type Model, type Outward } from "../../src/model/model";
import type { LayerBundle } from "../../src/model/layers";
import type { CodeMap, Floor, Group, MapNode, Relation, RelationKind } from "../../src/model/types";

export class Reference {
  readonly map: CodeMap;
  readonly nodes: Map<string, MapNode>;
  readonly groups: Map<string, Group & { container: string }>;
  private memberOf: Map<string, string>;

  constructor(private m: Model) {
    this.map = m.map;
    this.nodes = m.nodes;
    this.groups = m.groups;
    this.memberOf = (m as unknown as { memberOf: Map<string, string> }).memberOf;
  }

  floor(container: string): Floor | undefined { return this.m.floor(container); }
  path(container: string): string[] { return this.m.path(container); }
  floorOf(id: string): string | undefined { return this.m.floorOf(id); }
  commonFloor(container: string, otherFloor: string): string { return this.m.commonFloor(container, otherFloor); }
  doorId(anchor: string): string { return this.m.doorId(anchor); }

  /** Map any node to the item that stands for it on `container`'s floor, or undefined if it is outside. */
  liftTo(container: string, id: string): string | undefined {
    const floor = this.floor(container);
    if (!floor) return undefined;
    if (container === SITE && (floor.utilities ?? []).includes(id)) return undefined;
    let cur: string | undefined = id;
    const seen = new Set<string>();
    while (cur && !seen.has(cur)) {
      seen.add(cur);
      if (cur in floor.items) return cur;
      const viaGroup = this.memberOf.get(cur);
      if (viaGroup && viaGroup in floor.items) return viaGroup;
      const n = this.nodes.get(cur);
      if (n?.kind === "table" && container === SITE) cur = n.parent ?? undefined;
      else cur = n?.parent ?? (viaGroup ? this.groups.get(viaGroup)?.container : undefined);
    }
    return undefined;
  }

  bundles(container: string, opts: { codeLinks?: boolean } = {}): { bundles: Bundle[]; outward: Outward[]; doors: Door[]; layered: LayerBundle[] } {
    const onSite = container === SITE;
    if (this.nodes.get(container)?.kind === "datastore")   // a warehouse is shelves: access is on each table
      return { bundles: [], outward: [], doors: [], layered: [] };
    const wanted = (k: RelationKind) =>
      RUNTIME.includes(k) || (k === "calls" && !onSite) || (k === "uses-code" && !!opts.codeLinks);
    const byKey = new Map<string, Bundle>();
    const out = new Map<string, Outward>();
    for (const r of this.map.relations) {
      if (!wanted(r.kind)) continue;
      const a = this.liftTo(container, r.from);
      const b = this.liftTo(container, r.to);
      if (a && b) {
        if (a === b) continue;
        const [x, y] = a < b ? [a, b] : [b, a];
        const key = `${x}|${y}`;
        let bundle = byKey.get(key);
        if (!bundle) {
          bundle = { key, a: x, b: y, relations: [], kinds: {}, inferred: 0, kind: r.kind, flow: "both" };
          byKey.set(key, bundle);
        }
        bundle.relations.push(r);
        bundle.kinds[r.kind] = (bundle.kinds[r.kind] ?? 0) + 1;
        if (r.confidence === "inferred") bundle.inferred++;
      } else if (a || b) {
        const item = (a ?? b)!;
        const other = a ? r.to : r.from;
        const k = `${item}|${other}`;
        const o = out.get(k) ?? { item, other, relations: [] };
        o.relations.push(r);
        out.set(k, o);
      }
    }
    // relations leaving the floor go through doors on its frame (not on the site floor: it has no outside)
    const doors = new Map<string, Door & { votes: number }>();
    if (!onSite) {
      for (const o of out.values()) {
        const anchor = this.anchorFor(container, o.other);
        const id = this.doorId(anchor);
        for (const r of o.relations) {
          const upstream = r.data === "back" ? r.to : r.from;      // `both` keeps the caller first
          const leaves = this.liftTo(container, upstream) === o.item;
          const d = doors.get(id) ?? { id, anchor, side: "out", votes: 0 };
          d.votes += leaves ? 1 : -1;
          doors.set(id, d);
          const [x, y] = o.item < id ? [o.item, id] : [id, o.item];
          const key = `${x}|${y}`;
          let bundle = byKey.get(key);
          if (!bundle) {
            bundle = { key, a: x, b: y, relations: [], kinds: {}, inferred: 0, kind: r.kind, flow: "both" };
            byKey.set(key, bundle);
          }
          bundle.relations.push(r);
          bundle.kinds[r.kind] = (bundle.kinds[r.kind] ?? 0) + 1;
          if (r.confidence === "inferred") bundle.inferred++;
        }
      }
      for (const d of doors.values()) d.side = d.votes >= 0 ? "out" : "in";
    }
    const lift = (id: string) => this.liftTo(container, id) ?? (onSite ? undefined : this.doorId(this.anchorFor(container, id)));
    for (const b of byKey.values()) {
      b.kind = DRAW_ORDER.find((k) => b.kinds[k]) ?? b.kind;
      b.flow = flowOf(b, lift);
    }
    const hubs = new Set(this.floor(container)?.hubs ?? []);
    const layered: LayerBundle[] = [];
    for (const [k, b] of byKey) {
      if ((!hubs.has(b.a) && !hubs.has(b.b)) || b.kind === "batch") continue;
      byKey.delete(k);
      const own = b.relations.filter((r) => r.kind === b.kind);
      const ends = new Set((own.length ? own : b.relations).map((r) => lift(r.to)));
      for (const h of new Set([b.a, b.b])) if (hubs.has(h)) layered.push({ ...b, layer: h, into: ends.has(h) });
    }
    return {
      doors: [...doors.values()].map(({ id, anchor, side }) => ({ id, anchor, side })).sort((p, q) => p.id.localeCompare(q.id)),
      bundles: [...byKey.values()].sort((p, q) => p.key.localeCompare(q.key)),
      layered: layered.sort((p, q) => p.key.localeCompare(q.key) || p.layer.localeCompare(q.layer)),
      outward: [...out.values()].sort((p, q) => (p.item + p.other).localeCompare(q.item + q.other)),
    };
  }

  anchorFor(container: string, other: string): string {
    const shared = this.commonFloor(container, this.floorOf(other) ?? SITE);
    return this.liftTo(shared, other) ?? other;
  }

  landing(container: string, anchor: string): { floor: string; door: string } | undefined {
    if (!this.floor(anchor)) return undefined;
    let far: string | undefined;
    for (const o of this.bundles(container).outward) {
      if (this.anchorFor(container, o.other) !== anchor) continue;
      const f = this.floorOf(o.other) ?? SITE;
      const home = this.path(f).includes(anchor) ? f : anchor;
      far = far === undefined ? home : this.commonFloor(far, home);
    }
    if (far === undefined) return undefined;
    const down = this.path(far);
    for (let i = down.length - 1; i >= down.indexOf(anchor); i--) {
      const door = this.doorId(this.anchorFor(down[i], container));
      if (this.bundles(down[i]).doors.some((d) => d.id === door)) return { floor: down[i], door };
    }
    return undefined;
  }

  relationsOf(id: string): Relation[] {
    const inside = (x: string) => x === id || this.isInside(x, id);
    return this.map.relations.filter((r) => r.kind !== "uses-code" && (inside(r.from) || inside(r.to)));
  }

  isInside(id: string, container: string): boolean {
    let cur = this.nodes.get(id)?.parent ?? undefined;
    const g = this.groups.get(container);
    if (g) return g.members.some((m) => m === id || this.isInside(id, m));
    while (cur) {
      if (cur === container) return true;
      cur = this.nodes.get(cur)?.parent ?? undefined;
    }
    return false;
  }
}

const byCode = (model: Model, ids: string[]): string[] =>
  ids.sort((a, b) => (model.codes.get(a) ?? a).localeCompare(model.codes.get(b) ?? b, undefined, { numeric: true }));

/** Every method inside `id` (a package, file or class), in code order. */
export function methodsIn(model: Model, ref: Reference, id: string): string[] {
  return byCode(model, model.map.nodes.filter((n) => n.kind === "method" && ref.isInside(n.id, id)).map((n) => n.id));
}

function flowOf(b: Bundle, lift: (id: string) => string | undefined): Bundle["flow"] {
  let fwd = 0, back = 0;
  for (const r of b.relations) {
    const from = lift(r.from), to = lift(r.to);
    const d = r.data ?? (r.kind === "db-read" ? "back" : r.kind === "stream" ? "both" : "forward");
    if (d === "both") { fwd++; back++; continue; }
    const [up] = d === "back" ? [to, from] : [from, to];
    if (up === b.a) fwd++; else back++;
  }
  return fwd && back ? "both" : fwd ? "a→b" : "b→a";
}
