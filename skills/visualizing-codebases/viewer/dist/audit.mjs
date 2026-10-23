// audit-inputs: 5aab1ff085d797eb6890439f5341df213feef044bf62fa95caefe40ec648a64a
import { readFileSync } from "node:fs";
// src/model/model.ts
var SITE = "site";
var RUNTIME = [
	"request",
	"event",
	"stream",
	"batch",
	"ext-call",
	"db-read",
	"db-write",
	"hand-off"
];
/** Kinds drones fly: an event through a topic, a hand-off through an in-process queue. */
var flies = (kind) => kind === "event" || kind === "hand-off";
var MapError = class extends Error {};
var DOOR = "door:";
/** The item a box stands for: a door's anchor (`door:<anchor>`, see `Model.doorId`), else the id itself. */
var doorAnchor = (id) => id.startsWith(DOOR) ? id.slice(5) : id;
/** Relation kinds in the order a line is drawn by: a bundle takes the first kind it carries. */
/** `localeCompare(…, undefined, { numeric: true })` made once: the same order (numeric runs as numbers), without a
*  collator per comparison. Every code-order sort shares it. */
var numericCollator = new Intl.Collator(void 0, { numeric: true });
var DRAW_ORDER = [
	"stream",
	"event",
	"hand-off",
	"batch",
	"request",
	"ext-call",
	"db-write",
	"db-read",
	"calls",
	"uses-code"
];
var Model = class {
	map;
	nodes = /* @__PURE__ */ new Map();
	groups = /* @__PURE__ */ new Map();
	codes = /* @__PURE__ */ new Map();
	memberOf = /* @__PURE__ */ new Map();
	twinHome = /* @__PURE__ */ new Map();
	twinnedBy = /* @__PURE__ */ new Map();
	implementers = /* @__PURE__ */ new Map();
	landings = /* @__PURE__ */ new Map();
	constructor(map) {
		if (!map || typeof map !== "object" || !map.meta) throw new MapError("This file is not a code map.");
		const v = map.meta.schema_version;
		if (typeof v === "number" && v > 3) throw new MapError(`This map uses format version ${v}, newer than this viewer (version 3). Open it with the viewer from the same skill version.`);
		if (v !== 2 && v !== 3) throw new MapError(`This map uses format version ${v}; rescan the repository with the current skill to get version 3.`);
		if (!map.layout?.containers || !Array.isArray(map.nodes) || !Array.isArray(map.relations)) throw new MapError("This map is missing parts (nodes, relations or layout); rescan the repository.");
		this.map = map;
		for (const n of map.nodes) {
			this.nodes.set(n.id, n);
			for (const t of n.twins ?? []) {
				this.twinHome.set(`twin:${t}`, n.id);
				this.twinnedBy.set(t, [...this.twinnedBy.get(t) ?? [], n.id]);
			}
			for (const t of n.implements ?? []) this.implementers.set(t, [...this.implementers.get(t) ?? [], n.id]);
		}
		for (const list of this.implementers.values()) list.sort();
		for (const [cid, floor] of Object.entries(map.layout.containers)) for (const g of floor.groups ?? []) {
			this.groups.set(g.id, {
				...g,
				container: cid
			});
			for (const m of g.members) this.memberOf.set(m, g.id);
		}
		this.assignCodes();
	}
	floor(container) {
		return this.map.layout.containers[container];
	}
	/** The real package a twin stands for (a module two services deploy), or undefined. */
	twinOf(id) {
		return this.twinHome.has(id) ? id.slice(5) : void 0;
	}
	/** The services that also deploy package `id` as a twin (its code sits elsewhere), in map order; [] for none. */
	twinDeployers(id) {
		return this.twinnedBy.get(id) ?? [];
	}
	label(id) {
		if (id.startsWith(DOOR)) return this.label(doorAnchor(id));
		const twin = this.twinOf(id);
		if (twin) return this.label(twin);
		return this.nodes.get(id)?.name ?? this.groups.get(id)?.label ?? id;
	}
	/** The name an item shows wherever it stands for itself (box, floor list, inspector, search, name tag): on one floor
	*  no two items show the same name. An implementation reads as one (`BillingService.Live`, `DeadLetters.live (impl)`);
	*  a companion `X$` adds ` (object)` only beside `X`; overloads add their arity (`run/2`); any other clash adds the
	*  shortest run of parent segments that tells them apart. Never cut. `label` stays the map's own name. */
	itemName(id) {
		if (id.startsWith(DOOR)) return this.itemName(doorAnchor(id));
		const c = this.homeFloor(id);
		return c === void 0 ? this.baseName(id) : this.namesOn(c).get(id);
	}
	/** The floor whose names an item wears: the first, in sorted order, that lists it. Found without naming anything, so
	*  a name asks for one floor's clash rules, not every floor's. */
	homeFloor(id) {
		if (!this.firstFloor) {
			this.firstFloor = /* @__PURE__ */ new Map();
			for (const c of Object.keys(this.map.layout.containers).sort()) for (const item of Object.keys(this.map.layout.containers[c].items ?? {})) if (!this.firstFloor.has(item)) this.firstFloor.set(item, c);
		}
		return this.firstFloor.get(id);
	}
	firstFloor;
	/** Each item's name on one floor, clashes told apart (rules on `itemName`); worked out once per floor. */
	namesOn(c) {
		let name = this.floorNames.get(c);
		if (name) return name;
		const items = Object.keys(this.map.layout.containers[c].items ?? {}).sort();
		name = new Map(items.map((id) => [id, this.baseName(id)]));
		const clashes = () => {
			const by = /* @__PURE__ */ new Map();
			for (const [id, n] of name) by.set(n, [...by.get(n) ?? [], id]);
			return [...by.values()].filter((ids) => ids.length > 1);
		};
		for (const ids of clashes()) for (const id of ids) if (id.endsWith("$") && ids.includes(id.slice(0, -1))) name.set(id, `${name.get(id)} (object)`);
		for (const ids of clashes()) for (const id of ids) {
			const sig = /#([^#]+\/[^#/]+)$/.exec(this.twinOf(id) ?? id)?.[1];
			if (sig) name.set(id, sig);
		}
		for (const ids of clashes()) {
			const base = new Map(ids.map((id) => [id, name.get(id)]));
			for (let k = 1; k <= 12; k++) {
				const cand = ids.map((id) => {
					const p = lastSegments(this.twinOf(id) ?? id, k);
					return p ? `${p}.${base.get(id)}` : base.get(id);
				});
				if (new Set(cand).size === ids.length || k === 12) {
					ids.forEach((id, i) => name.set(id, cand[i]));
					break;
				}
			}
		}
		for (const ids of clashes()) for (const id of ids) name.set(id, `${name.get(id)} (${this.codes.get(id) ?? id})`);
		this.floorNames.set(c, name);
		return name;
	}
	floorNames = /* @__PURE__ */ new Map();
	/** An item's own name, before any floor clash: implementations qualified by the class that holds them. */
	baseName(id) {
		const twin = this.twinOf(id);
		if (twin) return this.baseName(twin);
		const n = this.nodes.get(id);
		if (!n) return this.label(id);
		const owner = n.parent ? this.nodes.get(n.parent) : void 0;
		const ownerName = owner?.kind === "class" ? owner.name : "";
		const anon = /\.([^.#/]+)\$impl$/.exec(id);
		if (anon) return `${ownerName || (lastSegments(id, 1) ?? "")}.${anon[1]} (impl)`.replace(/^\./, "");
		if (n.implements?.length && ownerName) return `${ownerName}.${n.name}`;
		return n.name;
	}
	kindOf(id) {
		const twin = this.twinOf(id);
		if (twin) return this.kindOf(twin);
		return this.nodes.get(id)?.kind ?? (this.groups.has(id) ? "group" : "unknown");
	}
	/** Containers from the site down to `container` (inclusive), via groups where they apply. */
	path(container) {
		const out = [];
		let cur = container;
		while (cur && cur !== "site") {
			out.unshift(cur);
			const g = this.groups.get(cur);
			cur = g ? g.container : this.memberOf.get(cur) ?? this.nodes.get(cur)?.parent ?? "site";
		}
		return [SITE, ...out];
	}
	/** The container whose floor shows `id` as an item (deepest). */
	floorOf(id) {
		const home = this.twinHome.get(id);
		if (home) return home;
		const group = this.groups.get(id);
		if (group) return group.container;
		const g = this.memberOf.get(id);
		if (g) return g;
		const n = this.nodes.get(id);
		if (!n) return void 0;
		if (!n.parent) return SITE;
		return n.parent;
	}
	/** Map any node to the item that stands for it on `container`'s floor, or undefined if it is outside. */
	liftTo(container, id) {
		const floor = this.floor(container);
		if (!floor) return void 0;
		const onSite = container === SITE;
		if (onSite && (floor.utilities ?? []).includes(id)) return void 0;
		for (const step of this.liftChain(id, onSite)) {
			if (Object.hasOwn(floor.items, step.id)) return step.id;
			if (step.group && Object.hasOwn(floor.items, step.group)) return step.group;
		}
	}
	/** The walk `liftTo` makes up from `id`, the same on every floor: each id on the way and the group it is a member of.
	*  Only the site floor differs, for a table with no datastore (it stops there). Kept per id. */
	liftChain(id, onSite) {
		let chain = this.chains.get(id);
		if (chain && onSite) {
			const end = chain.findIndex((s) => {
				const n = this.nodes.get(s.id);
				return n?.kind === "table" && !n.parent;
			});
			return end < 0 || end === chain.length - 1 ? chain : chain.slice(0, end + 1);
		}
		if (chain) return chain;
		const steps = [];
		let cur = id;
		const seen = /* @__PURE__ */ new Set();
		while (cur && !seen.has(cur)) {
			seen.add(cur);
			const viaGroup = this.memberOf.get(cur);
			steps.push(viaGroup ? {
				id: cur,
				group: viaGroup
			} : { id: cur });
			cur = this.nodes.get(cur)?.parent ?? (viaGroup ? this.groups.get(viaGroup)?.container : void 0);
		}
		this.chains.set(id, steps);
		return this.liftChain(id, onSite);
	}
	chains = /* @__PURE__ */ new Map();
	/** One bundle per pair of items on this floor, plus relations leaving the floor. `layered`: the lines kept out of
	*  the base layer, each tagged with the extra layer that draws it (a line in two layers is listed once per
	*  layer, so count or collect its key once); `bundles` never holds them. Worked out once per floor and code-links
	*  flag (the map never changes under a Model) and shared: callers must not mutate the result. */
	bundles(container, opts = {}) {
		const k = `${container}|${opts.codeLinks ? 1 : 0}`;
		let b = this.floorBundles.get(k);
		if (!b) this.floorBundles.set(k, b = this.bundlesOf(container, !!opts.codeLinks));
		return b;
	}
	floorBundles = /* @__PURE__ */ new Map();
	bundlesOf(container, codeLinks) {
		const onSite = container === SITE;
		if (this.nodes.get(container)?.kind === "datastore") return {
			bundles: [],
			outward: [],
			doors: [],
			layered: []
		};
		const wanted = (k) => RUNTIME.includes(k) || k === "calls" && !onSite || k === "uses-code" && codeLinks;
		const byKey = /* @__PURE__ */ new Map();
		const out = /* @__PURE__ */ new Map();
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
					bundle = {
						key,
						a: x,
						b: y,
						relations: [],
						kinds: {},
						inferred: 0,
						kind: r.kind,
						flow: "both"
					};
					byKey.set(key, bundle);
				}
				bundle.relations.push(r);
				bundle.kinds[r.kind] = (bundle.kinds[r.kind] ?? 0) + 1;
				if (r.confidence === "inferred") bundle.inferred++;
			} else if (a || b) {
				const item = a ?? b;
				const other = a ? r.to : r.from;
				const k = `${item}|${other}`;
				const o = out.get(k) ?? {
					item,
					other,
					relations: []
				};
				o.relations.push(r);
				out.set(k, o);
			}
		}
		const doors = /* @__PURE__ */ new Map();
		if (!onSite) {
			for (const o of out.values()) {
				const anchor = this.anchorFor(container, o.other);
				const id = this.doorId(anchor);
				for (const r of o.relations) {
					const upstream = r.data === "back" ? r.to : r.from;
					const leaves = this.liftTo(container, upstream) === o.item;
					const d = doors.get(id) ?? {
						id,
						anchor,
						side: "out",
						votes: 0
					};
					d.votes += leaves ? 1 : -1;
					doors.set(id, d);
					const [x, y] = o.item < id ? [o.item, id] : [id, o.item];
					const key = `${x}|${y}`;
					let bundle = byKey.get(key);
					if (!bundle) {
						bundle = {
							key,
							a: x,
							b: y,
							relations: [],
							kinds: {},
							inferred: 0,
							kind: r.kind,
							flow: "both"
						};
						byKey.set(key, bundle);
					}
					bundle.relations.push(r);
					bundle.kinds[r.kind] = (bundle.kinds[r.kind] ?? 0) + 1;
					if (r.confidence === "inferred") bundle.inferred++;
				}
			}
			for (const d of doors.values()) d.side = d.votes >= 0 ? "out" : "in";
		}
		const lift = (id) => this.liftTo(container, id) ?? (onSite ? void 0 : this.doorId(this.anchorFor(container, id)));
		for (const b of byKey.values()) {
			b.kind = DRAW_ORDER.find((k) => b.kinds[k]) ?? b.kind;
			b.flow = flowOf$1(b, lift);
		}
		const hubs = new Set(this.floor(container)?.hubs ?? []);
		const layered = [];
		for (const [k, b] of byKey) {
			if (!hubs.has(b.a) && !hubs.has(b.b) || b.kind === "batch") continue;
			byKey.delete(k);
			const own = b.relations.filter((r) => r.kind === b.kind);
			const ends = new Set((own.length ? own : b.relations).map((r) => lift(r.to)));
			for (const h of /* @__PURE__ */ new Set([b.a, b.b])) if (hubs.has(h)) layered.push({
				...b,
				layer: h,
				into: ends.has(h)
			});
		}
		return {
			doors: [...doors.values()].map(({ id, anchor, side }) => ({
				id,
				anchor,
				side
			})).sort((p, q) => p.id.localeCompare(q.id)),
			bundles: [...byKey.values()].sort((p, q) => p.key.localeCompare(q.key)),
			layered: layered.sort((p, q) => p.key.localeCompare(q.key) || p.layer.localeCompare(q.layer)),
			outward: [...out.values()].sort((p, q) => (p.item + p.other).localeCompare(q.item + q.other))
		};
	}
	/** The relations with an end that may lift to an item on `container`'s floor, in map order: those with an item of
	*  the floor on an end's lift chain (as an id or its group); on the site floor, all of them. The rest lift to nothing
	*  there, so `bundles` skips them. */
	relationsNear(container) {
		const rels = this.map.relations;
		if (container === "site") return rels;
		if (!this.relsByChain) {
			this.relsByChain = /* @__PURE__ */ new Map();
			rels.forEach((r, i) => {
				for (const end of [r.from, r.to]) for (const step of this.liftChain(end, false)) for (const k of step.group ? [step.id, step.group] : [step.id]) {
					const list = this.relsByChain.get(k);
					if (!list) this.relsByChain.set(k, [i]);
					else if (list[list.length - 1] !== i) list.push(i);
				}
			});
		}
		const near = /* @__PURE__ */ new Set();
		for (const item of Object.keys(this.floor(container)?.items ?? {})) for (const i of this.relsByChain.get(item) ?? []) near.add(i);
		return [...near].sort((a, b) => a - b).map((i) => rels[i]);
	}
	relsByChain;
	/** The deepest floor both `container` and `other` sit on, and the item standing for `other` there. */
	commonFloor(container, otherFloor) {
		const here = this.path(container), there = this.path(otherFloor);
		let i = 0;
		while (i < here.length && i < there.length && here[i] === there[i]) i++;
		return here[Math.max(0, i - 1)];
	}
	/** A datastore keeps its own id inside buildings (it is drawn as the same warehouse on its lane);
	*  anything else outside the floor is reached through a door on the frame. */
	doorId(anchor) {
		return this.nodes.get(anchor)?.kind === "datastore" ? anchor : `${DOOR}${anchor}`;
	}
	anchorFor(container, other) {
		const shared = this.commonFloor(container, this.floorOf(other) ?? "site");
		return this.liftTo(shared, other) ?? other;
	}
	/** Where the door to `anchor` on `container`'s floor leads: the door back on the far side, on the deepest floor inside
	*  `anchor` that still shows it, on the way down to the far ends of the relations through the door (an end that is
	*  `anchor` itself, a job its service runs, is drawn on `anchor`'s own floor). Undefined when `anchor` has no floor
	*  showing a door back: the door then leads to `anchor` on the floor both share. */
	doorLanding(container, anchor) {
		const k = `${container}|${anchor}`;
		if (!this.landings.has(k)) this.landings.set(k, this.landing(container, anchor));
		return this.landings.get(k);
	}
	/** What the door to `anchor` on `container`'s floor is named after: the building its double-click opens (the floor
	*  doorLanding finds), else `anchor`. */
	doorShows(container, anchor) {
		return this.doorLanding(container, anchor)?.floor ?? anchor;
	}
	landing(container, anchor) {
		if (!this.floor(anchor)) return void 0;
		let far;
		for (const o of this.bundles(container).outward) {
			if (this.anchorFor(container, o.other) !== anchor) continue;
			const f = this.floorOf(o.other) ?? "site";
			const home = this.path(f).includes(anchor) ? f : anchor;
			far = far === void 0 ? home : this.commonFloor(far, home);
		}
		if (far === void 0) return void 0;
		const down = this.path(far);
		for (let i = down.length - 1; i >= down.indexOf(anchor); i--) {
			const door = this.doorId(this.anchorFor(down[i], container));
			if (this.bundles(down[i]).doors.some((d) => d.id === door)) return {
				floor: down[i],
				door
			};
		}
	}
	/** Which services write and read a table, as short codes (S1 S4), for the warehouse shelves. */
	tableAccess(table) {
		const writers = /* @__PURE__ */ new Set(), readers = /* @__PURE__ */ new Set();
		for (const r of this.map.relations) {
			if (r.to !== table || r.kind !== "db-write" && r.kind !== "db-read") continue;
			const who = this.liftTo(SITE, r.from);
			if (who) (r.kind === "db-write" ? writers : readers).add(this.codes.get(who) ?? who);
		}
		const sort = (s) => [...s].sort(numericCollator.compare);
		return {
			writers: sort(writers),
			readers: sort(readers)
		};
	}
	/** Utilities (shared externals) each item on the site floor calls: drawn as badges. */
	badges(container) {
		const res = /* @__PURE__ */ new Map();
		if (container !== "site") return res;
		const utilities = new Set(this.floor("site")?.utilities ?? []);
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
	implementersOf(id) {
		return this.implementers.get(id) ?? [];
	}
	/** What `id` implements: the trait (or class) ids it names in `implements`. */
	implementedBy(id) {
		return [...this.nodes.get(id)?.implements ?? []].filter((t) => this.nodes.has(t)).sort();
	}
	/** Trait → implementation links lifted to this floor's items: one per pair of distinct items, sorted by key. */
	implementLinks(container) {
		const out = /* @__PURE__ */ new Map();
		for (const [t, impls] of this.implementers) {
			const trait = this.liftTo(container, t);
			if (!trait) continue;
			for (const i of impls) {
				const impl = this.liftTo(container, i);
				if (!impl || impl === trait) continue;
				const key = `${trait}|${impl}`;
				if (!out.has(key)) out.set(key, {
					key,
					trait,
					impl
				});
			}
		}
		return [...out.values()].sort((p, q) => p.key.localeCompare(q.key));
	}
	/** The item on `container` holding the implementation of the trait `id` stands in (`id` itself or its nearest
	*  enclosing class, e.g. a trait method). Only when that trait has exactly one implementer whose lifted item
	*  exists on this floor (two implementers in one companion still count as two), and that item is not `id`'s own. */
	implementerOn(container, id) {
		let cur = id;
		while (cur && !this.implementers.has(cur)) cur = this.nodes.get(cur)?.parent ?? void 0;
		if (!cur) return void 0;
		const lifted = this.implementersOf(cur).map((i) => this.liftTo(container, i)).filter((x) => !!x);
		if (lifted.length !== 1) return void 0;
		const here = this.liftTo(container, id);
		return here && lifted[0] !== here ? lifted[0] : void 0;
	}
	/** The relations (no code links) with an end that is `id` or inside it, in map order. */
	relationsOf(id) {
		if (!this.relsByOwner) {
			this.relsByOwner = /* @__PURE__ */ new Map();
			for (const r of this.map.relations) {
				if (r.kind === "uses-code") continue;
				const owners = /* @__PURE__ */ new Set([
					r.from,
					...this.insideOf(r.from),
					r.to,
					...this.insideOf(r.to)
				]);
				for (const o of owners) {
					const list = this.relsByOwner.get(o);
					if (list) list.push(r);
					else this.relsByOwner.set(o, [r]);
				}
			}
		}
		return [...this.relsByOwner.get(id) ?? []];
	}
	relsByOwner;
	/** Whether `id` is inside `container`: below it in the parent chain, or (a floor group) a member of it, inside a
	*  member, or inside a group that is one. */
	isInside(id, container) {
		return this.insideOf(id).has(container);
	}
	/** Everything `id` is inside: its parent chain, and the floor groups whose members hold it or one of those (a group
	*  in a group: both). From the groups' own members, as one id can be listed by groups on two floors. Kept per id. */
	insideOf(id) {
		let set = this.inside.get(id);
		if (set) return set;
		if (!this.holders) {
			this.holders = /* @__PURE__ */ new Map();
			for (const g of this.groups.values()) for (const m of g.members) {
				const h = this.holders.get(m);
				if (h) h.push(g.id);
				else this.holders.set(m, [g.id]);
			}
		}
		const s = /* @__PURE__ */ new Set();
		let cur = this.nodes.get(id)?.parent ?? void 0;
		while (cur && !s.has(cur)) {
			s.add(cur);
			cur = this.nodes.get(cur)?.parent ?? void 0;
		}
		for (const a of s) if (this.groups.has(a)) s.delete(a);
		const queue = [id, ...s];
		for (let i = 0; i < queue.length; i++) for (const g of this.holders.get(queue[i]) ?? []) if (!s.has(g)) {
			s.add(g);
			queue.push(g);
		}
		this.inside.set(id, set = s);
		return set;
	}
	inside = /* @__PURE__ */ new Map();
	holders;
	/** Every id `x` with `isInside(x, id)`: the nodes below it, and for a floor group its members and what is inside
	*  them. Unordered. */
	descendants(id) {
		const out = /* @__PURE__ */ new Set(), walked = /* @__PURE__ */ new Set();
		const below = (x) => {
			if (walked.has(x)) return;
			walked.add(x);
			for (const c of this.children.get(x) ?? []) {
				out.add(c);
				below(c);
			}
		};
		const inGroup = (g, seen = /* @__PURE__ */ new Set()) => {
			if (seen.has(g)) return;
			seen.add(g);
			for (const m of this.groups.get(g).members) {
				out.add(m);
				if (this.groups.has(m)) inGroup(m, seen);
				else below(m);
			}
		};
		if (this.groups.has(id)) inGroup(id);
		else below(id);
		return [...out];
	}
	children = /* @__PURE__ */ new Map();
	/** Short codes: S1, S1·P2, S1·P2·C3·M4 … stable for a given set of ids (sorted). */
	assignCodes() {
		const prefix = {
			service: "S",
			library: "L",
			datastore: "D",
			external: "X",
			topic: "T",
			"in-process-queue": "Q",
			package: "P",
			class: "C",
			file: "F",
			method: "M",
			table: "T"
		};
		const kids = /* @__PURE__ */ new Map();
		const roots = [];
		for (const n of this.map.nodes) {
			if (n.parent) {
				const c = this.children.get(n.parent);
				if (c) c.push(n.id);
				else this.children.set(n.parent, [n.id]);
			}
			if (n.parent && this.nodes.has(n.parent)) kids.set(n.parent, [...kids.get(n.parent) ?? [], n]);
			else roots.push(n);
		}
		const walk = (list, base) => {
			const counters = {};
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
		for (const [tid] of this.twinHome) this.codes.set(tid, this.codes.get(tid.slice(5)) ?? "");
	}
	search(text, limit = 30) {
		const t = text.trim().toLowerCase();
		if (!t) return [];
		const hits = [];
		for (const r of this.searchRows()) {
			const score = r.code === t ? 0 : r.name === t || r.shown === t ? 1 : r.name.startsWith(t) || r.shown.startsWith(t) ? 2 : r.name.includes(t) || r.shown.includes(t) ? 3 : r.idl.includes(t) ? 4 : -1;
			if (score >= 0) hits.push([score, r.id]);
		}
		return hits.sort((a, b) => a[0] - b[0] || a[1].localeCompare(b[1])).slice(0, limit).map((h) => h[1]);
	}
	/** Each node's code, map name, shown name (`itemName`) and id, lowercased once: built on the first search, so a map
	*  nobody searches never names every node. */
	searchRows() {
		return this.rows ??= this.map.nodes.map((n) => ({
			id: n.id,
			code: (this.codes.get(n.id) ?? "").toLowerCase(),
			name: n.name.toLowerCase(),
			shown: this.itemName(n.id).toLowerCase(),
			idl: n.id.toLowerCase()
		}));
	}
	rows;
};
/** The last `k` segments of the path that holds `id` (`svc::a.b.C` → `a.b` for k = 2; a method's holder is its class),
*  without companion `$`s; undefined when there are none. */
function lastSegments(id, k) {
	const q = id.includes("::") ? id.slice(id.indexOf("::") + 2) : id;
	const hash = q.indexOf("#");
	const segs = (hash >= 0 ? q.slice(0, hash) : q).split(/[./]/).filter(Boolean).map((s) => s.replace(/\$+$/, ""));
	const holder = hash >= 0 ? segs : segs.slice(0, -1);
	return holder.length ? holder.slice(-k).join(".") : void 0;
}
function flowOf$1(b, lift) {
	let fwd = 0, back = 0;
	for (const r of b.relations) {
		const from = lift(r.from), to = lift(r.to);
		const d = r.data ?? (r.kind === "db-read" ? "back" : r.kind === "stream" ? "both" : "forward");
		if (d === "both") {
			fwd++;
			back++;
			continue;
		}
		const [up] = d === "back" ? [to, from] : [from, to];
		if (up === b.a) fwd++;
		else back++;
	}
	return fwd && back ? "both" : fwd ? "a→b" : "b→a";
}
// src/factory/tiles.ts
/** n, e, s, w: index (i + 2) % 4 is the opposite direction. */
var DIRS = [
	"n",
	"e",
	"s",
	"w"
];
var STEP = {
	n: [0, -1],
	e: [1, 0],
	s: [0, 1],
	w: [-1, 0]
};
var OPP = {
	n: "s",
	s: "n",
	e: "w",
	w: "e"
};
/** `chest`: a cache only one machine uses, standing beside that machine on the site floor instead of on a lane. 2x2 is its
*  smallest size; a chest grows up to a lane-end store box until its name shows whole (fit.ts `chestSize`). */
var FOOT = {
	service: [5, 5],
	dock: [5, 5],
	rack: [4, 3],
	installed: [4, 5],
	package: [5, 3],
	warehouse: [6, 3],
	hub: [3, 3],
	door: [7, 3],
	chest: [2, 2]
};
/** Which footprint a map kind takes; a library is a rack on the site shelf and a wall unit inside a factory. */
function footprintFor(kind, site) {
	switch (kind) {
		case "service": return "service";
		case "external": return "dock";
		case "library": return site ? "rack" : "installed";
		case "datastore": return "warehouse";
		case "topic":
		case "in-process-queue": return "hub";
		case "door": return "door";
		default: return "package";
	}
}
var inside = (r, x, y) => x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h;
/** The travel direction from tile (x, y) into the rectangle beside it, or null if it does not touch one side. */
function dirInto(r, x, y) {
	for (const d of DIRS) if (inside(r, x + STEP[d][0], y + STEP[d][1])) return d;
	return null;
}
/** The edge a junction piece's branch leaves by (split) or joins through (merge). */
var joinEdge = (p) => p.join === "merge" ? OPP[p.in] : p.out;
// src/floor/names.ts
/** Longest dotted (or path) prefix shared by at least two names, ending at a separator. */
function commonPrefix(names) {
	if (names.length < 2) return "";
	let p = names[0];
	for (const n of names) while (p && !n.startsWith(p)) p = p.slice(0, -1);
	if (names.every((n) => n === p || n.startsWith(p + ".") || n.startsWith(p + "/")) && names.some((n) => n !== p)) return p + ".";
	const cut = Math.max(p.lastIndexOf("."), p.lastIndexOf("/"));
	return cut > 0 ? p.slice(0, cut + 1) : "";
}
/** Up to `max` lines, breaking after `.`, `_`, `/`, `-` or a space, or before `(` or a camelCase capital; if it still does not fit, keep the end (most specific). */
function nameLines(s, width, size, max) {
	const per = Math.max(4, Math.floor(width / (size * .56)));
	if (s.length <= per) return [s];
	const lines = [];
	let rest = s;
	while (rest.length > per && lines.length < max - 1) {
		const window = rest.slice(0, per);
		const after = Math.max(window.lastIndexOf("."), window.lastIndexOf("_"), window.lastIndexOf("/"), window.lastIndexOf(" "), window.lastIndexOf("-"));
		const before = window.lastIndexOf("(");
		let camel = -1;
		for (let i = window.length - 1; i > 0; i--) if (/[A-Z]/.test(window[i]) && /[a-z0-9]/.test(window[i - 1])) {
			camel = i;
			break;
		}
		const sep = Math.max(after + 1, before);
		let cut = sep > per / 3 ? sep : camel > per / 3 ? camel : per;
		if (cut === per && rest.length - cut <= 2) cut = rest.length - 3;
		lines.push(rest.slice(0, cut).trimEnd());
		rest = rest.slice(cut).trimStart();
	}
	lines.push(rest.length > per ? "…" + rest.slice(rest.length - per + 1) : rest);
	return lines;
}
/** "Stripe API WebSocket (stream.stripe.com/streams)" → title "Stripe API WebSocket", endpoint for the subline. */
function splitEndpoint(label) {
	const m = /^(.*\S)\s*\(([^()]+)\)$/.exec(label);
	return m ? {
		title: m[1],
		endpoint: m[2]
	} : {
		title: label,
		endpoint: ""
	};
}
/** A door's name relative to the floors above it: strip the deepest enclosing package but keep its last
*  segment for context (`com.acme.market.service.stripe` under `com.acme.market.service` → `service.stripe`). */
function doorName(label, above) {
	const title = splitEndpoint(label).title;
	const outer = above.filter((a) => title.startsWith(a + ".")).sort((a, b) => b.length - a.length)[0];
	if (!outer) return title;
	const cut = outer.lastIndexOf(".");
	return cut > 0 ? title.slice(cut + 1) : title;
}
/** The dotted prefix every item on a floor shares, from the map's own names (`Model.label`), never from the floor-unique
*  ones: a tag added to tell items apart (`config/1`, `X (object)`, `a.Twin`) must not become something to strip.
*  Doors, datastores and twins keep their own names and take no part. */
function floorPrefix(model, ids) {
	return commonPrefix(ids.filter((id) => !id.startsWith("door:") && model.kindOf(id) !== "datastore" && !model.twinOf(id)).map((id) => model.label(id)));
}
/** `full` without the floor's shared dotted `prefix` (from `commonPrefix`); the stem package itself keeps its last segment. */
function stripShared(full, prefix) {
	if (prefix && full === prefix.slice(0, -1)) return full.split(/[./]/).pop() ?? full;
	return prefix && full.startsWith(prefix) && full.length > prefix.length ? full.slice(prefix.length) : full;
}
/** The name an item's box and the floor list show: its floor-unique name (`Model.itemName`) less the floor's shared
*  prefix; an external drops its endpoint, a table its default schema. */
function shownName(model, id, prefix) {
	let full = model.itemName(id);
	if (model.kindOf(id) === "external") return splitEndpoint(full).title;
	if (model.kindOf(id) === "table") full = full.replace(/^public\./, "");
	return stripShared(full, prefix);
}
// src/factory/fit.ts
var PLATE_FONT = 10.5;
/** A label's width at `size`, estimated (never measured, so placement cannot depend on font loading): Archivo bold
*  averages under 0.56 em a letter on these words (measured: "group notifier ×2" is 82 px at 10.5, estimated 100),
*  plus 4 px padding a side. The drawn text is centred in it and shrunk in the rare case it is wider. */
var plateW = (text, size = PLATE_FONT) => Math.ceil(text.length * size * .56) + 8;
var CHAR = .56;
var fits = (s, width, size) => s.length * size * CHAR <= width;
/** Does every break in `lines` (from nameLines) fall between words: after a separator or a space, or before "(" or a
*  camelCase capital, never inside a word ("reservatio" / "n-events")? A line not found in `name` counts as not clean. */
function cleanBreaks(name, lines) {
	let at = 0;
	for (const l of lines.slice(0, -1)) {
		const i = name.indexOf(l, at);
		if (i < 0) return false;
		at = i + l.length;
		const a = name[at - 1], b = name.slice(at).trimStart()[0];
		if (!(/[-_./ ]/.test(a) || name[at] === " " || b === "(" || /[a-z0-9]/.test(a) && /[A-Z]/.test(b))) return false;
	}
	return true;
}
/** A name in up to `max` lines: the largest size that wraps whole; if that wrap breaks inside a word, one size smaller
*  when that breaks between words (never more: the floor's smallest name sets its codes switch). If even the smallest
*  size does not wrap whole, the front is kept and the last line ends with "…" (a name is never cut from the front). */
function fitName(name, width, max, sizes = [
	14,
	13,
	12,
	11,
	10
]) {
	const at = (size) => {
		const lines = nameLines(name, width, size, max);
		return lines[lines.length - 1].startsWith("…") ? void 0 : {
			lines,
			size
		};
	};
	const i = sizes.findIndex((size) => at(size));
	if (i >= 0) {
		const whole = at(sizes[i]);
		if (cleanBreaks(name, whole.lines) || i + 1 >= sizes.length) return whole;
		const next = at(sizes[i + 1]);
		return next && cleanBreaks(name, next.lines) ? next : whole;
	}
	const size = sizes[sizes.length - 1];
	const per = Math.max(4, Math.floor(width / (size * CHAR)));
	const lines = nameLines(name, width, size, max + 8).slice(0, max);
	const last = lines.length - 1;
	lines[last] = lines[last].slice(0, per - 1).trimEnd() + "…";
	return {
		lines,
		size
	};
}
/** One line of text, never starting with "…": the largest size that fits; else, for a path, leading segments are dropped
*  ("GET /v1/orders/{id}" → "GET /orders/{id}"); else the end is cut. */
function fitLine(text, width, sizes = [11, 10]) {
	for (const size of sizes) if (fits(text, width, size)) return {
		text,
		size
	};
	const size = sizes[sizes.length - 1];
	const at = text.includes(" · ") ? text.lastIndexOf(" · ") + 3 : 0;
	const head = text.slice(0, at), tail = text.slice(at);
	const verb = /^[A-Z]+ (?=\/)/.exec(tail)?.[0] ?? "";
	const path = tail.slice(verb.length);
	if (path.includes("/")) {
		const segs = path.split("/").filter(Boolean);
		const lead = path.startsWith("/") ? "/" : "";
		for (let i = 1; i < segs.length; i++) {
			const cand = head + verb + lead + segs.slice(i).join("/");
			if (fits(cand, width, size)) return {
				text: cand,
				size
			};
		}
	}
	const per = Math.max(4, Math.floor(width / (size * CHAR)));
	return {
		text: text.length > per ? text.slice(0, per - 1).trimEnd() + "…" : text,
		size
	};
}
/** A method's parameters for a sub line at 10 px: "(a, b, c)", else "(a, b, …)" with as many leading ones as fit, else "(n params)". */
function fitSignature(params, width) {
	const full = `(${params.join(", ")})`;
	if (fits(full, width, 10)) return full;
	for (let k = params.length - 1; k >= 1; k--) {
		const cut = `(${params.slice(0, k).join(", ")}, …)`;
		if (fits(cut, width, 10)) return cut;
	}
	return `(${params.length} ${params.length === 1 ? "param" : "params"})`;
}
/** Is `lines` the whole of `name`: nothing cut, no "…", each break after a hyphen, an underscore or a dot? */
var shownWhole = (name, lines) => lines.join("") === name && !lines.some((l) => l.includes("…")) && lines.slice(0, -1).every((l) => /[-_.]$/.test(l));
/** A cache chest's name room, in px from the box's edges: under the code tab and the lid strap (`top`), above the lower
*  strap (`bottom`), `inset` narrower than the box, at the machine name sizes, on up to two lines. */
var CHEST_NAME = {
	top: 20,
	bottom: 8,
	inset: 12,
	ix: 6,
	maxLines: 2,
	sizes: [
		14,
		13,
		12,
		11,
		10
	]
};
/** The chest name in a `w`×`h`-tile chest: the largest size at which it shows whole and fits the name room; undefined
*  when it does not at any size. The painter draws exactly this. */
function chestFit(name, w, h) {
	const { top, bottom, inset, maxLines, sizes } = CHEST_NAME;
	for (const size of sizes) {
		const lines = nameLines(name, w * 24 - inset, size, maxLines);
		if (shownWhole(name, lines) && top + lines.length * (size + 2) <= h * 24 - bottom) return {
			lines,
			size
		};
	}
}
/** A cache chest's footprint: the narrowest (then the shortest) from FOOT.chest up to a lane-end store box (FOOT.warehouse)
*  that shows its name whole; narrow first, since a chest stands in a corridor between machines. Undefined when even the
*  lane-end box cannot: the cache keeps its lane. */
function chestSize(name) {
	const [w0, h0] = FOOT.chest, [w1, h1] = FOOT.warehouse;
	for (let w = w0; w <= w1; w++) for (let h = h0; h <= h1; h++) if (chestFit(name, w, h)) return [w, h];
}
/** Where a box's name goes, by footprint (world px): its top, the width it wraps in, its lines and sizes, its left inset. */
function nameSpec(b) {
	const y = b.y * 24, W = b.w * 24;
	const base = {
		top: y + 20,
		w: W - 14,
		maxLines: 2,
		sizes: [
			14,
			13,
			12,
			11,
			10
		],
		ix: 7
	};
	switch (b.foot) {
		case "service": return {
			...base,
			top: y + 58
		};
		case "package": return {
			...base,
			top: y + 22
		};
		case "dock": return {
			...base,
			ix: 14,
			top: y + 50,
			w: W - 20
		};
		case "rack": return {
			...base,
			top: y + 36,
			sizes: [
				13,
				12,
				11,
				10
			]
		};
		case "installed": return {
			...base,
			top: y + 44,
			w: W - 12,
			maxLines: 4,
			sizes: [
				12,
				11,
				10
			],
			ix: 6
		};
		case "warehouse": return {
			...base,
			top: y + 22,
			maxLines: 1
		};
		case "hub": return {
			...base,
			top: y + 26,
			w: W - 4,
			ix: 4,
			sizes: [
				11,
				10,
				9
			]
		};
		case "chest": return {
			...base,
			top: y + CHEST_NAME.top,
			w: W - CHEST_NAME.inset,
			ix: CHEST_NAME.ix,
			maxLines: CHEST_NAME.maxLines,
			sizes: CHEST_NAME.sizes
		};
		default: return base;
	}
}
/** The free band inside a service or package between its fitted name and its sub line (world px), where a consumer's tag
*  may sit; estimated from the name fit, never measured. Undefined for other footprints. */
function freeBand(b, name) {
	if (b.foot !== "service" && b.foot !== "package") return void 0;
	const spec = nameSpec(b), fit = fitName(name, spec.w, spec.maxLines, spec.sizes);
	return {
		x0: b.x * 24 + 5,
		y0: spec.top + fit.lines.length * (fit.size + 2) + 3,
		x1: (b.x + b.w) * 24 - 5,
		y1: (b.y + b.h) * 24 - 19
	};
}
/** The smallest a machine or door name renders on screen before the floor switches to codes: 9 px held two wheel notches
*  further out (the owner: names were still readable there). One notch is x e^-0.2 (deltaY 100, exp(-deltaY / 500)),
*  so 9 x e^-0.4, about 6 px. Sub lines, tags and plates keep their own 9 px rule (`subShown`). */
var NAME_MIN_PX = 9 * Math.exp(-.4);
/** Zoom under which a name of `minName` px would render under NAME_MIN_PX: the floor shows codes instead. One switch for
*  the whole floor, from the smallest name drawn on it (14 px names alone would switch at about 6/14). */
var codeZoom = (minName) => NAME_MIN_PX / minName;
// src/factory/messaging.ts
/** The short label each flight's plate shows (owner decision: short words). */
var FLIGHT_LABEL = {
	produce: "produce",
	enqueue: "enqueue",
	copy: "copy",
	take: "take",
	push: "push",
	pull: "pull",
	failure: "on failure"
};
/** The airfield an in-process queue's hub stands on, inside its service's floor. */
var IN_PROCESS = "in-process";
/** "kafka" from "topic:kafka:orders": the same split the layout's airfields use; an in-process queue's is IN_PROCESS. */
var brokerOf = (topic) => topic.startsWith("inq:") ? IN_PROCESS : topic.split(":")[1] ?? "";
var byStr$3 = (a, b) => a < b ? -1 : a > b ? 1 : 0;
/** The topic whose failures land on topic `id` (it is a dead-letter hub), when that topic is in the map; else null. */
function deadLetterOf(model, id) {
	const src = model.nodes.get(id)?.dead_letter_of;
	return src && model.nodes.get(src)?.kind === "topic" ? src : null;
}
function messaging(model, container, tf, bundles) {
	const onSite = container === SITE;
	const hubs = /* @__PURE__ */ new Map();
	for (const box of [...tf.boxes.values()].sort((p, q) => byStr$3(p.id, q.id))) {
		const topic = doorAnchor(box.id);
		const node = model.nodes.get(topic);
		if (node?.kind !== "topic" && node?.kind !== "in-process-queue") continue;
		const delivery = node.delivery === "queue" ? "queue" : "fan-out";
		hubs.set(box.id, {
			item: box.id,
			topic,
			broker: brokerOf(topic),
			delivery,
			dlqOf: deadLetterOf(model, topic),
			waiting: delivery === "queue"
		});
	}
	const lift = (id) => model.liftTo(container, id) ?? (onSite ? void 0 : model.doorId(model.anchorFor(container, id)));
	const produced = /* @__PURE__ */ new Map();
	const consumed = /* @__PURE__ */ new Map();
	const failed = /* @__PURE__ */ new Map();
	for (const b of bundles) {
		const hubEnd = hubs.get(b.a) ? b.a : hubs.get(b.b) ? b.b : null;
		if (!hubEnd) continue;
		const machine = hubEnd === b.a ? b.b : b.a;
		if (hubs.has(machine)) continue;
		const hub = hubs.get(hubEnd);
		for (const r of b.relations) {
			if (!flies(r.kind)) continue;
			if (lift(r.to) === hubEnd) {
				const into = r.on_failure ? failed : produced;
				const k = `${machine}|${hubEnd}`;
				const e = into.get(k) ?? {
					machine,
					hub,
					rels: []
				};
				e.rels.push(r);
				into.set(k, e);
			} else if (lift(r.from) === hubEnd) {
				const k = `${machine}|${hubEnd}|${r.group ?? ""}`;
				const e = consumed.get(k) ?? {
					machine,
					hub,
					group: r.group,
					rels: []
				};
				e.rels.push(r);
				consumed.set(k, e);
			}
		}
	}
	const ids = (rels) => rels.map((r) => r.id).sort(byStr$3);
	const failures = [...failed.values()].map(({ machine, hub, rels }) => ({
		machine,
		item: hub.item,
		dlq: hub.topic,
		flight: "failure",
		viaRelations: ids(rels)
	})).sort((p, q) => byStr$3(p.machine, q.machine) || byStr$3(p.dlq, q.dlq));
	const producers = [...produced.values()].map(({ machine, hub, rels }) => ({
		machine,
		item: hub.item,
		topic: hub.topic,
		flight: hub.delivery === "queue" ? "enqueue" : "produce",
		viaRelations: ids(rels)
	})).sort((p, q) => byStr$3(p.machine, q.machine) || byStr$3(p.topic, q.topic));
	const consumers = [...consumed.values()].map(({ machine, hub, group, rels }) => {
		rels.sort((p, q) => byStr$3(p.id, q.id));
		const subscription = rels.find((r) => r.subscription)?.subscription;
		const reps = rels.map((r) => replicasOf(model, r.to)).filter((n) => n !== void 0);
		const replicas = reps.length ? Math.max(...reps) : void 0;
		const dlqs = new Set([...hubs.values()].filter((h) => h.dlqOf === hub.topic).map((h) => h.topic));
		const onFailureTo = failures.find((f) => f.machine === machine && dlqs.has(f.dlq))?.dlq;
		const flight = subscription ?? (hub.delivery === "queue" ? "take" : "copy");
		const tags = [...group ? [`group ${group}`] : [], ...replicas && replicas > 1 ? [`${replicas} replicas`] : []];
		const c = {
			machine,
			item: hub.item,
			topic: hub.topic,
			flight,
			tags,
			viaRelations: ids(rels)
		};
		if (group !== void 0) c.group = group;
		if (replicas !== void 0) c.replicas = replicas;
		if (subscription) c.subscription = subscription;
		if (onFailureTo) c.onFailureTo = onFailureTo;
		return c;
	}).sort((p, q) => byStr$3(p.machine, q.machine) || byStr$3(p.topic, q.topic) || byStr$3(p.group ?? "", q.group ?? ""));
	const fields = /* @__PURE__ */ new Map();
	for (const h of hubs.values()) fields.set(h.broker, [...fields.get(h.broker) ?? [], h]);
	return {
		airfields: [...fields.entries()].sort(([p], [q]) => byStr$3(p, q)).map(([broker, list]) => ({
			broker,
			hubs: list.sort((p, q) => byStr$3(p.topic, q.topic))
		})),
		producers,
		consumers,
		failures
	};
}
/** Replicas of the service that runs `id`: the nearest service up its parents. */
function replicasOf(model, id) {
	let cur = id;
	const seen = /* @__PURE__ */ new Set();
	while (cur && !seen.has(cur)) {
		seen.add(cur);
		const n = model.nodes.get(cur);
		if (!n) return void 0;
		if (n.kind === "service") return n.replicas;
		cur = n.parent ?? void 0;
	}
}
// src/factory/layout.ts
/** Tiles a zone's label needs: its upper-case name at 9.5 px (a generous 7.5 px a letter) plus a margin. */
var labelTiles = (name) => Math.ceil((name.length * 7.5 + 12) / 24);
var M = 2;
var GX0 = 6;
var GY0 = 4;
var PAD = 1;
var DOOR_GAP = 3;
var LABEL = 1;
var AIR_MIN = 4;
var ROWS = /* @__PURE__ */ new Set([
	"shelf",
	"bay",
	"hubs"
]);
var ROW_TILES = 60;
function laneGaps(tf) {
	const order = tf.lanes.map((_, i) => i).sort((a, b) => tf.lanes[a].y - tf.lanes[b].y);
	const out = [];
	for (let k = 0; k + 1 < order.length; k++) {
		const a = tf.lanes[order[k]], b = tf.lanes[order[k + 1]];
		const g = {
			above: order[k],
			below: order[k + 1],
			x0: Math.max(a.x0, b.x0),
			x1: Math.min(a.x1, b.x1),
			y0: a.y + 3,
			y1: b.y
		};
		if (g.x1 > g.x0 && g.y1 > g.y0) out.push(g);
	}
	return out;
}
function layoutTiles(model, container, doors = [], opts = {}) {
	return settleChests(soleCaches(model, container).keys(), (laned) => layoutOnce(model, container, doors, laned.size ? {
		...opts,
		laned
	} : opts), opts.laned);
}
/** Lays a floor out (`pass`) until every single-owner cache (`sole`) is either a chest or in the `laned` set: a cache
*  with no room for its chest keeps its lane, and the floor is laid out again with that lane. A new lane may take
*  another chest's room, so this repeats until the set stops changing; it only grows, so it ends within one pass per
*  cache. Every cache then has a chest or a lane, and every note names a real lane. */
function settleChests(sole, pass, start = /* @__PURE__ */ new Set()) {
	const caches = [...sole];
	let laned = new Set(start), tf = pass(laned);
	for (let i = 0; i < caches.length; i++) {
		const lost = caches.filter((id) => !laned.has(id) && tf.boxes.get(id)?.foot !== "chest");
		if (!lost.length) break;
		laned = /* @__PURE__ */ new Set([...laned, ...lost]);
		tf = pass(laned);
	}
	return tf;
}
/** Caches only one machine uses on the site floor, each with that machine: store id → machine id. "One machine" is
*  counted by lifted bundle ends, so a service's several methods are one user. Inside a factory, none. */
function soleCaches(model, container) {
	const out = /* @__PURE__ */ new Map();
	if (container !== "site") return out;
	const items = model.floor("site")?.items ?? {};
	const users = /* @__PURE__ */ new Map();
	for (const b of model.bundles(SITE).bundles) for (const [s, o] of [[b.a, b.b], [b.b, b.a]]) {
		const n = model.nodes.get(s);
		if (n?.kind !== "datastore" || n.store !== "cache" || !(s in items)) continue;
		(users.get(s) ?? users.set(s, /* @__PURE__ */ new Set()).get(s)).add(o);
	}
	for (const [s, us] of users) if (us.size === 1) out.set(s, [...us][0]);
	return out;
}
function layoutOnce(model, container, doors, opts) {
	const gap = opts.gap ?? 0;
	const GX = GX0 + gap, GY = GY0 + gap;
	const floor = model.floor(container);
	if (!floor) throw new Error(`no floor for ${container}`);
	const site = container === SITE;
	const boxes = /* @__PURE__ */ new Map();
	const zones = [];
	const lanes = [];
	const kindOf = (id) => model.kindOf(id);
	const pairs = model.implementLinks(container);
	const put = (id, kind, region, x, y, foot = footprintFor(kind, site), size = FOOT[foot]) => {
		const [w, h] = size;
		const b = {
			id,
			kind,
			foot,
			region,
			x,
			y,
			w,
			h
		};
		boxes.set(id, b);
		return b;
	};
	const cells = (...regions) => Object.entries(floor.items).filter(([, c]) => regions.includes(c.region)).sort(([, p], [, q]) => p.row - q.row || p.col - q.col);
	/** The scanner's cells on a uniform grid from (x0, y0), gaps left by items placed elsewhere closed up.
	*  `wrap`: a grid taller than 0.8 x its width (pitch counted) is re-wrapped to a screen shape. */
	const grid = (list, region, x0, y0, wrap = false) => {
		if (!list.length) return [];
		const sizes = list.map(([id]) => FOOT[footprintFor(kindOf(id), site)]);
		const pw = Math.max(...sizes.map((s) => s[0])) + GX, ph = Math.max(...sizes.map((s) => s[1])) + GY;
		const cols = [...new Set(list.map(([, c]) => c.col))].sort((a, b) => a - b);
		const rows = [...new Set(list.map(([, c]) => c.row))].sort((a, b) => a - b);
		if (wrap && rows.length * ph > .8 * cols.length * pw) {
			const n = list.length;
			const ordered = [...list].sort(([, p], [, q]) => p.col - q.col || p.row - q.row);
			let best = 1, bestD = Infinity;
			for (let c = 1; c <= n; c++) {
				const d = Math.abs(c * pw / (Math.ceil(n / c) * ph) - 1.6);
				if (d < bestD - 1e-9) {
					best = c;
					bestD = d;
				}
			}
			const per = Math.ceil(n / best);
			const runs = Array.from({ length: Math.ceil(n / per) }, (_, c) => Math.min(per, n - c * per));
			return (besideOrder(ordered.map(([id]) => id), runs) ?? ordered.map(([id]) => id)).map((id, i) => put(id, kindOf(id), region, x0 + Math.floor(i / per) * pw, y0 + i % per * ph));
		}
		if (ROWS.has(region) && rows.length === 1 && cols.length * pw > ROW_TILES && cols.length * pw > 3.2 * ph) {
			const n = list.length, ordered = [...list].sort(([, p], [, q]) => p.col - q.col);
			let per = n, bestD = Infinity;
			for (let r = 1; r <= n; r++) {
				const c = Math.ceil(n / r), d = Math.abs(c * pw / (r * ph) - 1.6);
				if (d < bestD - 1e-9) {
					per = c;
					bestD = d;
				}
			}
			return ordered.map(([id], i) => put(id, kindOf(id), region, x0 + i % per * pw, y0 + Math.floor(i / per) * ph));
		}
		const ordered = [...list].sort(([, p], [, q]) => p.col - q.col || p.row - q.row);
		const slots = ordered.map(([, c]) => [cols.indexOf(c.col), rows.indexOf(c.row)]);
		const runs = [];
		slots.forEach(([cx, ry], i) => {
			if (i && cx === slots[i - 1][0] && ry === slots[i - 1][1] + 1) runs[runs.length - 1]++;
			else runs.push(1);
		});
		const ids = besideOrder(ordered.map(([id]) => id), runs);
		if (ids) return ids.map((id, i) => put(id, kindOf(id), region, x0 + slots[i][0] * pw, y0 + slots[i][1] * ph));
		return list.map(([id, c]) => put(id, kindOf(id), region, x0 + cols.indexOf(c.col) * pw, y0 + rows.indexOf(c.row) * ph));
	};
	/** Implementations beside their interfaces (owner, 2026-10-06), within one region's grid. `ids` in reading order;
	*  `runs`: the grid's slots in that order cut into runs of neighbours (consecutive slots of a run touch). A unit is an
	*  interface followed by its implementations (each beside the first interface it implements, by id; an
	*  implementation that is itself implemented brings its own after it). A unit takes the reading place of its earliest
	*  item (an interface read after its implementation moves up to it: fewer lines cross than when the implementation
	*  always moves). Each run takes the first unit that still fits in it, so a pair is never cut by a run's end while a
	*  smaller unit fills the gap (a unit no run can hold is cut). Undefined when no pair lies inside `ids`: the grid as
	*  before. */
	const besideOrder = (ids, runs) => {
		const here = new Set(ids);
		const anchor = /* @__PURE__ */ new Map();
		for (const l of pairs) if (here.has(l.trait) && here.has(l.impl) && (!anchor.has(l.impl) || l.trait < anchor.get(l.impl))) anchor.set(l.impl, l.trait);
		if (!anchor.size) return void 0;
		const done = /* @__PURE__ */ new Set();
		const emit = (id, unit) => {
			if (done.has(id)) return;
			done.add(id);
			unit.push(id);
			for (const i of ids) if (anchor.get(i) === id) emit(i, unit);
		};
		const units = [];
		for (const id of ids) if (!anchor.has(id) && !done.has(id)) {
			const u = [];
			emit(id, u);
			units.push(u);
		}
		for (const id of ids) if (!done.has(id)) {
			const u = [];
			emit(id, u);
			units.push(u);
		}
		const at = new Map(ids.map((id, i) => [id, i])), first = (u) => Math.min(...u.map((id) => at.get(id)));
		units.sort((p, q) => first(p) - first(q));
		const out = [];
		for (const len of runs) {
			let room = len;
			while (room > 0 && units.length) {
				const k = Math.max(0, units.findIndex((u) => u.length <= room));
				const u = units.splice(k, 1)[0];
				out.push(...u.slice(0, room));
				if (u.length > room) units.unshift(u.slice(room));
				room -= Math.min(room, u.length);
			}
		}
		return out;
	};
	/** The work grid: its corridors get their own extra width. Machines right of / below corridor i move over by the
	*  sum of the extras before them, so no two machines come closer. */
	let workList = [];
	const work = (list) => {
		workList = list;
		const xs = [...new Set(list.map((b) => b.x))].sort((p, q) => p - q);
		const ys = [...new Set(list.map((b) => b.y))].sort((p, q) => p - q);
		const sum = (g, n) => {
			let t = 0;
			for (let i = 0; i < n; i++) t += g?.[i] ?? 0;
			return t;
		};
		for (const b of list) {
			b.x += sum(opts.colGaps, xs.indexOf(b.x));
			b.y += sum(opts.rowGaps, ys.indexOf(b.y));
		}
	};
	/** The work grid's corridors where its machines finally stand (after any spreading down the room). Approximate on an
	*  inside floor with several region grids: their pitches differ, so a "column" is any distinct left edge and a
	*  corridor between two of them may be narrower than the real aisle (or 0 where grids of different pitch meet). */
	const measureAisles = (list) => {
		if (!list.length) return {
			cols: [],
			rows: []
		};
		const xs = [...new Set(list.map((b) => b.x))].sort((p, q) => p - q);
		const ys = [...new Set(list.map((b) => b.y))].sort((p, q) => p - q);
		const x0 = xs[0], y0 = ys[0], x1 = right(list, 0), y1 = bottom(list, 0);
		const reach = (pick, far) => Math.max(...list.filter(pick).map(far));
		return {
			cols: xs.slice(1).map((x, i) => {
				const l = reach((b) => b.x === xs[i], (b) => b.x + b.w);
				return {
					x: l,
					y: y0,
					w: Math.max(0, x - l),
					h: y1 - y0
				};
			}),
			rows: ys.slice(1).map((y, j) => {
				const t = reach((b) => b.y === ys[j], (b) => b.y + b.h);
				return {
					x: x0,
					y: t,
					w: x1 - x0,
					h: Math.max(0, y - t)
				};
			})
		};
	};
	const isQueue = (topic) => {
		const n = model.nodes.get(topic);
		return (n?.kind === "topic" || n?.kind === "in-process-queue") && n.delivery === "queue";
	};
	/** A queue hub's waiting stack: the tile right of its bottom row (as the mock draws it). */
	const stackTile = (b) => ({
		x: b.x + b.w,
		y: b.y + b.h - 1,
		w: 1,
		h: 1
	});
	/** Hub order in an airfield: the scanner's, but each dead-letter hub moved to the slot right after its source. */
	const dlqNext = (ids) => {
		const here = new Set(ids);
		const srcOf = (id) => {
			const s = model.nodes.get(id)?.dead_letter_of;
			return s && s !== id && here.has(s) ? s : void 0;
		};
		const out = [], done = /* @__PURE__ */ new Set();
		const emit = (id) => {
			if (done.has(id)) return;
			done.add(id);
			out.push(id);
			for (const d of ids) if (srcOf(d) === id) emit(d);
		};
		for (const id of ids) if (!srcOf(id)) emit(id);
		for (const id of ids) emit(id);
		return out;
	};
	const right = (list, fallback) => list.length ? Math.max(...list.map((b) => b.x + b.w)) : fallback;
	const bottom = (list, fallback) => list.length ? Math.max(...list.map((b) => b.y + b.h)) : fallback;
	/** A zone round `list`, one tile off its machines, with a label row at the bottom; undefined when empty. */
	const zone = (name, list, airfield = false) => {
		if (!list.length) return void 0;
		const x = Math.min(...list.map((b) => b.x)) - PAD, y = Math.min(...list.map((b) => b.y)) - PAD;
		const z = {
			name,
			x,
			y,
			w: Math.max(right(list, 0) + PAD - x, labelTiles(name)) + (opts.zoneWiden?.[name] ?? 0),
			h: bottom(list, 0) + PAD + LABEL - y,
			airfield
		};
		zones.push(z);
		return z;
	};
	/** First content row below a zone (a two-tile aisle between zones). */
	const next = (z, y) => z ? z.y + z.h + 2 + gap + PAD : y;
	const laneBand = (l) => ({
		x: l.x0,
		y: l.y,
		w: l.x1 - l.x0,
		h: 3
	});
	/** One lane per database or busy item, its box at the lane's left end; returns the next free row. */
	const laneRows = (list, x, y, x1) => {
		for (const l of list) {
			const b = put(l.box, l.kind, l.kind === "datastore" ? "bus" : "lane", x, y, l.kind === "datastore" ? "warehouse" : void 0);
			lanes.push({
				id: l.id,
				label: model.label(l.id),
				x0: x + b.w,
				x1: Math.max(x1, x + b.w + 6),
				y: y + Math.floor((b.h - 3) / 2)
			});
			y += Math.max(b.h, 3) + 2 + gap + (opts.laneGaps?.[lanes.length - 1] ?? 0);
		}
		return y;
	};
	const chests = new Map([...soleCaches(model, container)].filter(([id]) => !opts.laned?.has(id)));
	const chestName = (id) => shownName(model, id, floorPrefix(model, Object.keys(floor.items)));
	const why = (id) => chestSize(chestName(id)) ? `no room beside ${soleCaches(model, container).get(id)}` : "its name does not fit a chest";
	const gaps = [];
	const notes = [...opts.laned ?? []].sort().map((id) => `chest: ${id} stays a lane: ${why(id)}`);
	if (site) {
		const stores = cells("bus").filter(([id]) => kindOf(id) === "datastore" && !chests.has(id));
		const busy = cells("lane");
		const x0 = M + (stores.length || busy.length ? FOOT.warehouse[0] + GX : 0) + PAD;
		let y = 3;
		const shelf = grid(cells("shelf"), "shelf", x0, y);
		const hubs = grid(cells("hubs"), "hubs", x0, shelf.length ? bottom(shelf, y) + GY : y);
		y = next(zone("library shelf", [...shelf, ...hubs]), y);
		const line = cells("line", "grid");
		const works = grid(line.filter(([id]) => kindOf(id) !== "external"), "line", x0, y, true);
		work(works);
		const ox = right(works, x0) + GX + 2 + (opts.zoneWiden?.["production line"] ?? 0);
		const [dw, dh] = FOOT.dock;
		const perCol = Math.max(1, Math.floor((bottom(works, y) - y + GY) / (dh + GY)));
		const outside = line.filter(([id]) => kindOf(id) === "external").map(([id], i) => put(id, "external", "outside", ox + Math.floor(i / perCol) * (dw + GX), y + i % perCol * (dh + GY)));
		y = Math.max(next(zone("production line", works), y), next(zone("outside world", outside), y));
		const topics = cells("bus").filter(([id]) => kindOf(id) === "topic");
		const brokers = [...new Set(topics.map(([id]) => id.split(":")[1]))].sort();
		let ax = x0;
		const ay = y;
		let yAir = y;
		for (const br of brokers) {
			const own = dlqNext(topics.filter(([id]) => id.split(":")[1] === br).map(([id]) => id)).map((id, i) => put(id, "topic", "airfield", ax + i * (FOOT.hub[0] + GX), ay));
			const z = zone(br, [...own, ...own.flatMap((b) => isQueue(b.id) ? [stackTile(b)] : [])], true);
			ax = z.x + z.w + 2 + gap + PAD;
			yAir = Math.max(yAir, next(z, y));
		}
		if (brokers.length) y = Math.max(yAir, next(zone("read-only", grid(cells("bay"), "bay", ax, ay)), y));
		const x1 = right([...boxes.values()], x0 + 20) + PAD;
		const sy = y;
		y = laneRows([...stores.map(([id]) => ({
			id,
			box: id,
			kind: "datastore"
		})), ...busy.map(([id]) => ({
			id,
			box: id,
			kind: kindOf(id)
		}))], M, y, x1);
		const rest = grid(cells("bus").filter(([id]) => kindOf(id) !== "topic" && kindOf(id) !== "datastore"), "bus", x0, y);
		y = next(zone("storage", [
			...[...boxes.values()].filter((b) => b.y >= sy && (b.region === "bus" || b.region === "lane")),
			...rest,
			...lanes.map(laneBand)
		]), y);
		if (!brokers.length) zone("read-only", grid(cells("bay"), "bay", x0, y));
		const edge = right([...boxes.values()], 0) + PAD;
		for (const l of lanes) l.x1 = Math.max(l.x1, edge);
		for (const [id, owner] of [...chests].sort(([p], [q]) => p < q ? -1 : p > q ? 1 : 0)) {
			const size = chestSize(chestName(id));
			const spot = size && chestSpot(boxes.get(owner), size, [...boxes.values()], lanes.map(laneBand), zones);
			if (spot) {
				put(id, "datastore", "chest", spot.x, spot.y, "chest", size);
				gaps.push(chestGap(boxes.get(owner), {
					...spot,
					w: size[0],
					h: size[1]
				}));
			} else notes.push(`chest: ${id} stays a lane: ${why(id)}`);
		}
	} else {
		const isLib = (d) => kindOf(d.anchor) === "library";
		const isStore = (d) => kindOf(d.anchor) === "datastore";
		const ins = doors.filter((d) => d.side === "in" && !isLib(d) && !isStore(d));
		const outs = doors.filter((d) => d.side === "out" && !isLib(d) && !isStore(d));
		const libs = doors.filter(isLib);
		const colW = FOOT.door[0] + 2;
		const cx = 3;
		const wx = M + (ins.length || libs.length ? colW + GX : 0) + PAD;
		const top = 3;
		let y = top;
		const placedAll = [];
		for (const region of [
			"shelf",
			"hubs",
			"line",
			"grid",
			"bus",
			"bay"
		]) {
			const placed = grid(cells(region), region, wx, y, region === "line");
			placedAll.push(...placed);
			if (placed.length) y = bottom(placed, y) + GY;
		}
		work(placedAll);
		if (placedAll.length) y = bottom(placedAll, y) + GY;
		const perRow = Math.max(AIR_MIN, Math.floor((right(placedAll, wx) - wx + GX) / (FOOT.hub[0] + GX)));
		const inq = cells("airfield").map(([id], i) => put(id, kindOf(id), "airfield", wx + i % perRow * (FOOT.hub[0] + GX), y + Math.floor(i / perRow) * (FOOT.hub[1] + GY)));
		if (inq.length) y = bottom(inq, y) + PAD + LABEL + GY;
		const x1 = right([...boxes.values()], wx + 20) + PAD;
		y = laneRows([...doors.filter(isStore).map((d) => ({
			id: d.anchor,
			box: d.id,
			kind: "datastore"
		})), ...cells("lane").map(([id]) => ({
			id,
			box: id,
			kind: kindOf(id)
		}))], wx, y, x1);
		const floorBottom = Math.max(y, 9);
		const rowExtras = (opts.rowGaps ?? []).reduce((t, g) => t + g, 0);
		const plainBottom = Math.max(y - rowExtras, 9);
		const dh = FOOT.door[1], ih = FOOT.installed[1];
		const tail = 2;
		const both = ins.length > 0 && libs.length > 0;
		const yardDoor = ins.find((d) => d.id === opts.inYard?.door)?.id;
		const keep = yardDoor ? opts.inYard.rows : 0;
		const leftNeed = top + keep + ins.length * dh + libs.length * ih + (Math.max(0, ins.length + libs.length - 1) - (both ? 1 : 0)) * DOOR_GAP + (both ? 4 : 0) + tail;
		const rightNeed = top + outs.length * dh + Math.max(0, outs.length - 1) * DOOR_GAP + tail;
		const plainRoom = Math.max(plainBottom, leftNeed, rightNeed);
		const extra = plainRoom - plainBottom;
		const lanesBox = (l) => [...boxes.values()].find((b) => b.x + b.w === l.x0 && b.y <= l.y && l.y < b.y + b.h);
		const rowYs = [...new Set([...boxes.values()].map((b) => b.y))].sort((p, q) => p - q);
		const colXs = [...new Set([...boxes.values()].map((b) => b.x))].sort((p, q) => p - q);
		const rowPer = extra > 0 && rowYs.length > 1 ? Math.floor(extra / (rowYs.length - 1)) : 0;
		const colPer = colXs.length > 1 ? rowPer : 0;
		const room = Math.max(plainRoom, floorBottom + rowPer * Math.max(0, rowYs.length - 1));
		if (rowPer > 0) {
			const lb = new Map(lanes.map((l) => [l, lanesBox(l)]));
			for (const l of lanes) {
				const b = lb.get(l);
				if (b) l.y += rowYs.indexOf(b.y) * rowPer;
			}
			for (const b of boxes.values()) {
				b.y += rowYs.indexOf(b.y) * rowPer;
				b.x += colXs.indexOf(b.x) * colPer;
			}
			for (const l of lanes) {
				const b = lb.get(l);
				if (b) l.x0 = b.x + b.w;
			}
			const edge = right([...boxes.values()], 0) + PAD;
			for (const l of lanes) l.x1 = Math.max(l.x1 + colPer * (colXs.length - 1), edge);
		}
		const air = zone(IN_PROCESS, [...inq, ...inq.flatMap((b) => isQueue(b.id) ? [stackTile(b)] : [])], true);
		/** A fixed-width column zone from row y0; returns the first row below it. */
		const column = (name, list, x, y0, y1 = 0) => {
			if (!list.length) return y0;
			const z = {
				name,
				x: x - PAD,
				y: y0 - PAD,
				w: Math.max(colW, labelTiles(name)),
				h: Math.max(y1, bottom(list, y0) + tail) - (y0 - PAD),
				airfield: false
			};
			zones.push(z);
			return z.y + z.h + 1 + PAD;
		};
		/** Doors spread evenly down the column: the spare room divided between them (at least DOOR_GAP apart). */
		const spread = (n, used, avail) => n > 1 ? Math.max(DOOR_GAP, DOOR_GAP + Math.floor((avail - used) / (n - 1))) : 0;
		const gL = spread(ins.length + libs.length - (both ? 1 : 0), leftNeed - top, room - top);
		let dy = top;
		const libTop = column("in", ins.map((d) => {
			const b = put(d.id, "door", "in", cx, dy, "door");
			dy += dh + gL + (d.id === yardDoor ? keep : 0);
			return b;
		}), cx, top, yardDoor ? bottom([boxes.get(yardDoor)], top) + keep + tail : 0);
		dy = libTop;
		column("installed libraries", libs.map((d) => {
			const b = put(d.id, "door", "installed", cx, dy, "installed");
			dy += ih + gL;
			return b;
		}), cx, libTop, room);
		const ox = Math.max(right([...boxes.values(), ...lanes.map(laneBand)], x1) + GX + PAD, air ? air.x + air.w + GX : 0);
		const gR = spread(outs.length, rightNeed - top, room - top);
		column("out", outs.map((d, i) => put(d.id, "door", "out", ox, top + i * (dh + gR), "door")), ox, top, Math.max(room, ...zones.map((z) => z.y + z.h)));
	}
	const all = [
		...boxes.values(),
		...zones,
		...lanes.map(laneBand)
	];
	const tf = {
		boxes,
		lanes,
		zones,
		cols: right(all, 18) + M,
		rows: bottom(all, 10) + M,
		strategy: floor.strategy,
		site,
		aisles: measureAisles(workList)
	};
	if (notes.length) tf.notes = notes;
	if (gaps.length) tf.chestGaps = gaps;
	const stacks = queueStacks(tf, (id) => {
		const t = doorAnchor(id);
		return isQueue(t) ? t : void 0;
	});
	if (stacks.length) tf.stacks = stacks;
	return tf;
}
/** Where a `w`×`h` cache chest stands beside its machine `b`: one tile off it (the gap its taps cross), centred on that side, on
*  the first side with room in the order below, right, left, above. Room: the chest and a one-tile ring round it (the
*  gap, and a corridor on its other sides) touch no box or lane and stay inside `b`'s zone, off its label row, so the
*  zone's edges and names are untouched. Undefined when no side has room (or `b` is in no zone). */
function chestSpot(b, [w, h], boxes, lanes, zones) {
	if (!b) return void 0;
	const z = zones.find((q) => b.x >= q.x && b.y >= q.y && b.x + b.w <= q.x + q.w && b.y + b.h <= q.y + q.h);
	if (!z) return void 0;
	const midX = b.x + Math.floor((b.w - w) / 2), midY = b.y + Math.floor((b.h - h) / 2);
	const sides = [
		{
			x: midX,
			y: b.y + b.h + 1
		},
		{
			x: b.x + b.w + 1,
			y: midY
		},
		{
			x: b.x - 1 - w,
			y: midY
		},
		{
			x: midX,
			y: b.y - 1 - h
		}
	];
	const hit = (r, q) => r.x < q.x + q.w && q.x < r.x + r.w && r.y < q.y + q.h && q.y < r.y + r.h;
	return sides.find((s) => {
		const ring = {
			x: s.x - 1,
			y: s.y - 1,
			w: w + 2,
			h: h + 2
		};
		return ring.x >= z.x && ring.y >= z.y && ring.x + ring.w <= z.x + z.w && ring.y + ring.h <= z.y + z.h - LABEL && !boxes.some((q) => hit(ring, q)) && !lanes.some((q) => hit(ring, q));
	});
}
/** The tiles between chest `c` and its machine `b` (one tile apart on one side), across the run both share. */
function chestGap(b, c) {
	const x0 = Math.max(b.x, c.x), x1 = Math.min(b.x + b.w, c.x + c.w), y0 = Math.max(b.y, c.y), y1 = Math.min(b.y + b.h, c.y + c.h);
	if (x1 > x0) return {
		x: x0,
		y: c.y > b.y ? b.y + b.h : b.y - 1,
		w: x1 - x0,
		h: 1
	};
	return {
		x: c.x > b.x ? b.x + b.w : b.x - 1,
		y: y0,
		w: 1,
		h: y1 - y0
	};
}
/** One free tile beside each queue hub (`topicOf` names a hub's topic when it is a queue): right of its bottom row, else
*  left of it, else under or over its middle; a tile on another box, a lane or another stack is not free. */
function queueStacks(tf, topicOf) {
	const out = [];
	const taken = (x, y) => x < 0 || y < 0 || x >= tf.cols || y >= tf.rows || [...tf.boxes.values()].some((b) => x >= b.x && x < b.x + b.w && y >= b.y && y < b.y + b.h) || tf.lanes.some((l) => x >= l.x0 && x < l.x1 && y >= l.y && y < l.y + 3) || out.some((s) => s.x === x && s.y === y);
	for (const b of [...tf.boxes.values()].sort((p, q) => p.id < q.id ? -1 : p.id > q.id ? 1 : 0)) {
		const topic = topicOf(b.id);
		if (!topic) continue;
		const mid = b.x + Math.floor((b.w - 1) / 2);
		const spot = [
			[b.x + b.w, b.y + b.h - 1],
			[b.x - 1, b.y + b.h - 1],
			[mid, b.y + b.h],
			[mid, b.y - 1]
		].find(([x, y]) => !taken(x, y));
		if (spot) out.push({
			item: b.id,
			topic,
			x: spot[0],
			y: spot[1]
		});
	}
	return out;
}
// src/factory/batch.ts
var byStr$2 = (a, b) => a < b ? -1 : a > b ? 1 : 0;
var byJob = (p, q) => byStr$2(p.job, q.job) || byStr$2(p.relation, q.relation);
/** `bundles` is taken for symmetry with messaging(); a scheduler's jobs on itself and an inner yard's jobs never form
*  bundles, so the relations are read from the map with the same lift. */
function batch(model, container, tf, _bundles) {
	const onSite = container === SITE;
	const lift = (id) => model.liftTo(container, id) ?? (onSite ? void 0 : model.doorId(model.anchorFor(container, id)));
	const above = new Set(onSite ? [] : model.path(container));
	const yards = /* @__PURE__ */ new Map();
	for (const r of model.map.relations) {
		if (r.kind !== "batch") continue;
		const dest = lift(r.to);
		if (!dest || !tf.boxes.has(dest)) continue;
		let source, inner = false;
		if (above.has(r.from) && model.liftTo(container, r.from) === void 0) {
			if (r.from !== container && model.liftTo(container, r.to) === void 0) continue;
			source = container;
			inner = true;
		} else {
			source = model.liftTo(container, r.from);
			if (!source || !tf.boxes.has(source)) continue;
		}
		const y = yards.get(source) ?? {
			inner,
			dests: /* @__PURE__ */ new Map(),
			self: []
		};
		yards.set(source, y);
		const j = jobOf(r);
		if (!inner && dest === source) y.self.push(j);
		else y.dests.set(dest, [...y.dests.get(dest) ?? [], j]);
	}
	return { yards: [...yards.entries()].sort(([p], [q]) => byStr$2(p, q)).map(([source, y]) => {
		const platforms = [...y.dests.entries()].sort(([p], [q]) => byStr$2(p, q)).map(([dest, jobs]) => ({
			dest,
			jobs: jobs.sort(byJob),
			runsPerDay: knownRuns(jobs)
		}));
		const selfJobs = y.self.sort(byJob);
		return {
			source,
			platforms,
			selfJobs,
			sign: summarise([...selfJobs, ...platforms.flatMap((p) => p.jobs)]),
			inner: y.inner
		};
	}) };
}
/** A platform's worth of jobs for `dest` from these batch relations (a yard-less station's, its scheduler off the floor). */
function platformOf(dest, relations) {
	const jobs = relations.filter((r) => r.kind === "batch").map(jobOf).sort(byJob);
	return {
		dest,
		jobs,
		runsPerDay: knownRuns(jobs)
	};
}
function jobOf(r) {
	return {
		relation: r.id,
		job: r.job ?? r.key ?? r.id,
		schedule: r.schedule ?? null,
		target: r.to
	};
}
/** Sum of the known runs a day of these jobs, or null when none is known. */
function knownRuns(jobs) {
	let sum = 0, any = false;
	for (const j of jobs) for (const s of j.schedule ?? []) {
		const n = runsPerDay(s);
		if (n !== null) {
			sum += n;
			any = true;
		}
	}
	return any ? sum : null;
}
var DOW = [
	"sun",
	"mon",
	"tue",
	"wed",
	"thu",
	"fri",
	"sat"
];
var MON = [
	"jan",
	"feb",
	"mar",
	"apr",
	"may",
	"jun",
	"jul",
	"aug",
	"sep",
	"oct",
	"nov",
	"dec"
];
var DOW_NAME = [
	"Sun",
	"Mon",
	"Tue",
	"Wed",
	"Thu",
	"Fri",
	"Sat"
];
/** The five fields of a cron line (a six-field line drops its seconds), or null when it is not one. */
function fields(cron) {
	const f = cron.trim().split(/\s+/).filter(Boolean);
	if (f.length === 6) f.shift();
	if (f.length !== 5) return null;
	const [minute, hour, dom, month, dow] = f;
	return {
		minute,
		hour,
		dom,
		month,
		dow
	};
}
var wild = (f) => f === "*" || f === "?";
/** The values a cron field fires on, or null when it does not parse. */
function values(field, min, max, names = [], nameBase = 0) {
	const num = (s) => {
		const i = names.indexOf(s.toLowerCase());
		if (i >= 0) return i + nameBase;
		if (!/^\d+$/.test(s)) return null;
		const n = Number(s);
		return n >= min && n <= max ? n : null;
	};
	const out = /* @__PURE__ */ new Set();
	for (const part of field.split(",")) {
		const [base, stepS, extra] = part.split("/");
		if (extra !== void 0 || base === "") return null;
		const step = stepS === void 0 ? 1 : /^\d+$/.test(stepS) ? Number(stepS) : 0;
		if (step < 1) return null;
		let lo, hi;
		if (wild(base)) {
			lo = min;
			hi = max;
		} else if (base.includes("-")) {
			const [a, b, more] = base.split("-");
			if (more !== void 0) return null;
			lo = num(a);
			hi = num(b);
		} else {
			lo = num(base);
			hi = stepS === void 0 ? lo : max;
		}
		if (lo === null || hi === null || lo > hi) return null;
		for (let v = lo; v <= hi; v += step) out.add(v);
	}
	return out.size ? out : null;
}
function parse(c) {
	const minutes = values(c.minute, 0, 59), hours = values(c.hour, 0, 23);
	const doms = wild(c.dom) ? null : values(c.dom, 1, 31);
	const months = wild(c.month) ? null : values(c.month, 1, 12, MON, 1);
	let dows = wild(c.dow) ? null : values(c.dow, 0, 7, DOW);
	if (!minutes || !hours || !wild(c.dom) && !doms || !wild(c.month) && !months || !wild(c.dow) && !dows) return null;
	if (dows?.has(7)) dows = new Set([...dows].map((d) => d % 7));
	return {
		minutes,
		hours,
		doms,
		months,
		dows
	};
}
/** How many times a day a schedule fires: a fraction for a weekly (1/7 per listed weekday) or monthly (1/30 per listed
*  day) one. Null for "manual", "on <event>" and anything that is not a cron line. */
function runsPerDay(cron) {
	const c = fields(cron);
	const p = c && parse(c);
	if (!p) return null;
	let perDay = p.minutes.size * p.hours.size;
	if (p.dows && p.doms) perDay *= Math.min(1, p.dows.size / 7 + p.doms.size / 30);
	else if (p.dows) perDay *= p.dows.size / 7;
	else if (p.doms) perDay *= p.doms.size / 30;
	if (p.months) perDay *= p.months.size / 12;
	return perDay;
}
var pad = (n) => String(n).padStart(2, "0");
var single = (s) => s.size === 1 ? [...s][0] : null;
var isDemand = (s) => s.trim().toLowerCase() === "manual";
var isEvent = (s) => /^on\s+\S/i.test(s.trim());
/** A cron line in words: "daily 02:00", "hourly :05", "every 15 min", "weekly Mon 01:00"; else its runs. */
function phrase(cron) {
	const c = fields(cron);
	const p = c && parse(c);
	if (!c || !p) return cron.trim() || "on demand";
	const m = single(p.minutes), h = single(p.hours);
	const anyDay = !p.doms && !p.dows && !p.months;
	if (anyDay && wild(c.hour)) {
		const step = /^\*\/(\d+)$/.exec(c.minute);
		if (wild(c.minute)) return "every minute";
		if (step && 60 % Number(step[1]) === 0) return `every ${step[1]} min`;
		if (m !== null) return `hourly :${pad(m)}`;
	}
	if (m !== null && h !== null && !p.months) {
		const at = `${pad(h)}:${pad(m)}`;
		if (anyDay) return `daily ${at}`;
		if (p.dows && !p.doms) return `weekly ${[...p.dows].sort((a, b) => a - b).map((d) => DOW_NAME[d]).join(",")} ${at}`;
		if (p.doms && !p.dows) return `monthly day ${[...p.doms].sort((a, b) => a - b).join(",")} ${at}`;
	}
	return rate(runsPerDay(cron) ?? 0) ?? cron.trim();
}
/** A run count as a rate, never 0: per day, else per week, else per month; null when it is nothing at all. */
function rate(perDay) {
	if (perDay >= 1) return `${Math.round(perDay)}×/day`;
	if (Math.round(perDay * 7) >= 1) return `${Math.round(perDay * 7)}×/week`;
	if (Math.round(perDay * 30) >= 1) return `${Math.round(perDay * 30)}×/month`;
	return perDay > 0 ? "<1×/month" : null;
}
/** The yard's sign: one job reads its schedule in words; several read "N jobs · K×/day", with "+ on demand" when some
*  have no schedule. Never empty, never "0×/day". */
function summarise(jobs) {
	if (jobs.length === 0) return "no jobs";
	if (jobs.length === 1) {
		const s = (jobs[0].schedule ?? []).filter((x) => x.trim());
		if (s.length === 0 || s.every(isDemand)) return "on demand";
		if (s.length === 1) return isEvent(s[0]) ? s[0].trim().replace(/\s+/g, " ") : phrase(s[0]);
	}
	let sum = 0, known = false, demand = false, events = false;
	for (const j of jobs) {
		const s = (j.schedule ?? []).filter((x) => x.trim());
		if (s.length === 0 || s.every(isDemand)) {
			demand = true;
			continue;
		}
		for (const x of s) {
			const n = runsPerDay(x);
			if (n !== null) {
				sum += n;
				known = true;
			} else if (isEvent(x)) events = true;
			else if (isDemand(x)) demand = true;
		}
	}
	const tail = [...demand ? ["on demand"] : [], ...events ? ["on events"] : []];
	const head = known ? rate(sum) : null;
	const what = jobs.length === 1 ? `${(jobs[0].schedule ?? []).length} schedules` : `${jobs.length} jobs`;
	if (head) return [`${what} · ${head}`, ...tail].join(" + ");
	if (tail.length) return `${what} · ${tail.join(" + ")}`;
	return what;
}
/** The ids a rail's two ends go by in the router (trunks group on them) and in tests. */
var yardId = (source) => `yard:${source}`;
var stationId = (s) => `station:${s.source}>${s.dest}`;
var DEPTH = 4;
var STATION = 3;
var byStr$1 = (a, b) => a < b ? -1 : a > b ? 1 : 0;
var centre$3 = (r) => ({
	x: r.x + r.w / 2,
	y: r.y + r.h / 2
});
/** The floor's batch and its reserved tiles; undefined on a floor with no yard (it lays out and routes as before). */
function rails(model, container, tf, bundles, ladders) {
	const b = batch(model, container, tf, bundles);
	const inbound = doorRails(tf, bundles);
	if (!b.yards.length && !inbound.length) return void 0;
	const key = (x, y) => y * tf.cols + x;
	const held = /* @__PURE__ */ new Set();
	const kept = /* @__PURE__ */ new Set();
	const label = /* @__PURE__ */ new Set();
	const box = new Int32Array(tf.cols * tf.rows).fill(-1);
	const ids = [...tf.boxes.keys()];
	const hold = (r) => {
		for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) held.add(key(x, y));
	};
	ids.forEach((id, i) => {
		const r = tf.boxes.get(id);
		hold(r);
		for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) box[key(x, y)] = i;
	});
	for (const l of tf.lanes) hold({
		x: l.x0,
		y: l.y,
		w: l.x1 - l.x0,
		h: 3
	});
	for (const s of tf.stacks ?? []) hold({
		x: s.x,
		y: s.y,
		w: 1,
		h: 1
	});
	for (const d of tf.landing?.docks ?? []) hold(d);
	for (const z of tf.zones) for (let x = z.x; x < z.x + z.w; x++) label.add(key(x, z.y + z.h - 1));
	const onFloor = (x, y) => x >= 0 && y >= 0 && x < tf.cols && y < tf.rows;
	const open = (x, y) => onFloor(x, y) && !held.has(key(x, y)) && !kept.has(key(x, y));
	/** Free floor; with `named`, off every zone's label row too. */
	const clear = (r, named = true) => {
		for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) if (!open(x, y) || named && label.has(key(x, y))) return false;
		return true;
	};
	/** No box but `own` touches the rect's sides: other machines keep the tiles their lines plug into. */
	const alone = (r, own) => {
		for (let x = r.x - 1; x <= r.x + r.w; x++) for (let y = r.y - 1; y <= r.y + r.h; y++) {
			if ((x === r.x - 1 || x === r.x + r.w) === (y === r.y - 1 || y === r.y + r.h)) continue;
			if (onFloor(x, y) && box[key(x, y)] >= 0 && box[key(x, y)] !== own) return false;
		}
		return true;
	};
	const yards = [], unplaced = [];
	for (const y of b.yards) {
		const machine = machineOf(model, container, tf, y);
		const placed = placeYard(tf, y, machine, {
			clear,
			alone,
			open,
			ids
		}, ladders?.get(y.source));
		if (!placed) {
			unplaced.push({ source: y.source });
			continue;
		}
		hold(placed);
		for (const e of exits(placed)) {
			kept.add(key(e.x, e.y));
			kept.add(key(e.x + STEP[e.d][0], e.y + STEP[e.d][1]));
		}
		if (!y.platforms.length) placed.sign = {
			x: placed.x + placed.w - 1,
			y: placed.y
		};
		else {
			const s = signSpot(placed).find((p) => clear({
				x: p.x,
				y: p.y,
				w: 1,
				h: 1
			}) && alone({
				x: p.x,
				y: p.y,
				w: 1,
				h: 1
			}, machine ? ids.indexOf(machine) : -1));
			placed.sign = s ?? null;
			if (s) hold({
				x: s.x,
				y: s.y,
				w: 1,
				h: 1
			});
		}
		yards.push(placed);
	}
	const stations = [], shells = [];
	const byKey = new Map(bundles.map((q) => [q.key, q]));
	const rel = new Map(model.map.relations.map((r) => [r.id, r]));
	const carried = /* @__PURE__ */ new Set();
	for (const y of yards) {
		const jobs = new Map(b.yards.find((q) => q.source === y.source).platforms.map((p) => [p.dest, p.jobs]));
		for (const [i, p] of y.platforms.entries()) {
			const s = placeStation(tf.boxes.get(p.dest), exitOf(y, i), (r) => clear(r), (e) => open(e.x, e.y) && !label.has(key(e.x, e.y)), busy(tf, bundles, p.dest, y.machine));
			if (!s) {
				unplaced.push({
					source: y.source,
					dest: p.dest
				});
				continue;
			}
			const k = y.machine ? y.machine < p.dest ? `${y.machine}|${p.dest}` : `${p.dest}|${y.machine}` : "";
			let track = k;
			if (!k || byKey.get(k)?.kind !== "batch" || carried.has(k)) {
				const mine = jobs.get(p.dest), relations = mine.map((j) => rel.get(j.relation)).filter(Boolean);
				track = `rail:${mine[0].relation}`;
				shells.push({
					key: track,
					a: y.machine ?? yardId(y.source),
					b: p.dest,
					relations,
					kinds: { batch: relations.length },
					inferred: relations.filter((r) => r.confidence === "inferred").length,
					kind: "batch",
					flow: "a→b"
				});
			} else carried.add(k);
			const st = {
				dest: p.dest,
				source: y.source,
				...s,
				track
			};
			hold(st);
			kept.add(key(st.entry.x, st.entry.y));
			stations.push(st);
		}
	}
	for (const q of inbound) {
		if (carried.has(q.key)) continue;
		const d = tf.boxes.get(q.dest), m = tf.boxes.get(q.door);
		const s = placeStation(d, {
			x: Math.floor(m.x + m.w / 2),
			y: Math.floor(m.y + m.h / 2),
			d: "e"
		}, (r) => clear(r), (e) => open(e.x, e.y) && !label.has(key(e.x, e.y)), busy(tf, bundles, q.dest, q.door));
		if (!s) {
			unplaced.push({
				source: q.door,
				dest: q.dest
			});
			continue;
		}
		carried.add(q.key);
		const st = {
			dest: q.dest,
			source: q.door,
			...s,
			track: q.key,
			door: q.door,
			platform: platformOf(q.dest, bundles.find((x) => x.key === q.key).relations)
		};
		hold(st);
		kept.add(key(st.entry.x, st.entry.y));
		stations.push(st);
	}
	return {
		batch: b,
		yards,
		stations,
		shells,
		unplaced
	};
}
/** Batch bundles that come in by a door to an item on the floor (their scheduler lies off it): by key. */
function doorRails(tf, bundles) {
	const isDoor = (id) => tf.boxes.get(id)?.foot === "door";
	const out = [];
	for (const q of bundles) {
		if (q.kind !== "batch" || !tf.boxes.has(q.a) || !tf.boxes.has(q.b)) continue;
		const [src, dst] = q.flow === "b→a" ? [q.b, q.a] : q.flow === "a→b" ? [q.a, q.b] : isDoor(q.a) ? [q.a, q.b] : [q.b, q.a];
		if (isDoor(src) && !isDoor(dst)) out.push({
			key: q.key,
			door: src,
			dest: dst
		});
	}
	return out.sort((p, q) => byStr$1(p.key, q.key));
}
/** How many of a machine's other lines (bundles but the rail from `machine`, events excepted: drones fly) have their
*  far end wholly past each of its sides: a lane counts as its band. A station keeps off the busy sides. */
function busy(tf, bundles, id, machine) {
	const d = tf.boxes.get(id), out = {
		n: 0,
		e: 0,
		s: 0,
		w: 0
	};
	for (const b of bundles) {
		if (flies(b.kind) || b.a !== id && b.b !== id) continue;
		const other = b.a === id ? b.b : b.a;
		if (other === machine) continue;
		const lane = tf.lanes.find((l) => l.id === other);
		const r = lane ? {
			x: lane.x0,
			y: lane.y,
			w: lane.x1 - lane.x0,
			h: 3
		} : tf.boxes.get(other);
		if (!r) continue;
		if (r.y + r.h <= d.y) out.n++;
		if (r.x >= d.x + d.w) out.e++;
		if (r.y >= d.y + d.h) out.s++;
		if (r.x + r.w <= d.x) out.w++;
	}
	return out;
}
/** The box a yard stands against: its scheduler's own box; on an inner floor the door its jobs come in by (the one most
*  of them use, by id on a tie), or null when no such door is on the floor. */
function machineOf(model, container, tf, y) {
	if (!y.inner) return y.source;
	const votes = /* @__PURE__ */ new Map();
	const rel = new Map(model.map.relations.map((r) => [r.id, r]));
	for (const p of y.platforms) for (const j of p.jobs) {
		const r = rel.get(j.relation);
		if (!r) continue;
		const door = model.doorId(model.anchorFor(container, r.from));
		if (tf.boxes.has(door)) votes.set(door, (votes.get(door) ?? 0) + 1);
	}
	return [...votes.entries()].sort(([p, a], [q, c]) => c - a || byStr$1(p, q))[0]?.[0] ?? null;
}
/** The door of the in column `y`'s jobs come in by, when `y` is an inner yard (a free-standing yard: its scheduler is off
*  the floor); undefined otherwise. */
function inColumn(tf, y, machine) {
	const m = machine ? tf.boxes.get(machine) : void 0;
	return y.inner && m?.region === "in" ? m : void 0;
}
/** The rows the in column keeps free below the door of the floor's free-standing yard (one free row, then a row per
*  platform); undefined on a floor with none. The layout is run again with them (plan.ts `layFloor`). */
function inYardRows(model, container, tf, bundles) {
	for (const y of batch(model, container, tf, bundles).yards) {
		const door = machineOf(model, container, tf, y);
		if (inColumn(tf, y, door)) return {
			door,
			rows: 1 + Math.max(1, y.platforms.length)
		};
	}
}
/** The yard's rect, side, way out and platform tiles: against the machine side facing most destinations (an e or w side
*  on a tie), level on every side (its platforms rows; against an n or s side its rails leave the row ends nearer the
*  destinations, else the other ends), as near that side's middle as leaves the middle tile to the
*  machine's other lines and leans toward the destinations; the first side where the yard, its exits and the tile
*  past each exit are free, no other machine touches it and it keeps off the zones' label rows -- then, failing that
*  everywhere, the first where the yard and its exits are free (a tall yard beside a door may cross its column's label
*  row: the name finds its own clear room). An inner yard at a door of the in column stands free in that column, below
*  that door; an inner yard with no door stands at the floor's left edge. With a `ladder` the yard is a tile wider (its
*  throat), its rows in the ladder's order, and its rails leave only by the ladder's exit rows. */
function placeYard(tf, y, machine, c, ladder) {
	const dests = y.platforms.map((p) => tf.boxes.get(p.dest));
	const n = dests.length;
	const door = inColumn(tf, y, machine);
	const own = machine ? c.ids.indexOf(machine) : -1;
	const W = DEPTH + (ladder ? 1 : 0);
	const exitRows = ladder ? ladder.map((q, i) => i).filter((i) => ladder[i].exit === ladder[i].dest) : [];
	const leaving = (r, out) => ladder ? exitsOf(out, exitRows.map((i) => ({
		x: out === "e" ? r.x + r.w - 1 : r.x,
		y: r.y + i
	}))) : exitsOf(out, platformTiles(r, out, n));
	const fits = (r, out, strict) => {
		if (!c.clear(r, strict)) return false;
		if (strict && !c.alone(r, own)) return false;
		for (const e of leaving(r, out)) {
			if (!c.open(e.x, e.y)) return false;
			if (strict && !c.open(e.x + STEP[e.d][0], e.y + STEP[e.d][1])) return false;
		}
		return true;
	};
	const make = (r, side, out) => {
		const yb = {
			source: y.source,
			machine,
			...r,
			side,
			out,
			platforms: [],
			sign: null
		};
		const tiles = platformTiles(r, out, n, ladder ? 1 : 0);
		if (ladder) {
			yb.platforms = ladder.map((q, i) => ({
				dest: q.dest,
				...tiles[i]
			}));
			yb.ladder = ladder.map((q) => ladder.findIndex((o) => o.dest === q.exit));
			return yb;
		}
		yb.platforms = y.platforms.map((p, i) => ({
			p,
			at: centre$3(dests[i]).y
		})).sort((a, q) => a.at - q.at || byStr$1(a.p.dest, q.p.dest)).map(({ p }, i) => ({
			dest: p.dest,
			...tiles[i]
		}));
		return yb;
	};
	if (door) {
		const w = W, h = Math.max(1, n);
		for (let x = door.x; x + w <= door.x + door.w; x++) {
			const r = {
				x,
				y: door.y + door.h + 1,
				w,
				h
			};
			if (fits(r, "e", true) && leaving(r, "e").every((e) => c.open(e.x + 2, e.y))) return {
				...make(r, "e", "e"),
				free: true
			};
		}
	}
	if (!machine) {
		const w = W, h = Math.max(1, n);
		for (const strict of [true, false]) for (let yy = 0; yy + h <= tf.rows; yy++) for (const x of [
			3,
			2,
			1
		]) {
			const r = {
				x,
				y: yy,
				w,
				h
			};
			if (fits(r, "e", strict)) return make(r, "e", "e");
		}
		return;
	}
	const m = tf.boxes.get(machine);
	const target = dests.length ? {
		x: dests.reduce((t, d) => t + centre$3(d).x, 0) / n,
		y: dests.reduce((t, d) => t + centre$3(d).y, 0) / n
	} : centre$3(m);
	const sides = sideOrder(m, dests);
	for (const strict of [true, false]) for (const side of sides) {
		const upright = side === "e" || side === "w";
		const w = W, h = Math.max(1, n);
		const len = upright ? h : w, L = upright ? m.h : m.w, ax = upright ? "y" : "x";
		const offs = [];
		for (let o = -(len - 1); o <= L - 1; o++) offs.push(o);
		const mid = (L - 1) / 2, lean = target[ax] - (ax === "x" ? m.x : m.y);
		const rank = (o) => [
			len <= L && (o < 0 || o + len > L) ? 1 : 0,
			!n ? Math.min(Math.abs(o), Math.abs(L - len - o)) : 0,
			n && len < L && o <= mid && mid < o + len ? 1 : 0,
			Math.abs(o + len / 2 - lean),
			o
		];
		offs.sort((p, q) => {
			const a = rank(p), bb = rank(q);
			for (let i = 0; i < a.length; i++) if (a[i] !== bb[i]) return a[i] - bb[i];
			return 0;
		});
		for (const o of offs) {
			const r = rectOn(m, side, o, w, h);
			const outs = upright ? [side] : target.x >= r.x + w / 2 ? ["e", "w"] : ["w", "e"];
			for (const out of outs) if (fits(r, out, strict)) return make(r, side, out);
		}
	}
}
/** A machine's sides in the order a yard tries them: by how many destinations lie wholly past each (the centre's
*  direction when none does), an e or w side first on a tie, then n e s w. A yard with no destinations tries e, w, n, s. */
function sideOrder(m, dests) {
	if (!dests.length) return [
		"e",
		"w",
		"n",
		"s"
	];
	const count = {
		n: 0,
		e: 0,
		s: 0,
		w: 0
	};
	for (const d of dests) {
		const past = [];
		if (d.y + d.h <= m.y) past.push("n");
		if (d.x >= m.x + m.w) past.push("e");
		if (d.y >= m.y + m.h) past.push("s");
		if (d.x + d.w <= m.x) past.push("w");
		if (!past.length) {
			const a = centre$3(m), b = centre$3(d), dx = b.x - a.x, dy = b.y - a.y;
			past.push(Math.abs(dx) >= Math.abs(dy) ? dx >= 0 ? "e" : "w" : dy >= 0 ? "s" : "n");
		}
		for (const s of past) count[s]++;
	}
	const flat = (s) => s === "e" || s === "w" ? 0 : 1;
	return [
		"n",
		"e",
		"s",
		"w"
	].sort((p, q) => count[q] - count[p] || flat(p) - flat(q));
}
/** The w×h rect flush against `side` of `m`, starting `off` tiles along it. */
function rectOn(m, side, off, w, h) {
	switch (side) {
		case "n": return {
			x: m.x + off,
			y: m.y - h,
			w,
			h
		};
		case "s": return {
			x: m.x + off,
			y: m.y + m.h,
			w,
			h
		};
		case "w": return {
			x: m.x - w,
			y: m.y + off,
			w,
			h
		};
		case "e": return {
			x: m.x + m.w,
			y: m.y + off,
			w,
			h
		};
	}
}
/** A yard rect's n platform tiles, top row first: the tile at the `out` end (e or w) of each row, `inset` tiles in from
*  it (1 past a ladder's throat). */
function platformTiles(r, out, n, inset = 0) {
	return Array.from({ length: n }, (_, i) => ({
		x: out === "e" ? r.x + r.w - 1 - inset : r.x + inset,
		y: r.y + i
	}));
}
var exitsOf = (side, tiles) => tiles.map((p) => ({
	x: p.x + STEP[side][0],
	y: p.y + STEP[side][1],
	d: side
}));
/** Where the yard's rails leave it, travelling `out`, top row first: the tile just past each platform; on a ladder, the
*  tile just past the throat at each exit row. */
function exits(y) {
	if (!y.ladder) return exitsOf(y.out, y.platforms);
	return exitsOf(y.out, y.platforms.filter((_, i) => y.ladder[i] === i).map((p) => ({
		x: p.x + STEP[y.out][0],
		y: p.y
	})));
}
/** The exit platform i's rail leaves by (one of `exits(y)`, the same object). */
function exitOf(y, i, all = exits(y)) {
	const p = y.platforms[y.ladder ? y.ladder[i] : i], k = y.ladder ? 2 : 1;
	return all.find((e) => e.x === p.x + STEP[y.out][0] * k && e.y === p.y);
}
/** Each yard whose first routing sends more than one platform's rail out by one exit (a rail riding a trunk starts on
*  the trunk's), with its ladder: the platforms leaving by one exit lie together (groups in the order of their exits
*  down the yard, each in its rows' order), that exit at an end of the group, so the throat runs one way to it and no
*  rail crosses another inside the yard: the end it already was at; from a middle row, the `middle` end (planFloor
*  tries both). Undefined when no yard needs one. */
function yardLadders(tf, routes, middle = "top") {
	const r = tf.rails;
	if (!r) return void 0;
	const byKey = new Map(routes.map((q) => [q.key, q]));
	const out = /* @__PURE__ */ new Map();
	for (const y of r.yards) {
		if (y.ladder || y.platforms.length < 2) continue;
		const [sx, sy] = STEP[y.out];
		const route = (i) => {
			const s = r.stations.find((q) => !q.door && q.source === y.source && q.dest === y.platforms[i].dest);
			const q = s && byKey.get(s.track);
			return q && !q.failed && q.pieces.length ? q : void 0;
		};
		const groups = /* @__PURE__ */ new Map();
		y.platforms.forEach((_, i) => {
			const f = route(i)?.pieces[0];
			const j = f ? y.platforms.findIndex((p) => p.x === f.x - sx && p.y === f.y - sy) : -1;
			const k = j >= 0 ? j : i;
			groups.set(k, [...groups.get(k) ?? [], i]);
		});
		if ([...groups.values()].every((g) => g.length < 2)) continue;
		const rows = [];
		for (const [j, g] of [...groups.entries()].sort(([a], [b]) => a - b)) {
			g.sort((a, b) => a - b);
			const at = g.indexOf(j), top = at === 0 || at !== g.length - 1 && middle === "top";
			const exit = y.platforms[top ? g[0] : g[g.length - 1]].dest;
			for (const i of g) rows.push({
				dest: y.platforms[i].dest,
				exit
			});
		}
		out.set(y.source, rows);
	}
	return out.size ? out : void 0;
}
/** The two tiles just past a station's ends, along its destination's wall, each with the way a rail runs into it. */
function stationEnds(s) {
	if (s.side === "n" || s.side === "s") return [{
		x: s.x - 1,
		y: s.y,
		d: "e"
	}, {
		x: s.x + s.w,
		y: s.y,
		d: "w"
	}];
	return [{
		x: s.x,
		y: s.y - 1,
		d: "s"
	}, {
		x: s.x,
		y: s.y + s.h,
		d: "n"
	}];
}
/** Candidate sign tiles beside a yard. Against an e or w side: over its top row, then under its bottom row, nearest the
*  machine's far side first but never against the machine. Against an n or s side: past its far row (away from the
*  machine), from the end its rails do not leave by, then past that end, far row first. */
function signSpot(y) {
	const spots = [];
	if (y.side === "e" || y.side === "w") {
		const xs = Array.from({ length: y.w }, (_, i) => y.side === "e" ? y.x + 1 + i : y.x + y.w - 2 - i).filter((x) => x >= y.x && x < y.x + y.w);
		for (const yy of [y.y - 1, y.y + y.h]) for (const x of xs) spots.push({
			x,
			y: yy
		});
	} else {
		const far = y.side === "n" ? y.y - 1 : y.y + y.h;
		const xs = Array.from({ length: y.w }, (_, i) => y.out === "e" ? y.x + i : y.x + y.w - 1 - i);
		for (const x of xs) spots.push({
			x,
			y: far
		});
		const end = y.out === "e" ? y.x - 1 : y.x + y.w;
		for (let i = 0; i < y.h; i++) spots.push({
			x: end,
			y: y.side === "n" ? y.y + i : y.y + y.h - 1 - i
		});
	}
	return spots;
}
/** A station strip on the side of `d` facing the yard exit `from`: as long as the side allows up to 3 with a tile of
*  wall beyond each end (so both ends run along the wall), as near the side's middle as free, its entry (the end nearer
*  `from`) free. A side that holds a full strip of 3 goes before one that holds less (a one-tile station reads as no
*  siding), then a side fewer of the machine's other lines head past (`busy`), then the nearer one. Only the entry is
*  kept for the rail: the far end's tile stays free for the machine's other lines. */
function placeStation(d, from, clear, free, busy) {
	const a = centre$3(d), b = {
		x: from.x + .5,
		y: from.y + .5
	}, dx = b.x - a.x, dy = b.y - a.y;
	const v = dy >= 0 ? "s" : "n", h = dx >= 0 ? "e" : "w";
	const opp = {
		n: "s",
		s: "n",
		e: "w",
		w: "e"
	};
	const [p, q] = Math.abs(dy) >= Math.abs(dx) ? [v, h] : [h, v];
	const facing = [
		p,
		q,
		opp[q],
		opp[p]
	];
	const order = facing.slice().sort((s1, s2) => busy[s1] - busy[s2] || facing.indexOf(s1) - facing.indexOf(s2));
	for (const least of [STATION, 1]) for (const side of order) {
		const L = side === "n" || side === "s" ? d.w : d.h;
		for (let len = Math.min(STATION, Math.max(1, L - 2)); len >= least; len--) {
			const mid = Math.floor((L - len) / 2), offs = [mid];
			for (let k = 1; k <= L; k++) offs.push(mid - k, mid + k);
			for (const o of offs) {
				if (o < 1 || o + len > L - 1) continue;
				const r = side === "n" || side === "s" ? rectOn(d, side, o, len, 1) : rectOn(d, side, o, 1, len);
				if (!clear(r)) continue;
				const dist = (e) => Math.abs(e.x - from.x) + Math.abs(e.y - from.y);
				const entry = stationEnds({
					...r,
					side
				}).sort((e, f) => dist(e) - dist(f))[0];
				if (free(entry)) return {
					...r,
					side,
					entry
				};
			}
		}
	}
}
/** Every floor tile the rails hold: yards, stations and sign tiles beside yards (the router's obstacles). */
function railRects(tf) {
	const r = tf.rails;
	if (!r) return [];
	const inside = (y, s) => s.x >= y.x && s.x < y.x + y.w && s.y >= y.y && s.y < y.y + y.h;
	return [
		...r.yards.map((y) => ({
			x: y.x,
			y: y.y,
			w: y.w,
			h: y.h
		})),
		...r.yards.flatMap((y) => y.sign && !inside(y, y.sign) ? [{
			x: y.sign.x,
			y: y.sign.y,
			w: 1,
			h: 1
		}] : []),
		...r.stations.map((s) => ({
			x: s.x,
			y: s.y,
			w: s.w,
			h: s.h
		}))
	];
}
/** Every station's rail ends, keyed by its track (a batch bundle's key or a shell's): from its yard to its station.
*  Empty on a floor with no rails. */
function railEnds(tf) {
	const out = /* @__PURE__ */ new Map();
	const r = tf.rails;
	if (!r) return out;
	for (const y of r.yards) {
		const all = exits(y);
		y.platforms.forEach((p, i) => {
			const s = r.stations.find((q) => q.source === y.source && q.dest === p.dest);
			if (s) out.set(s.track, {
				yard: y,
				own: exitOf(y, i, all),
				yardExits: all,
				station: s,
				entry: s.entry,
				dest: p.dest
			});
		});
	}
	for (const s of r.stations) if (s.door) out.set(s.track, {
		yardExits: [],
		station: s,
		entry: s.entry,
		dest: s.dest,
		door: s.door
	});
	return out;
}
// src/factory/pads.ts
/** A receiving dock's length along its side, tiles. */
var DOCK = 3;
var ROLE = {
	produce: 0,
	consume: 1,
	failure: 2
};
var byStr = (a, b) => a < b ? -1 : a > b ? 1 : 0;
var centre$2 = (r) => ({
	x: r.x + r.w / 2,
	y: r.y + r.h / 2
});
var padMark = (p) => ({
	x: p.x * 24 + 9 / 2,
	y: (p.y + 1) * 24 - 3 - 15,
	w: 15,
	h: 15
});
/** Where a pad's drone takes off and lands: its mark's centre, world px. */
var padCentre = (p) => {
	const m = padMark(p);
	return {
		x: m.x + m.w / 2,
		y: m.y + m.h / 2
	};
};
/** The px a machine's pads take from the right of its bottom row (its sub line and role tag stop short of them). */
var padReserve = (pads) => pads ? pads * 24 : 0;
/** The floor's messaging and its reserved tiles; undefined on a floor with no hub (it lays out and routes as before). */
function landing(model, container, tf, bundles) {
	const msg = messaging(model, container, tf, bundles);
	if (!msg.airfields.length) return void 0;
	const hubBroker = new Map(msg.airfields.flatMap((a) => a.hubs.map((h) => [h.item, a.broker])));
	/** What a dock faces: its broker's airfield on the site, the hub itself (a door) inside a building. */
	const facing = (item) => {
		return (tf.site ? tf.zones.find((q) => q.airfield && q.name === hubBroker.get(item)) : void 0) ?? tf.boxes.get(item);
	};
	const wants = [];
	const want = (w) => wants.push({
		...w,
		prefs: sides(tf.boxes.get(w.machine), facing(w.item), tf.site)
	});
	for (const p of msg.producers) want({
		machine: p.machine,
		item: p.item,
		topic: p.topic,
		role: "produce",
		flight: p.flight,
		dock: false
	});
	for (const c of msg.consumers) want({
		machine: c.machine,
		item: c.item,
		topic: c.topic,
		role: "consume",
		flight: c.flight,
		dock: c.subscription === "push",
		...c.group !== void 0 ? { group: c.group } : {}
	});
	for (const f of msg.failures) want({
		machine: f.machine,
		item: f.item,
		topic: f.dlq,
		role: "failure",
		flight: f.flight,
		dock: false
	});
	const held = /* @__PURE__ */ new Set();
	const key = (x, y) => y * tf.cols + x;
	const hold = (r) => {
		for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) held.add(key(x, y));
	};
	for (const b of tf.boxes.values()) hold(b);
	for (const l of tf.lanes) hold({
		x: l.x0,
		y: l.y,
		w: l.x1 - l.x0,
		h: 3
	});
	for (const s of tf.stacks ?? []) hold({
		x: s.x,
		y: s.y,
		w: 1,
		h: 1
	});
	for (const g of tf.chestGaps ?? []) hold(g);
	const free = (r) => {
		if (r.x < 0 || r.y < 0 || r.x + r.w > tf.cols || r.y + r.h > tf.rows) return false;
		for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) if (held.has(key(x, y))) return false;
		return true;
	};
	const pads = [], docks = [], unplaced = [];
	const strip = (p) => {
		const { prefs: _, ...w } = p;
		return w;
	};
	const machines = [...new Set(wants.map((w) => w.machine))].sort(byStr);
	for (const id of machines) {
		const m = tf.boxes.get(id);
		const mine = wants.filter((w) => w.machine === id && !w.dock).sort((p, q) => centre$2(tf.boxes.get(p.item)).x - centre$2(tf.boxes.get(q.item)).x || ROLE[p.role] - ROLE[q.role] || byStr(p.topic, q.topic) || byStr(p.group ?? "", q.group ?? ""));
		const room = Math.max(0, m.w - 1), laid = mine.slice(0, room);
		laid.forEach((w, i) => {
			const { prefs: _, dock: __, ...rest } = w;
			pads.push({
				...rest,
				x: m.x + m.w - laid.length + i,
				y: m.y + m.h - 1,
				inside: true
			});
		});
		for (const w of mine.slice(room)) unplaced.push(strip(w));
		let pending = wants.filter((w) => w.machine === id && w.dock).map((w) => ({
			w,
			pref: 0
		}));
		const closed = /* @__PURE__ */ new Set();
		while (pending.length) {
			for (const p of pending) while (p.pref < 4 && closed.has(p.w.prefs[p.pref])) p.pref++;
			for (const p of pending) if (p.pref >= 4) unplaced.push(strip(p.w));
			pending = pending.filter((p) => p.pref < 4);
			if (!pending.length) break;
			const count = /* @__PURE__ */ new Map();
			for (const p of pending) count.set(p.w.prefs[p.pref], (count.get(p.w.prefs[p.pref]) ?? 0) + 1);
			const side = [
				"n",
				"e",
				"s",
				"w"
			].filter((d) => count.has(d)).sort((a, b) => count.get(b) - count.get(a))[0];
			closed.add(side);
			const here = pending.filter((p) => p.w.prefs[p.pref] === side);
			const axis = side === "n" || side === "s" ? "x" : "y";
			here.sort((p, q) => centre$2(tf.boxes.get(p.w.item))[axis] - centre$2(tf.boxes.get(q.w.item))[axis] || byStr(p.w.topic, q.w.topic) || byStr(p.w.group ?? "", q.w.group ?? ""));
			const toward = here.reduce((t, p) => t + centre$2(tf.boxes.get(p.w.item))[axis], 0) / here.length - centre$2(m)[axis];
			const offs = layRun(m, side, here.length, free, Math.abs(toward) < 1 ? 0 : Math.sign(toward));
			const done = /* @__PURE__ */ new Set();
			for (let i = 0; i < here.length; i++) {
				const p = here[i], at = offs[i];
				if (at === void 0) {
					p.pref++;
					continue;
				}
				done.add(p);
				const w = p.w, rect = tileRect(m, side, at, DOCK);
				hold(rect);
				docks.push({
					machine: w.machine,
					item: w.item,
					topic: w.topic,
					role: w.role,
					...w.group !== void 0 ? { group: w.group } : {},
					flight: w.flight,
					...rect,
					side
				});
			}
			pending = pending.filter((p) => !done.has(p));
		}
	}
	const order = (a, b) => byStr(a.machine, b.machine) || byStr(a.item, b.item) || byStr(a.group ?? "", b.group ?? "");
	pads.sort((a, b) => order(a, b) || ROLE[a.role] - ROLE[b.role]);
	docks.sort(order);
	unplaced.sort((a, b) => order(a, b) || ROLE[a.role] - ROLE[b.role]);
	return {
		messaging: msg,
		pads,
		docks,
		stacks: tf.stacks ?? [],
		unplaced
	};
}
/** Every floor tile messaging and the rails hold: waiting stacks and receiving docks (push and webhook), then rail yards, sign tiles and
*  stations (the router's obstacles). Pads sit inside their machines and hold none. */
function reservedRects(tf) {
	return [
		...(tf.stacks ?? []).map((s) => ({
			x: s.x,
			y: s.y,
			w: 1,
			h: 1
		})),
		...(tf.landing?.docks ?? []).map((d) => ({
			x: d.x,
			y: d.y,
			w: d.w,
			h: d.h
		})),
		...(tf.webhooks ?? []).map((d) => ({
			x: d.x,
			y: d.y,
			w: d.w,
			h: d.h
		})),
		...railRects(tf)
	];
}
/** The sides of `m` in the order they face `t`: the main axis first (on the site, the vertical one when `t` is wholly
*  above or below), then the other, then their opposites. */
function sides(m, t, site) {
	const a = centre$2(m), b = centre$2(t), dx = b.x - a.x, dy = b.y - a.y;
	const v = dy >= 0 ? "s" : "n", h = dx >= 0 ? "e" : "w";
	const opp = {
		n: "s",
		s: "n",
		e: "w",
		w: "e"
	};
	const apart = t.y >= m.y + m.h || t.y + t.h <= m.y;
	const [p, q] = site && apart || Math.abs(dy) >= Math.abs(dx) ? [v, h] : [h, v];
	return [
		p,
		q,
		opp[q],
		opp[p]
	];
}
/** Offsets along `side` for a run of `count` docks (`len` tiles each, DOCK by default) laid end to end, as near the
*  side's middle as free
*  tiles allow, one tile toward `lean` (-1, 0, 1) when the side has room either way; when the whole run fits nowhere,
*  the last docks are dropped (undefined) until it does. */
function layRun(m, side, count, free, lean, len = DOCK) {
	const n = side === "n" || side === "s" ? m.w : m.h;
	for (let k = count; k > 0; k--) {
		const total = k * len;
		if (total > n) continue;
		const mid = Math.floor((n - total) / 2), leaned = mid + lean;
		const ideal = n - total >= 2 && (n <= 3 || leaned >= 1 && leaned + total <= n - 1) ? leaned : mid;
		const starts = [ideal];
		for (let d = 1; d <= n; d++) starts.push(ideal + d, ideal - d);
		for (const s0 of starts) {
			if (s0 < 0 || s0 + total > n) continue;
			const offs = Array.from({ length: k }, (_, i) => s0 + i * len);
			if (offs.every((o) => free(tileRect(m, side, o, len)))) return [...offs, ...Array.from({ length: count - k }, () => void 0)];
		}
	}
	return Array.from({ length: count }, () => void 0);
}
/** The rect `len` tiles long just outside `side` of `m`, starting `off` tiles along it. */
function tileRect(m, side, off, len) {
	switch (side) {
		case "n": return {
			x: m.x + off,
			y: m.y - 1,
			w: len,
			h: 1
		};
		case "s": return {
			x: m.x + off,
			y: m.y + m.h,
			w: len,
			h: 1
		};
		case "w": return {
			x: m.x - 1,
			y: m.y + off,
			w: 1,
			h: len
		};
		case "e": return {
			x: m.x + m.w,
			y: m.y + off,
			w: 1,
			h: len
		};
	}
}
/** A webhook dock's id as a line end (the router's trunk groups and the plug checks). */
var webhookDockId = (machine) => `webhook:${machine}`;
/** A webhook's sign: the relation's key, `webhook` when it has none. */
var webhookSign = (key) => key?.trim() || "webhook";
/** The inbound webhook bundles on the site, by their service: its bundle keys, its signs, and its callers' boxes. */
function inboundWebhooks(model, tf, bundles) {
	const inbound = /* @__PURE__ */ new Map();
	if (!tf.site) return inbound;
	const ext = (id) => tf.boxes.get(id)?.kind === "external";
	for (const b of bundles) {
		if (b.kind !== "request" || ext(b.a) === ext(b.b)) continue;
		const [outside, machine] = ext(b.a) ? [b.a, b.b] : [b.b, b.a];
		if (tf.boxes.get(machine)?.kind !== "service") continue;
		const calls = b.relations.filter((r) => r.kind === "request" && model.kindOf(r.from) === "external");
		if (!calls.length) continue;
		const w = inbound.get(machine) ?? inbound.set(machine, {
			keys: [],
			signs: /* @__PURE__ */ new Set(),
			callers: []
		}).get(machine);
		w.keys.push(b.key);
		for (const r of calls) w.signs.add(webhookSign(r.key));
		w.callers.push(tf.boxes.get(outside));
	}
	return inbound;
}
/** Does the site have an inbound webhook (a request from an outside service into a service)? Only then does planFloor
*  route a first time to see where its belts arrive. */
var hasWebhooks = (model, tf, bundles) => inboundWebhooks(model, tf, bundles).size > 0;
/** The site's inbound webhook docks, placed after the push docks and the rails (their tiles, and the tiles rails start
*  and end on, held) from a first routing of the floor (`routes`, no dock yet): each dock stands on the side of its
*  service its first belt arrived at, else on the first side with a free run in the push dock's order (facing its
*  callers). Undefined on an inside floor or a site with none. A service whose four sides have no free run gets no
*  dock: its belts plug into its wall as before, and `notes` says so. */
function webhookDocks(model, tf, bundles, routes) {
	const inbound = inboundWebhooks(model, tf, bundles);
	if (!inbound.size) return void 0;
	const held = /* @__PURE__ */ new Set();
	const key = (x, y) => y * tf.cols + x;
	const hold = (r) => {
		for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) held.add(key(x, y));
	};
	for (const b of tf.boxes.values()) hold(b);
	for (const l of tf.lanes) hold({
		x: l.x0,
		y: l.y,
		w: l.x1 - l.x0,
		h: 3
	});
	for (const r of reservedRects(tf)) hold(r);
	for (const e of railEnds(tf).values()) for (const t of [...e.yardExits, e.entry]) hold({
		x: t.x,
		y: t.y,
		w: 1,
		h: 1
	});
	for (const g of tf.chestGaps ?? []) hold(g);
	const free = (r) => {
		if (r.x < 0 || r.y < 0 || r.x + r.w > tf.cols || r.y + r.h > tf.rows) return false;
		for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) if (held.has(key(x, y))) return false;
		return true;
	};
	/** The side of `m` a routed line plugs into, if it does. */
	const plugSide = (m, r) => {
		const ps = r?.pieces ?? [];
		if (!ps.length) return void 0;
		const f = ps[0], l = ps[ps.length - 1];
		const inBox = (x, y) => x >= m.x && y >= m.y && x < m.x + m.w && y < m.y + m.h;
		if (inBox(l.x + STEP[l.out][0], l.y + STEP[l.out][1])) return OPP[l.out];
		if (inBox(f.x - STEP[f.in][0], f.y - STEP[f.in][1])) return f.in;
	};
	const docks = [], notes = [];
	for (const machine of [...inbound.keys()].sort(byStr)) {
		const w = inbound.get(machine), m = tf.boxes.get(machine), keys = [...w.keys].sort(byStr);
		const cs = w.callers.map(centre$2), at = {
			x: cs.reduce((s, c) => s + c.x, 0) / cs.length,
			y: cs.reduce((s, c) => s + c.y, 0) / cs.length
		};
		const order = sides(m, {
			x: at.x,
			y: at.y,
			w: 0,
			h: 0
		}, tf.site);
		const arrived = plugSide(m, routes.find((r) => r.key === keys[0]));
		const prefs = arrived ? [arrived, ...order.filter((d) => d !== arrived)] : order;
		const signs = [...w.signs].sort(byStr);
		const method = /^([A-Z]+)\s/.exec(signs[0])?.[1], more = signs.length > 1 ? ` +${signs.length - 1}` : "";
		const words = [.../* @__PURE__ */ new Set([
			`${signs[0]}${more}`,
			...method ? [`${method}${more}`] : [],
			"webhook"
		])];
		let placed = false;
		sides: for (const side of prefs) {
			const level = side === "n" || side === "s", n = level ? m.w : m.h;
			const tries = level ? words.map((t) => ({
				face: t,
				len: Math.max(DOCK, Math.ceil(plateW(t, 10) / 24) + 1)
			})).filter((q) => q.len <= n) : [];
			tries.push({ len: DOCK });
			const axis = level ? "x" : "y";
			const toward = at[axis] - centre$2(m)[axis];
			for (const q of tries) {
				const [off] = layRun(m, side, 1, free, Math.abs(toward) < 1 ? 0 : Math.sign(toward), q.len);
				if (off === void 0) continue;
				const rect = tileRect(m, side, off, q.len);
				hold(rect);
				docks.push({
					machine,
					keys,
					signs,
					...q.face !== void 0 ? { face: q.face } : {},
					...rect,
					side
				});
				placed = true;
				break sides;
			}
		}
		if (!placed) notes.push(`webhook dock: ${machine} has no free side; its belts plug into its wall`);
	}
	return {
		docks,
		notes
	};
}
// src/factory/clear.ts
var ZONE_FONT = 9.5;
/** A zone name's size in world px at scale 1, estimated (never measured, so layout cannot depend on font loading): a
*  bold capital is at most 0.72 em wide, and the line box is 13 px tall. The drawn text is never larger. */
var zoneTextSize = (name) => ({
	w: Math.ceil(name.length * ZONE_FONT * .72),
	h: 13
});
var SHADOW = 5;
var ABOVE = 20;
var LINE_HALF = 6;
var MARGIN = 2;
/** Everything a zone name must stay off: machines with their shadows, chimneys and tabs; lanes; every line piece
*  (housings and junction plates sit on piece tiles); drone and failed lines as drawn (flight paths). */
function floorObstacles(tf, routes) {
	const out = [];
	for (const b of tf.boxes.values()) {
		const x0 = b.x * 24, y0 = b.y * 24;
		out.push({
			x0,
			y0: b.foot === "door" ? y0 : y0 - ABOVE,
			x1: x0 + b.w * 24 + SHADOW,
			y1: y0 + b.h * 24 + SHADOW
		});
	}
	for (const l of tf.lanes) out.push({
		x0: l.x0 * 24,
		y0: l.y * 24,
		x1: l.x1 * 24,
		y1: (l.y + 3) * 24
	});
	for (const r of reservedRects(tf)) out.push({
		x0: r.x * 24,
		y0: r.y * 24,
		x1: (r.x + r.w) * 24,
		y1: (r.y + r.h) * 24
	});
	for (const r of routes) out.push(...routeRects(r));
	return out;
}
/** A line as drawn: its piece tiles (only those on top with `top`: a tunnel's pieces are under the floor), or, with no
*  pieces (a drone or failed line drawn point to point), its segments `LINE_HALF` wide. */
function routeRects(r, top = false) {
	const out = [];
	for (const p of r.pieces) if (!top || !p.under) out.push({
		x0: p.x * 24,
		y0: p.y * 24,
		x1: (p.x + 1) * 24,
		y1: (p.y + 1) * 24
	});
	if (r.pieces.length) return out;
	for (let i = 1; i < r.points.length; i++) {
		const a = r.points[i - 1], b = r.points[i], n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / LINE_HALF));
		for (let k = 0; k <= n; k++) {
			const x = a.x + (b.x - a.x) * k / n, y = a.y + (b.y - a.y) * k / n;
			out.push({
				x0: x - LINE_HALF,
				y0: y - LINE_HALF,
				x1: x + LINE_HALF,
				y1: y + LINE_HALF
			});
		}
	}
	return out;
}
var hit$1 = (a, b) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
/** Obstacles indexed by the tiles they touch: a query looks only at its own tiles. */
var Clearance = class {
	cols;
	cells = /* @__PURE__ */ new Map();
	constructor(rects = [], cols = 4096) {
		this.cols = cols;
		for (const r of rects) this.add(r);
	}
	each(r, f) {
		for (let ty = Math.floor(r.y0 / 24); ty <= Math.floor((r.y1 - 1e-6) / 24); ty++) for (let tx = Math.floor(r.x0 / 24); tx <= Math.floor((r.x1 - 1e-6) / 24); tx++) if (f(ty * this.cols + tx)) return true;
		return false;
	}
	add(r) {
		this.each(r, (k) => {
			const l = this.cells.get(k);
			if (l) l.push(r);
			else this.cells.set(k, [r]);
		});
	}
	/** Does `r`, with a small margin, touch no obstacle? */
	free(r) {
		const q = {
			x0: r.x0 - MARGIN,
			y0: r.y0 - MARGIN,
			x1: r.x1 + MARGIN,
			y1: r.y1 + MARGIN
		};
		return !this.each(q, (k) => this.cells.get(k)?.some((o) => hit$1(q, o)));
	}
};
var labelBox = (p, k) => ({
	x0: p.ax,
	y0: p.ay - p.h * k,
	x1: p.ax + p.w * k,
	y1: p.ay
});
/** The best spot for a zone's name: bottom-left anchors on every tile column of the zone's bottom three rows, each
*  grown (up and right) as far as it stays inside the zone and clear of every obstacle; the largest wins, the lowest
*  and leftmost on a tie. The winning box is added to `clear`, so the next zone's name keeps off it. A zone with no
*  clear spot keeps the old corner at scale 1 (it hides itself when that is too small to read). */
function planZoneLabel(z, clear) {
	const { w, h } = zoneTextSize(z.name);
	const inner = {
		x0: z.x * 24 + 2,
		y0: z.y * 24 + 2,
		x1: (z.x + z.w) * 24 - 2,
		y1: (z.y + z.h) * 24 - 2
	};
	const ok = (p, k) => {
		const b = labelBox({
			...p,
			w,
			h
		}, k);
		return b.x0 >= inner.x0 && b.x1 <= inner.x1 && b.y0 >= inner.y0 && b.y1 <= inner.y1 && clear.free(b);
	};
	let best;
	for (let j = 0; j < z.h && (j < 3 || !best); j++) for (let tx = z.x; tx < z.x + z.w; tx++) {
		const p = {
			ax: tx * 24 + 6,
			ay: (z.y + z.h) * 24 - 5 - j * 24,
			w,
			h,
			maxK: 1,
			clear: true
		};
		if (!ok(p, 1)) continue;
		let lo = 1, hi = 4;
		if (ok(p, hi)) lo = hi;
		else for (let i = 0; i < 12; i++) {
			const mid = (lo + hi) / 2;
			if (ok(p, mid)) lo = mid;
			else hi = mid;
		}
		p.maxK = Math.floor(lo * 100) / 100;
		if (!best || p.maxK > best.maxK + 1e-9) best = p;
	}
	const plan = best ?? {
		ax: z.x * 24 + 6,
		ay: (z.y + z.h) * 24 - 5,
		w,
		h,
		maxK: 1,
		clear: false
	};
	clear.add(labelBox(plan, plan.maxK));
	return plan;
}
var BADGE_FONT = 10.5;
/** A `used by N` badge's size in world px at scale 1, estimated as `zoneTextSize` is (a bold character is at most
*  0.62 em wide here, plus 4 px padding each side): the drawn badge is never larger, so its spot holds it. */
var badgeSize = (n) => ({
	w: Math.ceil(`used by ${n}`.length * BADGE_FONT * .62) + 8,
	h: 14
});
var badgeBox = (p, k) => {
	const w = p.w * k, h = p.h * k, x0 = p.ax + p.ox * w, y0 = p.ay + p.oy * h;
	return {
		x0,
		y0,
		x1: x0 + w,
		y1: y0 + h
	};
};
var SLIDE = 40;
/** The best spot for a `w`×`h` badge beside machine `m` (world px): the one that grows furthest while clear. First the
*  plain spots (right and left centred on the box, below and above from its left edge), right first on a tie, then
*  below, left, above; then each side's sliding spots, nearest the plain one first: on the right and left an anchor at
*  every 2 px from `SLIDE` above the box to `SLIDE` below it, the badge growing down or up from it; below and above, at
*  every 2 px along the box (never past its ends, so no line runs between it and its box), growing right or left. A
*  later spot wins only by growing further. The
*  winning box (at its `maxK`) joins `clear`. With no clear spot even at scale 1, it stands below at scale 1. */
function planBadge(m, w, h, clear) {
	const gap = 3, cy = m.y + m.h / 2;
	const R = m.x + m.w + SHADOW + gap, L = m.x - gap, B = m.y + m.h + SHADOW + gap, A = m.y - ABOVE - gap;
	const at = (side, ax, ay, ox, oy) => ({
		side,
		ax,
		ay,
		ox,
		oy,
		w,
		h,
		maxK: 1,
		clear: true
	});
	const plain = [
		at("right", R, cy, 0, -.5),
		at("below", m.x, B, 0, 0),
		at("left", L, cy, -1, -.5),
		at("above", m.x, A, 0, -1)
	];
	const slid = [];
	for (let y = m.y - SLIDE; y <= m.y + m.h + SLIDE; y += 2) for (const oy of [0, -1]) for (const [side, ax, ox] of [[
		"right",
		R,
		0
	], [
		"left",
		L,
		-1
	]]) slid.push({
		p: at(side, ax, y, ox, oy),
		d: Math.abs(y + oy * h + h / 2 - cy)
	});
	for (let x = m.x; x <= m.x + m.w; x += 2) for (const ox of [0, -1]) for (const [side, ay, oy] of [[
		"below",
		B,
		0
	], [
		"above",
		A,
		-1
	]]) slid.push({
		p: at(side, x, ay, ox, oy),
		d: Math.abs(x + ox * w - m.x)
	});
	const order = {
		right: 0,
		below: 1,
		left: 2,
		above: 3
	};
	slid.sort((a, b) => a.d - b.d || order[a.p.side] - order[b.p.side]);
	let best;
	for (const p of [...plain, ...slid.map((s) => s.p)]) {
		if (best?.maxK === 4) break;
		if (!clear.free(badgeBox(p, 1))) continue;
		let lo = 1, hi = 4;
		if (clear.free(badgeBox(p, hi))) lo = hi;
		else for (let i = 0; i < 12; i++) {
			const mid = (lo + hi) / 2;
			if (clear.free(badgeBox(p, mid))) lo = mid;
			else hi = mid;
		}
		p.maxK = Math.floor(lo * 100) / 100;
		if (!best || p.maxK > best.maxK + 1e-9) best = p;
	}
	const plan = best ?? {
		...plain[1],
		clear: false
	};
	clear.add(badgeBox(plan, plan.maxK));
	return plan;
}
function placeBadges(items, clear, layerTiles, spots = /* @__PURE__ */ new Map()) {
	if (items.some((i) => !spots.has(i.id))) for (const r of layerTiles) clear.add(r);
	for (const i of items) if (!spots.has(i.id)) spots.set(i.id, planBadge(i.m, i.w, i.h, clear));
	return spots;
}
/** Every layer's lines as drawn: the tiles of their top pieces, and drone or failed lines point to point. */
function layerTileRects(layers) {
	return Object.values(layers ?? {}).flatMap((l) => l.routes.flatMap((r) => routeRects(r, true)));
}
/** Where a lane's name sits: from the left, the first gap between crossing lines wide enough for the name scaled to
*  `kWant`; else the widest gap. `room` is that gap's width from the name's left edge. A line past the lane's end
*  bounds no gap: the last one ends at the lane's end. Pure, for the test. */
function laneLabelSpot(x0, x1, w, blocked, kWant, pad = 6) {
	const gaps = [];
	let start = x0 + pad;
	for (const b of blocked.filter((b) => b > x0 && b < x1).sort((p, q) => p - q)) {
		if (b - pad > start) gaps.push({
			s: start,
			e: b - pad
		});
		start = Math.max(start, b + pad + 2);
	}
	gaps.push({
		s: start,
		e: x1 - pad
	});
	const g = gaps.find((q) => q.e - q.s >= w * kWant) ?? gaps.reduce((best, q) => q.e - q.s > best.e - best.s ? q : best);
	return {
		x: g.s,
		room: g.e - g.s
	};
}
/** The lane name's scale the spot is chosen for: 3x its size is readable down to a zoom of 0.25. */
var LANE_WANT = 3;
var LANE_LABEL_H = 17;
var LANE_CHAR = .56;
/** A lane's name plate width at scale 1, estimated (the drawing measures the text): for the router and the audit. */
var laneNameWidth = (name) => Math.ceil(name.length * 12 * LANE_CHAR) + 10;
/** The tiles at a short lane's start where its name sits, as [x0, x1): a lane too short to hold its name twice over,
*  so a line crossing it or ending on it there leaves the name no room (the router keeps lines off them where it can);
*  undefined on a longer lane, whose name finds a gap between the lines. */
function laneNameTiles(l, name) {
	const w = laneNameWidth(name);
	if ((l.x1 - l.x0) * 24 >= 2 * (w + 12 + 2)) return void 0;
	return [l.x0, Math.min(l.x1, l.x0 + Math.ceil((w + 12 + 2) / 24))];
}
/** A lane's name plate, `w` px wide at scale 1 (its text plus 10): its top-left corner, its height, and the largest
*  scale its spot holds. Pure, for the map audit (text.ts), which estimates `w` where the drawing measures it. */
function laneLabelPlan(l, w, blocked) {
	const tall = Math.max(1, 66 / LANE_LABEL_H);
	const spot = laneLabelSpot(l.x0 * 24, l.x1 * 24, w, blocked, Math.min(tall, LANE_WANT));
	return {
		x: spot.x,
		y: l.y * 24 + 4,
		w,
		h: LANE_LABEL_H,
		maxK: Math.max(1, Math.min(tall, spot.room / w))
	};
}
// src/factory/router.ts
var TURN = 3;
var UNDER = 6;
var MAX_UNDER = 4;
var RANK = {
	pipe: 0,
	belt: 1,
	rail: 2,
	tapRW: 3,
	tapW: 3,
	tapR: 3,
	drone: 9
};
var CHEST_RANK = 1.5;
var HUG = 3;
var FREE = -1;
var BOX = -2;
var LANE = -3;
var BASE = 1073741823;
var CORNER = 3;
var OFF = 1.25;
var RIDE = .3;
var EDGE = 1;
var BADGE = 2;
var BADGE_ROOM = {
	w: 7,
	h: 2
};
var NAME = 3;
function lineKind(b, tap) {
	if (tap) return b.kinds["db-write"] && b.kinds["db-read"] ? "tapRW" : b.kinds["db-write"] ? "tapW" : "tapR";
	if (flies(b.kind)) return "drone";
	if (b.kind === "stream") return "pipe";
	if (b.kind === "batch") return "rail";
	return "belt";
}
var DX = DIRS.map((d) => STEP[d][0]);
var DY = DIRS.map((d) => STEP[d][1]);
var centre$1 = (r) => ({
	x: (r.x + r.w / 2) * 24,
	y: (r.y + r.h / 2) * 24
});
var band = (l) => ({
	x: l.x0,
	y: l.y,
	w: l.x1 - l.x0,
	h: 3
});
/** `base`: given, this is a layer's pass: the lines already laid on this floor, which `bundles` route over. Their tiles on top are
*  held by a line no layer line may ride: a layer line goes round them where it can and under them where it must, never
*  along them; they are read, never changed. */
function routeTiles(tf, bundles, base) {
	const { cols, rows } = tf;
	const occ = new Int32Array(cols * rows).fill(FREE);
	const at = (x, y) => y * cols + x;
	const ok = (x, y) => x >= 0 && y >= 0 && x < cols && y < rows;
	const fill = (r, v) => {
		for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) if (ok(x, y)) occ[at(x, y)] = v;
	};
	for (const l of tf.lanes) fill(band(l), LANE);
	for (const b of tf.boxes.values()) fill(b, BOX);
	for (const r of reservedRects(tf)) fill(r, BOX);
	for (const r of base ?? []) for (const p of r.pieces) if (!p.under && ok(p.x, p.y) && occ[at(p.x, p.y)] === FREE) occ[at(p.x, p.y)] = BASE;
	const owner = new Int32Array(cols * rows).fill(-1);
	const index = /* @__PURE__ */ new Map();
	const own = (id, b) => {
		index.set(id, index.size);
		for (let y = b.y; y < b.y + b.h; y++) for (let x = b.x; x < b.x + b.w; x++) if (ok(x, y)) owner[at(x, y)] = index.size - 1;
	};
	for (const b of tf.boxes.values()) own(b.id, b);
	const rails = railEnds(tf);
	for (const y of tf.rails?.yards ?? []) own(yardId(y.source), y);
	for (const st of tf.rails?.stations ?? []) own(stationId(st), st);
	const hooks = /* @__PURE__ */ new Map();
	for (const d of tf.webhooks ?? []) {
		own(webhookDockId(d.machine), d);
		for (const k of d.keys) hooks.set(k, {
			id: webhookDockId(d.machine),
			rect: d,
			into: OPP[d.side]
		});
	}
	const gate = rails.size ? new Int32Array(cols * rows).fill(-1) : null;
	for (const e of rails.values()) {
		for (const x of e.yardExits) if (ok(x.x, x.y)) gate[at(x.x, x.y)] = index.get(yardId(e.yard.source));
		if (ok(e.entry.x, e.entry.y)) gate[at(e.entry.x, e.entry.y)] = index.get(stationId(e.station));
	}
	const edge = new Uint8Array(cols * rows);
	for (const z of tf.zones) if (z.airfield) {
		for (let y = z.y; y < z.y + z.h; y++) for (const x of [z.x, z.x + z.w - 1]) if (ok(x, y)) edge[at(x, y)] = EDGE;
	}
	for (const z of tf.zones) for (let x = z.x; x < z.x + z.w; x++) if (ok(x, z.y + z.h - 1)) edge[at(x, z.y + z.h - 1)] = EDGE;
	for (const g of laneGaps(tf)) if (g.y1 - g.y0 > 2) {
		for (const y of [g.y0, g.y1 - 1]) for (let x = g.x0; x < g.x1; x++) if (ok(x, y)) edge[at(x, y)] = Math.max(edge[at(x, y)], EDGE);
	}
	for (const b of tf.boxes.values()) if (b.region === "hubs") {
		const y0 = b.y + Math.floor(b.h / 2) - BADGE_ROOM.h;
		for (let y = y0; y < y0 + BADGE_ROOM.h; y++) for (let x = b.x + b.w; x < b.x + b.w + BADGE_ROOM.w; x++) if (ok(x, y)) edge[at(x, y)] = Math.max(edge[at(x, y)], BADGE);
	}
	const named = new Uint8Array(cols * rows);
	for (const l of tf.lanes) {
		const n = laneNameTiles(l, l.label);
		if (n) {
			for (let y = l.y; y < l.y + 3; y++) for (let x = n[0]; x < n[1]; x++) if (ok(x, y)) named[at(x, y)] = 1;
		}
	}
	const MANY = -9;
	const nb = new Int32Array(cols * rows * 2).fill(-1);
	for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
		const t = at(x, y);
		for (let d = 0; d < 4; d++) {
			const nx = x + STEP[DIRS[d]][0], ny = y + STEP[DIRS[d]][1];
			if (!ok(nx, ny)) continue;
			const o = owner[at(nx, ny)];
			if (o < 0 || o === nb[2 * t] || o === nb[2 * t + 1]) continue;
			if (nb[2 * t] === -1) nb[2 * t] = o;
			else if (nb[2 * t + 1] === -1) nb[2 * t + 1] = o;
			else nb[2 * t + 1] = MANY;
		}
	}
	const jobs = [];
	const out = [];
	const laneOf = (b) => tf.lanes.find((l) => l.id === b.id);
	/** A rail from its yard (a platform's exit) to its station. The yard stands in as the line's source box: its id names
	*  the yard (trunks group on it); kind, foot and region are placeholders no rule reads. */
	const railJob = (b, rail) => {
		const y = rail.yard, st = rail.station;
		const src = y ? {
			id: yardId(y.source),
			kind: "yard",
			foot: "package",
			region: "rail",
			x: y.x,
			y: y.y,
			w: y.w,
			h: y.h
		} : tf.boxes.get(rail.door);
		if (!src) return;
		const from = rail.own ?? src;
		jobs.push({
			b,
			src,
			dst: st,
			kind: "rail",
			reverse: false,
			est: Math.abs(from.x - st.x) + Math.abs(from.y - st.y),
			to: stationId(st),
			rail
		});
	};
	for (const b of bundles) {
		const A = tf.boxes.get(b.a), B = tf.boxes.get(b.b);
		if (!A || !B) continue;
		const both = b.flow === "both";
		if (flies(b.kind)) {
			const [s, d] = b.flow === "b→a" ? [B, A] : [A, B];
			out.push({
				key: b.key,
				kind: "drone",
				both,
				pieces: [],
				points: [centre$1(s), centre$1(d)]
			});
			continue;
		}
		const rail = rails.get(b.key);
		if (rail && b.kind === "batch") {
			railJob(b, rail);
			continue;
		}
		const la = laneOf(A), lb = laneOf(B);
		if (!!la !== !!lb) {
			const [box, laneBox, lane] = lb ? [
				A,
				B,
				lb
			] : [
				B,
				A,
				la
			];
			const store = laneBox.kind === "datastore";
			const kind = lineKind(b, store);
			const fromLane = store ? kind === "tapR" : lb ? b.flow === "b→a" : b.flow === "a→b";
			jobs.push({
				b,
				src: box,
				dst: band(lane),
				kind,
				reverse: fromLane,
				tap: store ? lane.id : void 0,
				est: Math.abs(box.y - lane.y),
				to: laneBox.id,
				lane: true
			});
			continue;
		}
		const hook = hooks.get(b.key);
		if (hook) {
			const src = A.kind === "external" ? A : B, back = b.flow === (src === A ? "b→a" : "a→b");
			jobs.push({
				b,
				src,
				dst: hook.rect,
				kind: lineKind(b, false),
				reverse: back,
				est: Math.abs(src.x - hook.rect.x) + Math.abs(src.y - hook.rect.y),
				to: hook.id,
				into: hook.into
			});
			continue;
		}
		const ca = A.kind === "datastore", cb = B.kind === "datastore";
		if (ca !== cb) {
			const [box, chest] = cb ? [A, B] : [B, A];
			const kind = lineKind(b, true);
			jobs.push({
				b,
				src: box,
				dst: chest,
				kind,
				reverse: kind === "tapR",
				tap: chest.id,
				est: Math.abs(box.x - chest.x) + Math.abs(box.y - chest.y),
				to: chest.id
			});
			continue;
		}
		const [src, dst] = b.flow === "b→a" ? [B, A] : [A, B];
		jobs.push({
			b,
			src,
			dst,
			kind: lineKind(b, false),
			reverse: false,
			est: Math.abs(src.x - dst.x) + Math.abs(src.y - dst.y),
			to: dst.id
		});
	}
	if (!base) for (const sh of tf.rails?.shells ?? []) {
		const rail = rails.get(sh.key);
		if (rail) railJob(sh, rail);
	}
	const ends = (j) => {
		const t = `${j.kind}|${j.reverse}`;
		return {
			src: `s|${j.src.id}|${t}`,
			dst: `d|${j.to}|${t}`
		};
	};
	const count = /* @__PURE__ */ new Map();
	for (const j of jobs) for (const k of Object.values(ends(j))) count.set(k, (count.get(k) ?? 0) + 1);
	const plan = /* @__PURE__ */ new Map();
	for (const j of jobs) {
		const e = ends(j);
		const [first, second] = j.reverse ? ["dst", "src"] : ["src", "dst"], nf = count.get(e[first]), ns = count.get(e[second]);
		const m = nf >= 2 && nf >= ns ? first : ns >= 2 ? second : null;
		plan.set(j, m ? {
			mode: m,
			group: e[m],
			size: count.get(e[m])
		} : {
			mode: null,
			group: j.b.key,
			size: 1
		});
	}
	const rank = (j) => j.tap && !tf.lanes.some((l) => l.id === j.tap) ? CHEST_RANK : RANK[j.kind];
	jobs.sort((p, q) => rank(p) - rank(q) || plan.get(q).size - plan.get(p).size || (plan.get(p).size > 1 ? plan.get(p).group < plan.get(q).group ? -1 : plan.get(p).group > plan.get(q).group ? 1 : 0 : 0) || p.est - q.est || p.b.key.localeCompare(q.b.key));
	const g = new Float64Array(cols * rows * 4).fill(Infinity);
	const prev = new Int32Array(cols * rows * 4).fill(-1);
	const done = new Uint8Array(cols * rows * 4);
	const goaled = new Uint8Array(cols * rows * 4);
	const touched = new Int32Array(cols * rows * 4);
	let nTouched = 0;
	const heap = new Heap();
	const meta = [];
	const tileIn = new Int8Array(cols * rows), tileOut = new Int8Array(cols * rows);
	const dirIdx = (d) => DIRS.indexOf(d);
	let cur = null;
	const MIXED = -2;
	const tileSrc = new Int32Array(cols * rows).fill(-1), tileTo = new Int32Array(cols * rows).fill(-1);
	const tileN = new Int32Array(cols * rows);
	const tileJoin = new Uint8Array(cols * rows);
	const housed = new Uint8Array(cols * rows);
	const tileHood = new Uint8Array(cols * rows);
	const tileTun = new Int32Array(cols * rows);
	const holders = new Array(cols * rows);
	const flowEnds = (j) => j.reverse ? {
		src: j.to,
		dst: j.src.id
	} : {
		src: j.src.id,
		dst: j.to
	};
	let me = null;
	let mode = "src";
	let meSrc = NaN, meTo = NaN;
	let curEnds = null;
	const slot = /* @__PURE__ */ new Map();
	const placed = /* @__PURE__ */ new Map();
	const place = (j, cells) => {
		const id = slot.get(j) ?? out.length;
		const both = j.b.flow === "both";
		let r;
		if (!cells) r = {
			key: j.b.key,
			kind: j.kind,
			both,
			pieces: [],
			points: [centre$1(j.src), centre$1(j.dst)],
			tap: j.tap,
			failed: true
		};
		else {
			if (me) markJoins(cells);
			const s = index.get(j.src.id), t = index.get(j.to);
			for (const p of cells) if (!p.under && occ[at(p.x, p.y)] >= 0) {
				const c = at(p.x, p.y);
				if (tileSrc[c] !== s) tileSrc[c] = MIXED;
				if (tileTo[c] !== t) tileTo[c] = MIXED;
			}
			const fe = flowEnds(j);
			for (const p of cells) if (!p.under) {
				const c = at(p.x, p.y);
				if (p.join) tileJoin[c] = 1;
				if (p.hoodBefore || p.hoodAfter) housed[c] = 1;
				tileN[c]++;
				(holders[c] ?? (holders[c] = [])).push({
					...fe,
					axis: dirIdx(j.reverse ? p.out : p.in) % 2
				});
			}
			cells.forEach((p, i) => {
				if (p.under || occ[at(p.x, p.y)] !== FREE) return;
				const c = at(p.x, p.y);
				tileSrc[c] = s;
				tileTo[c] = t;
				occ[c] = id;
				tileIn[c] = dirIdx(p.in);
				tileOut[c] = dirIdx(p.out);
				tileHood[c] = p.hoodBefore ? 1 : 0;
				let n = 0;
				if (p.hoodBefore) while (cells[i + 1 + n]?.under) n++;
				tileTun[c] = n;
			});
			meta[id] = {
				src: j.src.id,
				to: j.to,
				rev: j.reverse,
				kind: j.kind
			};
			for (const k of Object.values(ends(j))) placed.set(k, (placed.get(k) ?? 0) + 1);
			const pieces = j.reverse ? reversed(cells) : cells;
			r = {
				key: j.b.key,
				kind: j.kind,
				both,
				pieces,
				points: piecesToPoints(pieces),
				tap: j.tap,
				failed: void 0
			};
		}
		if (slot.has(j)) out[id] = r;
		else {
			slot.set(j, id);
			out.push(r);
		}
		return !!cells;
	};
	const failedJobs = [];
	for (const j of jobs) {
		const m = plan.get(j).mode;
		cur = j;
		me = m ? j : null;
		mode = m ?? "src";
		if (!place(j, clean(j, MAX_UNDER))) failedJobs.push(j);
	}
	for (const j of failedJobs) {
		me = cur = j;
		let cells = null;
		tries: for (const u of [MAX_UNDER, 12]) for (const m of ["src", "dst"]) {
			mode = m;
			cells = clean(j, u);
			if (cells) break tries;
		}
		place(j, cells);
	}
	me = null;
	return out;
	/** A search whose line never crosses its own tile on top: a tile it would repeat is closed and the search rerun. */
	function clean(j, maxUnder) {
		const closed = [];
		try {
			for (let n = 0; n < 4; n++) {
				const cells = search(j.src, j.dst, maxUnder, j.to, j.rail, j.into, j.lane);
				if (!cells) return null;
				const seen = /* @__PURE__ */ new Set();
				const again = cells.find((p) => {
					if (p.under) return false;
					const t = at(p.x, p.y);
					if (seen.has(t)) return true;
					seen.add(t);
					return false;
				});
				if (!again) return cells;
				closed.push([at(again.x, again.y), occ[at(again.x, again.y)]]);
				occ[at(again.x, again.y)] = BOX;
			}
			return null;
		} finally {
			for (const [t, v] of closed.reverse()) occ[t] = v;
		}
	}
	/** Does tile t carry (on top) any line sharing a data-flow end with the one being searched, along the axis of a tunnel heading `d`? */
	function mateAlong(t, d) {
		const list = holders[t], fe = curEnds;
		if (!list || !fe) return false;
		return list.some((h) => (h.src === fe.src || h.dst === fe.dst) && h.axis === d % 2);
	}
	/** May the line being searched run on tile t (held by line v) arriving in direction d? */
	function shares(v, t, d) {
		const m = meta[v];
		if (!me || !m || m.rev !== me.reverse || m.kind !== me.kind) return false;
		return mode === "src" ? tileSrc[t] === meSrc && tileIn[t] === d : tileTo[t] === meTo;
	}
	/** The tile one step from t along direction index d, or -1 off the floor. */
	function next(t, d) {
		const x = t % cols + STEP[DIRS[d]][0], y = (t / cols | 0) + STEP[DIRS[d]][1];
		return ok(x, y) ? at(x, y) : -1;
	}
	/** May a line leave the trunk at t (a split)? Not where the trunk alone runs on into tiles others share: the holder would
	*  hop between partners. Likewise a line may join at t (a merge) only if the trunk did not arrive there shared. */
	function canLeave(t) {
		const n = next(t, tileOut[t]);
		return roomAt(t) && (tileN[t] >= 2 || n < 0 || tileN[n] <= 1);
	}
	function canJoin(t) {
		const p = next(t, (tileIn[t] + 2) % 4);
		return roomAt(t) && (tileN[t] >= 2 || p < 0 || tileN[p] <= 1);
	}
	/** Room round a junction (the owner's 2 in, 1 out): the trunk runs straight through it, and the trunk tiles either side
	*  are plain pieces -- no other junction, no underground housing -- as is the tile on the junction itself. The plate
	*  keeps off the factory walls: no machine touches its tile on any side (a plate against a wall reads as part of it). */
	function roomAt(t) {
		if (tileIn[t] !== tileOut[t] || tileJoin[t] || housed[t] || nb[2 * t] !== -1) return false;
		const plain = (n) => n < 0 || !tileJoin[n] && !housed[n];
		return plain(next(t, tileOut[t])) && plain(next(t, (tileIn[t] + 2) % 4));
	}
	/** Which way may the line go on from a trunk tile it arrived at: -1 anywhere (it splits off), else the way the trunk runs. */
	function forced(t) {
		return mode === "src" ? -1 : tileOut[t];
	}
	/** Mark the one junction of a line on a trunk: its last shared tile (split, shared source) or its first (merge, shared target). */
	function markJoins(cells) {
		const shared = cells.filter((p) => !p.under && occ[at(p.x, p.y)] >= 0);
		if (!shared.length) return;
		if (mode === "src") shared[shared.length - 1].join = "split";
		else shared[0].join = "merge";
	}
	/** A* from any side of `src` to any tile beside `dst` (with `entry`, only running into it that way); null when walled in. A rail (`rail`) starts only on its own
	*  platform's exit, or on another exit of its yard where a trunk it rides starts, and ends only on an end of its
	*  station, running into it along the destination's wall. */
	function search(src, dst, maxUnder, dstId, rail, entry, lane = false) {
		const mine = [index.get(src.id), dstId === void 0 ? void 0 : index.get(dstId)];
		curEnds = cur ? flowEnds(cur) : null;
		meSrc = me ? index.get(me.src.id) ?? NaN : NaN;
		meTo = me ? index.get(me.to) ?? NaN : NaN;
		const m0 = mine[0] ?? -1, m1 = mine[1] ?? -1, m2 = rail ? index.get(rail.dest) : -1;
		/** A tile as this line sees it: another rail's start or end tile is a wall. */
		const eff = gate ? (t) => gate[t] >= 0 && gate[t] !== m0 && gate[t] !== m1 ? BOX : occ[t] : (t) => occ[t];
		const rides = (t) => {
			const m = meta[occ[t]];
			return !!me && !!m && m.rev === me.reverse && m.kind === me.kind;
		};
		const startOk = (t, d) => eff(t) === FREE || me !== null && mode === "src" && occ[t] >= 0 && shares(occ[t], t, d);
		const endOk = (t) => eff(t) === FREE || occ[t] >= 0 && rides(t) && (mode === "src" ? tileSrc[t] === meSrc : tileTo[t] === meTo);
		/** A rail's start tiles: its own exit when free, any exit of its yard a trunk to ride starts on (on a ladder, its own
		*  exit only: the yard planned which rails leave together). */
		const starts = rail?.yard ? rail.yardExits.filter((e) => ok(e.x, e.y) && (!rail.yard.ladder || e === rail.own)).map((e) => [
			e.x,
			e.y,
			DIRS.indexOf(e.d),
			e === rail.own ? 1 : 0
		]) : [];
		const startAt = (x, y, di, mineToo) => {
			const t = at(x, y);
			return eff(t) === FREE && mineToo === 1 || me !== null && mode === "src" && occ[t] >= 0 && shares(occ[t], t, di);
		};
		const isEnd = (x, y) => !!rail && rail.entry.x === x && rail.entry.y === y;
		let lead = null;
		if (rail?.yard?.free) {
			lead = /* @__PURE__ */ new Map();
			for (const e of rail.yardExits) for (let s = 0; s < 2; s++) if (ok(e.x + STEP[e.d][0] * s, e.y + STEP[e.d][1] * s)) lead.set(at(e.x + STEP[e.d][0] * s, e.y + STEP[e.d][1] * s), DIRS.indexOf(e.d));
		}
		if (rail?.yard) {
			if (!starts.some(([x, y, di, o]) => startAt(x, y, di, o))) return null;
		} else if (!DIRS.some((d, di) => side(src, d).some(([x, y]) => ok(x, y) && startOk(at(x, y), di)))) return null;
		if (rail) {
			if (!(ok(rail.entry.x, rail.entry.y) && endOk(at(rail.entry.x, rail.entry.y)))) return null;
		} else if (!DIRS.some((d) => (!entry || d === OPP[entry]) && side(dst, d).some(([x, y]) => ok(x, y) && endOk(at(x, y))))) return null;
		for (let i = 0; i < nTouched; i++) {
			const t = touched[i];
			g[t] = Infinity;
			prev[t] = -1;
			done[t] = 0;
			goaled[t] = 0;
		}
		nTouched = 0;
		heap.clear();
		const GOAL = g.length;
		const key = (x, y, d) => at(x, y) * 4 + d;
		const dx0 = dst.x - 1, dx1 = dst.x + dst.w, dy0 = dst.y - 1, dy1 = dst.y + dst.h;
		const hw = me && (placed.get(ends(me)[mode]) ?? 0) > 0 ? RIDE : 1;
		const h = (x, y) => hw * (Math.max(0, dx0 - x, x - dx1) + Math.max(0, dy0 - y, y - dy1));
		const relax = (nk, cost, from, x, y) => {
			if (cost < g[nk]) {
				if (g[nk] === Infinity) touched[nTouched++] = nk;
				g[nk] = cost;
				prev[nk] = from;
				heap.push(cost + h(x, y), nk);
			}
		};
		if (rail?.yard) {
			for (const [x, y, di, o] of starts) if (startAt(x, y, di, o)) relax(key(x, y, di), 0, -1, x, y);
		} else for (let di = 0; di < 4; di++) for (const [x, y, off] of side(src, DIRS[di])) {
			if (!ok(x, y)) continue;
			const v = eff(at(x, y));
			if (v === FREE || me && mode === "src" && v >= 0 && shares(v, at(x, y), di)) relax(key(x, y, di), v === FREE ? endCost(src, DIRS[di], off) : 0, -1, x, y);
		}
		const rider = me !== null, dstMode = mode === "dst";
		while (heap.size) {
			let k = heap.pop();
			if (k >= GOAL) {
				k -= GOAL;
				return build(k, dirInto(dst, (k >> 2) % cols, (k >> 2) / cols | 0));
			}
			if (done[k]) continue;
			done[k] = 1;
			const cell = k >> 2, di = k & 3, x = cell % cols, y = cell / cols | 0;
			const here = cell, hv = occ[here], gk = g[k];
			const riding = rider && hv >= 0;
			const only = riding ? forced(here) : -1;
			const into0 = !(x >= dx0 && x <= dx1 && y >= dy0 && y <= dy1) || rail && !isEnd(x, y) ? null : dirInto(dst, x, y), into = entry && into0 !== entry ? null : into0;
			const leaves = !(riding && !dstMode) || canLeave(here);
			const lock = lead !== null && lead.get(here) === di ? di : -1;
			if (into && (only < 0 || into === DIRS[only]) && leaves) {
				const end = next(here, dirIdx(into));
				const off = hv === FREE ? endCost(dst, into, offMid(dst, x, y, into), lane) + (end >= 0 && named[end] ? NAME : 0) : 0;
				if (off === 0) return build(k, into);
				if (!goaled[k]) {
					goaled[k] = 1;
					heap.push(g[k] + off, GOAL + k);
				}
			}
			for (let ni = 0; ni < 4; ni++) {
				if (ni === (di + 2) % 4) continue;
				if (only >= 0 && ni !== only) continue;
				if (lock >= 0 && ni !== lock) continue;
				const dx = DX[ni], dy = DY[ni];
				const nx = x + dx, ny = y + dy;
				if (nx < 0 || ny < 0 || nx >= cols || ny >= rows) continue;
				const nt = cell + dy * cols + dx, v = eff(nt);
				if (v === FREE) {
					if (!(riding && dstMode) && leaves) {
						const a = nb[2 * nt], b = nb[2 * nt + 1];
						const cost = gk + 1 + ((a >= 0 && a !== m0 && a !== m1 && a !== m2 || b >= 0 && b !== m0 && b !== m1 && b !== m2 || b === MANY ? HUG : 0) + edge[nt]) + (ni === di ? 0 : TURN);
						relax(nt * 4 + ni, cost, k, nx, ny);
					}
				} else if (v !== BOX) {
					if (riding && tileHood[here] && ni === tileOut[here]) {
						const n = tileTun[here], ex = x + dx * (n + 1), ey = y + dy * (n + 1);
						let clear = ok(ex, ey) && eff(at(ex, ey)) >= 0 && shares(occ[at(ex, ey)], at(ex, ey), ni);
						for (let s = 1; s <= n && clear; s++) clear = eff(at(x + dx * s, y + dy * s)) !== BOX && !mateAlong(at(x + dx * s, y + dy * s), ni);
						if (clear) relax(key(ex, ey, ni), g[k] + RIDE * (n + 1), k, ex, ey);
						continue;
					}
					const share = me !== null && v >= 0 && (riding || mode === "dst") && shares(v, at(nx, ny), ni) && (!riding || ni === tileOut[here]) && (riding || canJoin(at(nx, ny)));
					const rose = share && prev[k] >= 0 && Math.abs((prev[k] >> 2) % cols - x) + Math.abs(((prev[k] >> 2) / cols | 0) - y) > 1;
					if (share && !(rose && hv === FREE)) relax(key(nx, ny, ni), g[k] + RIDE + (riding || ni === di ? 0 : TURN), k, nx, ny);
					if (ni !== di || riding) continue;
					if (prev[k] >= 0 && occ[prev[k] >> 2] >= 0) continue;
					let hidden = mateAlong(at(nx, ny), ni);
					let name = named[nt];
					for (let s = 2; s <= maxUnder + 1 && !hidden; s++) {
						const tx = x + dx * s, ty = y + dy * s;
						if (!ok(tx, ty)) break;
						const tv = eff(at(tx, ty));
						if (tv === BOX) break;
						if (tv === FREE) {
							relax(key(tx, ty, ni), g[k] + s + UNDER + (name ? NAME : 0), k, tx, ty);
							break;
						}
						hidden = mateAlong(at(tx, ty), ni);
						name |= named[at(tx, ty)];
					}
				}
			}
		}
		return null;
		function build(k, into) {
			const chain = [];
			for (let c = k; c !== -1; c = prev[c]) chain.push(c);
			chain.reverse();
			const ps = [];
			for (const c of chain) {
				const cell = c >> 2, d = DIRS[c & 3], x = cell % cols, y = cell / cols | 0;
				const last = ps[ps.length - 1];
				if (last) {
					const [dx, dy] = STEP[d];
					for (let tx = last.x + dx, ty = last.y + dy; tx !== x || ty !== y; tx += dx, ty += dy) ps.push({
						x: tx,
						y: ty,
						in: d,
						out: d,
						under: true,
						hoodBefore: false,
						hoodAfter: false
					});
				}
				ps.push({
					x,
					y,
					in: d,
					out: d,
					under: false,
					hoodBefore: false,
					hoodAfter: false
				});
			}
			for (let i = 0; i < ps.length; i++) {
				ps[i].out = i + 1 < ps.length ? ps[i + 1].in : into;
				ps[i].hoodBefore = !ps[i].under && !!ps[i + 1]?.under;
				ps[i].hoodAfter = !ps[i].under && !!ps[i - 1]?.under;
			}
			return ps;
		}
	}
}
/** How far tile (x, y), just outside the side of `b` it enters through (`d`, the travel direction), is from that side's middle. */
function offMid(b, x, y, d) {
	return d === "e" || d === "w" ? Math.abs(y - (b.y + (b.h - 1) / 2)) : Math.abs(x - (b.x + (b.w - 1) / 2));
}
/** Is a tile `off` from the middle of a side of `b` that side's outermost tile (a side of three or more tiles)? */
function cornerTile(b, d, off) {
	const n = d === "n" || d === "s" ? b.w : b.h;
	return n >= 3 && off === (n - 1) / 2;
}
/** What an end `off` tiles from a side's middle costs: OFF a tile, at least CORNER on the outermost tile. A lane
*  (`lane`) runs under every machine above it: no tile of its side is better than another, so a line drops straight
*  onto it and only its outermost tile costs CORNER. */
function endCost(b, d, off, lane = false) {
	return Math.max(lane ? 0 : off * OFF, cornerTile(b, d, off) ? CORNER : 0);
}
/** Tiles just outside one side of a box, with each tile's distance from the middle of that side. */
function side(b, d) {
	const out = [];
	if (d === "n" || d === "s") {
		const y = d === "n" ? b.y - 1 : b.y + b.h, mid = b.x + (b.w - 1) / 2;
		for (let x = b.x; x < b.x + b.w; x++) out.push([
			x,
			y,
			Math.abs(x - mid)
		]);
	} else {
		const x = d === "w" ? b.x - 1 : b.x + b.w, mid = b.y + (b.h - 1) / 2;
		for (let y = b.y; y < b.y + b.h; y++) out.push([
			x,
			y,
			Math.abs(y - mid)
		]);
	}
	return out;
}
/** Pixel corners of a tile line: from its entry edge, through each corner tile's centre, to its exit edge. */
function piecesToPoints(ps) {
	if (!ps.length) return [];
	const c = (p) => ({
		x: p.x * 24 + 12,
		y: p.y * 24 + 12
	});
	const f = ps[0], l = ps[ps.length - 1];
	const pts = [{
		x: c(f).x - STEP[f.in][0] * 24 / 2,
		y: c(f).y - STEP[f.in][1] * 24 / 2
	}];
	for (const p of ps) if (p.in !== p.out) pts.push(c(p));
	pts.push({
		x: c(l).x + STEP[l.out][0] * 24 / 2,
		y: c(l).y + STEP[l.out][1] * 24 / 2
	});
	return pts;
}
/** The same line travelled the other way (a read runs from the lane up to the machine). */
function reversed(ps) {
	return ps.slice().reverse().map((p) => ({
		...p,
		in: OPP[p.out],
		out: OPP[p.in],
		hoodBefore: p.hoodAfter,
		hoodAfter: p.hoodBefore,
		...p.join ? { join: p.join === "split" ? "merge" : "split" } : {}
	}));
}
/** A binary min-heap of keys by priority, on typed arrays that grow as needed and are kept between searches (`clear`).
*  The same comparisons as swapping sifts, so ties pop in the same order: the plans do not change. */
var Heap = class {
	f = /* @__PURE__ */ new Float64Array(1024);
	k = /* @__PURE__ */ new Int32Array(1024);
	size = 0;
	clear() {
		this.size = 0;
	}
	push(f, k) {
		if (this.size === this.k.length) {
			const nf = new Float64Array(this.size * 2), nk = new Int32Array(this.size * 2);
			nf.set(this.f);
			nk.set(this.k);
			this.f = nf;
			this.k = nk;
		}
		const F = this.f, K = this.k;
		let i = this.size++;
		while (i > 0) {
			const p = i - 1 >> 1;
			if (F[p] <= f) break;
			F[i] = F[p];
			K[i] = K[p];
			i = p;
		}
		F[i] = f;
		K[i] = k;
	}
	/** Bottom-up: down the path of smaller children (the right one only when strictly smaller) to a leaf, back up to
	*  the deepest entry on it still below the last one, which goes there as the path above moves up one. A top-down
	*  sift stops at that same place, as priorities only grow down the path: the same heap, fewer comparisons. */
	pop() {
		const F = this.f, K = this.k;
		const top = K[0], n = --this.size;
		if (n) {
			const lf = F[n], lk = K[n];
			let j = 0;
			for (let l = 1; l < n; l = 2 * j + 1) j = l + (+(F[l + 1] < F[l]) & +(l + 1 < n));
			while (j > 0 && F[j] >= lf) j = j - 1 >> 1;
			let cf = lf, ck = lk;
			while (j > 0) {
				const tf = F[j], tk = K[j];
				F[j] = cf;
				K[j] = ck;
				cf = tf;
				ck = tk;
				j = j - 1 >> 1;
			}
			F[0] = cf;
			K[0] = ck;
		}
		return top;
	}
};
// src/factory/flights.ts
var DOT = 4;
var centre = (r) => ({
	x: (r.x + r.w / 2) * 24,
	y: (r.y + r.h / 2) * 24
});
var flightKey = (machine, item) => [machine, item].sort().join("|");
/** A consumer tag's key: its flight's key and its group, since one machine may take from one hub in two groups. */
var tagKey = (machine, item, group) => `${flightKey(machine, item)}|${group ?? ""}`;
/** Every placed flight on the floor: one per pad and one per dock, sorted like the pads; none on a floor with no hub. */
function flightPaths(tf) {
	const land = tf.landing;
	if (!land) return [];
	const msg = land.messaging;
	const rels = (machine, item, role, group) => {
		if (role === "produce") return msg.producers.find((p) => p.machine === machine && p.item === item)?.viaRelations ?? [];
		if (role === "failure") return msg.failures.find((f) => f.machine === machine && f.item === item)?.viaRelations ?? [];
		return msg.consumers.find((c) => c.machine === machine && c.item === item && c.group === group)?.viaRelations ?? [];
	};
	const out = [];
	const px = (r) => ({
		x0: r.x * 24,
		y0: r.y * 24,
		x1: (r.x + r.w) * 24,
		y1: (r.y + r.h) * 24
	});
	const add = (w, launch, dock) => {
		const hubBox = tf.boxes.get(w.item);
		if (!hubBox) return;
		const straight = [launch, centre(hubBox)];
		const pts = hubBox.foot === "door" ? clipInto(straight, px(hubBox)) : straight;
		const outbound = w.flight === "produce" || w.flight === "enqueue" || w.flight === "failure" || w.flight === "pull";
		out.push({
			key: flightKey(w.machine, w.item),
			flight: w.flight,
			role: w.role,
			machine: w.machine,
			item: w.item,
			topic: w.topic,
			...w.group !== void 0 ? { group: w.group } : {},
			dock,
			dead: w.flight === "failure",
			launch,
			hub: pts[pts.length - 1],
			outbound,
			points: outbound ? pts : [...pts].reverse(),
			relations: rels(w.machine, w.item, w.role, w.group)
		});
	};
	for (const p of land.pads) add(p, padCentre(p), false);
	for (const d of land.docks) add(d, centre(d), true);
	return spreadLandings(out, tf);
}
/** How long two paths must run that close to be on top of each other, not just crossing: a tile, three dots and their
*  gaps (2 px on, 6 off). Lines crossing at more than about 14° are that close for less (2·3 px / sin 14° ≈ 24 px), so
*  this also asks that they come in close in direction. */
var OVERLAP_RUN = 24;
/** Landing points keep this far in from the edge's corners. */
var LANDING_INSET = 6;
/** How much wider a spread is tried each time, up to the whole edge, while paths in it still run together. */
var WIDEN_STEP = 4;
/** The part of a path a reader sees at its hub end: from its pad or dock to where it first reaches the hub's box (the
*  rest, to a hub's centre, is under the hub). */
function visiblePart(p, hubBox) {
	const pts = clipInto([p.launch, p.hub], hubBox);
	return [pts[0], pts[pts.length - 1]];
}
/** The stretch of segment `a`, as a part [t0, t1] of it (0 at a[0], 1 at a[1]), whose points lie within `tol` of
*  segment `b`, or undefined. Closed form: the points within `tol` of `b` make a capsule (a band along `b` and a disc at
*  each end), convex, so `a` meets it in one stretch, from the first of its entries to the last of its exits. */
function nearStretch(a, b, tol) {
	const dx = a[1].x - a[0].x, dy = a[1].y - a[0].y;
	let lo = Infinity, hi = -Infinity;
	const take = (s, e) => {
		if (s <= e) {
			lo = Math.min(lo, s);
			hi = Math.max(hi, e);
		}
	};
	const disc = (c) => {
		const fx = a[0].x - c.x, fy = a[0].y - c.y, A = dx * dx + dy * dy, B = 2 * (fx * dx + fy * dy), C = fx * fx + fy * fy - tol * tol;
		if (A === 0) {
			if (C <= 0) take(0, 1);
			return;
		}
		const disc2 = B * B - 4 * A * C;
		if (disc2 < 0) return;
		const r = Math.sqrt(disc2);
		take((-B - r) / (2 * A), (-B + r) / (2 * A));
	};
	disc(b[0]);
	disc(b[1]);
	const bx = b[1].x - b[0].x, by = b[1].y - b[0].y, L = Math.hypot(bx, by);
	if (L > 0) {
		const ux = bx / L, uy = by / L;
		const u0 = (a[0].x - b[0].x) * ux + (a[0].y - b[0].y) * uy, du = dx * ux + dy * uy;
		const v0 = -(a[0].x - b[0].x) * uy + (a[0].y - b[0].y) * ux, dv = -dx * uy + dy * ux;
		let s = -Infinity, e = Infinity;
		for (const [p0, dp, min, max] of [[
			u0,
			du,
			0,
			L
		], [
			v0,
			dv,
			-tol,
			tol
		]]) {
			if (dp === 0) {
				if (p0 < min || p0 > max) {
					s = 1;
					e = 0;
				}
				continue;
			}
			const t1 = (min - p0) / dp, t2 = (max - p0) / dp;
			s = Math.max(s, Math.min(t1, t2));
			e = Math.min(e, Math.max(t1, t2));
		}
		take(s, e);
	}
	const s = Math.max(0, lo), e = Math.min(1, hi);
	return s <= e ? [s, e] : void 0;
}
/** The part [t0, t1] of segment `a` inside rect `r` (Liang–Barsky), or undefined. */
function insideStretch(a, r) {
	let t0 = 0, t1 = 1;
	const dx = a[1].x - a[0].x, dy = a[1].y - a[0].y;
	for (const [p, q] of [
		[-dx, a[0].x - r.x0],
		[dx, r.x1 - a[0].x],
		[-dy, a[0].y - r.y0],
		[dy, r.y1 - a[0].y]
	]) {
		if (p === 0) {
			if (q < 0) return void 0;
			continue;
		}
		const t = q / p;
		if (p < 0) {
			if (t > t1) return void 0;
			if (t > t0) t0 = t;
		} else {
			if (t < t0) return void 0;
			if (t < t1) t1 = t;
		}
	}
	return t0 < t1 ? [t0, t1] : void 0;
}
/** How much of segment `a`, in px, runs within `tol` of segment `b` on open floor: outside every rect of `boxes`. */
function alongside(a, b, tol, boxes) {
	const near = nearStretch(a, b, tol);
	if (!near) return 0;
	const len = Math.hypot(a[1].x - a[0].x, a[1].y - a[0].y);
	const cut = boxes.map((r) => insideStretch(a, r)).filter((s) => !!s && s[1] > near[0] && s[0] < near[1]).map(([s, e]) => [Math.max(s, near[0]), Math.min(e, near[1])]).sort((u, v) => u[0] - v[0]);
	let covered = 0, end = near[0];
	for (const [s, e] of cut) if (e > end) {
		covered += e - Math.max(s, end);
		end = e;
	}
	return (near[1] - near[0] - covered) * len;
}
/** How long two segments run on top of each other on open floor: the shorter of each one's stretch within OVERLAP_PX
*  of the other outside every rect of `boxes` (the same either way round). Under a box they are hidden, not on top of
*  each other: `flights.hidden` reports that. */
function runTogether(a, b, boxes = []) {
	return Math.min(alongside(a, b, 3, boxes), alongside(b, a, 3, boxes));
}
/** Two launches in line with a hub: one lies within OVERLAP_PX of the other's straight line to the hub's centre (one
*  machine straight behind another). Their paths can be spread only as far as the hub's edge allows. */
function inLine(a, b, hubCentre) {
	return segDist(a, b, hubCentre) <= 3 || segDist(b, a, hubCentre) <= 3;
}
var segDist = (q, a, b) => {
	const dx = b.x - a.x, dy = b.y - a.y, l2 = dx * dx + dy * dy;
	const t = l2 ? Math.max(0, Math.min(1, ((q.x - a.x) * dx + (q.y - a.y) * dy) / l2)) : 0;
	return Math.hypot(q.x - a.x - t * dx, q.y - a.y - t * dy);
};
/** Paths into one hub that run on top of each other (`runTogether` at least OVERLAP_RUN over the parts a reader sees,
*  on open floor) get their own landing points on the hub's edge; every other path keeps its landing (the hub's
*  centre, a door's edge), so twenty consumers spread round a hub stay as they are. A group of paths that overlap, one
*  with the next, lands on the edge its mean direction reaches, `LANDING_GAP` apart, centred where that direction
*  meets the edge, in the order the paths cross the edge's line, so they do not cross. Paths in line (`inLine`) cross
*  it at one place: the nearest pad takes the middle point and the farther ones the outer points, and while two paths
*  of the group still run together the points are spread wider, up to the whole edge. More paths than the edge holds
*  at LANDING_GAP: the extras share the nearest point, in order (`flights.overlap` reports them); no path is dropped.
*  A path moved this way may then run on another: the groups merge and are spread again, until none does. The path
*  stays one straight segment, drawn under the machines as before. Deterministic: the paths keep their order, and
*  ties go by distance, then by the paths' fields, never by where they sit in the input. */
function spreadLandings(paths, tf) {
	const px = (r) => ({
		x0: r.x * 24,
		y0: r.y * 24,
		x1: (r.x + r.w) * 24,
		y1: (r.y + r.h) * 24
	});
	const faces = keepOffBoxes(tf, 0).map((b) => b.r);
	const out = [...paths];
	const byHub = /* @__PURE__ */ new Map();
	paths.forEach((p, i) => (byHub.get(p.item) ?? byHub.set(p.item, []).get(p.item)).push(i));
	for (const [item, idx] of byHub) {
		const box = tf.boxes.get(item);
		if (!box || idx.length < 2) continue;
		const r = px(box);
		const parent = new Map(idx.map((i) => [i, i]));
		const find = (i) => parent.get(i) === i ? i : find(parent.get(i));
		const union = (a, b) => {
			const x = find(a), y = find(b);
			if (x === y) return false;
			parent.set(Math.max(x, y), Math.min(x, y));
			return true;
		};
		const collide = (cur, a, b) => runTogether(visiblePart(cur[a], r), visiblePart(cur[b], r), faces) >= OVERLAP_RUN;
		for (let a = 0; a < idx.length; a++) for (let b = a + 1; b < idx.length; b++) if (collide(paths, idx[a], idx[b])) union(idx[a], idx[b]);
		for (let round = 0; round < idx.length; round++) {
			const groups = /* @__PURE__ */ new Map();
			for (const i of idx) (groups.get(find(i)) ?? groups.set(find(i), []).get(find(i))).push(i);
			const cur = [...paths];
			for (const g of groups.values()) if (g.length > 1) {
				const launches = g.map((i) => paths[i].launch), ties = g.map((i) => tieKey(paths[i]));
				for (let gap = 12;; gap += WIDEN_STEP) {
					const lands = landingPoints(launches, r, gap, ties);
					g.forEach((i, k) => {
						cur[i] = landAt(paths[i], lands.points[k]);
					});
					if (g.every((a, x) => g.slice(x + 1).every((b) => !collide(cur, a, b))) || lands.widest) break;
				}
			}
			for (const i of idx) out[i] = cur[i];
			let merged = false;
			for (let a = 0; a < idx.length; a++) for (let b = a + 1; b < idx.length; b++) if (find(idx[a]) !== find(idx[b]) && collide(cur, idx[a], idx[b])) merged = union(idx[a], idx[b]) || merged;
			if (!merged) break;
		}
	}
	return out;
}
/** What orders two paths whose launches are the same distance along the edge and from the hub: their own fields. */
var tieKey = (p) => `${p.machine}|${p.flight}|${p.group ?? ""}|${p.dock ? 1 : 0}`;
/** The path to `hub` instead: the same flight, one straight segment from its launch. */
var landAt = (p, hub) => ({
	...p,
	hub,
	points: p.outbound ? [p.launch, hub] : [hub, p.launch]
});
/** One landing point per launch on box `r`'s edge, `gap` apart (see `spreadLandings`), in the launches' order;
*  `widest`: the points already take the whole edge, so a wider gap would change nothing. `ties` orders launches the
*  geometry cannot (default: their index). */
function landingPoints(launches, r, gap = 12, ties) {
	const c = {
		x: (r.x0 + r.x1) / 2,
		y: (r.y0 + r.y1) / 2
	}, hw = (r.x1 - r.x0) / 2, hh = (r.y1 - r.y0) / 2;
	let mx = 0, my = 0;
	for (const l of launches) {
		const d = Math.hypot(l.x - c.x, l.y - c.y) || 1;
		mx += (l.x - c.x) / d;
		my += (l.y - c.y) / d;
	}
	if (!mx && !my) my = -1;
	const level = Math.abs(my) * hw >= Math.abs(mx) * hh;
	const at = level ? my < 0 ? r.y0 : r.y1 : mx < 0 ? r.x0 : r.x1;
	const lo = (level ? r.x0 : r.y0) + LANDING_INSET, hi = (level ? r.x1 : r.y1) - LANDING_INSET;
	const anchor = level ? c.x + mx / Math.abs(my) * hh : c.y + my / Math.abs(mx) * hw;
	const cross = launches.map((l) => {
		const [u, v, cu, cv] = level ? [
			l.x,
			l.y,
			c.x,
			c.y
		] : [
			l.y,
			l.x,
			c.y,
			c.x
		];
		return v === cv ? u : u + (cu - u) * (at - v) / (cv - v);
	});
	const far = launches.map((l) => Math.hypot(l.x - c.x, l.y - c.y));
	const tie = (a, b) => (ties ? ties[a] < ties[b] ? -1 : ties[a] > ties[b] ? 1 : 0 : 0) || a - b;
	const order = launches.map((_, i) => i).sort((a, b) => cross[a] - cross[b] || far[a] - far[b] || tie(a, b));
	const n = launches.length, room = Math.max(0, hi - lo);
	const cap = Math.floor(room / 12) + 1, k = Math.min(n, cap);
	const step = k > 1 ? Math.min(gap, room / (k - 1)) : 0;
	const start = Math.min(Math.max(anchor - (k - 1) * step / 2, lo), hi - (k - 1) * step);
	const slotOf = (rank) => n <= cap ? rank : Math.round(rank * (cap - 1) / (n - 1));
	const slots = order.map((_, rank) => start + slotOf(rank) * step);
	const placed = new Array(n);
	for (let s = 0; s < n;) {
		let e = s + 1;
		while (e < n && inLine(launches[order[e]], launches[order[e - 1]], c)) e++;
		const run = order.slice(s, e), mid = cross[run[0]];
		const free = slots.slice(s, e).map((u, j) => ({
			u,
			j
		})).sort((a, b) => Math.abs(a.u - mid) - Math.abs(b.u - mid) || a.j - b.j);
		[...run].sort((a, b) => far[a] - far[b] || tie(a, b)).forEach((i, j) => {
			placed[i] = free[j].u;
		});
		s = e;
	}
	return {
		points: launches.map((_, i) => level ? {
			x: placed[i],
			y: at
		} : {
			x: at,
			y: placed[i]
		}),
		widest: k < 2 || step < gap || (k - 1) * step >= room - 1e-9
	};
}
/** `flightKeepOff`'s rects, each with what it is (`name`) and the box it belongs to (`owner`: the box itself, a dock's
*  or webhook dock's machine, a waiting stack's hub). `shadow`: px the boxes' shadow adds right and below (0: their
*  faces alone). */
function keepOffBoxes(tf, shadow = 5) {
	const SHADOW = shadow;
	const boxes = [...tf.boxes.values()].map((r) => ({
		name: r.id,
		owner: r.id,
		r: {
			x0: r.x * 24,
			y0: r.y * 24,
			x1: (r.x + r.w) * 24 + SHADOW,
			y1: (r.y + r.h) * 24 + SHADOW
		}
	}));
	const tiles = (r) => ({
		x0: r.x * 24,
		y0: r.y * 24,
		x1: (r.x + r.w) * 24,
		y1: (r.y + r.h) * 24
	});
	const docks = (tf.landing?.docks ?? []).map((d) => ({
		name: `${d.machine}'s receiving dock`,
		owner: d.machine,
		r: tiles(d)
	}));
	const webhooks = (tf.webhooks ?? []).map((d) => ({
		name: `${d.machine}'s webhook dock`,
		owner: d.machine,
		r: tiles(d)
	}));
	const stacks = (tf.landing?.stacks ?? []).map((s) => ({
		name: `${s.item}'s waiting stack`,
		owner: s.item,
		r: tiles({
			x: s.x,
			y: s.y,
			w: 1,
			h: 1
		})
	}));
	return [
		...boxes,
		...docks,
		...webhooks,
		...stacks
	];
}
/** `pts` cut where they first reach `r`: the path then ends on `r`'s edge. Unchanged when they start inside it or never
*  reach it. */
function clipInto(pts, r) {
	for (let i = 1; i < pts.length; i++) {
		const a = pts[i - 1], b = pts[i];
		let t0 = 0, t1 = 1, hit = true;
		const dx = b.x - a.x, dy = b.y - a.y;
		for (const [p, q] of [
			[-dx, a.x - r.x0],
			[dx, r.x1 - a.x],
			[-dy, a.y - r.y0],
			[dy, r.y1 - a.y]
		]) {
			if (p === 0) {
				if (q < 0) hit = false;
				continue;
			}
			const t = q / p;
			if (p < 0) {
				if (t > t0) t0 = t;
			} else if (t < t1) t1 = t;
		}
		if (!hit || t0 > t1) continue;
		if (t0 <= 0) return pts;
		return [...pts.slice(0, i), {
			x: a.x + dx * t0,
			y: a.y + dy * t0
		}];
	}
	return pts;
}
/** The drone routes the flight paths replace: a bundle every relation of which some placed flight carries. A bundle only
*  partly carried (a want left unplaced, or a relation no flight carries) keeps its old machine→hub route as well as the
*  flights it has: nothing is lost, and the carried relations are then drawn twice (accepted; no real floor has one). */
function coveredKeys(paths, bundles) {
	const carried = new Set(paths.flatMap((p) => p.relations));
	const keys = new Set(paths.map((p) => p.key));
	return new Set(bundles.filter((b) => keys.has(b.key) && b.relations.length > 0 && b.relations.every((r) => carried.has(r.id))).map((b) => b.key));
}
/** Small squares along a path: what a label must stay off (a diagonal path's bounding box would block far too much). */
function pathRects$1(pts, half = DOT) {
	const out = [];
	for (let i = 1; i < pts.length; i++) {
		const a = pts[i - 1], b = pts[i], len = Math.hypot(b.x - a.x, b.y - a.y), n = Math.max(1, Math.ceil(len / half));
		for (let k = 0; k <= n; k++) {
			const x = a.x + (b.x - a.x) * k / n, y = a.y + (b.y - a.y) * k / n;
			out.push({
				x0: x - half,
				y0: y - half,
				x1: x + half,
				y1: y + half
			});
		}
	}
	return out;
}
/** What labels on this floor keep off: everything `floorObstacles` lists, without the drone routes the flight paths
*  replace, plus the flight paths themselves. A floor with no hub gets exactly `floorObstacles(tf, routes)`. */
function messagingObstacles(tf, routes, paths, covered) {
	return [...floorObstacles(tf, covered.size ? routes.filter((r) => !covered.has(r.key)) : routes), ...paths.flatMap((p) => pathRects$1(p.points))];
}
/** Where along a path a plate is tried: the middle first, then stepping out to either end (not onto the pad or hub). */
var STEPS = [.5, ...Array.from({ length: 13 }, (_, i) => [.5 - (i + 1) * .03, .5 + (i + 1) * .03]).flat()];
/** One plate per flight, beside its path near the middle and never on it: candidates step out from the middle along
*  the path, on either side, a little further each round; the first box inside the floor and clear of `clear` wins and
*  joins it. No clear room: no plate. Deterministic: paths in the given order. */
function placePlates(paths, clear, bounds) {
	const out = [];
	for (const [i, p] of paths.entries()) {
		const text = FLIGHT_LABEL[p.flight];
		const w = plateW(text), h = 17;
		const segs = p.points.slice(1).map((b, k) => [p.points[k], b]).map((sg, k) => ({
			sg,
			k,
			len: Math.hypot(sg[1].x - sg[0].x, sg[1].y - sg[0].y)
		})).sort((u, v) => v.len - u.len || u.k - v.k);
		let got;
		search: for (const gap of [6, 14]) for (const { sg: [a, b], len } of segs) {
			const nx = -(b.y - a.y) / (len || 1), ny = (b.x - a.x) / (len || 1);
			const reach = Math.abs(nx) * w / 2 + Math.abs(ny) * h / 2;
			const sides = ny > 1e-9 || Math.abs(ny) <= 1e-9 && nx < 0 ? [-1, 1] : [1, -1];
			for (const t of STEPS) for (const s of sides) {
				const cx = a.x + (b.x - a.x) * t + nx * s * (gap + reach), cy = a.y + (b.y - a.y) * t + ny * s * (gap + reach);
				const box = {
					x0: Math.round(cx - w / 2),
					y0: Math.round(cy - h / 2),
					x1: Math.round(cx - w / 2) + w,
					y1: Math.round(cy - h / 2) + h
				};
				if (box.x0 < bounds.x0 || box.y0 < bounds.y0 || box.x1 > bounds.x1 || box.y1 > bounds.y1 || !clear.free(box)) continue;
				got = {
					key: p.key,
					text,
					x: box.x0,
					y: box.y0,
					w,
					h,
					of: i
				};
				clear.add(box);
				break search;
			}
		}
		if (got) out.push(got);
	}
	return out;
}
/** Labels that belong to a box (a consumer's tags, a dock's sign), tried in `spots` order: the first clear one wins. */
function placeBeside(key, text, spots, clear, bounds, size = PLATE_FONT, w = plateW(text, size)) {
	const h = 17;
	for (const s of spots) {
		const box = {
			x0: Math.round(s.x),
			y0: Math.round(s.y),
			x1: Math.round(s.x) + w,
			y1: Math.round(s.y) + h
		};
		if (box.x0 < bounds.x0 || box.y0 < bounds.y0 || box.x1 > bounds.x1 || box.y1 > bounds.y1 || !clear.free(box)) continue;
		clear.add(box);
		return {
			key,
			text,
			x: box.x0,
			y: box.y0,
			w,
			h
		};
	}
}
/** Spots for a `w`-wide label under box `r` (world px, shadow included): just below it, then a tile further down (past
*  a belt running along it); left-aligned, right-aligned, centred. */
function spotsUnder(r, w) {
	const cx = (r.x0 + r.x1) / 2 - w / 2;
	return [4, 28].flatMap((dy) => [
		r.x0,
		r.x1 - w,
		cx
	].map((x) => ({
		x,
		y: r.y1 + dy
	})));
}
/** Spots beside box `r`, level with its bottom: right, then left. */
function spotsBeside(r, w, h = 17) {
	return [{
		x: r.x1 + 6,
		y: r.y1 - h
	}, {
		x: r.x0 - 6 - w,
		y: r.y1 - h
	}];
}
/** The consumer tags a machine wears: one line per consumer with tags (`group notifier · 2 replicas`), in the model's
*  order, each keyed by `tagKey` (machine, hub and group). `wide` is the longest text the tag ever shows (a take's
*  pulse, `replica 3 of 3`), which its box is sized for. None on the site: the overview is too detailed for them (the
*  owner, 2026-10-06); the consumer's own floor shows them. */
function consumerTags(tf) {
	if (tf.site) return [];
	return (tf.landing?.messaging.consumers ?? []).filter((c) => c.tags.length).map((c) => {
		const text = c.tags.join(" · "), n = c.replicas ?? 1;
		const pulse = c.flight === "take" && n > 1 ? replicaPulse(text, n, n) : text;
		return {
			machine: c.machine,
			key: tagKey(c.machine, c.item, c.group),
			text,
			wide: pulse.length > text.length ? pulse : text
		};
	});
}
/** A replica tag's text while replica `k` (from 1) of `n` takes a crate: `N replicas` reads `replica k of N`. */
var replicaPulse = (base, k, n) => base.replace(/\d+ replicas$/, `replica ${k} of ${n}`);
/** A receiving dock's sign: `POST <path>` when the push endpoint is known (the relation's key is a path, or a request
*  into the handler names one), else `push`. */
function dockSign(model, relations) {
	const path = (key) => {
		const m = /^(?:POST\s+)?(\/\S*)$/.exec(key?.trim() ?? "");
		return m ? m[1] : void 0;
	};
	const rels = relations.map((id) => model.map.relations.find((r) => r.id === id)).filter((r) => !!r);
	for (const r of rels) {
		const p = path(r.key);
		if (p) return `POST ${p}`;
	}
	for (const r of rels) {
		const into = model.map.relations.find((q) => q.kind === "request" && q.to === r.to && /^POST\s+\//.test(q.key ?? ""));
		if (into) return `POST ${path(into.key)}`;
	}
	return "push";
}
/** Every messaging label on a floor, placed in this order so the ones that say most win the room: consumer tags under
*  their machines, dock signs, then one plate per flight. `clear` holds the floor's obstacles (and its zone names);
*  each placed label joins it. `inside` gives a machine's free inner band (under its name, over its sub line), where a
*  tag goes when no clear spot under the machine is left; a tag there is `inside`. */
function messagingLabels(model, tf, paths, clear, inside) {
	const bounds = {
		x0: 0,
		y0: 0,
		x1: tf.cols * 24,
		y1: tf.rows * 24
	};
	const px = (r) => ({
		x0: r.x * 24,
		y0: r.y * 24,
		x1: (r.x + r.w) * 24,
		y1: (r.y + r.h) * 24
	});
	const tags = [];
	const bands = /* @__PURE__ */ new Map();
	for (const t of consumerTags(tf)) {
		const box = tf.boxes.get(t.machine);
		if (!box) continue;
		const r = px(box), w = plateW(t.wide), shadowed = {
			...r,
			x1: r.x1 + 5,
			y1: r.y1 + 5
		};
		let got = placeBeside(t.key, t.text, spotsUnder(shadowed, w), clear, bounds, PLATE_FONT, w);
		const band = bands.get(t.machine) ?? inside?.(t.machine);
		if (!got && band && band.x1 - band.x0 >= w && band.y1 - band.y0 >= 17) {
			got = {
				key: t.key,
				text: t.text,
				x: Math.round(band.x0),
				y: Math.round(band.y0),
				w,
				h: 17
			};
			bands.set(t.machine, {
				...band,
				y0: band.y0 + 17 + 2
			});
			tags.push({
				...got,
				machine: t.machine,
				inside: true
			});
			continue;
		}
		got ??= placeBeside(t.key, t.text, spotsBeside(shadowed, w), clear, bounds, PLATE_FONT, w);
		if (got) tags.push({
			...got,
			machine: t.machine,
			inside: false
		});
	}
	const signs = [];
	for (const d of tf.landing?.docks ?? []) {
		const text = dockSign(model, paths.find((p) => p.dock && p.machine === d.machine && p.item === d.item && p.group === d.group)?.relations ?? []);
		const r = px(d), w = plateW(text, 10);
		const vertical = d.side === "w" || d.side === "e";
		const [ox, oy] = {
			n: [0, -1],
			s: [0, 1],
			w: [-1, 0],
			e: [1, 0]
		}[d.side];
		const base = {
			n: {
				x: 0,
				y: r.y0 - 4 - 17
			},
			s: {
				x: 0,
				y: r.y1 + 4
			},
			w: {
				x: r.x0 - 4 - w,
				y: 0
			},
			e: {
				x: r.x1 + 4,
				y: 0
			}
		}[d.side];
		const along = vertical ? [
			r.y0,
			r.y1 - 17,
			(r.y0 + r.y1) / 2 - 17 / 2
		] : [
			r.x0,
			r.x1 - w,
			(r.x0 + r.x1) / 2 - w / 2
		];
		const open = [0, 12].flatMap((k) => along.map((v) => vertical ? {
			x: base.x + ox * k,
			y: v
		} : {
			x: v,
			y: base.y + oy * k
		}));
		const ends = vertical ? [r.y0 - 4 - 17, r.y1 + 4].map((y) => ({
			x: d.side === "w" ? r.x1 - 3 - w : r.x0 + 3,
			y
		})) : [{
			x: r.x0 - 4 - w,
			y: (r.y0 + r.y1) / 2 - 17 / 2
		}, {
			x: r.x1 + 4,
			y: (r.y0 + r.y1) / 2 - 17 / 2
		}];
		const key = flightKey(d.machine, d.item);
		let got = placeBeside(key, text, [...open, ...ends], clear, bounds, 10);
		const long = r.x1 - r.x0, cx = (r.x0 + r.x1) / 2, cy = (r.y0 + r.y1) / 2;
		if (!got && vertical) got = placeBeside(key, text, [
			24,
			36,
			48
		].flatMap((k) => along.map((v) => ({
			x: base.x + ox * k,
			y: v
		}))), clear, bounds, 10);
		if (!got && !vertical && w <= long - 6) got = {
			key,
			text,
			x: Math.round(cx - w / 2),
			y: Math.round(cy - 17 / 2),
			w,
			h: 17
		};
		if (got) signs.push(got);
	}
	return {
		tags,
		signs,
		plates: placePlates(paths, clear, bounds)
	};
}
// src/factory/plan.ts
var WIDEN = 2;
var MAX_START = 3;
var MAX_EXTRA = 6;
/** Starting corridor gap from demand: lines at the busiest box beyond what its sides carry comfortably. The base
*  corridors are already 6 across and 4 down (they were 4 and 3), so one extra tile per six lines past eight. */
function startGap(bundles) {
	const load = /* @__PURE__ */ new Map();
	for (const b of bundles) {
		if (flies(b.kind)) continue;
		load.set(b.a, (load.get(b.a) ?? 0) + 1);
		load.set(b.b, (load.get(b.b) ?? 0) + 1);
	}
	const busiest = Math.max(0, ...load.values());
	return Math.min(MAX_START, Math.max(0, Math.ceil((busiest - 8) / 6)));
}
/** Belts side by side in a corridor: the most on-top tiles travelling along it (down a column corridor, across a row
*  corridor) in any one cross-section. A trunk tile is one belt however many lines ride it. Cross-sections where the
*  corridor meets a crossing one (`cross`) are not counted: lines turn there. */
function corridorLoad(r, routes, along, cross = [], held = []) {
	if (r.w <= 0 || r.h <= 0) return 0;
	const axis = along === "down" ? ["n", "s"] : ["e", "w"];
	const span = along === "down" ? r.h : r.w;
	const seen = Array.from({ length: span }, () => /* @__PURE__ */ new Set());
	for (const q of routes) if (!q.failed) for (const p of q.pieces) {
		if (p.under || !inside(r, p.x, p.y) || !(axis.includes(p.in) || axis.includes(p.out))) continue;
		if (along === "down") seen[p.y - r.y].add(p.x);
		else seen[p.x - r.x].add(p.y);
	}
	for (const h of held) for (let y = h.y; y < h.y + h.h; y++) for (let x = h.x; x < h.x + h.w; x++) {
		if (!inside(r, x, y)) continue;
		if (along === "down") seen[y - r.y].add(x);
		else seen[x - r.x].add(y);
	}
	const crossed = (i) => cross.some((c) => along === "down" ? i + r.y >= c.y && i + r.y < c.y + c.h : i + r.x >= c.x && i + r.x < c.x + c.w);
	return Math.max(0, ...seen.filter((_, i) => !crossed(i)).map((s) => s.size));
}
/** Extra tiles per corridor: a corridor whose load reaches its width minus one is full and gets one tile per belt
*  past width minus two (so one or two: belts on top never outnumber tiles), at most MAX_EXTRA; undefined when no
*  corridor is full. Belts, not lines: lines riding one trunk share its tile, and widening for them measured worse
*  (the large real map: +6% floor area, one file floor at 78% of its baseline tiles, against +1% and 73%). */
function trafficGaps(tf, routes) {
	const cols = tf.aisles?.cols ?? [], rows = tf.aisles?.rows ?? [], held = reservedRects(tf);
	const extra = (r, along) => {
		const width = along === "down" ? r.w : r.h, load = corridorLoad(r, routes, along, along === "down" ? rows : cols, held);
		return width > 0 && load >= width - 1 ? Math.min(MAX_EXTRA, load - (width - 2)) : 0;
	};
	const colGaps = cols.map((r) => extra(r, "down"));
	const rowGaps = rows.map((r) => extra(r, "across"));
	return [...colGaps, ...rowGaps].some((g) => g > 0) ? {
		colGaps,
		rowGaps
	} : void 0;
}
/** Lane gaps whose lines run along more rows than the gap has inner rows (rows next to no lane): a line then runs along
*  a row next to a lane, where the lanes' taps end and their underground runs come up, so it passes those stubs as if it
*  touched them. A gap of two rows has no inner row. Each with the first line along it and where. */
function crowdedLaneGaps(tf, routes) {
	const out = [];
	for (const g of laneGaps(tf)) {
		const rect = {
			x: g.x0,
			y: g.y0,
			w: g.x1 - g.x0,
			h: g.y1 - g.y0
		};
		const along = routes.flatMap((r) => r.pieces.filter((p) => !p.under && alongRow(p) && inside(rect, p.x, p.y)).map((p) => ({
			key: r.key,
			at: {
				x: p.x,
				y: p.y
			}
		})));
		if (new Set(along.map((a) => a.at.y)).size > g.y1 - g.y0 - 2) out.push({
			gap: g,
			...along[0]
		});
	}
	return out;
}
/** A piece that enters or leaves its tile sideways: its line runs along the row there. */
var alongRow = (p) => p.in === "e" || p.in === "w" || p.out === "e" || p.out === "w";
var failures = (routes) => routes.filter((r) => r.failed).length;
/** Crossings as drawn: underground runs, a trunk going under counted once however many lines ride it. */
function crossings$1(routes) {
	const runs = /* @__PURE__ */ new Set();
	for (const r of routes) r.pieces.forEach((p, i) => {
		if (!p.under || i === 0 || r.pieces[i - 1].under) return;
		let e = i;
		while (e < r.pieces.length - 1 && r.pieces[e].under) e++;
		const a = r.pieces[i - 1], b = r.pieces[e];
		runs.add(`${a.x},${a.y}>${b.x},${b.y}`);
	});
	return runs.size;
}
/** The floor laid out with its messaging, rails and webhook docks placed (tf.landing, tf.rails, tf.webhooks) before
*  any routing: pads inside their machines, receiving docks reserved outside them; rail yards, their signs and stations
*  reserved after the docks; then the site's inbound webhook docks, where a first routing's belts arrive. A floor with a
*  free-standing yard is laid out again with rows kept for it in the in column. A floor with no hub and no yard is exactly layoutTiles.
*  `ladders`: the yards that stand as ladders (a throat column), planned from a first routing (`planFloor`). */
function layFloor(model, container, doors, bundles, opts = {}, ladders) {
	let tf = layoutTiles(model, container, doors, opts);
	const inYard = inYardRows(model, container, tf, bundles);
	if (inYard) tf = layoutTiles(model, container, doors, {
		...opts,
		inYard
	});
	const l = landing(model, container, tf, bundles);
	if (l) tf.landing = l;
	const r = rails(model, container, tf, bundles, ladders);
	if (r) tf.rails = r;
	if (hasWebhooks(model, tf, bundles)) {
		const w = webhookDocks(model, tf, bundles, routeTiles(tf, bundles));
		if (w?.docks.length) tf.webhooks = w.docks;
		if (w?.notes.length) tf.notes = [...tf.notes ?? [], ...w.notes];
	}
	return tf;
}
/** The floor's base plan (`planBase`), then each extra layer's lines (`layered`, from `Model.bundles`) routed over it. */
function planFloor(model, container, doors, bundles, layered = []) {
	const base = planBase(model, container, doors, bundles);
	return layered.length ? {
		...base,
		layers: routeLayers(base, layered)
	} : base;
}
/** Each layer's lines routed on the base's floor over its lines (`routeTiles`' `base`): the base plan is never touched,
*  and no layer sees another's lines (one layer shows at a time), so a line in two layers is routed in each. Planned
*  in item-id order, which changes nothing (each layer is independent); the list's order is `floor.hubs` (layers.ts). */
function routeLayers(base, layered) {
	const by = /* @__PURE__ */ new Map();
	for (const b of layered) by.set(b.layer, [...by.get(b.layer) ?? [], b]);
	const out = {};
	for (const id of [...by.keys()].sort()) out[id] = { routes: routeTiles(base.tf, by.get(id), base.routes) };
	return out;
}
/** Route once; widen the crowded corridors and route a second time, kept only if no more lines fail and it crosses
*  strictly less. Only a floor with no crowded corridor, whose lines still fail, gets the old retry (every corridor
*  GAP + WIDEN, taken if no more lines fail): a floor never routes a third time, but for a full lane gap's one more row
*  (`roomierLanes`). When the traffic pass already routed, its answer stands, failures included. A floor where some
*  yard sends more than one platform's rail out by one exit is planned once more with that yard a ladder (`yardLadders`;
*  twice when an exit leaves from a group's middle row: its top end, or its bottom end when that crosses strictly
*  less), kept if no more lines fail and no more rails go unplaced. */
function planBase(model, container, doors, bundles) {
	let best = routeFloor(model, container, doors, bundles);
	const top = yardLadders(best.tf, best.routes, "top");
	if (top) {
		const bottom = yardLadders(best.tf, best.routes, "bottom");
		const same = JSON.stringify([...top]) === JSON.stringify([...bottom]);
		const unplaced = (q) => q.tf.rails?.unplaced.length ?? 0;
		const ok = (q) => failures(q.routes) <= failures(best.routes) && unplaced(q) <= unplaced(best);
		let laddered;
		for (const l of same ? [top] : [top, bottom]) {
			const q = routeFloor(model, container, doors, bundles, l);
			if (ok(q) && (!laddered || crossings$1(q.routes) < crossings$1(laddered.routes))) laddered = q;
		}
		if (laddered) best = laddered;
	}
	return best.tf.landing ? {
		...best,
		landing: best.tf.landing
	} : best;
}
function routeFloor(model, container, doors, bundles, ladders) {
	const gap = startGap(bundles);
	let opts = { gap };
	const tf = layFloor(model, container, doors, bundles, opts, ladders);
	let best = {
		tf,
		routes: routeTiles(tf, bundles),
		gap
	};
	const widths = trafficGaps(best.tf, best.routes);
	if (widths) {
		const tf2 = layFloor(model, container, doors, bundles, {
			gap,
			...widths
		}, ladders);
		const routes2 = routeTiles(tf2, bundles);
		if (failures(routes2) <= failures(best.routes) && crossings$1(routes2) < crossings$1(best.routes)) {
			best = {
				tf: tf2,
				routes: routes2,
				gap
			};
			opts = {
				gap,
				...widths
			};
		}
	}
	if (!widths && failures(best.routes)) {
		const wider = layFloor(model, container, doors, bundles, { gap: gap + WIDEN }, ladders);
		const routes3 = routeTiles(wider, bundles);
		if (failures(routes3) <= failures(best.routes)) {
			best = {
				tf: wider,
				routes: routes3,
				gap: gap + WIDEN
			};
			opts = { gap: gap + WIDEN };
		}
	}
	const roomy = roomierLanes(model, container, doors, bundles, ladders, best, opts);
	return roomierZones(model, container, doors, bundles, ladders, roomy.plan, roomy.opts);
}
var ZONE_WIDEN_MAX = 8;
/** The zones whose name finds no clear spot (`planZoneLabel`, against what the drawing keeps labels off, zones in
*  drawing order). */
function crampedZones(tf, routes, bundles) {
	const flights = flightPaths(tf);
	const clear = new Clearance(messagingObstacles(tf, routes, flights, coveredKeys(flights, bundles)), tf.cols + 8);
	return tf.zones.filter((z) => !planZoneLabel({
		...z,
		name: z.name.toUpperCase()
	}, clear).clear).map((z) => z.name);
}
/** A plan with a cramped zone (lines crossing its label row leave its name no clear spot) laid out again with each
*  such zone a tile wider on the right, then another, until every name it widened finds a spot (at most
*  ZONE_WIDEN_MAX); kept if no more lines fail. A cache that kept its lane keeps it: the room a zone gains is for its
*  name, not for a chest that would move the lines. None found, or a zone that cannot grow (a door column): the plan as it
*  was. */
function roomierZones(model, container, doors, bundles, ladders, best, opts) {
	const cramped = crampedZones(best.tf, best.routes, bundles);
	if (!cramped.length) return best;
	const width = (tf) => tf.zones.filter((z) => cramped.includes(z.name)).map((z) => z.w).join();
	let prev = width(best.tf);
	const laned = /* @__PURE__ */ new Set([...opts.laned ?? [], ...[...soleCaches(model, container).keys()].filter((id) => best.tf.boxes.get(id)?.foot !== "chest")]);
	for (let k = 1; k <= ZONE_WIDEN_MAX; k++) {
		const tf = layFloor(model, container, doors, bundles, {
			...opts,
			...laned.size ? { laned } : {},
			zoneWiden: Object.fromEntries(cramped.map((n) => [n, k]))
		}, ladders);
		if (width(tf) === prev) break;
		prev = width(tf);
		const routes = routeTiles(tf, bundles);
		const left = crampedZones(tf, routes, bundles);
		if (failures(routes) <= failures(best.routes) && !cramped.some((n) => left.includes(n))) return {
			...best,
			tf,
			routes
		};
	}
	return best;
}
/** A plan whose lane gaps are full (`crowdedLaneGaps`) laid out once more with one more row in each, kept if no more
*  lines fail and fewer gaps are full: the owner's 2026-10-21 comment, lanes too close where lines crowd the gap. */
function roomierLanes(model, container, doors, bundles, ladders, best, opts) {
	const full = crowdedLaneGaps(best.tf, best.routes);
	if (!full.length) return {
		plan: best,
		opts
	};
	const laneGaps = best.tf.lanes.map((_, i) => full.some((f) => f.gap.above === i) ? 1 : 0);
	const tf = layFloor(model, container, doors, bundles, {
		...opts,
		laneGaps
	}, ladders);
	const routes = routeTiles(tf, bundles);
	return failures(routes) <= failures(best.routes) && crowdedLaneGaps(tf, routes).length < full.length ? {
		plan: {
			...best,
			tf,
			routes
		},
		opts: {
			...opts,
			laneGaps
		}
	} : {
		plan: best,
		opts
	};
}
// src/factory/plan-job.ts
/** Floor `container`'s plan: its bundles (`b`, when the caller has them already), then `planFloor` over them. */
function planJob(model, container, b = model.bundles(container)) {
	return planFloor(model, container, b.doors, b.bundles, b.layered);
}
// src/audit/lines.ts
/** A line's possible ends, by id: its key's two boxes (or lanes), for a rail the rail yards and stations, and for an
*  inbound webhook its service's receiving dock (the belt plugs into the dock, not the wall). */
function endRects(tf, r) {
	const out = r.key.split("|").flatMap((id) => {
		const lane = tf.lanes.find((l) => l.id === id), box = tf.boxes.get(id);
		return lane ? [[id, {
			x: lane.x0,
			y: lane.y,
			w: lane.x1 - lane.x0,
			h: 3
		}]] : box ? [[id, box]] : [];
	});
	for (const d of tf.webhooks ?? []) if (d.keys.includes(r.key)) out.push([webhookDockId(d.machine), d]);
	if (r.kind === "rail" && tf.rails) {
		for (const y of tf.rails.yards) out.push([yardId(y.source), y]);
		for (const s of tf.rails.stations) out.push([stationId(s), s]);
	}
	return out;
}
/** Which of the line's two endpoints (by id) its first piece leaves and its last piece arrives at: the data flow. An
*  end that touches no box (a line plugged into empty floor, which `lines.plugged` reports) goes by its tile. */
function flowOf(tf, r) {
	const ends = endRects(tf, r);
	const ps = r.pieces, f = ps[0], l = ps[ps.length - 1];
	const hit = (x, y) => ends.find(([, e]) => inside(e, x, y))?.[0] ?? `tile ${x},${y}`;
	return {
		src: hit(f.x - STEP[f.in][0], f.y - STEP[f.in][1]),
		dst: hit(l.x + STEP[l.out][0], l.y + STEP[l.out][1])
	};
}
/** The trunk rules: one trunk per line, one junction, labelled by data flow. (Junction plates off the walls is its own
*  check: `plateWallViolations`.) */
function trunkViolations(tf, routes) {
	const out = [];
	const bad = (detail, at) => out.push(at ? {
		detail,
		at
	} : { detail });
	const lines = routes.filter((r) => r.pieces.length);
	const flow = new Map(lines.map((r) => [r, flowOf(tf, r)]));
	const onTop = /* @__PURE__ */ new Map();
	const below = /* @__PURE__ */ new Map();
	for (const r of lines) r.pieces.forEach((p, i) => {
		const m = p.under ? below : onTop, k = `${p.x},${p.y}`;
		(m.get(k) ?? m.set(k, []).get(k)).push({
			r,
			i
		});
	});
	/** The tiles just before and after the underground run holding piece i: where it goes under and comes up. */
	const run = (ps, i) => {
		let a = i, b = i;
		while (ps[a - 1]?.under) a--;
		while (ps[b + 1]?.under) b++;
		const f = ps[a - 1], l = ps[b + 1];
		return `${f?.x},${f?.y}>${l?.x},${l?.y}`;
	};
	/** A trunk goes under as one belt: piece i of r runs underground with a partner sharing `end`, same way, entering and leaving together. */
	const underWith = (r, i, end) => {
		const p = r.pieces[i], f = flow.get(r);
		return (below.get(`${p.x},${p.y}`) ?? []).some((o) => o.r !== r && flow.get(o.r)[end] === f[end] && o.r.pieces[o.i].in === p.in && run(o.r.pieces, o.i) === run(r.pieces, i));
	};
	for (const r of lines) {
		const seen = /* @__PURE__ */ new Set();
		for (const p of r.pieces) if (!p.under) {
			const k = `${p.x},${p.y}`;
			if (seen.has(k)) bad(`${r.key} repeats tile ${k}`, p);
			seen.add(k);
		}
		const f = flow.get(r);
		for (const p of r.pieces) if (p.under) {
			for (const o of onTop.get(`${p.x},${p.y}`) ?? []) {
				const fo = flow.get(o.r);
				if (o.r === r || fo.src !== f.src && fo.dst !== f.dst) continue;
				if ((o.r.pieces[o.i].in === "n" || o.r.pieces[o.i].in === "s") === (p.in === "n" || p.in === "s")) bad(`${r.key} runs under ${o.r.key} at ${p.x},${p.y}, along it`, p);
			}
			r.pieces.forEach((q, i) => {
				if (q !== p) return;
				for (const o of below.get(`${p.x},${p.y}`) ?? []) {
					const fo = flow.get(o.r), oq = o.r.pieces[o.i];
					if (o.r === r || fo.src !== f.src && fo.dst !== f.dst) continue;
					if ((oq.in === "n" || oq.in === "s") !== (p.in === "n" || p.in === "s")) continue;
					if (!(fo.src === f.src && underWith(r, i, "src") || fo.dst === f.dst && underWith(r, i, "dst"))) bad(`${r.key} runs under with ${o.r.key} at ${p.x},${p.y} but not as one trunk`, p);
				}
			});
		}
	}
	for (const r of lines) for (let i = 0; i + 1 < r.pieces.length; i++) {
		const p = r.pieces[i], q = r.pieces[i + 1];
		if (p.under || q.under) continue;
		const hold = (x, y) => (onTop.get(`${x},${y}`) ?? []).filter((o) => o.r !== r);
		const hp = hold(p.x, p.y), hq = hold(q.x, q.y);
		if (!hp.length || !hq.length) continue;
		if (!hp.some((a) => hq.some((b) => a.r === b.r && b.i === a.i + 1))) bad(`${r.key} hops between lines at ${q.x},${q.y}`, q);
	}
	for (const [k, list] of onTop) for (let a = 0; a < list.length; a++) for (let b = a + 1; b < list.length; b++) {
		const A = list[a], B = list[b];
		if (A.r === B.r) continue;
		const pa = A.r.pieces[A.i], pb = B.r.pieces[B.i], fa = flow.get(A.r), fb = flow.get(B.r);
		const leaving = fa.src === fb.src && pa.in === pb.in, arriving = fa.dst === fb.dst && pa.out === pb.out;
		if (!(leaving || arriving)) bad(`${A.r.key} and ${B.r.key} share ${k} without sharing a source (same way in) or a target (same way out)`, pa);
		const joins = [A.r, B.r].map((r) => r.pieces.filter((p) => p.join).length);
		if (!(Math.max(...joins) > 0)) bad(`${A.r.key} and ${B.r.key} share ${k} but neither has a junction`, pa);
	}
	for (const r of lines) {
		const js = r.pieces.map((p, i) => [p, i]).filter(([p]) => p.join);
		if (js.length > 1) bad(`${r.key} has more than one junction`, js[1][0]);
		if (!js.length) continue;
		const [p, i] = js[0], { src, dst } = flow.get(r);
		junctionRoom(onTop, below, r, p, bad);
		const here = (onTop.get(`${p.x},${p.y}`) ?? []).filter((o) => o.r !== r);
		if (!(here.length > 0)) bad(`${r.key} junction on a tile nobody else holds`, p);
		const sharedAt = (k, end) => {
			const q = r.pieces[k];
			return q.under ? underWith(r, k, end) : (onTop.get(`${q.x},${q.y}`) ?? []).some((o) => o.r !== r);
		};
		if (p.join === "split") {
			if (!here.some((o) => flow.get(o.r).src === src)) bad(`${r.key} split without a shared source`, p);
			for (let k = 0; k <= i; k++) if (!sharedAt(k, "src")) bad(`${r.key} not on a trunk before its split`, r.pieces[k]);
		} else {
			if (!here.some((o) => flow.get(o.r).dst === dst)) bad(`${r.key} merge without a shared target`, p);
			for (let k = i; k < r.pieces.length; k++) if (!sharedAt(k, "dst")) bad(`${r.key} not on a trunk after its merge`, r.pieces[k]);
		}
	}
	return out;
}
/** Room round a junction (2 in, 1 out): the trunk runs straight through it, and the trunk tiles either side and the branch's
*  first tile are plain pieces -- no other junction, no underground housing. */
function junctionRoom(onTop, below, r, p, bad) {
	const at = `${r.key} junction ${p.x},${p.y}`;
	const here = onTop.get(`${p.x},${p.y}`);
	const branch = joinEdge(p), edges = /* @__PURE__ */ new Set();
	for (const { r: o, i } of here) {
		const q = o.pieces[i];
		edges.add(OPP[q.in]);
		edges.add(q.out);
	}
	edges.delete(branch);
	const trunk = [...edges];
	if (!(trunk.length === 2 && OPP[trunk[0]] === trunk[1])) bad(`${at}: the trunk does not run straight (${trunk})`, p);
	const plain = (d, what) => {
		const k = `${p.x + STEP[d][0]},${p.y + STEP[d][1]}`;
		for (const { r: o, i } of onTop.get(k) ?? []) {
			const q = o.pieces[i];
			if (q.join !== void 0) bad(`${at}: ${what} is another junction`, p);
			if (q.hoodBefore || q.hoodAfter) bad(`${at}: ${what} is an underground housing`, p);
		}
		if (below.has(k) && !onTop.has(k)) bad(`${at}: ${what} is underground`, p);
	};
	for (const d of trunk) plain(d, "the trunk tile " + d);
	plain(branch, "the branch tile");
	for (const { r: o, i } of here) {
		const q = o.pieces[i];
		if (q.hoodBefore || q.hoodAfter) bad(`${at}: a housing on the junction`, p);
	}
}
/** Every tile line is a contiguous chain whose ends plug into its two endpoints, and never sits on a machine. */
function pluggedViolations(tf, r) {
	const out = [];
	const ps = r.pieces;
	if (!ps.length) return out;
	const ends = endRects(tf, r).map(([, e]) => e);
	for (let i = 1; i < ps.length; i++) {
		const a = ps[i - 1], p = ps[i];
		if (p.x !== a.x + STEP[a.out][0] || p.y !== a.y + STEP[a.out][1]) out.push({
			detail: `${r.key} breaks between piece ${i - 1} and ${i}: expected ${a.x + STEP[a.out][0]},${a.y + STEP[a.out][1]}, got ${p.x},${p.y}`,
			at: {
				x: p.x,
				y: p.y
			}
		});
		else if (p.in !== a.out) out.push({
			detail: `${r.key} piece ${i} comes in by ${p.in}, the piece before leaves by ${a.out}`,
			at: {
				x: p.x,
				y: p.y
			}
		});
	}
	const before = {
		x: ps[0].x - STEP[ps[0].in][0],
		y: ps[0].y - STEP[ps[0].in][1]
	};
	const last = ps[ps.length - 1];
	const after = {
		x: last.x + STEP[last.out][0],
		y: last.y + STEP[last.out][1]
	};
	const hit = (p) => ends.findIndex((e) => inside(e, p.x, p.y));
	const hb = hit(before), ha = hit(after);
	if (hb < 0) out.push({
		detail: `${r.key} starts in empty floor`,
		at: before
	});
	if (ha < 0) out.push({
		detail: `${r.key} ends in empty floor`,
		at: after
	});
	if (hb === ha) out.push({
		detail: `${r.key} starts and ends at the same endpoint`,
		at: before
	});
	for (const p of ps) for (const b of tf.boxes.values()) if (inside(b, p.x, p.y)) out.push({
		detail: `${r.key} on ${b.id}`,
		at: {
			x: p.x,
			y: p.y
		}
	});
	for (const p of ps) if (p.under && p.in !== p.out) out.push({
		detail: `${r.key} turns underground`,
		at: {
			x: p.x,
			y: p.y
		}
	});
	return out;
}
/** Every underground run has an above-ground piece before it and one after it (where it goes under and comes up). */
function underViolations(r) {
	const out = [];
	const ps = r.pieces;
	for (let i = 0; i < ps.length; i++) {
		if (!ps[i].under || ps[i - 1]?.under) continue;
		let e = i;
		while (ps[e + 1]?.under) e++;
		const at = {
			x: ps[i].x,
			y: ps[i].y
		};
		if (i === 0) out.push({
			detail: `${r.key} starts underground at ${at.x},${at.y}: no piece before the run`,
			at
		});
		if (e === ps.length - 1) out.push({
			detail: `${r.key} ends underground at ${ps[e].x},${ps[e].y}: no piece after the run`,
			at: {
				x: ps[e].x,
				y: ps[e].y
			}
		});
	}
	return out;
}
/** Line ends that sit in the outermost tile of a machine side (sides of 3+ tiles) and turn on the tile next to the box,
*  while that side's middle tile holds no end of any line: row 13's lines that "plug in beside a box's corner after an
*  extra turn, not mid-side". A straight run out of a corner tile is allowed: the router charges a corner end about a
*  turn (router.ts `CORNER`), so it plugs in there only when that beats leaving mid-side with turns. */
function midSideViolations(tf, routes) {
	const ends = [];
	const add = (b, x, y, side, key, turns) => {
		if (!inside(b, x, y)) return;
		const vertical = side === "n" || side === "s";
		ends.push({
			box: b.id,
			side,
			i: vertical ? x - b.x : y - b.y,
			n: vertical ? b.w : b.h,
			x,
			y,
			key,
			turns
		});
	};
	for (const r of routes) {
		if (!r.pieces.length) continue;
		const f = r.pieces[0], l = r.pieces[r.pieces.length - 1];
		for (const b of tf.boxes.values()) {
			add(b, f.x - STEP[f.in][0], f.y - STEP[f.in][1], f.in, r.key, f.in !== f.out);
			add(b, l.x + STEP[l.out][0], l.y + STEP[l.out][1], OPP[l.out], r.key, l.in !== l.out);
		}
	}
	const out = [];
	const reserved = reservedRects(tf);
	for (const e of ends) {
		if (!e.turns || e.n < 3 || !(e.i === 0 || e.i === e.n - 1)) continue;
		const mids = [Math.floor((e.n - 1) / 2), Math.ceil((e.n - 1) / 2)];
		const b = tf.boxes.get(e.box), vertical = e.side === "n" || e.side === "s";
		const beside = (i) => vertical ? {
			x: b.x + i,
			y: e.side === "n" ? b.y - 1 : b.y + b.h
		} : {
			x: e.side === "w" ? b.x - 1 : b.x + b.w,
			y: b.y + i
		};
		if (!(mids.some((i) => {
			const t = beside(i);
			return reserved.some((r) => t.x >= r.x && t.x < r.x + r.w && t.y >= r.y && t.y < r.y + r.h);
		}) || ends.some((o) => o.box === e.box && o.side === e.side && mids.includes(o.i)))) out.push({
			detail: `${e.key} ends in the ${e.i === 0 ? "first" : "last"} tile of ${e.box}'s ${e.side} side and turns while its middle tile is free`,
			at: {
				x: e.x,
				y: e.y
			}
		});
	}
	return out;
}
/** A junction plate keeps off the factory walls: its tile touches no machine box on any side (the owner's 2026-10-06
*  comment: a plate right against a wall reads as part of the machine). Pads and docks are meant to touch theirs. */
function plateWallViolations(tf, r) {
	const out = [];
	for (const p of r.pieces) if (p.join) {
		for (const b of tf.boxes.values()) for (const d of [
			"n",
			"e",
			"s",
			"w"
		]) if (inside(b, p.x + STEP[d][0], p.y + STEP[d][1])) out.push({
			detail: `${r.key} junction ${p.x},${p.y} touches ${b.id} (${d})`,
			at: {
				x: p.x,
				y: p.y
			}
		});
	}
	return out;
}
var laneAt = (tf, x, y) => tf.lanes.find((l) => x >= l.x0 && x < l.x1 && y >= l.y && y < l.y + 3);
/** A line onto a lane that turns sideways next to a lane (in a gap between lanes, or on the row along a lane's edge)
*  while heading for its lane, over it, where going straight on to the lane is free: no machine, dock or line on top in
*  the tiles between (a lane it would pass under is no obstacle). The owner's 2026-10-21 comment: a tap left its
*  splitter sideways and hooked before it dropped, where a straight drop would do. Turns farther up, among the machines,
*  are the trunks' (lines into one lane merge). */
function laneDropViolations(tf, routes) {
	const held = /* @__PURE__ */ new Set();
	for (const r of routes) for (const p of r.pieces) if (!p.under) held.add(`${p.x},${p.y}`);
	const walls = [...tf.boxes.values(), ...reservedRects(tf)];
	const free = (x, y) => !held.has(`${x},${y}`) && !walls.some((w) => inside(w, x, y));
	const gaps = laneGaps(tf).map((g) => ({
		x: g.x0,
		y: g.y0,
		w: g.x1 - g.x0,
		h: g.y1 - g.y0
	}));
	const out = [];
	for (const r of routes) {
		if (!r.pieces.length) continue;
		const f = r.pieces[0], l = r.pieces[r.pieces.length - 1];
		const into = laneAt(tf, l.x + STEP[l.out][0], l.y + STEP[l.out][1]);
		const lane = into ?? laneAt(tf, f.x - STEP[f.in][0], f.y - STEP[f.in][1]);
		if (!lane) continue;
		const walk = into ? r.pieces : reversed(r.pieces);
		const d = walk[walk.length - 1].out;
		if (d !== "n" && d !== "s") continue;
		const dy = STEP[d][1];
		for (const p of walk) {
			if (p.under || p.in !== d || p.out === d || p.x < lane.x0 || p.x >= lane.x1) continue;
			if (!laneAt(tf, p.x, p.y - 1) && !laneAt(tf, p.x, p.y + 1) && !gaps.some((g) => inside(g, p.x, p.y))) continue;
			let y = p.y + dy, ok = true;
			for (; y >= 0 && y < tf.rows && laneAt(tf, p.x, y) !== lane && ok; y += dy) ok = !!laneAt(tf, p.x, y) || free(p.x, y);
			if (ok && laneAt(tf, p.x, y) === lane) out.push({
				detail: `${r.key} turns ${p.out} at ${p.x},${p.y} on its way to lane ${lane.id}, where it could go straight on`,
				at: {
					x: p.x,
					y: p.y
				}
			});
		}
	}
	return out;
}
/** A line along a lane gap that another line passes under in the same underground run as a lane: that line comes up
*  only on the line's other side, past the lane, so its stub ends right on the line, as if the two touched. The owner's
*  2026-10-21 comment: a crossing between lanes must read as passing under. */
function gapStubViolations(tf, routes) {
	const below = /* @__PURE__ */ new Map();
	for (const r of routes) r.pieces.forEach((p, i) => {
		if (p.under) {
			const k = `${p.x},${p.y}`;
			(below.get(k) ?? below.set(k, []).get(k)).push({
				r,
				i
			});
		}
	});
	const out = [];
	for (const g of laneGaps(tf)) for (const r of routes) for (const p of r.pieces) {
		if (p.under || !alongRow(p) || p.x < g.x0 || p.x >= g.x1 || p.y < g.y0 || p.y >= g.y1) continue;
		for (const { r: o, i } of below.get(`${p.x},${p.y}`) ?? []) {
			if (o === r) continue;
			let a = i, b = i;
			while (o.pieces[a - 1]?.under) a--;
			while (o.pieces[b + 1]?.under) b++;
			const lane = o.pieces.slice(a, b + 1).map((q) => laneAt(tf, q.x, q.y)).find((x) => x);
			if (lane) out.push({
				detail: `${o.key} passes under ${r.key} at ${p.x},${p.y} and under lane ${lane.id} in one run: its stub ends on the line`,
				at: {
					x: p.x,
					y: p.y
				}
			});
		}
	}
	return out;
}
/** Lane gaps whose lines run along more rows than the gap has rows next to no lane (plan.ts `crowdedLaneGaps`): a line
*  runs among the lanes' stubs and tap ends, and the gap is full. The owner's 2026-10-21 comment: lanes too close where
*  lines crowd the gap (the layout gives such a gap one more row). */
function laneGapViolations(tf, routes) {
	return crowdedLaneGaps(tf, routes).map(({ gap, key, at }) => ({
		detail: `the gap between lanes ${tf.lanes[gap.above].id} and ${tf.lanes[gap.below].id} (${gap.y1 - gap.y0} rows) is full: ${key} runs along it next to a lane`,
		at
	}));
}
/** Failed routes: any on a floor of fewer than 100 routes, more than 1% of them on a bigger one. */
function failedViolations(routes) {
	const failed = routes.filter((r) => r.failed);
	if (!failed.length) return [];
	if (routes.length >= 100 && failed.length <= routes.length * .01) return [];
	return [{ detail: `${failed.length} of ${routes.length} routes failed: ${failed.map((r) => r.key).join(", ")}` }];
}
// src/factory/boxname.ts
var NAME_FITS = {
	name: fitName,
	chest: chestFit
};
/** The words of the door to `anchor` on `container`'s floor: the code of the building it opens (Model.doorShows), then
*  that building's name relative to the floors above. */
function doorWords(model, container, anchor) {
	const shows = model.doorShows(container, anchor);
	return `${model.codes.get(shows) ?? ""} ${doorName(model.label(shows), model.path(container).map((c) => model.label(c)))}`;
}
/** A 7-tile door's name (`drawDoor`): wrapped by its width `w` px less 34, 2 lines down to 10 px. */
var fitDoorName = (words, w, fits = NAME_FITS) => fits.name(words, w - 34, 2, [
	12.5,
	12,
	11,
	10
]);
/** A machine's name (`paintBox`): a chest's own fit when it has one, else the footprint's name spec. */
function fitMachineName(b, name, fits = NAME_FITS) {
	const spec = nameSpec(b);
	return (b.foot === "chest" ? fits.chest(name, b.w, b.h) : void 0) ?? fits.name(name, spec.w, spec.maxLines, spec.sizes);
}
function nameContext(model, container, boxes, doors) {
	return {
		doorOf: new Map(doors.map((d) => [d.id, d])),
		prefix: floorPrefix(model, [...boxes].filter((b) => b.kind !== "door").map((b) => b.id)),
		container
	};
}
/** The name a box shows and its fit, as factory-draw.ts draws it: a door-footprint box its door's words (`drawDoor`); a
*  door box on another footprint its anchor's label; a machine its shown name (`paintBox`). */
function boxNameFit(model, ctx, b, fits = NAME_FITS) {
	if (b.foot === "door") return {
		...fitDoorName(doorWords(model, ctx.container, ctx.doorOf.get(b.id).anchor), b.w * 24, fits),
		door: true
	};
	const door = b.kind === "door" ? ctx.doorOf.get(b.id) : void 0;
	return {
		...fitMachineName(b, door ? model.label(door.anchor) : shownName(model, b.id, ctx.prefix), fits),
		door: false
	};
}
// src/factory/subline.ts
/** The factory's sub line: the shape and the role tag already say the kind and role, so only the count of what is inside. */
function factorySubOf(model, floorBundles, m) {
	if ([
		"datastore",
		"external",
		"table",
		"method"
	].includes(m.kind)) return subline(model, floorBundles, m);
	const real = model.twinOf(m.id) ?? m.id;
	const n = m.kind === "group" ? model.groups.get(m.id)?.members.length ?? 0 : model.map.nodes.filter((x) => x.parent === real).length;
	return n ? `${n} inside` : "";
}
function subline(model, floorBundles, m) {
	const real = model.twinOf(m.id) ?? m.id;
	const n = model.nodes.get(real);
	if (m.kind === "datastore") {
		const tables = model.map.nodes.filter((x) => x.parent === m.id).length;
		const bundles = floorBundles.filter((b) => b.a === m.id || b.b === m.id);
		return `${tables} tables · R ${bundles.filter((b) => b.kinds["db-read"]).length} · W ${bundles.filter((b) => b.kinds["db-write"]).length}`;
	}
	if (m.kind === "group") return `${model.groups.get(m.id)?.members.length ?? 0} inside · open`;
	if (m.kind === "table") {
		const a = model.tableAccess(m.id);
		return [a.writers.length ? `W ${a.writers.join(" ")}` : "", a.readers.length ? `R ${a.readers.join(" ")}` : ""].filter(Boolean).join(" · ") || "no access found";
	}
	if (m.kind === "method") return n?.signature ? `(${n.signature.params.map((p) => p.name).join(", ")})` : "";
	if (m.kind === "external") return ["external", splitEndpoint(model.label(m.id)).endpoint].filter(Boolean).join(" · ");
	const children = model.map.nodes.filter((x) => x.parent === real).length;
	return `${n?.role ? `${n.role} · ` : ""}${m.kind}${children ? ` · ${children} inside` : ""}`;
}
// src/factory/rail-place.ts
/** The key a yard is selected by (and its views fade with): its rails' ends grouped as in the router. */
var yardKey = (source) => yardId(source);
/** A box's short code on its own floor: the code without the floor's own code in front (`S7·P1·F11` on S7·P1 reads
*  `F11`); a door wears its anchor's. */
function shortCode(model, container, id) {
	const code = model.codes.get(id.startsWith("door:") ? id.slice(5) : id) ?? "";
	const own = model.codes.get(container);
	return own && code.startsWith(own + "·") ? code.slice(own.length + 1) : code;
}
/** Placed after the zone names and messaging labels, into the same clear room (`clear`): each sign's text beside its
*  tile (right, left, below, above), then each station's label on its open side (away from the wall), never over a
*  line, a machine or another label. A sign with no room shows its text on hover only; a station with no room has no
*  label. Deterministic: yards and stations in their order. */
function railLabels(model, container, tf, clear) {
	const r = tf.rails;
	if (!r) return {
		signs: [],
		stations: []
	};
	const bounds = {
		x0: 0,
		y0: 0,
		x1: tf.cols * 24,
		y1: tf.rows * 24
	};
	const signs = [];
	for (const y of r.yards) {
		if (!y.sign) continue;
		const text = r.batch.yards.find((q) => q.source === y.source).sign;
		const got = [text, ...signLines(text)].reduce((done, t) => done ?? placeBox(yardKey(y.source), t, signSpots(y, t), clear, bounds), void 0);
		if (got) signs.push({
			...got,
			source: y.source
		});
	}
	const stations = [];
	if (new Set(r.stations.map((s) => s.source)).size > 1) for (const s of r.stations) {
		const text = shortCode(model, container, r.yards.find((y) => y.source === s.source)?.machine ?? s.source);
		if (!text) continue;
		const w = plateW(text, 10), x0 = s.x * 24, y0 = s.y * 24, x1 = (s.x + s.w) * 24, y1 = (s.y + s.h) * 24;
		const cx = (x0 + x1) / 2 - w / 2, cy = (y0 + y1) / 2 - 17 / 2;
		const spots = {
			n: [{
				x: cx,
				y: y0 - 3 - 17
			}],
			s: [{
				x: cx,
				y: y1 + 3
			}],
			w: [{
				x: x0 - 3 - w,
				y: cy
			}],
			e: [{
				x: x1 + 3,
				y: cy
			}]
		}[s.side];
		const got = placeBeside(s.track, text, spots, clear, bounds, 10, w);
		if (got) stations.push({
			...got,
			station: stationId(s)
		});
	}
	return {
		signs,
		stations
	};
}
/** A sign's text on two lines when one does not fit: split before its ` + ` tail, else at its ` · `, else at its last
*  space (`daily` over `01:00`). */
function signLines(text) {
	const plus = text.indexOf(" + "), dot = text.indexOf(" · "), sp = text.lastIndexOf(" ");
	if (plus > 0) return [`${text.slice(0, plus)}\n${text.slice(plus + 1)}`];
	if (dot > 0) return [`${text.slice(0, dot)}\n${text.slice(dot + 3)}`];
	if (sp > 0) return [`${text.slice(0, sp)}\n${text.slice(sp + 1)}`];
	return [];
}
/** A label's box for `text` (one or more lines) at PLATE_FONT: as wide as its longest line, a plate tall per line. */
var boxSize = (text, size = PLATE_FONT) => {
	const lines = text.split("\n");
	return {
		w: Math.max(...lines.map((l) => plateW(l, size))),
		h: 17 + (lines.length - 1) * (size + 3)
	};
};
/** Spots for a sign's text: beside its tile (right, left), under and over it, then under and over its yard. */
function signSpots(y, text) {
	const { w, h } = boxSize(text), s = y.sign;
	const x0 = s.x * 24, y0 = s.y * 24, mid = y0 + (24 - h) / 2;
	const yx0 = y.x * 24, yx1 = (y.x + y.w) * 24, yy0 = y.y * 24, yy1 = (y.y + y.h) * 24;
	return [
		{
			x: x0 + 24 + 3,
			y: mid
		},
		{
			x: x0 - 3 - w,
			y: mid
		},
		{
			x: x0,
			y: y0 + 24 + 3
		},
		{
			x: x0 + 24 - w,
			y: y0 + 24 + 3
		},
		{
			x: x0,
			y: y0 - 3 - h
		},
		{
			x: x0 + 24 - w,
			y: y0 - 3 - h
		},
		{
			x: yx0 + 8,
			y: yy1 + 3
		},
		{
			x: yx1 - w,
			y: yy1 + 3
		},
		{
			x: yx0 + 8,
			y: yy0 - 3 - h
		},
		{
			x: yx1 - w,
			y: yy0 - 3 - h
		}
	];
}
/** `placeBeside` for a label of one or more lines: the first spot clear of `clear` and inside `bounds` wins and joins it. */
function placeBox(key, text, spots, clear, bounds) {
	const { w, h } = boxSize(text);
	for (const s of spots) {
		const box = {
			x0: Math.round(s.x),
			y0: Math.round(s.y),
			x1: Math.round(s.x) + w,
			y1: Math.round(s.y) + h
		};
		if (box.x0 < bounds.x0 || box.y0 < bounds.y0 || box.x1 > bounds.x1 || box.y1 > bounds.y1 || !clear.free(box)) continue;
		clear.add(box);
		return {
			key,
			text,
			x: box.x0,
			y: box.y0,
			w,
			h
		};
	}
}
// src/model/layers.ts
/** The floor's extra layers, one per heavily used item with a line, in `floor.hubs` order. Empty on most floors (no
*  layers button). Pure: from the model alone. */
function floorLayers(model, container) {
	const hubs = model.floor(container)?.hubs ?? [];
	if (!hubs.length) return [];
	const layered = model.bundles(container).layered;
	const out = [];
	for (const h of hubs) {
		const list = layered.filter((b) => b.layer === h);
		if (list.length) out.push({
			id: h,
			name: model.codes.get(h) ?? h,
			full: model.itemName(h),
			count: list.length,
			item: h,
			usedBy: list.filter((b) => b.into).length
		});
	}
	return out;
}
// src/floor/lane.ts
/** x positions where a vertical run crosses, or ends on, the lane band at `y` (± half its height). */
function crossings(routes, y, half) {
	const xs = /* @__PURE__ */ new Set();
	for (const r of routes) for (let i = 1; i < r.points.length; i++) {
		const a = r.points[i - 1], b = r.points[i];
		if (a.x !== b.x) continue;
		const lo = Math.min(a.y, b.y), hi = Math.max(a.y, b.y);
		if (lo <= y + half && hi >= y - half) xs.add(a.x);
	}
	return [...xs].sort((p, q) => p - q);
}
/** The paths drawn point to point over a floor: drone lines no flight carries, and the flights. */
function pointPaths(routes, flights, covered) {
	return [...routes.filter((r) => r.kind === "drone" && !covered.has(r.key)).map((r) => r.points), ...flights.map((f) => f.points)];
}
var PATH_STEP = 8;
/** x positions a lane's name keeps off (clear.ts `laneLabelSpot`): where a vertical run crosses or ends on the lane
*  (`crossings`), and every PATH_STEP px along where a drone or flight path (`paths`, `pointPaths`) runs over it. */
function laneCrossings(l, routes, paths) {
	const y0 = l.y * 24, y1 = (l.y + 3) * 24;
	const xs = new Set(crossings(routes, (y0 + y1) / 2, (y1 - y0) / 2));
	for (const pts of paths) for (let i = 1; i < pts.length; i++) {
		const a = pts[i - 1], b = pts[i];
		const t0 = a.y === b.y ? a.y >= y0 && a.y <= y1 ? 0 : 1 : Math.max(0, Math.min((y0 - a.y) / (b.y - a.y), (y1 - a.y) / (b.y - a.y)));
		const t1 = a.y === b.y ? a.y >= y0 && a.y <= y1 ? 1 : 0 : Math.min(1, Math.max((y0 - a.y) / (b.y - a.y), (y1 - a.y) / (b.y - a.y)));
		if (t1 < t0) continue;
		const xa = a.x + (b.x - a.x) * t0, xb = a.x + (b.x - a.x) * t1, lo = Math.min(xa, xb), hi = Math.max(xa, xb);
		for (let x = lo; x < hi; x += PATH_STEP) xs.add(x);
		xs.add(hi);
	}
	return [...xs].sort((p, q) => p - q);
}
/** Travel speed in px/s: belts and pipes keep a steady 60; a train crosses its rail (`length`) in at most TRAIN_SECS.
*  A drone (event) passes its floor's longest flight as `length`, so every drone on a floor flies at one speed, a
*  short hop takes less time than a long one, and the longest crosses in at most FLIGHT_SECS. */
function moverSpeed(kind, length) {
	return flies(kind) ? Math.max(60, length / 5) : kind === "train" ? Math.max(60, length / 3) : 60;
}
// src/audit/text.ts
/** The fitting functions the drawing uses; a test may pass others to prove the check sees a cut. */
var FITS = {
	name: fitName,
	line: fitLine,
	signature: fitSignature,
	chest: chestFit
};
var tileAt = (px, py) => ({
	x: Math.floor(px / 24),
	y: Math.floor(py / 24)
});
var cut = (s) => s.startsWith("…");
var tagWidth = (tag) => Math.ceil(tag.length * 9.5 * .56);
/** Every machine name, sub line and signature on the floor as the drawing fits it (factory-draw.ts, machines.ts
*  `paintBox`, draw.ts `drawDoor`), reported when a shown line starts with "…": cut from the front. The sub line's width
*  takes the role tag's estimated width (the drawing measures it); a front cut does not depend on the width. */
function cutViolations(model, container, plan, fit = FITS) {
	const { tf } = plan, out = [];
	const { bundles, doors } = model.bundles(container);
	const ctx = nameContext(model, container, tf.boxes.values(), doors);
	const report = (what, b, lines, px, py) => {
		const bad = lines.find(cut);
		if (bad !== void 0) out.push({
			detail: `${what} of ${b.id} cut: '${bad}'`,
			at: tileAt(px, py)
		});
	};
	for (const b of tf.boxes.values()) {
		const x = b.x * 24, y = b.y * 24, W = b.w * 24, H = b.h * 24;
		const f = boxNameFit(model, ctx, b, fit);
		if (b.foot === "door") {
			report("name", b, f.lines, x + (ctx.doorOf.get(b.id).side === "out" ? 8 : 28), y + 19);
			continue;
		}
		const real = model.twinOf(b.id) ?? b.id;
		const spec = nameSpec(b);
		report("name", b, f.lines, x + spec.ix, spec.top);
		const sub = b.kind === "door" ? "" : factorySubOf(model, bundles, b);
		const params = b.kind === "method" ? model.nodes.get(real)?.signature?.params.map((q) => q.name) : void 0;
		if (!(sub || params) || [
			"installed",
			"hub",
			"rack",
			"chest"
		].includes(b.foot)) continue;
		const tag = b.foot === "package" ? model.nodes.get(real)?.role : void 0;
		const reserve = padReserve(tf.landing?.pads.filter((q) => q.machine === b.id).length ?? 0);
		const subW = W - spec.ix - 8 - (tag ? reserve + tagWidth(tag) + 6 : reserve);
		const top = y + H - 17;
		if (spec.top + f.lines.length * (f.size + 2) > top) continue;
		if (params) report("signature", b, [fit.signature(params, subW)], x + spec.ix, top);
		else report("sub line", b, [fit.line(sub, subW, [11, 10]).text], x + spec.ix, top);
	}
	return out;
}
var hit = (a, b) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
var LINE_WORD = {
	tapR: "tap",
	tapW: "tap",
	tapRW: "tap"
};
/** The labels the plan places, as factory-draw.ts places them and in its order (each joins the floor's clear room, so
*  the order decides the spots): the zone names, the messaging labels, the rail labels (placed only so the badges see
*  the room they take: not checked here), then the `used by N` badges, beside their machines, clear of every layer's
*  lines. Lane names are `laneLabelRects`: they take no clear room. */
function labelRects(model, container, plan, bundles) {
	const { tf, routes } = plan;
	let msg = plan.msg;
	if (!msg) {
		const flights = flightPaths(tf), covered = coveredKeys(flights, bundles);
		msg = {
			flights,
			covered,
			obstacles: messagingObstacles(tf, routes, flights, covered)
		};
	}
	const clear = new Clearance(msg.obstacles, tf.cols + 8);
	const out = [];
	for (const z of tf.zones) {
		const p = planZoneLabel({
			...z,
			name: z.name.toUpperCase()
		}, clear);
		out.push({
			what: `zone '${z.name}' label`,
			boxes: [labelBox(p, 1), labelBox(p, p.maxK)]
		});
	}
	for (const r of layerTileRects(plan.layers)) clear.add(r);
	if (tf.landing) {
		const prefix = floorPrefix(model, [...tf.boxes.values()].filter((b) => b.kind !== "door").map((b) => b.id));
		const band = (id) => {
			const b = tf.boxes.get(id);
			return b ? freeBand(b, shownName(model, id, prefix)) : void 0;
		};
		const labels = msg.labels ?? messagingLabels(model, tf, msg.flights, clear, band);
		const box = (l) => ({
			x0: l.x,
			y0: l.y,
			x1: l.x + l.w,
			y1: l.y + l.h
		});
		for (const t of labels.tags) out.push({
			what: `tag '${t.text}'`,
			boxes: [box(t)],
			...t.inside ? { inside: t.machine } : {}
		});
		for (const s of labels.signs) out.push({
			what: `sign '${s.text}'`,
			boxes: [box(s)]
		});
		for (const p of labels.plates) out.push({
			what: `plate '${p.text}'`,
			boxes: [box(p)]
		});
	}
	if (tf.rails && !plan.rail) railLabels(model, container, tf, clear);
	const items = floorLayers(model, container).filter((l) => l.usedBy > 0 && tf.boxes.has(l.item)).map((l) => {
		const q = tf.boxes.get(l.item);
		return {
			id: l.item,
			usedBy: l.usedBy,
			m: {
				x: q.x * 24,
				y: q.y * 24,
				w: q.w * 24,
				h: q.h * 24
			},
			...badgeSize(l.usedBy)
		};
	});
	const spots = placeBadges(items, clear, layerTileRects(plan.layers), plan.badges ? new Map(plan.badges) : void 0);
	for (const i of items) {
		const s = spots.get(i.id);
		out.push({
			what: `badge 'used by ${i.usedBy}'`,
			boxes: [badgeBox(s, 1), badgeBox(s, s.maxK)]
		});
	}
	return out;
}
/** Each lane's name plate as the drawing places it (ground.ts `paintLane`, clear.ts `laneLabelPlan`, between the base's
*  lines and the `paths` crossing the lane), at its estimated width: at scale 1 and at its largest. A store's lane
*  shows its label, a busy item's lane the item's name as the floor list shows it. */
function laneLabelRects(model, plan, paths) {
	const { tf, routes } = plan;
	const prefix = floorPrefix(model, [...tf.boxes.values()].filter((b) => b.kind !== "door").map((b) => b.id));
	return tf.lanes.map((l) => {
		const name = tf.boxes.has(l.id) && model.kindOf(l.id) !== "datastore" ? shownName(model, l.id, prefix) : l.label;
		const p = laneLabelPlan(l, laneNameWidth(name), laneCrossings(l, routes, paths));
		const box = (k) => ({
			x0: p.x,
			y0: p.y,
			x1: p.x + p.w * k,
			y1: p.y + p.h * k
		});
		return {
			what: `lane '${name}' name`,
			boxes: [box(1), box(p.maxK)]
		};
	});
}
/** A path drawn point to point (a drone line, a flight) as squares along each segment, `half` px either side. */
var pathRects = (pts, half) => pts.slice(1).flatMap((b, i) => {
	const a = pts[i], n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / half));
	return Array.from({ length: n + 1 }, (_, k) => {
		const x = a.x + (b.x - a.x) * k / n, y = a.y + (b.y - a.y) * k / n;
		return {
			x0: x - half,
			y0: y - half,
			x1: x + half,
			y1: y + half
		};
	});
});
var PATH_HALF = 2;
/** Every label the plan places (`labelRects`) that overlaps a line tile on top or a machine box: in the base view
*  against the base's lines, and in each layer view against that layer's lines (a layer shows over the base). A consumer
*  tag placed inside its machine's free band is not over that machine. Flight paths are not tiles: a plate stands on its
*  own flight by design. A lane's name (`laneLabelRects`) is checked against the same line tiles and against the drone
*  and flight paths too: it sits where tiles cross the lane, so a path or the lane's end is what it can run into. */
function overLineViolations(model, container, plan, bundles) {
	const { tf } = plan;
	const tiles = (routes) => routes.flatMap((r) => r.pieces.filter((p) => !p.under).map((p) => ({
		word: LINE_WORD[r.kind] ?? r.kind,
		rect: {
			x0: p.x * 24,
			y0: p.y * 24,
			x1: (p.x + 1) * 24,
			y1: (p.y + 1) * 24
		}
	})));
	const views = [["", tiles(plan.routes)], ...Object.entries(plan.layers ?? {}).map(([id, l]) => [` (layer ${id})`, tiles(l.routes)])];
	const boxes = [...tf.boxes.values()].map((b) => ({
		id: b.id,
		rect: {
			x0: b.x * 24,
			y0: b.y * 24,
			x1: (b.x + b.w) * 24,
			y1: (b.y + b.h) * 24
		}
	}));
	const out = [];
	const flights = plan.msg?.flights ?? flightPaths(tf), covered = plan.msg?.covered ?? coveredKeys(flights, bundles);
	const paths = [...plan.routes.filter((r) => r.kind === "drone" && !covered.has(r.key)), ...flights].map((q) => ({
		key: q.key,
		rects: pathRects(q.points, PATH_HALF)
	}));
	for (const l of laneLabelRects(model, plan, pointPaths(plan.routes, flights, covered))) {
		const at = tileAt(l.boxes[0].x0, l.boxes[0].y0);
		for (const [view, ts] of views) {
			const t = ts.find((q) => l.boxes.some((r) => hit(r, q.rect)));
			if (t) out.push({
				detail: `${l.what} over a ${t.word}${view}`,
				at
			});
		}
		const q = paths.find((q) => q.rects.some((a) => l.boxes.some((r) => hit(r, a))));
		if (q) out.push({
			detail: `${l.what} over the path of ${q.key}`,
			at
		});
	}
	for (const l of labelRects(model, container, plan, bundles)) {
		const at = tileAt(l.boxes[0].x0, l.boxes[0].y0);
		const box = boxes.find((b) => b.id !== l.inside && l.boxes.some((r) => hit(r, b.rect)));
		if (box) out.push({
			detail: `${l.what} over box ${box.id}`,
			at
		});
		for (const [view, ts] of views) {
			const t = ts.find((q) => l.boxes.some((r) => hit(r, q.rect)));
			if (t) out.push({
				detail: `${l.what} over a ${t.word}${view}`,
				at
			});
		}
	}
	return out;
}
/** Every zone whose label has no spot inside it even on an empty floor (`planZoneLabel` with nothing in the way):
*  narrower (or lower) than its label. */
function narrowZoneViolations(plan) {
	const out = [];
	for (const z of plan.tf.zones) {
		const p = planZoneLabel({
			...z,
			name: z.name.toUpperCase()
		}, new Clearance([], plan.tf.cols + 8));
		if (p.clear) continue;
		const b = labelBox(p, 1);
		out.push({
			detail: `zone '${z.name}' label does not fit (${z.w} ${z.w === 1 ? "tile" : "tiles"})`,
			at: tileAt(b.x0, b.y0)
		});
	}
	return out;
}
// src/floor/fitscale.ts
/** Floor bounds `w`×`h` px in a `screenW`×`screenH` canvas, `bottomInset` px kept clear at the bottom. Inside floors keep
*  a 120 px pad round them; every floor keeps 60 px for its title and a 0.94 margin. Unclamped. */
function fitScale(w, h, screenW, screenH, site, bottomInset = 0) {
	const pad = site ? 0 : 120;
	return Math.min(screenW / (w + pad), (screenH - bottomInset) / (h + pad + 60)) * .94;
}
/** The Fit zoom's limits: the scene never fits a floor further out than FIT_MIN or further in than FIT_MAX. */
var FIT_MIN = .12;
var FIT_MAX = 1.4;
var clampFit = (s) => Math.max(FIT_MIN, Math.min(FIT_MAX, s));
/** The zoom the scene's Fit picks (`fitScale`, clamped): what the map audit measures against the names/codes switch. */
function fitZoom(w, h, screenW, screenH, site, bottomInset = 0) {
	return clampFit(fitScale(w, h, screenW, screenH, site, bottomInset));
}
// src/audit/floor.ts
/** The longest a moving item may take over one line, seconds (audit row 25): a train over its rail, a drone over its
*  flight (drones fly slower, so a floor's flights stay readable). */
var TRIP_MAX = {
	train: 3,
	event: 5
};
/** The floor area Fit is measured for (audit row 24). */
var FIT_AREA = {
	w: 1440,
	h: 900
};
var inBox = (b, x, y) => x >= b.x && x < b.x + b.w && y >= b.y && y < b.y + b.h;
var boxAt = (plan) => {
	const boxes = [...plan.tf.boxes.values()];
	return (x, y) => boxes.some((b) => inBox(b, x, y));
};
/** The base's lines and each layer's, with the suffix a violation names its view by. */
var views$1 = (plan) => [["", plan.routes], ...Object.entries(plan.layers ?? {}).map(([id, l]) => [` (layer ${id})`, l.routes])];
/** Every drone pad whose tile lies outside every box: a pad stands inside its machine, never on a corridor tile. */
function padCorridorViolations(plan) {
	const covered = boxAt(plan);
	return (plan.tf.landing?.pads ?? []).filter((p) => !covered(p.x, p.y)).map((p) => ({
		detail: `${p.role} pad of ${p.machine} (${p.topic}) on a corridor tile`,
		at: {
			x: p.x,
			y: p.y
		}
	}));
}
/** The movers whose trip the audit times: a train on a rail and a drone on a drone route (an event). Belts, pipes and
*  taps are not timed: their items run at a steady 60 px/s by design (lane.ts `moverSpeed`), so their trip grows with
*  the line; row 25 was about drones crawling along long flight paths. A train scales its speed to its rail; every
*  drone on a floor flies at the speed its longest flight sets, so that flight crosses in about FLIGHT_SECS. */
var TIMED = {
	rail: "train",
	drone: "event"
};
var secs = (s) => s.toFixed(1);
/** Every train or drone whose trip takes over its TRIP_MAX s end to end at the movers' speed (`speed`, the viewer's
*  lane.ts `moverSpeed`; a test may pass another to prove the check sees a slow mover): a rail's length is its piece
*  count times the tile, in the base and in each layer view; a flight's is its path's length (as drones.ts measures
*  it). A route with no pieces (a drone route, a failed line) carries nothing along tiles. */
function travelViolations(plan, speed = moverSpeed) {
	const out = [];
	const trip = (kind, length) => length / speed(kind, length);
	for (const [view, routes] of views$1(plan)) for (const r of routes) {
		const kind = TIMED[r.kind];
		if (!kind || !r.pieces.length) continue;
		const t = trip(kind, r.pieces.length * 24);
		if (t > TRIP_MAX[kind] + 1e-6) out.push({
			detail: `${r.kind} ${r.key} takes ${secs(t)} s (${r.pieces.length} tiles)${view}`,
			at: {
				x: r.pieces[0].x,
				y: r.pieces[0].y
			}
		});
	}
	const flights = flightPaths(plan.tf).map((f) => {
		let len = 0;
		for (let i = 1; i < f.points.length; i++) len += Math.hypot(f.points[i].x - f.points[i - 1].x, f.points[i].y - f.points[i - 1].y);
		return {
			f,
			len
		};
	});
	const longest = Math.max(0, ...flights.map((x) => x.len));
	for (const { f, len } of flights) {
		const t = len / speed("event", longest);
		if (t > TRIP_MAX.event + 1e-6) out.push({
			detail: `${f.flight} flight ${f.key} takes ${secs(t)} s (${Math.round(len)} px)`,
			at: {
				x: Math.floor(f.points[0].x / 24),
				y: Math.floor(f.points[0].y / 24)
			}
		});
	}
	return out;
}
/** Every relation bundle the floor holds (`model.bundles(container)`: its base bundles and each layer's) that the plan
*  draws nowhere: its key is on no base route and no layer route, and no flight carries it. Every route the plan holds
*  is drawn (a belt, a pipe, a tap, a rail, a dotted drone route, or a failed line dashed red), and a bundle its flights
*  carry whole (`coveredKeys`) is drawn as them. */
function lostViolations(model, container, plan) {
	const { bundles, layered } = model.bundles(container);
	const drawn = new Set(views$1(plan).flatMap(([, routes]) => routes.map((r) => r.key)));
	for (const k of coveredKeys(flightPaths(plan.tf), [...bundles, ...layered])) drawn.add(k);
	return [...bundles.map((b) => ({
		b,
		view: ""
	})), ...layered.map((b) => ({
		b,
		view: ` (layer ${b.layer})`
	}))].filter(({ b }) => !drawn.has(b.key)).map(({ b, view }) => ({ detail: `relation ${b.key} (${b.kind}) is in neither the base nor a layer${view}` }));
}
/** The smallest machine or door name the drawing fits on the floor, px, as the scene keeps it (`minName`: 14 before
*  any box is drawn, then each name's fitted size: factory-draw.ts `paintBox`, draw.ts `drawDoor`). */
function minNameSize(model, container, plan) {
	const ctx = nameContext(model, container, plan.tf.boxes.values(), model.bundles(container).doors);
	return Math.min(14, ...[...plan.tf.boxes.values()].map((b) => boxNameFit(model, ctx, b).size));
}
/** A floor more than WIDE times as wide (for its height) as the Fit canvas whose names do not read at Fit: Fit is held
*  back by its width, so a row of it should wrap (row 46: an airfield's hubs in one long row). Small wide floors read
*  at Fit and pass. */
function wideViolations(m, plan) {
	const { cols, rows } = plan.tf, aspect = cols / rows;
	if (aspect <= 2 * (FIT_AREA.w / FIT_AREA.h) || m.fitZoom >= m.switchZoom) return [];
	return [{ detail: `${cols}×${rows} tiles, ${aspect.toFixed(1)}:1: at Fit (${m.fitZoom.toFixed(2)}) names need ${m.switchZoom.toFixed(2)}` }];
}
/** The floor's measured numbers (no threshold yet):
*  - `congestion`: above-ground line tiles of the base (each tile once) divided by the tiles outside every box;
*  - `spacing.area`: machine area (every box but the doors) divided by the floor's area; `spacing.spread`: the
*    coefficient of variation of each machine's edge-to-edge gap to its nearest machine, tiles (0 under two machines);
*  - `fitZoom`: the zoom the scene's Fit picks for a FIT_AREA canvas (`fitZoom`, no bottom inset);
*  - `switchZoom`: the names/codes switch, `codeZoom` of the floor's smallest name (`minNameSize`). */
function measure(plan, model, container) {
	const { tf } = plan, boxed = boxAt(plan);
	const lines = /* @__PURE__ */ new Set();
	for (const r of plan.routes) for (const p of r.pieces) if (!p.under && !boxed(p.x, p.y)) lines.add(p.y * tf.cols + p.x);
	let free = 0;
	for (let y = 0; y < tf.rows; y++) for (let x = 0; x < tf.cols; x++) if (!boxed(x, y)) free++;
	const machines = [...tf.boxes.values()].filter((b) => b.kind !== "door");
	const area = machines.reduce((s, b) => s + b.w * b.h, 0) / Math.max(1, tf.cols * tf.rows);
	const gap = (a, b) => Math.hypot(Math.max(0, b.x - (a.x + a.w), a.x - (b.x + b.w)), Math.max(0, b.y - (a.y + a.h), a.y - (b.y + b.h)));
	const gaps = machines.length < 2 ? [] : machines.map((a) => Math.min(...machines.filter((b) => b !== a).map((b) => gap(a, b))));
	const mean = gaps.reduce((s, g) => s + g, 0) / Math.max(1, gaps.length);
	const sd = Math.sqrt(gaps.reduce((s, g) => s + (g - mean) ** 2, 0) / Math.max(1, gaps.length));
	return {
		congestion: free ? lines.size / free : 0,
		spacing: {
			area,
			spread: mean > 0 ? sd / mean : 0
		},
		fitZoom: fitZoom(tf.cols * 24, tf.rows * 24, FIT_AREA.w, FIT_AREA.h, container === SITE),
		switchZoom: codeZoom(minNameSize(model, container, plan))
	};
}
// src/audit/flights.ts
var name = (p) => `${p.flight} ${p.key}${p.group !== void 0 ? ` (${p.group})` : ""}`;
var tile = (q) => ({
	x: Math.floor(q.x / 24),
	y: Math.floor(q.y / 24)
});
var px = (tf, id) => {
	const r = tf.boxes.get(id);
	return r ? {
		x0: r.x * 24,
		y0: r.y * 24,
		x1: (r.x + r.w) * 24,
		y1: (r.y + r.h) * 24
	} : void 0;
};
/** Pairs of flight paths whose seen parts (`visiblePart`: from the pad or dock to the hub's edge) run within OVERLAP_PX
*  of each other for OVERLAP_RUN or more on open floor (outside every box's face: under a box they are hidden, which
*  `flights.hidden` reports), each with whether its pads are in line with their one hub (`inLine`). */
function overlaps(tf, paths) {
	const faces = keepOffBoxes(tf, 0).map((b) => b.r);
	const seen = paths.map((p) => {
		const r = px(tf, p.item);
		return r ? visiblePart(p, r) : [p.launch, p.hub];
	});
	const out = [];
	for (let i = 0; i < paths.length; i++) for (let j = i + 1; j < paths.length; j++) {
		const run = runTogether(seen[i], seen[j], faces);
		if (run < OVERLAP_RUN) continue;
		const a = paths[i], b = paths[j], hub = px(tf, a.item);
		const line = a.item === b.item && !!hub && inLine(a.launch, b.launch, {
			x: (hub.x0 + hub.x1) / 2,
			y: (hub.y0 + hub.y1) / 2
		});
		out.push({
			a,
			b,
			run,
			at: seen[i][1],
			inLine: line
		});
	}
	return out;
}
var told = (o) => ({
	detail: `${name(o.a)} and ${name(o.b)} run within 3 px of each other for ${Math.round(o.run)} px on open floor`,
	at: tile(o.at)
});
/** `flights.overlap`: two flight paths still on top of each other on open floor after their landings are spread
*  (`spreadLandings`): a group into one hub with more paths than its edge holds, sharing landing points, or paths into
*  different hubs. Paths whose pads are in line with their hub are `flights.in-line`'s. */
function overlapViolations(tf, paths = flightPaths(tf)) {
	return overlaps(tf, paths).filter((o) => !o.inLine).map(told);
}
/** `flights.in-line`, an advisory: two paths into one hub whose pads are in line with it (one machine straight behind
*  another) that still run together on open floor with their landings spread over the whole edge: the far pad is too
*  far from the hub, for the near one, for the edge's width to part them. */
function inLineViolations(tf, paths = flightPaths(tf)) {
	return overlaps(tf, paths).filter((o) => o.inLine).map(told);
}
/** A flight path that passes under a box it does not belong to, for HIDDEN_MIN or more of its length: one of
*  `flightKeepOff`'s (a machine, hub, store or door, a receiving or webhook dock, a waiting stack), by its face alone
*  (the shadow is not the box), other than its own machine's, its hub's, or theirs (the machine's docks, the hub's
*  stack). Paths are drawn under the machines, so that stretch is hidden. An advisory, not a map limit: a known look,
*  kept for now (format.md → Audit). */
function hiddenViolations(tf, paths = flightPaths(tf)) {
	const boxes = keepOffBoxes(tf, 0), out = [];
	for (const p of paths) for (const b of boxes) {
		if (b.owner === p.machine || b.owner === p.item) continue;
		let len = 0;
		for (let i = 1; i < p.points.length; i++) len += through(p.points[i - 1], p.points[i], b.r);
		if (len >= 8) out.push({
			detail: `${name(p)} passes under ${b.name} for ${Math.round(len)} px`,
			at: tile({
				x: (b.r.x0 + b.r.x1) / 2,
				y: (b.r.y0 + b.r.y1) / 2
			})
		});
	}
	return out;
}
/** How far segment a→b runs through `r`, in px (Liang–Barsky). */
function through(a, b, r) {
	let t0 = 0, t1 = 1;
	const dx = b.x - a.x, dy = b.y - a.y;
	for (const [p, q] of [
		[-dx, a.x - r.x0],
		[dx, r.x1 - a.x],
		[-dy, a.y - r.y0],
		[dy, r.y1 - a.y]
	]) {
		if (p === 0) {
			if (q < 0) return 0;
			continue;
		}
		const t = q / p;
		if (p < 0) {
			if (t > t1) return 0;
			if (t > t0) t0 = t;
		} else {
			if (t < t0) return 0;
			if (t < t1) t1 = t;
		}
	}
	return t1 > t0 ? (t1 - t0) * Math.hypot(dx, dy) : 0;
}
// src/audit/types.ts
/** The row of the owner's audit each check comes from. */
var ROW = {
	"lines.failed": "9",
	"lines.plugged": "9",
	"lines.trunks": "9",
	"lines.under": "2",
	"lines.mid-side": "13",
	"lines.plate-wall": "30",
	"lines.lane-drop": "—",
	"lines.gap-stub": "—",
	"lines.lane-gap": "—",
	"text.cut": "5",
	"text.over-line": "7, 8, 45",
	"zone.narrow": "26",
	"pads.corridor": "32",
	"travel.long": "25",
	"flights.overlap": "—",
	"flights.in-line": "—",
	"flights.hidden": "—",
	"lost.relation": "40",
	"floor.wide": "46",
	"plan.crashed": "—"
};
/** Advisory checks: what they find is a look that is known and kept for now, not a map limit. audit.py lists it in
*  audit.md under "Drawing advisories"; it never counts as a limit, nor changes the summary line. */
var ADVISORIES = /* @__PURE__ */ new Set(["flights.in-line", "flights.hidden"]);
// src/audit/run.ts
var firstLine = (e) => (String(e instanceof Error ? e.message : e).split("\n")[0] || "error").trim();
/** The base's lines and each layer's, with the suffix a violation names its view by. */
var views = (plan) => [["", plan.routes], ...Object.entries(plan.layers ?? {}).map(([id, l]) => [` (layer ${id})`, l.routes])];
/** A list check over each view (a layer's violations named by the layer), and a per-route check over each view's lines. */
var perView = (plan, check) => views(plan).flatMap(([view, routes]) => check(routes).map((v) => ({
	...v,
	detail: v.detail + view
})));
var perRoute = (plan, check) => perView(plan, (routes) => routes.filter((r) => r.pieces.length).flatMap(check));
/** Every check over one floor's plan, in the order of the check table. */
function checks(model, c, plan, measured) {
	const { tf } = plan, { bundles } = model.bundles(c);
	let paths;
	const flights = () => paths ??= flightPaths(tf);
	return [
		["lines.failed", () => perView(plan, failedViolations)],
		["lines.plugged", () => perRoute(plan, (r) => pluggedViolations(tf, r))],
		["lines.trunks", () => perView(plan, (routes) => trunkViolations(tf, routes))],
		["lines.under", () => perRoute(plan, underViolations)],
		["lines.mid-side", () => [...midSideViolations(tf, plan.routes), ...views(plan).slice(1).flatMap(([view, routes]) => midSideViolations(tf, [...plan.routes, ...routes]).filter((v) => routes.some((r) => v.detail.startsWith(`${r.key} `))).map((v) => ({
			...v,
			detail: v.detail + view
		})))]],
		["lines.plate-wall", () => perRoute(plan, (r) => plateWallViolations(tf, r))],
		["lines.lane-drop", () => perView(plan, (routes) => laneDropViolations(tf, routes))],
		["lines.gap-stub", () => perView(plan, (routes) => gapStubViolations(tf, routes))],
		["lines.lane-gap", () => perView(plan, (routes) => laneGapViolations(tf, routes))],
		["text.cut", () => cutViolations(model, c, plan)],
		["text.over-line", () => overLineViolations(model, c, plan, bundles)],
		["zone.narrow", () => narrowZoneViolations(plan)],
		["pads.corridor", () => padCorridorViolations(plan)],
		["travel.long", () => travelViolations(plan)],
		["flights.overlap", () => overlapViolations(tf, flights())],
		["flights.in-line", () => inLineViolations(tf, flights())],
		["flights.hidden", () => hiddenViolations(tf, flights())],
		["lost.relation", () => lostViolations(model, c, plan)],
		["floor.wide", () => wideViolations(measured(), plan)]
	];
}
/** What the audit may spend, in boxes: each floor costs its box count plus FLOOR_COST, for the work every floor takes
*  whatever its size. Counted in work, not time, so the same map always checks the same floors on any machine (about
*  30 s on the largest maps known). */
var BUDGET = 2500;
/** Audits the floors of `map`, in order, until they have spent `budget` (BUDGET): the floors after that go to
*  `skipped`. Each floor gets one result per check (the first violation and how many more), or one `plan.crashed` when
*  its plan throws; an empty floor is checked with no results. `measured` holds each planned floor's numbers by its
*  code. */
function auditMap(map, budget = BUDGET) {
	const model = new Model(map);
	const containers = map.layout.containers;
	const size = (c) => Object.keys(containers[c].items ?? {}).length;
	const floors = Object.keys(containers).sort((a, b) => Number(b === "site") - Number(a === "site") || size(b) - size(a) || a.localeCompare(b));
	const out = {
		checked: [],
		skipped: [],
		skippedCodes: [],
		results: [],
		measured: {}
	};
	let spent = 0;
	for (const c of floors) {
		if (spent >= budget) {
			out.skipped.push(c);
			out.skippedCodes.push(model.codes.get(c) ?? c);
			continue;
		}
		spent += size(c) + 3;
		out.checked.push(c);
		if (!size(c)) continue;
		const code = model.codes.get(c) ?? c;
		const result = (check, vs) => {
			const v = vs[0], advisory = ADVISORIES.has(check) ? { advisory: true } : {};
			if (!v) return {
				check,
				floor: c,
				code,
				row: ROW[check],
				ok: true,
				detail: "",
				...advisory
			};
			const more = vs.length > 1 ? ` (+${vs.length - 1} more)` : "";
			return {
				check,
				floor: c,
				code,
				row: ROW[check],
				ok: false,
				detail: v.detail + more,
				...v.at ? { at: {
					x: v.at.x,
					y: v.at.y
				} } : {},
				...advisory
			};
		};
		let plan;
		try {
			plan = planJob(model, c);
		} catch (e) {
			out.results.push(result("plan.crashed", [{ detail: `${code}: ${firstLine(e)}` }]));
			continue;
		}
		let numbers;
		const measured = () => numbers ??= measure(plan, model, c);
		for (const [check, run] of checks(model, c, plan, measured)) {
			let vs;
			try {
				vs = run();
			} catch (e) {
				vs = [{ detail: `the check crashed: ${firstLine(e)}` }];
			}
			out.results.push(result(check, vs));
		}
		try {
			out.measured[code] = measured();
		} catch {}
	}
	return out;
}
// src/audit/cli.ts
var args = process.argv.slice(2);
var path = args.find((a) => !a.startsWith("--"));
var map;
try {
	if (!path) throw new Error("usage: node audit.mjs <code-map.json> [--full]");
	map = JSON.parse(readFileSync(path, "utf8"));
} catch (e) {
	process.stderr.write(`audit: cannot read the map: ${String(e instanceof Error ? e.message : e).split("\n")[0]}\n`);
	process.exit(2);
}
var report;
try {
	report = auditMap(map, args.includes("--full") ? Infinity : BUDGET);
} catch (e) {
	process.stderr.write(`audit: ${String(e instanceof Error ? e.message : e).split("\n")[0]}\n`);
	process.exit(2);
}
process.stdout.write(`${JSON.stringify(report)}\n`);
export {};
