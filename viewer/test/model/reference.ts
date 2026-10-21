// The Model's walks as they were before its caches and indexes (commit 694efe3; names and search: 657fd48), copied
// verbatim as the reference the cached ones must equal (model_cache.test.ts). `this` is a Reference: its own copies of the walks, and the Model's
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

  // names and search as they were before names on demand and the search index (commit 657fd48)
  private twinOf(id: string): string | undefined { return this.m.twinOf(id); }
  private baseName(id: string): string { return this.m.baseName(id); }
  private get codes(): Map<string, string> { return this.m.codes; }

  itemName(id: string): string {
    if (id.startsWith("door:")) return this.itemName(id.slice("door:".length));
    this.floorNames ??= this.uniqueNames();
    return this.floorNames.get(id) ?? this.baseName(id);
  }
  private floorNames?: Map<string, string>;

  private uniqueNames(): Map<string, string> {
    const out = new Map<string, string>();
    for (const c of Object.keys(this.map.layout.containers).sort()) {
      const items = Object.keys(this.map.layout.containers[c].items ?? {}).sort();
      const name = new Map(items.map((id) => [id, this.baseName(id)]));
      const clashes = () => {
        const by = new Map<string, string[]>();
        for (const [id, n] of name) by.set(n, [...(by.get(n) ?? []), id]);
        return [...by.values()].filter((ids) => ids.length > 1);
      };
      // a companion object beside its class or trait
      for (const ids of clashes())
        for (const id of ids) if (id.endsWith("$") && ids.includes(id.slice(0, -1))) name.set(id, `${name.get(id)} (object)`);
      // overloads: the arity (and the scanner's own tie-break) from the id
      for (const ids of clashes())
        for (const id of ids) { const sig = /#([^#]+\/[^#/]+)$/.exec(this.twinOf(id) ?? id)?.[1]; if (sig) name.set(id, sig); }
      // anything else: the fewest parent segments that tell the clashing items apart
      for (const ids of clashes()) {
        const base = new Map(ids.map((id) => [id, name.get(id)!]));
        for (let k = 1; k <= 12; k++) {
          const cand = ids.map((id) => { const p = lastSegments(this.twinOf(id) ?? id, k); return p ? `${p}.${base.get(id)}` : base.get(id)!; });
          if (new Set(cand).size === ids.length || k === 12) { ids.forEach((id, i) => name.set(id, cand[i])); break; }
        }
      }
      for (const ids of clashes()) for (const id of ids) name.set(id, `${name.get(id)} (${this.codes.get(id) ?? id})`);   // last resort
      for (const [id, n] of name) if (!out.has(id)) out.set(id, n);
    }
    return out;
  }

  search(text: string, limit = 30): string[] {
    const t = text.trim().toLowerCase();
    if (!t) return [];
    const hits: [number, string][] = [];
    for (const n of this.map.nodes) {
      const code = (this.codes.get(n.id) ?? "").toLowerCase();
      const names = [n.name.toLowerCase(), this.itemName(n.id).toLowerCase()];   // the map's name and the one the floor shows
      const score = code === t ? 0 : names.some((x) => x === t) ? 1 : names.some((x) => x.startsWith(t)) ? 2 : names.some((x) => x.includes(t)) ? 3 : n.id.toLowerCase().includes(t) ? 4 : -1;
      if (score >= 0) hits.push([score, n.id]);
    }
    return hits.sort((a, b) => a[0] - b[0] || a[1].localeCompare(b[1])).slice(0, limit).map((h) => h[1]);
  }
}

function lastSegments(id: string, k: number): string | undefined {
  const q = id.includes("::") ? id.slice(id.indexOf("::") + 2) : id;
  const hash = q.indexOf("#");
  const segs = (hash >= 0 ? q.slice(0, hash) : q).split(/[./]/).filter(Boolean).map((s) => s.replace(/\$+$/, ""));
  const holder = hash >= 0 ? segs : segs.slice(0, -1);
  return holder.length ? holder.slice(-k).join(".") : undefined;
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
