// Where a trace starts (spec §3.1, any-box A2–A5): any box. A method, table, topic or external starts at itself, a
// datastore at its tables; a service, library, package, file, class or floor group at the entry points inside it, else
// at its boundary methods (methods inside it at one end of a traced relation whose other end is outside it), else at
// itself; a line at the nodes at both ends of what it carries. An entry point is a route's handler (`files[].routes`) or
// a method a request, event, stream or batch arrives at. The Python checklist uses the same rule (vizcode/examples.seeds).
import { numericCollator, type Model } from "../model/model";
import type { Target } from "../floor/state";
import type { Relation } from "../model/types";
import { TRACE_KINDS } from "./graph";

const ARRIVES = new Set(["request", "event", "stream", "batch"]);

/** The boxes that start a trace from the seeds inside them (spec A3). */
export const CONTAINERS: ReadonlySet<string> = new Set(["service", "library", "package", "file", "class", "group"]);

/** Any map node or floor group can start a trace (spec A2); a twin stands for the package it deploys. */
export const traceable = (model: Model, id: string): boolean => {
  const real = model.twinOf(id) ?? id;
  return model.nodes.has(real) || model.groups.has(real);
};

export interface EntryPoint { node: string; keys: string[] }

/** Is relation key `key` the route `method path`, with or without a mount prefix (vizcode/examples._mounted)? */
const mounted = (key: string, method: string, path: string): boolean => {
  const i = key.indexOf(" ");
  const [verb, full] = i < 0 ? [key, ""] : [key.slice(0, i), key.slice(i + 1)];
  return verb === method && (full === path || (path !== "/" && full.endsWith(path) && full.slice(0, -path.length).startsWith("/")));
};

/** The entry points inside service or library `owner`, each with the keys that arrive there, sorted by key. */
export function entryPoints(model: Model, owner: string): EntryPoint[] {
  const keys = new Map<string, Set<string>>();
  const add = (node: string, key?: string) => {
    if (model.nodes.get(node)?.kind !== "method" || !model.isInside(node, owner)) return;
    const s = keys.get(node) ?? new Set<string>();
    if (key) s.add(key);
    keys.set(node, s);
  };
  for (const r of model.map.relations) if (ARRIVES.has(r.kind)) add(r.to, r.key ?? undefined);
  // one key per route: a route fact a relation key already names with its mount prefix is that key
  for (const f of Object.values(model.map.files ?? {})) for (const r of f.routes ?? []) {
    if (r.handler && ![...(keys.get(r.handler) ?? [])].some((k) => mounted(k, r.method, r.path))) add(r.handler, `${r.method} ${r.path}`);
  }
  return [...keys].map(([node, k]) => ({ node, keys: [...k].sort() }))
    .sort((a, b) => (a.keys[0] ?? "").localeCompare(b.keys[0] ?? "") || a.node.localeCompare(b.node));
}

/** `ids` sorted in place by code (numeric runs as numbers), an id without a code by itself. */
const byCode = (model: Model, ids: string[]): string[] =>
  ids.sort((a, b) => numericCollator.compare(model.codes.get(a) ?? a, model.codes.get(b) ?? b));

/** Every method inside `id` (a package, file or class), in code order. */
export function methodsIn(model: Model, id: string): string[] {
  return byCode(model, model.descendants(id).filter((x) => model.nodes.get(x)?.kind === "method"));
}

export type SeedRule = "self" | "tables" | "entry points" | "boundary methods" | "container" | "ends";
export interface Seeds { ids: string[]; rule: SeedRule }

/** A line's trace (spec A5): its key on its floor, its title as the inspector names it, and the nodes it starts from. */
export interface LineStart { key: string; title: string; ends: readonly string[] }

/** The trace focus that stands for line `key`. */
export const lineFocus = (key: string): string => `line:${key}`;

/** Where a trace of line `key` starts (ruling R7): the map nodes at both ends of each relation it carries that a trace
 *  follows, once each, in code order; null when it carries none (a code link). */
export function lineStart(model: Model, key: string, relations: readonly Relation[], title: string): LineStart | null {
  const ends = new Set<string>();
  for (const r of relations) if (TRACE_KINDS.includes(r.kind)) for (const e of [r.from, r.to]) if (model.nodes.has(e)) ends.add(e);
  return ends.size ? { key, title, ends: byCode(model, [...ends]) } : null;
}

/** The methods inside container `id` at one end of a relation a trace follows whose other end is outside it (spec A3),
 *  in code order. */
export function boundaryMethods(model: Model, id: string): string[] {
  const inside = new Set(model.descendants(id));
  const within = (x: string) => x === id || inside.has(x);
  const out = new Set<string>();
  for (const r of model.relationsOf(id)) {   // every relation with an end inside `id`, in map order
    if (!TRACE_KINDS.includes(r.kind)) continue;
    for (const [end, other] of [[r.from, r.to], [r.to, r.from]] as const)
      if (model.nodes.get(end)?.kind === "method" && inside.has(end) && !within(other)) out.add(end);
  }
  return byCode(model, [...out]);
}

/** Where a trace of `focus` starts (spec A3, A5): a line's ends; a datastore's tables (itself with none); a container's
 *  entry points (inspector order), else its boundary methods, else itself (a floor group: its members); any other node
 *  itself; nothing for an id not in the map. */
export function seedsFor(model: Model, focus: string, line?: LineStart): Seeds {
  if (line) return { ids: [...line.ends], rule: "ends" };
  const kind = model.kindOf(focus);
  if (kind === "datastore") {
    const tables = model.map.nodes.filter((t) => t.kind === "table" && t.parent === focus).map((t) => t.id).sort();
    if (tables.length) return { ids: tables, rule: "tables" };
  }
  if (CONTAINERS.has(kind)) {
    const entries = entryPoints(model, focus).map((e) => e.node);
    if (entries.length) return { ids: entries, rule: "entry points" };
    const edge = boundaryMethods(model, focus);
    if (edge.length) return { ids: edge, rule: "boundary methods" };
    const group = model.groups.get(focus);
    return { ids: group ? group.members.filter((x) => model.nodes.has(x)) : [focus], rule: "container" };
  }
  return { ids: model.nodes.has(focus) ? [focus] : [], rule: "self" };
}

/** What a pick on floor `c` traces from while the pane is open (spec A2, A5): a node by its id (a twin as the package
 *  it stands for), a floor group by its id; a line by the ends of the relations it carries on this floor (`railLine`: a
 *  stand-in rail's or a yard's, which no bundle carries), titled as the inspector names it; null for a line that carries
 *  nothing a trace follows (a code link), or an id not in the map. */
export function startFor(model: Model, c: string, t: NonNullable<Target>,
  railLine?: (key: string) => { title: string; relations: readonly Relation[] } | undefined): { focus: string; line?: LineStart } | null {
  if (t.type === "node") {
    const id = model.twinOf(t.id) ?? t.id;
    return traceable(model, id) ? { focus: id } : null;
  }
  const b = model.bundles(c);
  const bundle = b.bundles.find((x) => x.key === t.key) ?? b.layered.find((x) => x.key === t.key);
  const rail = bundle ? undefined : railLine?.(t.key);
  const title = rail?.title ?? (t.key.includes("|") ? t.key.split("|").map((x) => model.label(x)).join(" ↔ ") : t.key);
  const line = lineStart(model, t.key, bundle?.relations ?? rail?.relations ?? [], title);
  return line ? { focus: lineFocus(t.key), line } : null;
}
