// A tiny code map written in a few lines, for the trace tests: services and libraries, one package each, classes with
// methods, and relations with an evidence line.
import { Model } from "../../src/model/model";
import type { CodeMap, Field, MapNode, RelationKind } from "../../src/model/types";

export interface Param { name: string; type: string | null; refs?: string[] }

export class MapBuilder {
  readonly nodes: MapNode[] = [];
  readonly relations: CodeMap["relations"] = [];
  extra: Partial<CodeMap> = {};

  private has(id: string) { return this.nodes.some((n) => n.id === id); }

  /** `svc:<name>` (or `lib:<name>`). */
  owner(name: string, kind: "service" | "library" = "service"): string {
    const id = `${kind === "service" ? "svc" : "lib"}:${name}`;
    this.nodes.push({ id, kind, name });
    return id;
  }

  /** A class `<owner name>::pkg.<cls>` in the owner's one package; `fields` when given. */
  cls(owner: string, cls: string, fields?: Field[], implementsIds?: string[]): string {
    const base = owner.slice(owner.indexOf(":") + 1);
    const pkg = `${base}::pkg/`, cid = `${base}::pkg.${cls}`;
    if (!this.has(pkg)) this.nodes.push({ id: pkg, kind: "package", name: "pkg", parent: owner });
    if (!this.has(cid)) this.nodes.push({ id: cid, kind: "class", name: cls, parent: pkg, file: `${base}/${cls}.py`, line: 1,
      ...(fields ? { fields } : {}), ...(implementsIds ? { implements: implementsIds } : {}) });
    return cid;
  }

  /** A method `<class>#<name>/<arity>` of class `cls` in `owner`. */
  method(owner: string, cls: string, name: string, params: Param[] = [], returns: string | null = null, returnsRefs?: string[]): string {
    const cid = this.cls(owner, cls);
    const mid = `${cid}#${name}/${params.length}`;
    this.nodes.push({ id: mid, kind: "method", name, parent: cid, file: `${cid.split("::")[0]}/${cls}.py`, line: 10,
      signature: { params, returns, ...(returnsRefs ? { returns_refs: returnsRefs } : {}) } });
    return mid;
  }

  node(n: MapNode): string {
    this.nodes.push(n);
    return n.id;
  }

  rel(kind: RelationKind, from: string, to: string, opts: { line?: number; file?: string; key?: string; inferred?: boolean } = {}): void {
    this.relations.push({
      id: `r:${kind}:${from}->${to}:${opts.key ?? ""}`, kind, from, to, key: opts.key ?? null,
      confidence: opts.inferred ? "inferred" : "confirmed", ...(opts.inferred ? { why: "matched by name only" } : {}),
      evidence: [{ file: opts.file ?? "f.py", line: opts.line ?? 1 }],
    });
  }

  map(): CodeMap {
    return {
      meta: { schema_version: 3, repo: "trace-test", commit: "0".repeat(40), scanned_at: "2026-10-13T00:00:00Z", languages: ["python"] },
      nodes: this.nodes, relations: this.relations, problems: [],
      layout: { version: 1, containers: { site: { strategy: "main-bus", items: {} } } },
      ...this.extra,
    } as unknown as CodeMap;
  }

  model(): Model {
    return new Model(this.map());
  }
}
