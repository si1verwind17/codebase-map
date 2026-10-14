// Machine names: drop what every item on a floor shares, wrap, and keep the specific end.
import type { Model } from "../model/model";

/** Longest dotted (or path) prefix shared by at least two names, ending at a separator. */
export function commonPrefix(names: string[]): string {
  if (names.length < 2) return "";
  let p = names[0];
  for (const n of names) while (p && !n.startsWith(p)) p = p.slice(0, -1);
  // one name may be the stem itself (com.acme.order beside com.acme.order.api): strip the stem too
  if (names.every((n) => n === p || n.startsWith(p + ".") || n.startsWith(p + "/")) && names.some((n) => n !== p)) return p + ".";
  const cut = Math.max(p.lastIndexOf("."), p.lastIndexOf("/"));
  return cut > 0 ? p.slice(0, cut + 1) : "";
}

/** Up to `max` lines, breaking after `.`, `_`, `/`, `-` or a space, or before `(` or a camelCase capital; if it still does not fit, keep the end (most specific). */
export function nameLines(s: string, width: number, size: number, max: number): string[] {
  const per = Math.max(4, Math.floor(width / (size * 0.56)));
  if (s.length <= per) return [s];
  const lines: string[] = [];
  let rest = s;
  while (rest.length > per && lines.length < max - 1) {
    const window = rest.slice(0, per);
    const after = Math.max(window.lastIndexOf("."), window.lastIndexOf("_"), window.lastIndexOf("/"), window.lastIndexOf(" "), window.lastIndexOf("-"));
    const before = window.lastIndexOf("(");
    let camel = -1;   // before a capital that follows a lower-case letter or digit: Discord|Notifier
    for (let i = window.length - 1; i > 0; i--) if (/[A-Z]/.test(window[i]) && /[a-z0-9]/.test(window[i - 1])) { camel = i; break; }
    const sep = Math.max(after + 1, before);
    let cut = sep > per / 3 ? sep : camel > per / 3 ? camel : per;   // separators first, camelCase second
    if (cut === per && rest.length - cut <= 2) cut = rest.length - 3;   // never strand a letter or two
    lines.push(rest.slice(0, cut).trimEnd());
    rest = rest.slice(cut).trimStart();
  }
  lines.push(rest.length > per ? "…" + rest.slice(rest.length - per + 1) : rest);
  return lines;
}

/** "Stripe API WebSocket (stream.stripe.com/streams)" → title "Stripe API WebSocket", endpoint for the subline. */
export function splitEndpoint(label: string): { title: string; endpoint: string } {
  const m = /^(.*\S)\s*\(([^()]+)\)$/.exec(label);
  return m ? { title: m[1], endpoint: m[2] } : { title: label, endpoint: "" };
}

/** A door's name relative to the floors above it: strip the deepest enclosing package but keep its last
 *  segment for context (`com.acme.market.service.stripe` under `com.acme.market.service` → `service.stripe`). */
export function doorName(label: string, above: string[]): string {
  const title = splitEndpoint(label).title;
  const outer = above.filter((a) => title.startsWith(a + ".")).sort((a, b) => b.length - a.length)[0];
  if (!outer) return title;
  const cut = outer.lastIndexOf(".");
  return cut > 0 ? title.slice(cut + 1) : title;
}

/** The dotted prefix every item on a floor shares, from the map's own names (`Model.label`), never from the floor-unique
 *  ones: a tag added to tell items apart (`config/1`, `X (object)`, `a.Twin`) must not become something to strip.
 *  Doors, datastores and twins keep their own names and take no part. */
export function floorPrefix(model: Model, ids: string[]): string {
  return commonPrefix(ids.filter((id) => !id.startsWith("door:") && model.kindOf(id) !== "datastore" && !model.twinOf(id)).map((id) => model.label(id)));
}

/** `full` without the floor's shared dotted `prefix` (from `commonPrefix`); the stem package itself keeps its last segment. */
export function stripShared(full: string, prefix: string): string {
  if (prefix && full === prefix.slice(0, -1)) return full.split(/[./]/).pop() ?? full;
  return prefix && full.startsWith(prefix) && full.length > prefix.length ? full.slice(prefix.length) : full;
}

/** The name an item's box and the floor list show: its floor-unique name (`Model.itemName`) less the floor's shared
 *  prefix; an external drops its endpoint, a table its default schema. */
export function shownName(model: Model, id: string, prefix: string): string {
  let full = model.itemName(id);
  if (model.kindOf(id) === "external") return splitEndpoint(full).title;
  if (model.kindOf(id) === "table") full = full.replace(/^public\./, "");   // the default schema says nothing
  return stripShared(full, prefix);
}
