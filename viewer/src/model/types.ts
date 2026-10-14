// The subset of code-map.json (schema v2) the viewer reads. See ../../format.md.

export type NodeKind =
  | "service" | "library" | "datastore" | "external" | "topic"
  | "package" | "class" | "file" | "method" | "table";

export interface MapNode {
  id: string;
  kind: NodeKind;
  name: string;
  parent?: string | null;
  lang?: string;
  file?: string;
  line?: number;
  visibility?: "public" | "private";
  metrics?: { methods?: number; loc?: number };
  fields?: Field[];   // on a class: its declared fields (scanner)
  signature?: { params: { name: string; type: string | null; refs?: string[] }[]; returns: string | null; returns_refs?: string[] };
  role?: "entry" | "logic" | "outbound" | "storage" | "model";
  summary?: string;
  defaulted?: boolean;
  twins?: string[];            // on a service: root packages of another service's module it also deploys
  implements?: string[];       // on a class: the class/trait ids it implements (scanner, Scala)
  delivery?: "fan-out" | "queue";          // on a topic
  dead_letter_of?: string;                 // on a topic: the topic whose failures land here
  replicas?: number;                       // on a service: instances running
  store?: "database" | "cache" | "bucket" | "warehouse";   // on a datastore
}

export type RelationKind =
  | "request" | "event" | "stream" | "batch" | "db-read" | "db-write" | "ext-call" | "uses-code" | "calls";

export interface Evidence { file: string; line?: number }

export interface Relation {
  id: string;
  kind: RelationKind;
  from: string;
  to: string;
  key?: string | null;
  confidence: "confirmed" | "inferred";
  why?: string;
  data?: "forward" | "back" | "both";
  deployment_dependent?: boolean;
  bidirectional?: boolean;
  via?: string;
  tables?: string[];
  subscription?: "push" | "pull";          // event consumed from a topic
  group?: string;                          // event consumed from a topic: consumer group
  on_failure?: boolean;                    // event published to a topic on failure
  schedule?: string[];                     // batch: cron, "manual" or "on <event>"
  job?: string;                            // batch: job name
  evidence: Evidence[];
}

export interface Field { name: string; type: string | null }

/** The label every shown example carries (format.md § Examples). */
export const EXAMPLE_LABEL = "example values, not computed";

/** A route fact of a file (format.md § Files): its handler is a node id (a method, or the file for inline handlers). */
export interface RouteFact { method: string; path: string; handler: string; line: number }
export interface FileInfo { lang: string; module: string; node: string; parse_error?: boolean; routes?: RouteFact[] }

/** A pinned trace (format.md § Pins). */
export type PinDirection = "downstream" | "upstream" | "both";
export interface Pin { id: string; title: string; start: string; direction: PinDirection; by: "agent" | "user" }

/** Examples (format.md § Examples): one per data type (keyed by class id) and one per entry point and key. */
export interface TypeExample { value: Record<string, unknown>; fingerprint?: string; stale?: boolean }
export interface EntryExample { node: string; key: string; request: unknown; response?: unknown; fingerprint?: string; stale?: boolean }
export interface Examples { types: Record<string, TypeExample>; entries: EntryExample[] }

export interface Cell { region: string; col: number; row: number }
export interface Group { id: string; label: string; members: string[]; kind: "data" | "family" | "range" }
export interface Floor {
  strategy: "main-bus" | "city-grid" | "bands" | "layered" | "shelves";
  items: Record<string, Cell>;
  lanes?: { id: string; row: number }[];
  groups?: Group[];
  utilities?: string[];
  hubs?: string[];
}

export interface Problem { text: string; nodes?: string[]; removed?: string[]; source?: string }

export interface CodeMap {
  meta: { schema_version: number; repo: string; root?: string | null; commit: string; scanned_at: string; languages: string[] };
  nodes: MapNode[];
  relations: Relation[];
  files?: Record<string, FileInfo>;
  pins?: Pin[];            // optional: maps made before the traces format have none
  unpinned?: string[];
  examples?: Examples;
  problems: Problem[];
  layout: { version: number; containers: Record<string, Floor> };
}
