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
/** `localeCompare(…, undefined, { numeric: true })` made once: the same order (numeric runs as numbers), without a
 *  collator per comparison. Every code-order sort shares it. */
export const numericCollator = new Intl.Collator(undefined, { numeric: true });

export const DRAW_ORDER: readonly RelationKind[] = ["stream", "event", "hand-off", "batch", "request", "ext-call", "db-write", "db-read", "calls", "uses-code"];

export class Model {
  readonly map: CodeMap;
  readonly nodes = new Map<string, MapNode>();
  readonly groups = new Map<string, Group & { container: string }>();
  readonly codes = new Map<string, string>();
  private memberOf = new Map<string, string>();
  private twinHome = new Map<string, string>();   // "twin:<pkg>" -> the service that deploys it
  private twinnedBy = new Map<string, string[]>();   // <pkg> -> the services that also deploy it as a twin, in map order
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
      for (const t of n.twins ?? []) { this.twinHome.set(`twin:${t}`, n.id); this.twinnedBy.set(t, [...(this.twinnedBy.get(t) ?? []), n.id]); }
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

  /** How many nodes have `id` as their parent. */
  childCount(id: string): number {
    return this.children.get(id)?.length ?? 0;
  }

  /** The real package a twin stands for (a module two services deploy), or undefined. */
  twinOf(id: string): string | undefined {
    return this.twinHome.has(id) ? id.slice(5) : undefined;
  }

  /** The service that deploys twin `id` (its floor shows the twin, or a module box holding it), or undefined. */
  twinHost(id: string): string | undefined {
    return this.twinHome.get(id);
  }

  /** On a module box (a `module` group of twins): the service that also deploys the module and the one its code sits
   *  under; undefined on anything else. */
  twinModule(id: string): { host: string; home: string } | undefined {
    const g = this.groups.get(id);
    const t = g?.kind === "module" ? g.members.find((m) => this.twinHome.has(m)) : undefined;
    if (!t) return undefined;
    return { host: this.twinHome.get(t)!, home: this.path(this.floorOf(t.slice(5)) ?? SITE)[1] };
  }

  /** The services that also deploy package `id` as a twin (its code sits elsewhere), in map order; [] for none. */
  twinDeployers(id: string): string[] {
    return this.twinnedBy.get(id) ?? [];
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
    const c = this.homeFloor(id);
    return c === undefined ? this.baseName(id) : this.namesOn(c).get(id)!;
  }

  /** The floor whose names an item wears: the first, in sorted order, that lists it. Found without naming anything, so
   *  a name asks for one floor's clash rules, not every floor's. */
  private homeFloor(id: string): string | undefined {
    if (!this.firstFloor) {
      this.firstFloor = new Map();
      for (const c of Object.keys(this.map.layout.containers).sort())
        for (const item of Object.keys(this.map.layout.containers[c].items ?? {}))
          if (!this.firstFloor.has(item)) this.firstFloor.set(item, c);
    }
    return this.firstFloor.get(id);
  }
  private firstFloor?: Map<string, string>;   // item id -> the first container in sorted order listing it

  /** Each item's name on one floor, clashes told apart (rules on `itemName`); worked out once per floor. */
  private namesOn(c: string): Map<string, string> {
    let name = this.floorNames.get(c);
    if (name) return name;
    const items = Object.keys(this.map.layout.containers[c].items ?? {}).sort();
    name = new Map(items.map((id) => [id, this.baseName(id)]));
    const clashes = () => {
      const by = new Map<string, string[]>();
      for (const [id, n] of name!) by.set(n, [...(by.get(n) ?? []), id]);
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
        if (new Set(cand).size === ids.length || k === 12) { ids.forEach((id, i) => name!.set(id, cand[i])); break; }
      }
    }
    for (const ids of clashes()) for (const id of ids) name.set(id, `${name.get(id)} (${this.codes.get(id) ?? id})`);   // last resort
    this.floorNames.set(c, name);
    return name;
  }
  private floorNames = new Map<string, Map<string, string>>();   // container -> its items' names

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

  kindOf(id: string): string {
    const twin = this.twinOf(id);
    if (twin) return this.kindOf(twin);
    return this.nodes.get(id)?.kind ?? (this.groups.has(id) ? "group" : "unknown");
  }

  /** Containers from the site down to `container` (inclusive), via groups where they apply. Kept per container and
   *  shared: callers must not mutate it. */
  path(container: string): readonly string[] {
    let p = this.paths.get(container);
    if (p) return p;
    const out: string[] = [];
    let cur: string | undefined = container;
    while (cur && cur !== SITE) {
      out.unshift(cur);
      const g = this.groups.get(cur);
      cur = g ? g.container : this.memberOf.get(cur) ?? this.nodes.get(cur)?.parent ?? SITE;
    }
    this.paths.set(container, (p = [SITE, ...out]));
    return p;
  }
  private paths = new Map<string, readonly string[]>();

  /** The container whose floor shows `id` as an item (deepest). */
  floorOf(id: string): string | undefined {
    const g = this.memberOf.get(id);   // first: a twin may sit in a module box on its service's floor
    if (g) return g;
    const home = this.twinHome.get(id);
    if (home) return home;
    const group = this.groups.get(id);
    if (group) return group.container;
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
   *  the base layer, each tagged with the extra layer that draws it (a line in two layers is listed once per
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
    const seen = new Map<string, string | undefined>();   // each end lifted once: the same far end recurs across relations
    const liftHere = (id: string) => {
      if (seen.has(id)) return seen.get(id);
      const item = this.liftTo(container, id);
      seen.set(id, item);
      return item;
    };
    for (const r of this.relationsNear(container)) {
      if (!wanted(r.kind)) continue;
      const a = liftHere(r.from);
      const b = liftHere(r.to);
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
        this.anchors.set(o, anchor);
        const id = this.doorId(anchor);
        for (const r of o.relations) {
          const upstream = r.data === "back" ? r.to : r.from;      // `both` keeps the caller first
          const leaves = liftHere(upstream) === o.item;
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
    const lift = (id: string) => liftHere(id) ?? (onSite ? undefined : this.doorId(this.anchorFor(container, id)));
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

  /** The relations that may show on `container`'s floor, in map order: those with an item of the floor on one end's
   *  lift chain (as an id or its group) and not on the other's; on the site floor, all of them. A relation whose two
   *  chains share the item lifts to it at both ends and draws nothing there; the rest lift to nothing there. */
  private relationsNear(container: string): readonly Relation[] {
    const rels = this.map.relations;
    if (container === SITE) return rels;
    this.prepare();   // no deadline: whatever is left of the index is built in this task, the floor is wanted now
    const index = this.relsByChain!, near = new Set<number>();
    for (const item of Object.keys(this.floor(container)?.items ?? {})) for (const i of index.get(item) ?? []) near.add(i);
    return [...near].sort((a, b) => a - b).map((i) => rels[i]);
  }
  private relsByChain?: Map<string, number[]>;

  /** Builds the index `relationsNear` reads, a slice at a time while `deadline` has time left (at least one chunk per
   *  call), so the viewer can build it in idle time before any floor needs it; with no deadline, all of it. True while
   *  some is left. Chain keys are small numbers, each end's worked out once, so two ends' keys compare as numbers. */
  prepare(deadline?: { timeRemaining(): number }): boolean {
    if (this.relsByChain) return false;
    const rels = this.map.relations;
    const b = (this.nearBuild ??= { next: 0, num: new Map<string, number>(), lists: [] as number[][], keysOf: new Map<string, number[]>() });
    const keys = (end: string) => {
      let k = b.keysOf.get(end);
      if (k) return k;
      k = [];
      for (const s of this.liftChain(end, false))
        for (const id of s.group ? [s.id, s.group] : [s.id]) {
          let n = b.num.get(id);
          if (n === undefined) { b.num.set(id, (n = b.lists.length)); b.lists.push([]); }
          k.push(n);
        }
      b.keysOf.set(end, k);
      return k;
    };
    const add = (k: number, i: number) => { const list = b.lists[k]; if (list[list.length - 1] !== i) list.push(i); };
    do {
      for (const end = Math.min(rels.length, b.next + 64); b.next < end; b.next++) {
        const r = rels[b.next], x = keys(r.from), y = keys(r.to);
        for (const k of x) if (!y.includes(k)) add(k, b.next);
        for (const k of y) if (!x.includes(k)) add(k, b.next);
      }
    } while (b.next < rels.length && (!deadline || deadline.timeRemaining() > 0));
    if (b.next < rels.length) return true;
    this.relsByChain = new Map([...b.num].filter(([, n]) => b.lists[n].length).map(([id, n]) => [id, b.lists[n]]));
    this.nearBuild = undefined;
    return false;
  }
  private nearBuild?: { next: number; num: Map<string, number>; lists: number[][]; keysOf: Map<string, number[]> };

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

  /** The relations leaving `container`'s floor through the door to `anchor`, each floor's grouped once. */
  private outwardTo(container: string, anchor: string): readonly Outward[] {
    let by = this.outwardByAnchor.get(container);
    if (!by) {
      by = new Map();
      for (const o of this.bundles(container).outward) {
        const a = this.anchors.get(o) ?? this.anchorFor(container, o.other);   // the site floor has no doors to name them
        const list = by.get(a);
        if (list) list.push(o); else by.set(a, [o]);
      }
      this.outwardByAnchor.set(container, by);
    }
    return by.get(anchor) ?? [];
  }
  private anchors = new WeakMap<Outward, string>();   // a relation group leaving a floor -> the anchor of its door
  private outwardByAnchor = new Map<string, Map<string, Outward[]>>();   // container -> anchor -> what leaves through it

  private landing(container: string, anchor: string): { floor: string; door: string } | undefined {
    if (!this.floor(anchor)) return undefined;
    let far: string | undefined;
    for (const o of this.outwardTo(container, anchor)) {
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
    const sort = (s: Set<string>) => [...s].sort(numericCollator.compare);
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

  /** The relations (no code links) with an end that is `id` or inside it, in map order. Gathered from the ends inside
   *  `id`, so the cost follows its size, not the map's; the last few answers are kept. */
  relationsOf(id: string): Relation[] {
    const rels = this.map.relations;
    if (!this.relsByEnd) {
      const index = (this.relsByEnd = new Map<string, number[]>());
      rels.forEach((r, i) => {
        if (r.kind === "uses-code") return;
        for (const end of r.from === r.to ? [r.from] : [r.from, r.to]) {
          const list = index.get(end);
          if (list) list.push(i); else index.set(end, [i]);
        }
      });
    }
    let found = this.relsOfRecent.get(id);
    if (!found) {
      const hit = new Uint8Array(rels.length);
      for (const x of [id, ...this.descendants(id)]) for (const i of this.relsByEnd.get(x) ?? []) hit[i] = 1;
      found = rels.filter((_, i) => hit[i]);
      if (this.relsOfRecent.size >= 8) this.relsOfRecent.delete(this.relsOfRecent.keys().next().value!);
      this.relsOfRecent.set(id, found);
    }
    return [...found];
  }
  private relsByEnd?: Map<string, number[]>;   // node id -> indexes of the relations (no code links) with it at an end
  private relsOfRecent = new Map<string, Relation[]>();   // the last few relationsOf answers, oldest first

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
      if (n.parent && this.nodes.has(n.parent)) { const k = kids.get(n.parent); if (k) k.push(n); else kids.set(n.parent, [n]); }
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
    const groupsOn = new Map<string, number>();   // container -> its groups numbered so far, in map order
    for (const [gid, g] of this.groups) {
      const base = this.codes.get(g.container) ?? "";
      const idx = (groupsOn.get(g.container) ?? 0) + 1;
      groupsOn.set(g.container, idx);
      this.codes.set(gid, base ? `${base}·G${idx}` : `G${idx}`);
    }
    for (const [tid] of this.twinHome) this.codes.set(tid, this.codes.get(tid.slice(5)) ?? "");   // a twin wears its original's code
  }

  search(text: string, limit = 30): string[] {
    const t = text.trim().toLowerCase();
    if (!t) return [];
    const hits: [number, string][] = [];
    for (const r of this.searchRows()) {
      const score = r.code === t ? 0 : r.name === t || r.shown === t ? 1 : r.name.startsWith(t) || r.shown.startsWith(t) ? 2
        : r.name.includes(t) || r.shown.includes(t) ? 3 : r.idl.includes(t) ? 4 : -1;
      if (score >= 0) hits.push([score, r.id]);
    }
    return hits.sort((a, b) => a[0] - b[0] || a[1].localeCompare(b[1])).slice(0, limit).map((h) => h[1]);
  }

  /** Each node's code, map name, shown name (`itemName`) and id, lowercased once: built on the first search, so a map
   *  nobody searches never names every node. */
  private searchRows(): readonly { id: string; code: string; name: string; shown: string; idl: string }[] {
    return this.rows ??= this.map.nodes.map((n) => ({
      id: n.id, code: (this.codes.get(n.id) ?? "").toLowerCase(), name: n.name.toLowerCase(),
      shown: this.itemName(n.id).toLowerCase(), idl: n.id.toLowerCase(),
    }));
  }
  private rows?: readonly { id: string; code: string; name: string; shown: string; idl: string }[];
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
