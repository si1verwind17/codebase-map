// Turns a code-map into what one floor needs: its items, short codes, and one bundled line per pair.
import type { CodeMap, Floor, Group, MapNode, Relation, RelationKind } from "./types";
import type { LayerBundle } from "./layers";

export const SITE = "site";
export const RUNTIME: RelationKind[] = ["request", "event", "stream", "batch", "ext-call", "db-read", "db-write", "hand-off"];
/** Kinds drones fly: an event through a topic, a hand-off through an in-process queue. */
export const flies = (kind: string): boolean => kind === "event" || kind === "hand-off";

export class MapError extends Error {}

export interface Bundle {
  key: string;                 // "a|b" with a < b
  a: string;                   // item ids on this floor
  b: string;
  relations: Relation[];
  kinds: Partial<Record<RelationKind, number>>;
  inferred: number;
  /** dominant kind used for drawing: stream > event > hand-off > batch > request > ext-call > db-write > db-read > calls */
  kind: RelationKind;
  /** which way data moves between a and b */
  flow: "a→b" | "b→a" | "both";
}

/** What `Model.bundles` gives for a floor. */
export interface FloorBundles { bundles: Bundle[]; outward: Outward[]; doors: Door[]; layered: LayerBundle[] }

export interface Outward {
  item: string;                // item on this floor
  other: string;               // node outside this floor
  relations: Relation[];
}

const DOOR = "door:";
/** The item a box stands for: a door's anchor (`door:<anchor>`, see `Model.doorId`), else the id itself. */
export const doorAnchor = (id: string): string => (id.startsWith(DOOR) ? id.slice(DOOR.length) : id);

/** A door on the floor's frame: where lines to and from the rest of the system leave this floor. */
export interface Door {
  id: string;                  // "door:<anchor>"
  anchor: string;              // the outside item it leads to (on the deepest floor both share)
  side: "in" | "out";          // in: data arrives through it (left edge); out: data leaves (right edge)
}

/** Relation kinds in the order a line is drawn by: a bundle takes the first kind it carries. */
export const DRAW_ORDER: readonly RelationKind[] = ["stream", "event", "hand-off", "batch", "request", "ext-call", "db-write", "db-read", "calls", "uses-code"];

export class Model {
  readonly map: CodeMap;
  readonly nodes = new Map<string, MapNode>();
  readonly groups = new Map<string, Group & { container: string }>();
  readonly codes = new Map<string, string>();
  private memberOf = new Map<string, string>();
  private twinHome = new Map<string, string>();   // "twin:<pkg>" -> the service floor that shows it
  private implementers = new Map<string, string[]>();   // trait/class id -> ids of the classes that implement it
  private landings = new Map<string, { floor: string; door: string } | undefined>();   // "<container>|<anchor>" -> doorLanding

  constructor(map: CodeMap) {
    if (!map || typeof map !== "object" || !map.meta) throw new MapError("This file is not a code map.");
    const v = map.meta.schema_version;
    if (typeof v === "number" && v > 3)
      throw new MapError(`This map uses format version ${v}, newer than this viewer (version 3). Open it with the viewer from the same skill version.`);
    if (v !== 2 && v !== 3)
      throw new MapError(`This map uses format version ${v}; rescan the repository with the current skill to get version 3.`);
    if (!map.layout?.containers || !Array.isArray(map.nodes) || !Array.isArray(map.relations))
      throw new MapError("This map is missing parts (nodes, relations or layout); rescan the repository.");
    this.map = map;
    for (const n of map.nodes) {
      this.nodes.set(n.id, n);
      for (const t of n.twins ?? []) this.twinHome.set(`twin:${t}`, n.id);
      for (const t of n.implements ?? []) this.implementers.set(t, [...(this.implementers.get(t) ?? []), n.id]);
    }
    for (const list of this.implementers.values()) list.sort();
    for (const [cid, floor] of Object.entries(map.layout.containers))
      for (const g of floor.groups ?? []) {
        this.groups.set(g.id, { ...g, container: cid });
        for (const m of g.members) this.memberOf.set(m, g.id);
      }
    this.assignCodes();
  }

  floor(container: string): Floor | undefined {
    return this.map.layout.containers[container];
  }

  /** The real package a twin stands for (a module two services deploy), or undefined. */
  twinOf(id: string): string | undefined {
    return this.twinHome.has(id) ? id.slice(5) : undefined;
  }

  label(id: string): string {
    if (id.startsWith(DOOR)) return this.label(doorAnchor(id));   // a door is named after where it leads
    const twin = this.twinOf(id);
    if (twin) return this.label(twin);
    return this.nodes.get(id)?.name ?? this.groups.get(id)?.label ?? id;
  }

  /** The name an item shows wherever it stands for itself (box, floor list, inspector, search, name tag): on one floor
   *  no two items show the same name. An implementation reads as one (`BillingService.Live`, `DeadLetters.live (impl)`);
   *  a companion `X$` adds ` (object)` only beside `X`; overloads add their arity (`run/2`); any other clash adds the
   *  shortest run of parent segments that tells them apart. Never cut. `label` stays the map's own name. */
  itemName(id: string): string {
    if (id.startsWith(DOOR)) return this.itemName(doorAnchor(id));
    this.floorNames ??= this.uniqueNames();
    return this.floorNames.get(id) ?? this.baseName(id);
  }
  private floorNames?: Map<string, string>;

  /** An item's own name, before any floor clash: implementations qualified by the class that holds them. */
  baseName(id: string): string {
    const twin = this.twinOf(id);
    if (twin) return this.baseName(twin);
    const n = this.nodes.get(id);
    if (!n) return this.label(id);
    const owner = n.parent ? this.nodes.get(n.parent) : undefined;
    const ownerName = owner?.kind === "class" ? owner.name : "";
    const anon = /\.([^.#/]+)\$impl$/.exec(id);   // `<owner>.<val>$impl`: an anonymous implementation
    if (anon) return `${ownerName || (lastSegments(id, 1) ?? "")}.${anon[1]} (impl)`.replace(/^\./, "");
    if (n.implements?.length && ownerName) return `${ownerName}.${n.name}`;
    return n.name;
  }

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

  kindOf(id: string): string {
    const twin = this.twinOf(id);
    if (twin) return this.kindOf(twin);
    return this.nodes.get(id)?.kind ?? (this.groups.has(id) ? "group" : "unknown");
  }

  /** Containers from the site down to `container` (inclusive), via groups where they apply. */
  path(container: string): string[] {
    const out: string[] = [];
    let cur: string | undefined = container;
    while (cur && cur !== SITE) {
      out.unshift(cur);
      const g = this.groups.get(cur);
      cur = g ? g.container : this.memberOf.get(cur) ?? this.nodes.get(cur)?.parent ?? SITE;
    }
    return [SITE, ...out];
  }

  /** The container whose floor shows `id` as an item (deepest). */
  floorOf(id: string): string | undefined {
    const home = this.twinHome.get(id);
    if (home) return home;
    const group = this.groups.get(id);
    if (group) return group.container;
    const g = this.memberOf.get(id);
    if (g) return g;
    const n = this.nodes.get(id);
    if (!n) return undefined;
    if (!n.parent) return SITE;
    return n.parent;
  }

  /** Map any node to the item that stands for it on `container`'s floor, or undefined if it is outside. */
  liftTo(container: string, id: string): string | undefined {
    const floor = this.floor(container);
    if (!floor) return undefined;
    const onSite = container === SITE;
    if (onSite && (floor.utilities ?? []).includes(id)) return undefined;
    for (const step of this.liftChain(id, onSite)) {
      // own keys only, as relationsNear lists them: an id like `constructor` is no item
      if (Object.hasOwn(floor.items, step.id)) return step.id;
      if (step.group && Object.hasOwn(floor.items, step.group)) return step.group;
    }
    return undefined;
  }

  /** The walk `liftTo` makes up from `id`, the same on every floor: each id on the way and the group it is a member of.
   *  Only the site floor differs, for a table with no datastore (it stops there). Kept per id. */
  private liftChain(id: string, onSite: boolean): readonly { id: string; group?: string }[] {
    let chain = this.chains.get(id);
    if (chain && onSite) {
      // the same walk, cut after a table with no datastore: on the site floor it goes no further
      const end = chain.findIndex((s) => { const n = this.nodes.get(s.id); return n?.kind === "table" && !n.parent; });
      return end < 0 || end === chain.length - 1 ? chain : chain.slice(0, end + 1);
    }
    if (chain) return chain;
    const steps: { id: string; group?: string }[] = [];
    let cur: string | undefined = id;
    const seen = new Set<string>();
    while (cur && !seen.has(cur)) {
      seen.add(cur);
      const viaGroup = this.memberOf.get(cur);
      steps.push(viaGroup ? { id: cur, group: viaGroup } : { id: cur });
      const n = this.nodes.get(cur);
      cur = n?.parent ?? (viaGroup ? this.groups.get(viaGroup)?.container : undefined);
    }
    this.chains.set(id, steps);
    return this.liftChain(id, onSite);
  }
  private chains = new Map<string, readonly { id: string; group?: string }[]>();   // id -> its walk off the site floor

  /** One bundle per pair of items on this floor, plus relations leaving the floor. `layered`: the lines kept out of
   *  the base layer (spec §15), each tagged with the extra layer that draws it (a line in two layers is listed once per
   *  layer, so count or collect its key once); `bundles` never holds them. Worked out once per floor and code-links
   *  flag (the map never changes under a Model) and shared: callers must not mutate the result. */
  bundles(container: string, opts: { codeLinks?: boolean } = {}): FloorBundles {
    const k = `${container}|${opts.codeLinks ? 1 : 0}`;
    let b = this.floorBundles.get(k);
    if (!b) this.floorBundles.set(k, (b = this.bundlesOf(container, !!opts.codeLinks)));
    return b;
  }
  private floorBundles = new Map<string, FloorBundles>();

  private bundlesOf(container: string, codeLinks: boolean): FloorBundles {
    const onSite = container === SITE;
    if (this.nodes.get(container)?.kind === "datastore")   // a warehouse is shelves: access is on each table
      return { bundles: [], outward: [], doors: [], layered: [] };
    const wanted = (k: RelationKind) =>
      RUNTIME.includes(k) || (k === "calls" && !onSite) || (k === "uses-code" && codeLinks);
    const byKey = new Map<string, Bundle>();
    const out = new Map<string, Outward>();
    for (const r of this.relationsNear(container)) {
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
    // a line touching a heavily used item (floor.hubs: the scanner's fan-in >= 8 items) stays out of the base layer:
    // it goes into that item's extra layer, shown on demand; a line between two such items is in both their layers (a
    // layer holds every line into and out of its item), one entry per layer with the same key. A batch line stays in
    // the base: a rail runs from a rail yard to a station, and only the base plans those (a layer's batch line would be
    // a rail with neither).
    const hubs = new Set(this.floor(container)?.hubs ?? []);
    const layered: LayerBundle[] = [];
    for (const [k, b] of byKey) {
      if ((!hubs.has(b.a) && !hubs.has(b.b)) || b.kind === "batch") continue;
      byKey.delete(k);
      // into an item when a relation of the kind the line is drawn as ends on it (a request from the hub beside a call
      // into it is a line from it); `kind` is the first DRAW_ORDER kind the bundle carries, so some relation always
      // matches; were none to, every relation would decide. Per layer: the same line runs into one item, out of the other
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

  /** The relations with an end that may lift to an item on `container`'s floor, in map order: those with an item of
   *  the floor on an end's lift chain (as an id or its group); on the site floor, all of them. The rest lift to nothing
   *  there, so `bundles` skips them. */
  private relationsNear(container: string): readonly Relation[] {
    const rels = this.map.relations;
    if (container === SITE) return rels;
    if (!this.relsByChain) {
      this.relsByChain = new Map();
      rels.forEach((r, i) => {
        for (const end of [r.from, r.to])
          for (const step of this.liftChain(end, false))
            for (const k of step.group ? [step.id, step.group] : [step.id]) {
              const list = this.relsByChain!.get(k);
              if (!list) this.relsByChain!.set(k, [i]);
              else if (list[list.length - 1] !== i) list.push(i);
            }
      });
    }
    const near = new Set<number>();
    for (const item of Object.keys(this.floor(container)?.items ?? {})) for (const i of this.relsByChain.get(item) ?? []) near.add(i);
    return [...near].sort((a, b) => a - b).map((i) => rels[i]);
  }
  private relsByChain?: Map<string, number[]>;

  /** The deepest floor both `container` and `other` sit on, and the item standing for `other` there. */
  commonFloor(container: string, otherFloor: string): string {
    const here = this.path(container), there = this.path(otherFloor);
    let i = 0;
    while (i < here.length && i < there.length && here[i] === there[i]) i++;
    return here[Math.max(0, i - 1)];
  }

  /** A datastore keeps its own id inside buildings (it is drawn as the same warehouse on its lane);
   *  anything else outside the floor is reached through a door on the frame. */
  doorId(anchor: string): string {
    return this.nodes.get(anchor)?.kind === "datastore" ? anchor : `${DOOR}${anchor}`;
  }

  anchorFor(container: string, other: string): string {
    const shared = this.commonFloor(container, this.floorOf(other) ?? SITE);
    return this.liftTo(shared, other) ?? other;
  }

  /** Where the door to `anchor` on `container`'s floor leads: the door back on the far side, on the deepest floor inside
   *  `anchor` that still shows it, on the way down to the far ends of the relations through the door (an end that is
   *  `anchor` itself, a job its service runs, is drawn on `anchor`'s own floor). Undefined when `anchor` has no floor
   *  showing a door back: the door then leads to `anchor` on the floor both share. */
  doorLanding(container: string, anchor: string): { floor: string; door: string } | undefined {
    const k = `${container}|${anchor}`;
    if (!this.landings.has(k)) this.landings.set(k, this.landing(container, anchor));
    return this.landings.get(k);
  }

  /** What the door to `anchor` on `container`'s floor is named after: the building its double-click opens (the floor
   *  doorLanding finds), else `anchor`. */
  doorShows(container: string, anchor: string): string {
    return this.doorLanding(container, anchor)?.floor ?? anchor;
  }

  private landing(container: string, anchor: string): { floor: string; door: string } | undefined {
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

  /** Which services write and read a table, as short codes (S1 S4), for the warehouse shelves. */
  tableAccess(table: string): { writers: string[]; readers: string[] } {
    const writers = new Set<string>(), readers = new Set<string>();
    for (const r of this.map.relations) {
      if (r.to !== table || (r.kind !== "db-write" && r.kind !== "db-read")) continue;
      const who = this.liftTo(SITE, r.from);
      if (who) (r.kind === "db-write" ? writers : readers).add(this.codes.get(who) ?? who);
    }
    const sort = (s: Set<string>) => [...s].sort((p, q) => p.localeCompare(q, undefined, { numeric: true }));
    return { writers: sort(writers), readers: sort(readers) };
  }

  /** Utilities (shared externals) each item on the site floor calls: drawn as badges. */
  badges(container: string): Map<string, string[]> {
    const res = new Map<string, string[]>();
    if (container !== SITE) return res;
    const utilities = new Set(this.floor(SITE)?.utilities ?? []);
    for (const r of this.map.relations) {
      if (!utilities.has(r.to)) continue;
      const from = this.liftTo(SITE, r.from);
      if (!from) continue;
      const list = res.get(from) ?? [];
      if (!list.includes(r.to)) list.push(r.to);
      res.set(from, list.sort());
    }
    return res;
  }

  /** The utility the legend shows as its example: the one most site items carry a tab for; null when no tab is drawn. */
  legendUtility(): { id: string; code: string; label: string } | null {
    const uses = new Map<string, number>();
    for (const list of this.badges(SITE).values()) for (const u of list) uses.set(u, (uses.get(u) ?? 0) + 1);
    const best = [...uses.entries()].filter(([u]) => this.codes.has(u)).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0];
    return best ? { id: best[0], code: this.codes.get(best[0])!, label: this.label(best[0]) } : null;
  }

  /** The classes that implement trait (or class) `id`, as node ids. */
  implementersOf(id: string): string[] {
    return this.implementers.get(id) ?? [];
  }

  /** What `id` implements: the trait (or class) ids it names in `implements`. */
  implementedBy(id: string): string[] {
    return [...(this.nodes.get(id)?.implements ?? [])].filter((t) => this.nodes.has(t)).sort();
  }

  /** Trait → implementation links lifted to this floor's items: one per pair of distinct items, sorted by key. */
  implementLinks(container: string): { key: string; trait: string; impl: string }[] {
    const out = new Map<string, { key: string; trait: string; impl: string }>();
    for (const [t, impls] of this.implementers) {
      const trait = this.liftTo(container, t);
      if (!trait) continue;
      for (const i of impls) {
        const impl = this.liftTo(container, i);
        if (!impl || impl === trait) continue;
        const key = `${trait}|${impl}`;
        if (!out.has(key)) out.set(key, { key, trait, impl });
      }
    }
    return [...out.values()].sort((p, q) => p.key.localeCompare(q.key));
  }

  /** The item on `container` holding the implementation of the trait `id` stands in (`id` itself or its nearest
   *  enclosing class, e.g. a trait method). Only when that trait has exactly one implementer whose lifted item
   *  exists on this floor (two implementers in one companion still count as two), and that item is not `id`'s own. */
  implementerOn(container: string, id: string): string | undefined {
    let cur: string | undefined = id;
    while (cur && !this.implementers.has(cur)) cur = this.nodes.get(cur)?.parent ?? undefined;
    if (!cur) return undefined;
    const lifted = this.implementersOf(cur).map((i) => this.liftTo(container, i)).filter((x): x is string => !!x);
    if (lifted.length !== 1) return undefined;
    const here = this.liftTo(container, id);
    return here && lifted[0] !== here ? lifted[0] : undefined;
  }

  private drawsImpl: boolean | undefined;
  /** Whether some floor draws a dotted implements link (the legend's entry shows only then). Computed once. */
  drawsImplements(): boolean {
    return (this.drawsImpl ??= this.implementers.size > 0 && Object.keys(this.map.layout.containers).some((c) => this.implementLinks(c).length > 0));
  }

  /** The relations (no code links) with an end that is `id` or inside it, in map order. */
  relationsOf(id: string): Relation[] {
    if (!this.relsByOwner) {
      this.relsByOwner = new Map();
      for (const r of this.map.relations) {
        if (r.kind === "uses-code") continue;
        const owners = new Set([r.from, ...this.insideOf(r.from), r.to, ...this.insideOf(r.to)]);
        for (const o of owners) {
          const list = this.relsByOwner.get(o);
          if (list) list.push(r); else this.relsByOwner.set(o, [r]);
        }
      }
    }
    return [...(this.relsByOwner.get(id) ?? [])];
  }
  private relsByOwner?: Map<string, Relation[]>;   // id -> the relations relationsOf gives it

  /** Whether `id` is inside `container`: below it in the parent chain, or (a floor group) a member of it, inside a
   *  member, or inside a group that is one. */
  isInside(id: string, container: string): boolean {
    return this.insideOf(id).has(container);
  }

  /** Everything `id` is inside: its parent chain, and the floor groups whose members hold it or one of those (a group
   *  in a group: both). From the groups' own members, as one id can be listed by groups on two floors. Kept per id. */
  private insideOf(id: string): ReadonlySet<string> {
    let set = this.inside.get(id);
    if (set) return set;
    if (!this.holders) {
      this.holders = new Map();
      for (const g of this.groups.values())
        for (const m of g.members) { const h = this.holders.get(m); if (h) h.push(g.id); else this.holders.set(m, [g.id]); }
    }
    const s = new Set<string>();
    let cur = this.nodes.get(id)?.parent ?? undefined;
    while (cur && !s.has(cur)) { s.add(cur); cur = this.nodes.get(cur)?.parent ?? undefined; }
    // a parent that is also a group's id counts only as that group (isInside asks a group's members)
    for (const a of s) if (this.groups.has(a)) s.delete(a);
    const queue = [id, ...s];
    for (let i = 0; i < queue.length; i++)
      for (const g of this.holders.get(queue[i]) ?? [])
        if (!s.has(g)) { s.add(g); queue.push(g); }
    this.inside.set(id, (set = s));
    return set;
  }
  private inside = new Map<string, ReadonlySet<string>>();
  private holders?: Map<string, string[]>;   // member id -> the groups that list it

  /** Every id `x` with `isInside(x, id)`: the nodes below it, and for a floor group its members and what is inside
   *  them. Unordered. */
  descendants(id: string): string[] {
    const out = new Set<string>(), walked = new Set<string>();
    // a group holds its members; anything else (even an id a group also has) holds its child nodes, all the way down
    const below = (x: string) => {
      if (walked.has(x)) return;
      walked.add(x);
      for (const c of this.children.get(x) ?? []) { out.add(c); below(c); }
    };
    const inGroup = (g: string, seen = new Set<string>()) => {
      if (seen.has(g)) return;
      seen.add(g);
      for (const m of this.groups.get(g)!.members) { out.add(m); if (this.groups.has(m)) inGroup(m, seen); else below(m); }
    };
    if (this.groups.has(id)) inGroup(id); else below(id);
    return [...out];
  }
  private children = new Map<string, string[]>();   // parent id -> its child nodes' ids (assignCodes)

  /** Short codes: S1, S1·P2, S1·P2·C3·M4 … stable for a given set of ids (sorted). */
  private assignCodes() {
    const prefix: Record<string, string> = {
      service: "S", library: "L", datastore: "D", external: "X", topic: "T", "in-process-queue": "Q",
      package: "P", class: "C", file: "F", method: "M", table: "T",
    };
    const kids = new Map<string, MapNode[]>();
    const roots: MapNode[] = [];
    for (const n of this.map.nodes) {
      if (n.parent) { const c = this.children.get(n.parent); if (c) c.push(n.id); else this.children.set(n.parent, [n.id]); }
      if (n.parent && this.nodes.has(n.parent)) kids.set(n.parent, [...(kids.get(n.parent) ?? []), n]);
      else roots.push(n);
    }
    const walk = (list: MapNode[], base: string) => {
      const counters: Record<string, number> = {};
      for (const n of [...list].sort((a, b) => a.id.localeCompare(b.id))) {
        const p = prefix[n.kind] ?? "N";
        counters[p] = (counters[p] ?? 0) + 1;
        const code = base ? `${base}·${p}${counters[p]}` : `${p}${counters[p]}`;
        this.codes.set(n.id, code);
        walk(kids.get(n.id) ?? [], code);
      }
    };
    walk(roots, "");
    for (const [gid, g] of this.groups) {
      const base = this.codes.get(g.container) ?? "";
      const idx = [...this.groups.values()].filter((x) => x.container === g.container).findIndex((x) => x.id === gid) + 1;
      this.codes.set(gid, base ? `${base}·G${idx}` : `G${idx}`);
    }
    for (const [tid] of this.twinHome) this.codes.set(tid, this.codes.get(tid.slice(5)) ?? "");   // a twin wears its original's code
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

/** The last `k` segments of the path that holds `id` (`svc::a.b.C` → `a.b` for k = 2; a method's holder is its class),
 *  without companion `$`s; undefined when there are none. */
function lastSegments(id: string, k: number): string | undefined {
  const q = id.includes("::") ? id.slice(id.indexOf("::") + 2) : id;
  const hash = q.indexOf("#");
  const segs = (hash >= 0 ? q.slice(0, hash) : q).split(/[./]/).filter(Boolean).map((s) => s.replace(/\$+$/, ""));
  const holder = hash >= 0 ? segs : segs.slice(0, -1);
  return holder.length ? holder.slice(-k).join(".") : undefined;
}

function flowOf(b: Bundle, lift: (id: string) => string | undefined): Bundle["flow"] {
  let fwd = 0, back = 0;
  for (const r of b.relations) {
    const from = lift(r.from), to = lift(r.to);
    // direction.py's defaults, for a map assembled without them
    const d = r.data ?? (r.kind === "db-read" ? "back" : r.kind === "stream" ? "both" : "forward");
    if (d === "both") { fwd++; back++; continue; }
    const [up] = d === "back" ? [to, from] : [from, to];
    if (up === b.a) fwd++; else back++;
  }
  return fwd && back ? "both" : fwd ? "a→b" : "b→a";
}
