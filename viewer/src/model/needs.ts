// What a class is built from (its constructor fact) and, the other way round, which classes are built from it.
import { numericCollator, SITE, type Model } from "./model";

export type Need = { name: string; type: string | null; refs: string[] };

/** The parameters of the constructor or factory of class `id`; null when it has none. `of` is the number of candidates when several. */
export function needsOf(model: Model, id: string): { needs: Need[]; from: string; file?: string; line?: number; of?: number } | null {
  const node = model.nodes.get(id);
  const c = node?.ctor;
  if (!c) return null;
  const method = c.method ? model.nodes.get(c.method) : undefined;
  if (c.method && !method) return null;
  const params = method ? (method.signature?.params ?? []) : (c.params ?? []);
  return {
    needs: params.map((p) => ({ name: p.name, type: p.type, refs: p.refs ?? [] })),
    from: method ? method.name : "class parameters",
    file: method ? method.file : node!.file,
    line: method ? method.line : c.line,
    ...(c.of ? { of: c.of } : {}),
  };
}

const consumers = new WeakMap<Model, Map<string, Set<string>>>();

/** Per class id, the classes that take it in their constructor; a class others implement is never built as itself. */
function consumersOf(model: Model): Map<string, Set<string>> {
  let index = consumers.get(model);
  if (!index) {
    index = new Map();
    for (const n of model.map.nodes) {
      if (n.kind !== "class" || model.implementersOf(n.id).length) continue;
      for (const need of needsOf(model, n.id)?.needs ?? [])
        for (const r of need.refs) index.set(r, (index.get(r) ?? new Set()).add(n.id));
    }
    consumers.set(model, index);
  }
  return index;
}

/** The classes that take `id` in their constructor, or an interface `id` implements, directly or through the interfaces
 *  those implement (`through`: the nearest such interface the class is taken as); in code order. */
export function neededBy(model: Model, id: string): { id: string; through: string | null }[] {
  const index = consumersOf(model);
  const found = new Map<string, string | null>();
  for (const c of index.get(id) ?? []) found.set(c, null);
  const seen = new Set([id]);
  for (let level = model.implementedBy(id); level.length; ) {
    const next: string[] = [];
    for (const iface of level) {
      if (seen.has(iface)) continue;
      seen.add(iface);
      for (const c of index.get(iface) ?? []) if (!found.has(c)) found.set(c, iface);
      next.push(...model.implementedBy(iface));
    }
    level = next;
  }
  found.delete(id);
  return [...found]
    .map(([cid, through]) => ({ id: cid, through }))
    .sort((a, b) => numericCollator.compare(model.codes.get(a.id) ?? a.id, model.codes.get(b.id) ?? b.id));
}

/** The service `id` sits in; undefined for a library, an external or the site. */
export function serviceOf(model: Model, id: string): string | undefined {
  const svc = model.path(model.floorOf(id) ?? SITE)[1];
  return svc && model.nodes.get(svc)?.kind === "service" ? svc : undefined;
}

/** `ids` split into those in the service of `context` (or in none) and those in another service. */
export function splitByService(model: Model, ids: string[], context: string): { here: string[]; other: string[] } {
  const home = serviceOf(model, context);
  const here: string[] = [];
  const other: string[] = [];
  for (const id of ids) {
    const svc = serviceOf(model, id);
    (home && svc && svc !== home ? other : here).push(id);
  }
  return { here, other };
}
