# code-map format

`code-map.json` = `meta` + `nodes` + `relations` + `pins` + `unpinned` +
`examples` + `files` + `problems` + `layout`. The JSON Schema is `scripts/schema/code-map.schema.json`;
`scripts/validate.py` also checks the rules a schema cannot express.
You write only `meaning.json`; `assemble.py` combines it with the structure pass.

## meta

`schema_version` (3: version 2 maps had `flows` and no pins or examples;
`diff.py` rescans them in full, and the viewer still opens them),
`scanner_version`, `repo` (the scanned folder's name), `root` (optional: the
scanned folder's path from the git top level, e.g. `demo/parking-city`; null at the top
level; every other path in the map is relative to that folder), `commit` (the one scanned
commit, 40 hex), `scanned_at`, `rules_version` (optional integer: the meaning rules the map was made under; absent = 1), `stack` (optional: sha256 of the parsed content of the `OUT/stack.yaml` the map was made with, as canonical JSON, so comments and spacing do not count; absent without one; `diff.py` runs `full` when it differs from the current file), `languages`, `domain_context` (path or null).

## Nodes and floors

| kind | floor | parent | written by |
|---|---|---|---|
| `service` | 0 | — | you |
| `library` | 0 | — | you (or defaulted for an unclaimed module) |
| `datastore` | 0 | — | you |
| `external` | 0 | — | you |
| `topic` | 0 | — | you |
| `table` | 1 | datastore | you |
| `in-process-queue` | 1 | service | you |
| `package` | 1 | service or library | scanner |
| `class` | 2 | package, class, or file (Python classes live in their module file) | scanner |
| `file` | 2 | package | scanner |
| `method` | 3 | class or file | scanner |

Fields: `id`, `kind`, `parent`, `name`, plus `lang`, `file`, `line`,
`visibility` (`public`/`private`), `metrics`, `signature`
(`{params: [{name, type, refs, optional}], returns, returns_refs}`; `refs` and `returns_refs` only where a type names a
repo class; `optional: true` on a parameter a call may leave out, recorded for Python and Scala) on methods, `fields`
on a class that declares fields, `ctor` on a class (all three: § Fields and type links), `modules` on services
and libraries (`defaulted: true` marks a library `assemble.py` created for an
unclaimed module), `implements` on a class (scanner: the class or trait ids it extends or, for an anonymous
body, implements, when the name resolves; `InvoiceRepo.Live` → `["billing::city.parking.billing.InvoiceRepo"]`;
in Go, every repo interface whose methods it has, by name and arity; `calls` counts a trait method and its
implementations' same-named methods as one target, drawn to the trait method, also when the implementation sits
below a class that does not declare the method; a trace continues from it into each implementation), `twins` on a service that also deploys another service's
module (root package ids; its floor shows them as `twin:<id>` items), `role` on packages (`entry`, `logic`, `outbound`,
`storage`, `model`; `role_why` when overridden), `tags`, `summary`,
`delivery` on topics (`fan-out` or `queue`; absent means `fan-out`) and on in-process queues (required there), `dead_letter_of` on a topic (the
topic whose failures land there), `replicas` on services (integer ≥ 1),
`store` on datastores (`database`, `cache`, `bucket` or `warehouse`;
`assemble.py` defaults it from the engine, so set it only when that is
wrong), `evidence` (required on services: the line that deploys it — compose,
Dockerfile, build, orchestrator registration, or the documented run command;
also required on an in-process queue (the line that creates it), on a topic that sets `delivery` or `dead_letter_of` and on a
datastore whose `store` differs from the engine default: the line that shows
it; optional elsewhere), `stale` (set by `diff.py` on a node whose evidence
line, or the method around it, changed; `assemble.py` refuses the map until
each flag is resolved).

### In-process queues

An `in-process-queue` is a queue, channel or hub that lives in one running service's memory: a ZIO `Queue` or `Hub`,
a Go channel, a Kotlin `Channel`, an `asyncio.Queue`, a Java `BlockingQueue`, a .NET `Channel`, an event bus. It is
lost when the process stops and no other service sees it, so it is never a topic and never on the site floor.
Id: `inq:<service name>:<name>`, the name being what the code calls it (the value, or the type it is injected
by): `inq:billing:receipts`. `parent` is the service that runs it, also when a library creates it (`evidence` then
points at the library line). `delivery` is `queue` (each item goes to one consumer) or `fan-out` (every subscriber
gets it: a hub, a broadcast channel, an event bus).

### Fields and type links

Written by the scanner; nothing in `meaning.json` sets them.

`fields: [{name, type, visibility}]` on a class that declares fields, in declared order. `type` is the declared type
text, or `null` where the language declares none. `visibility` (`public`/`private`, as on methods) is recorded where
the language says it by modifiers (Java, C#, Kotlin, Scala, PHP): `private` or `protected` make a field private, and
so does no access modifier at all in C# (outside an interface); a record's components are public. A class with no
declared fields has no `fields` key. A name quoted in the source loses its quotes (Scala and Kotlin backticks; PHP's
`$`).

| Language | Fields |
|---|---|
| Scala | a case class's parameters (its first parameter list) |
| Python | class-level annotated attributes (dataclass, pydantic, TypedDict, NamedTuple, SQLModel); not `ClassVar[...]` |
| Java | record components; non-static fields |
| Kotlin | `val`/`var` primary-constructor parameters; class properties |
| TypeScript | interface members; members of an object type alias (`type Quote = {…}` is a class node, `type Id = string` is not); class properties and constructor parameter properties, not static, not bound functions |
| JavaScript | class fields, not static, not bound functions (`type` is `null`) |
| Go | struct fields; an embedded field is named by its type |
| C# | positional record parameters; non-static properties |
| Rust | struct fields; a tuple struct's are `0`, `1`, … |
| PHP | typed non-static properties; promoted constructor parameters |
| Ruby | none: Ruby declares no fields |
| Protocol Buffers | a message's fields, `oneof` members included; `type` as written (`repeated Line`, `map<string,int32>`) |

A `.proto` file inside a module gives each of its messages a class node with `lang: proto`, id
`<module path>::<proto package>.<Message>` (no package: `_root_`), in that package; a nested message is
`<Outer>.<Inner>`, its parent the outer message. A message is left out when the module already has a class of its
name (generated code), and so are the messages nested in it. A `.proto` in no module gives protocol keys only. A
generated file (SKILL.md, step 1) keeps only its public classes with fields, the methods its routes name as
handlers, and what contains them. A kept class keeps its public fields only: by their `visibility`, or where a
language makes a field public by its name (Go upper case, Python no leading underscore); a class left with none is no
data type (a `.proto` message of its name then stands in). A class that is not generated keeps every field.

`refs` on a signature parameter and `returns_refs` on a signature: the class ids the type text names, each once, in
the order the names appear. Every name in the type text is tried, so `List[Reservation]`, `Future<Charge>` and
`Map[BayId, Status]` give their repo classes and skip library types; string literals are not (`'a' | 'b'`,
`Literal["x"]`), except a Python forward reference (`"Date"`, `List["Date"]`). A qualified name (`http.Request`,
`java.time.Instant`, `crate::models::Charge`) resolves only to a class in the package or file an import names by its
first part or by its local name (`from pkg import nodes` for `nodes.Item`, a Go import path for `store.Duration`,
`import * as models`, `import a.b as m`, Go `st "path"`), else to the class whose
qualified name it is; its last part alone never resolves, and its other parts are no names. A bare name resolves, in
order, to: a class in the same file; a class an import names (an explicit import, Scala braces included, a wildcard
or namespace import, a Go
import path, the file a relative import names, which Python resolves against the importing file's folder); a class in
the same package; a class whose name is unique among the languages that can name each other's classes (Java, Kotlin
and Scala; TypeScript and JavaScript; any other language alone). A level with one match resolves the name; a level
with several leaves it unresolved; a level with none passes to the next. Two stops: a name the file declares as a type
that is no class (a type alias such as `type Kind = "a" | "b"`, `typealias`, C# `using X = A.B;`; a Python
module-level `X = Tuple[...]` or `TypeVar`) never resolves there; a name an import names explicitly that finds no
class there stays unresolved when the import is from outside the repo (not relative, not under a repo package, module
name, tsconfig path alias or workspace package) or the imported file declares it as such a type (`from fastapi import
Request` and Scala `import java.time.{Instant}` never link the repo's `Request` or `Instant`). A type parameter the
method or a declaration around it declares (`<TEvent>`, `[T any]`, `impl<T>`, a class's `[A]`, a Go receiver's
`Bus[TEvent]`) never resolves, nor does any single-letter name (`T`). A qualified name whose first part is a library
the file imports (Go `log.Logger`, Python `logging.Logger`) never links a repo class in a folder of the same name; a
Python standard-library module is a library unless the repo has a top-level package or module of that name. Scala objects and anonymous
implementations are never targets. An unresolved name stays only in the type text.

`ctor`: the class's constructor or factory, what builds it, so a reader sees what the class needs. `{method}` names the
method that does: Python `__init__`, Ruby `initialize`, PHP `__construct`, TypeScript and JavaScript `constructor`,
Java and C# a method named as the class (not a C# `static` constructor), Rust `new` (whatever it returns), and Go a
top-level `New…` function in the type's folder whose return type names it unqualified (`*Store`, `(*Store, error)`;
not `[]*Store`, `map[string]*Store` or another package's `http.Handler`), unless the type is an interface a class
implements. With several, it is the one with the most parameters (the first by line on a tie) and `of` counts them.
Scala class parameters (not a case class's), a Kotlin primary constructor (not a `data`, `value`, `enum` or
`annotation` class's) and a C# primary constructor of a class or struct (`class Orders(IRepo repo)`) are no method:
`{params, line}` holds them, each parameter as on a signature, `refs` included. A C# primary constructor counts with the
class's explicit constructors: the one with the most parameters wins, and `of` counts them all. A Java or C# record and
a Java enum have none, whatever constructors they declare. A Kotlin secondary constructor is not read.
A class with none of these has no `ctor` key.

Fingerprints of data types and entry points are computed from `fields` and signatures by
`scripts/vizcode/fingerprint.py` (a class's fields; a handler's signature plus the fields of the classes in its
`refs` and `returns_refs`, one level); they are never stored on nodes.

### Ids

Ids are qualified names, never line numbers, so they survive edits; comments
in the viewer attach to them. Even a synthetic name (`$impl<n>`) counts
declarations within its owner, never lines.

| Node | Id |
|---|---|
| package | `<module path>::<package>/` — `order::com.acme.order.repo/` |
| Python file | `<module path>::<dotted module>` — `worker::worker.main` |
| Scala file with top-level defs | `<package id><File>.scala` |
| class | `<module path>::<package>.<Class>`; Scala objects end in `$` |
| method | `<owner id>#<name>/<arity>`; a repeated id gets `~2`, `~3` |
| Scala `val` holding behaviour (an effect, layer, stream or function; constants are skipped) | a method of arity 0 — `billing::city.parking.billing.Main$#run/0` |
| Scala anonymous implementation (`new T { … }`) | a class `<module path>::<package>.<Owner>.<val>$impl` — `billing::city.parking.billing.DeadLetters.live$impl`, its defs `…live$impl#park/3`; not assigned to a val: `<Owner>.$impl<n>`, `n` counting from 1 in source order within that owner (less stable than a val-named id: adding an earlier unnamed body renumbers it). Two bodies in one val get `~2` like any repeated id |
| Python function nested in an Airflow `@dag` function (or defined in a module-level `with DAG(...)` block) | a method of the file, like a top-level function — `jobs/dags::dags.bq_bay_events_export#export_snapshot/0`; when the name is also a top-level function of the file or a task of another DAG in it: `<file id>#<dag function>.<name>/<arity>` — `…#etl.extract/0`, or for a `with DAG(...)` block `<file id>#<dag_id>.<name>/<arity>` — `…#legacy.helper/1`, where the prefix is the dag id only when it is a plain string literal, else the `with … as <alias>` name, else `DAG<n>` (the block's place among the file's `with DAG` blocks, from 1). `calls` reaches a qualified task only from inside its own DAG |
| Function nested in another that a route names or decorates (any language but Scala) | a method of the outer function's owner, `<owner>#<outer>.<name>/<arity>` — `.::src/server.js#serve.listOrders/2`; the calls and strings inside it are its own, not the outer function's. Other nested functions are not nodes |
| service / library | `svc:<name>` / `lib:<name>` |
| datastore / table | `db:<engine>:<config key>` / `<datastore id>/<schema.table>` |
| external | `ext:http:<config key or host>`, `3p:<vendor>` |
| topic | `topic:<broker>:<name>` |

## Relations

| Field | Meaning |
|---|---|
| `id` | optional in `meaning.json`; `assemble.py` fills `r:<kind>:<from>-><to>:<key>`. |
| `kind` | `request`, `event`, `stream`, `batch`, `db-read`, `db-write`, `ext-call`, `hand-off` (a method to an in-process queue it puts items on, or the queue to the method that takes them; both ends in the queue's service); `uses-code` and `calls` (method to method, resolved by name; ambiguous ones `inferred`) come from the scanner |
| `data` | which way data moves: `forward`, `back` or `both`; defaulted per kind (db-read `back`, the rest `forward`), required on `stream`; a call's reply does not count, so a `request` or `ext-call` stays `forward` |
| `from`, `to` | the finest node known: method, else class, else service |
| `key` | protocol key: `POST /v1/orders/create`, `table public.orders`, topic name (on a job queue's topic, `job <name>`: one key per job), `grpc <package>.<Service>/<Rpc>` (`grpc parking.occupancy.v1.OccupancyFeed/Stream`; `grpc <Service>/<Rpc>` when the .proto has no package) |
| `confidence` | `confirmed` or `inferred` (needs `why`) |
| `deployment_dependent` | target is set per deployment |
| `bidirectional` | streams that flow both ways |
| `via` | library method that makes the call when `from` is the service running it; runtime relations never start inside a library |
| `tables` | concrete tables behind a wildcard key (`table th.*`), as found in configs; only with a wildcard key |
| `subscription` | `push` (push endpoint, SNS to HTTP) or `pull` (a Pub/Sub pull subscription); leave it out for Kafka, SQS and RabbitMQ consumers, where absent means the broker's normal consume; only on an `event` from a topic |
| `group` | consumer group or subscription name; only on an `event` from a topic |
| `on_failure` | `true` on an `event` to a topic that is published only when processing fails (dead-letter or retry); only on an `event` to a topic |
| `schedule` | array on a `batch`: 5- or 6-field cron, `manual`, or `on <event>` |
| `job` | DAG or task name of a `batch` |
| `stale` | set by `diff.py` on facts a rescan must re-resolve: a cited line or the method around it changed, an end or `via` node is gone or in another file, or the route the `key` names changed; `assemble.py` refuses the map while any remain |
| `evidence` | at least one `{file, line}`; rescans use it to find stale facts, and move it with its line when lines above it change or the file is renamed |

## Pins

```
pins: [{id, title, start, direction, by}]
unpinned: [<pin id>]
```

Pinned traces: the traces the viewer lists to start from (it computes each
trace from the relations; SKILL.md § Pinned traces). `id`: the slug of
the title (`a-z`, `0-9`, single `-`; a repeat gets `-2`, `-3`), unique. `start`: a
node id of any kind the viewer traces from: method, table, topic, in-process-queue, external,
datastore, service, library, package, file or class (a container starts from
the entry points inside it, else from its boundary methods — methods inside it
at one end of a relation whose other end is outside it — else from itself;
`examples.seeds`, the viewer's `seedsFor`). `direction`:
`downstream`, `upstream` or `both`. `by`: `agent` or `user`. `unpinned`:
agent pin ids the user removed; no pin may take one. `assemble.py` refuses a
pin with a missing field, a bad `direction` or `by`, an id that is not
its title's slug, a duplicate id, or an id in `unpinned`. A `start` that is in the map with
any other kind is refused (the error names the pin and the kind). A `start`
missing from the map is not refused: the audit lists it (`pin.start-missing`). `diff.py` carries
both keys over unchanged.

The viewer's pin changes reach the agent as a `## Pins` section of
`export-comment.md`, absent when there are none: pin lines first, then unpin
lines, one per line, a `|` in a title replaced by `/`:

```
## Pins
- pin: <title> | start: <node id> | direction: <downstream|upstream|both>
- unpin: <pin id>
```

## Examples

```
examples: {
  types:   {"<class id>": {value, fingerprint}},
  entries: [{node, key, request, response, fingerprint}]
}
```

Made-up values, shown labelled `example values, not computed` (SKILL.md §
Examples).

- `types`: keyed by the id of a class with `fields`; `value` is an object
  whose keys are field names (fields may be left out):
  `"orders::orders.models.Order": {"value": {"id": "ord-42", "total": 19.9}}`.
- `entries`: `node` is an entry point's handler method (the handler of a
  route in `files`, or the method a `request`, `event`, `stream` or `batch`
  relation ends at); `key` the route or the topic, stream or job name;
  `request` the payload in (any JSON); `response` what a route returns (left
  out for events, streams and jobs).
- `fingerprint`: stamped by `assemble.py`, overwriting any written: for a
  type, a digest of the class's fields in order (name and type text); for an
  entry, of the handler's signature text plus the type fingerprint of each
  class in its `refs` and `returns_refs` (`scripts/vizcode/fingerprint.py`).
- `stale`: set by `diff.py` when the stored fingerprint differs from the one
  recomputed against the new structure, or the class or handler is gone;
  `assemble.py` refuses the map while any remains.
- `assemble.py` refuses a `types` key that is not a class with fields, a
  `value` key that is not one of its field names, an entry whose `node` is
  not a method, and two entries with the same node and key.

## Files

`files` maps each scanned path to `{lang, module, node, parse_error}` and,
for a file with routes, `routes: [{method, path, handler, line}]`: the route
facts of `structure.json` whose handler is a node id (a method, an inline handler's own node named after
its route, or the file for a top-level inline handler and Rails routes), paths as written in code with the prefixes of the mounts the scanner joins
(`mounts` facts with `composed`), no other mount prefix.

## Layout

`layout.containers` holds one floor per container: `site` (the whole system),
every service, library, datastore, package, class and file, and every group.
`assemble.py` writes it; items keep their cells across scans unless it runs
with `--relayout`. Cells are integers; the viewer turns them into pixels.

Each floor: `strategy`, `items` (`{id: {region, col, row}}`), `lanes`,
`groups`, `utilities`, `hubs`.

| Strategy | Used for | Regions |
|---|---|---|
| `main-bus` | `site` with ≤ 20 services | `line`, `bus`, `lane`, `bay`, `shelf` |
| `city-grid` | `site` with > 20 services | `grid`, `shelf` |
| `bands` | a service or library | `line`, `bus`, `lane`, `shelf`, `hubs` |
| `layered` | a package, class, file or group | `line`, `lane`, `hubs` |
| `shelves` | a datastore | `shelf` |

- **Axes.** `line` and `bus` share one column axis (data flows left to right;
  the datastore warehouses sit after the last line column). `shelf`, `bay` and
  `hubs` each have their own column axis and one row (the viewer wraps a row
  more than twice as wide as the Fit canvas, and a service's airfield to its
  work area's width). `grid` uses both axes as plots. Rows in `line` count down from the top of the line; rows in
  `bus` are lane rows.
- **Regions.** `line`: the production line (sources at column 0, sinks last;
  on a `bands` floor entry packages in column 0, outbound last). `bus`: on
  `site`, datastores and topic hubs on their lane; on a `bands` floor, storage
  packages. `bay`: read-only services (dashboards). `shelf`: libraries on
  `site`, data-class packages on `bands`, tables on `shelves`. `lane`: a busy
  item (3+ callers) lifted onto its own lane, listed in `lanes` after any
  database lanes; the layout does it only when its estimated line crossings
  drop by at least 2 and a quarter (at most 2 per floor, kept on rescans). A
  service's floor also holds `twin:<package id>` items for modules it shares
  with another service (see `twins`). `hubs`:
  heavily shared items (fan-in ≥ 8); the viewer keeps every line into and out
  of each such item out of the base (batch rails excepted: they stay in the
  base with their yard) and shows them in that item's extra layer, named by
  its map code (the layers button); the item wears `used by N` (its callers).
- **`lanes`** and **`strategy`** are the scanner's layout memory: they keep
  positions stable across rescans, and the viewer does not use them.
- **`lanes`**: `[{id, row}]`. On `site`, one per datastore or message broker
  (a broker lane's id is `broker:<name>` and is not a node; its topics sit on
  it). On any floor, also one per busy item lifted onto its own lane (region
  `lane`, see above); its row is kept across rescans.
- **`utilities`** (`site` only): externals called by three or more services
  and nothing else. They have no cell: draw them as badges on their callers.
- **`groups`**: `[{id, label, members, kind}]` with `kind` `data`, `family`
  or `range`. A group is an item on its floor, its members are not, and the
  group is itself a container whose floor is laid out (and condensed) the
  same way.
- **Invariants** checked by `validate.py`: every item is a node or group, no
  two items share a cell, and every child of a container is placed on its
  floor, inside one of its groups, or (on `site`) listed as a utility.

## meaning.json

Everything you write. `summaries` maps structure node ids to one-line
descriptions (optional); `roles` overrides package roles (optional). Complete example for a small repo with a Scala
`shop` service, a Python `worker` service and shared code:

```json
{
  "domain_context": null,
  "nodes": [
    {
      "id": "svc:shop",
      "kind": "service",
      "name": "shop",
      "modules": [
        "shop"
      ],
      "evidence": [
        {
          "file": "docker-compose.yml",
          "line": 2
        }
      ]
    },
    {
      "id": "svc:worker",
      "kind": "service",
      "name": "worker",
      "modules": [
        "worker"
      ],
      "replicas": 3,
      "evidence": [
        {
          "file": "docker-compose.yml",
          "line": 3
        }
      ]
    },
    {
      "id": "lib:common",
      "kind": "library",
      "name": "common",
      "modules": [
        "common",
        "pylib",
        "scripts"
      ]
    },
    {
      "id": "topic:pubsub:orders",
      "kind": "topic",
      "name": "orders",
      "delivery": "fan-out",
      "evidence": [{"file": "deploy/pubsub.yaml", "line": 3}]
    },
    {
      "id": "topic:pubsub:orders-dlq",
      "kind": "topic",
      "name": "orders-dlq",
      "delivery": "fan-out",
      "dead_letter_of": "topic:pubsub:orders",
      "evidence": [{"file": "deploy/pubsub.yaml", "line": 12}]
    },
    {
      "id": "db:redis:CACHE_HOST",
      "kind": "datastore",
      "name": "redis",
      "store": "database",
      "evidence": [{"file": "worker/main.py", "line": 9}]
    },
    {
      "id": "db:postgres:DB_HOST",
      "kind": "datastore",
      "name": "postgres"
    },
    {
      "id": "db:postgres:DB_HOST/public.orders",
      "kind": "table",
      "parent": "db:postgres:DB_HOST",
      "name": "public.orders"
    }
  ],
  "relations": [
    {
      "kind": "request",
      "from": "svc:worker",
      "to": "shop::io.demo.shop.api.OrderApi$#createEndpoint/0",
      "key": "POST /v1/orders/create",
      "confidence": "inferred",
      "why": "worker posts to SHOP_URL; compose names the shop service but the URL is set per deployment",
      "deployment_dependent": true,
      "evidence": [
        {
          "file": "worker/main.py",
          "line": 13
        },
        {
          "file": "shop/src/main/scala/io/demo/shop/api/OrderApi.scala",
          "line": 4
        }
      ]
    },
    {
      "kind": "request",
      "from": "svc:worker",
      "to": "shop::io.demo.shop.api.OrderApi$#getEndpoint/0",
      "key": "GET /v1/orders/{id}",
      "confidence": "confirmed",
      "via": "pylib::pylib.client#call/0",
      "evidence": [
        {
          "file": "pylib/client.py",
          "line": 4
        },
        {
          "file": "shop/src/main/scala/io/demo/shop/api/OrderApi.scala",
          "line": 10
        }
      ]
    },
    {
      "kind": "db-write",
      "from": "shop::io.demo.shop.repo.PgOrderRepo#save/2",
      "to": "db:postgres:DB_HOST/public.orders",
      "key": "table public.orders",
      "confidence": "confirmed",
      "evidence": [
        {
          "file": "shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala",
          "line": 11
        }
      ]
    },
    {
      "kind": "event",
      "from": "worker::worker.main#run/2",
      "to": "topic:pubsub:orders",
      "key": "orders",
      "confidence": "confirmed",
      "evidence": [{"file": "worker/main.py", "line": 20}]
    },
    {
      "kind": "event",
      "from": "topic:pubsub:orders",
      "to": "shop::io.demo.shop.repo.PgOrderRepo#save/2",
      "key": "orders",
      "confidence": "confirmed",
      "subscription": "pull",
      "group": "shop-orders",
      "evidence": [{"file": "shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala", "line": 11}]
    },
    {
      "kind": "event",
      "from": "worker::worker.main#run/2",
      "to": "topic:pubsub:orders-dlq",
      "key": "orders-dlq",
      "confidence": "confirmed",
      "on_failure": true,
      "evidence": [{"file": "worker/main.py", "line": 24}]
    },
    {
      "kind": "batch",
      "from": "svc:worker",
      "to": "worker::worker.main#run/2",
      "key": "task run",
      "confidence": "confirmed",
      "schedule": ["0 2 * * *", "manual"],
      "job": "nightly_run",
      "evidence": [{"file": "worker/main.py", "line": 30}]
    }
  ],
  "pins": [
    {
      "id": "worker-job-creates-an-order",
      "title": "worker job creates an order",
      "start": "worker::worker.main#run/2",
      "direction": "downstream",
      "by": "agent"
    }
  ],
  "unpinned": [],
  "examples": {
    "types": {},
    "entries": [
      {
        "node": "worker::worker.main#run/2",
        "key": "task run",
        "request": {"job_id": "job-42"}
      },
      {
        "node": "shop::io.demo.shop.api.OrderApi$#createEndpoint/0",
        "key": "POST /v1/orders/create",
        "request": {"job": "job-42"},
        "response": {"id": "ord-42", "total": "19.90"}
      },
      {
        "node": "shop::io.demo.shop.api.OrderApi$#getEndpoint/0",
        "key": "GET /v1/orders/{id}",
        "request": {},
        "response": {"id": "ord-42", "total": "19.90"}
      },
      {
        "node": "shop::io.demo.shop.repo.PgOrderRepo#save/2",
        "key": "orders",
        "request": {"id": "ord-42", "total": "19.90"}
      }
    ]
  },
  "problems": [
    {
      "text": "SHOP_URL value is per deployment",
      "nodes": [
        "svc:worker"
      ],
      "source": "agent"
    }
  ],
  "summaries": {
    "worker::worker.main#run/2": "Runs a job by asking shop to create an order."
  }
}
```

## Working files in the output directory

| File | Committed | Written by |
|---|---|---|
| `code-map.json` | yes | `assemble.py` |
| `stack.yaml` | yes | you (see Stack below); the user may edit it |
| `README.md` | yes | `assemble.py`, rewritten each run: what each file here is for |
| `structure.json`, `summary.md` | no | `extract.py` |
| `meaning.json` | no | you; `diff.py` on incremental scans (all facts, stale ones flagged); `diff.py` also flags stale examples |
| `meaning.previous.json` | no | `diff.py` on full rescans: the previous map's facts in `meaning.json`'s shape, suspect ones flagged `stale` as on incremental scans; removed by `diff.py` on none/incremental runs and by `assemble.py` on exit 0 |
| `stale.json` | no | `diff.py`: `mode`, `reason` (why a rescan is full), `changed` files, the flagged `stale_relations`, `stale_nodes` and `stale_examples` (each with `why`), `why` (fact id → what it depends on that changed), `removed_nodes`, `moved_evidence` (evidence lines moved to their new place); on a full rescan, `previous_meaning` names the file above |
| `code-map.invalid.json` | no | `assemble.py` when validation fails |
| `index.html` | no | `assemble.py` (or `view.py` alone): the viewer with the map built in, minified and ASCII-escaped, so not byte-equal to `code-map.json` |
| `export-comment.md` | no | the viewer: review comments and pin changes (`## Pins`) for the agent |
| `map-notes.md` | yes | the user: standing notes on the map and acceptances (see Audit); read on every run, never edited by the agent |
| `audit.md` | no | `audit.py` (run by `assemble.py` on exit 0 and by `diff.py` on `none`): map limits, accepted, content warnings, findings |

## Modules

`structure.json` `modules`: `{id, path, lang, build}`, one per language per
folder. `id` is `mod:<path>`; a second language in the same folder gets
`mod:<path>#<lang>` (a Python one `#py`), and `meaning.json` `modules` claims
it as `<path>#<lang>`. `build` is where the module came from:

| `build` | Module folder |
|---|---|
| `sbt` | a project in `build.sbt` |
| `python-package` / `python-scripts` | the top folder of an `__init__.py` package / a folder of loose scripts |
| `maven` | `pom.xml` (and its `<modules>`) |
| `gradle` | `settings.gradle(.kts)` (and its `include`s) |
| `npm` | `package.json` (and its `workspaces`; `pnpm-workspace.yaml` `packages`) |
| `go` | `go.mod`, one module per file |
| `cargo` | `Cargo.toml` (and its `[workspace] members`) |
| `dotnet` | a `*.csproj`, one module per file |
| `bundler` | `Gemfile`, one per file |
| `composer` | `composer.json`, one per file |
| `dir` | none found: the file's top folder |

A file belongs to the nearest folder above it with a build file of its
language's ecosystem (`scripts/vizcode/packs/modules.yaml`). The next
`diff.py` run is `full` when a build file is added, removed or renamed, when
the set of modules changes ("modules changed"), and when a language the map's
`meta.languages` lacks is scanned ("new languages scanned"); an edit inside a
build file that leaves the modules as they were (a dependency bump) is not.

## Stack

`OUT/stack.yaml` adds libraries, route styles and table patterns to the
built-in packs (`scripts/vizcode/packs/<lang>.yaml`, same format): per
language (`python`, `scala`, `java`, `kotlin`, `csharp`, `typescript`,
`javascript`, `go`, `rust`, `ruby`, `php`) the groups `imports`
(`{prefix, kind}`), `routes`, `effects` (Scala type names; Scala only),
`ignore` (prefixes), `tables` (`name`, `regex` with a `table` group,
optional `when`) and `queues` (`name`, `regex`, `delivery` `queue` or `fan-out`, optional `when`: in-process queue
creation sites); and at the top level `exclude`, a list of path globs every scan leaves out (`extract.py --exclude`
adds to it), and `base_paths`, folder → path prefix (`account-service: /accounts`): a path only config or a proxy
sets (a servlet context path, a URI version), joined onto every route of the longest folder holding the route's
file. A route entry is one of:

- `form: regex` (the default): `name`, `regex` (with a `path` group, empty as `(?P<path>)` for a route on its
  mount's own path such as actix `resource("/x").route(get().to(h))`, optional
  `method`, `methods` and `handler` groups), `path` reader `literal` (the
  default) or `segments`, optional `when` and `method`; with `mount: true` the regex has
  a `path` and an optional `target` group, and its matches are mounts. Optional `expand`
  (action → `METHOD` or `METHOD /suffix`, or a list of them): a match gives one route per
  item of each action that its optional `only` / `except` groups keep (the words in them); an
  optional `param` group renames the suffixes' `:id`. Optional `handler_class` and
  `handler_method` (both or neither): templates of `{group}`, `{group|camel}` and, with `expand`,
  `{action}` fields naming the handler's class and method by convention, unused when an optional
  `nohandler` group matched (`references/stack.md`).
- `form: annotated` (not for Python or Scala): `name`, `verbs` (annotation
  name → HTTP method, or `from-method-arg`), optional `when`, `prefix`,
  `path_args` (default `[value, path, 0]`), `method_arg` (default `method`),
  `method_path`, `token` (path token → `class-stem` or `method-name`),
  `absolute` (path starts that drop the class prefix) and `skip_class` (class
  annotations marking an HTTP client: such a class gives no routes).

A `stack.yaml` route, table or queue entry named like a pack entry of its language
replaces it; any other repeated name is an error. It is data only;
`extract.py` reads it and rejects invalid content with exit 2. Rules, the
full format and when to write it: `references/stack.md` (when: SKILL.md § Stack). `structure.json` holds
the `stack` block (`digest`, `unrecognised`, `servers_without_routes`,
`patterns`, `overrides`) that `summary.md`'s Stack section prints. Each
`patterns` entry: `group` (`routes`, `tables` or `queues`), `lang`, `name`, `source`
(`pack`, `stack.yaml` or `built in`), `matches`, `files`, `first_file`, and
when they apply `form: annotated`, `mount: true`, and `duplicates` (the
pattern whose facts this one's matches repeated: every match was already
another pattern's). `overrides` entries are `{lang, prefix, pack_kind, kind}`
(a kind changed) or `{lang, group, name}` (a pack entry replaced).

A file's `routes` facts are `[{method, path, handler, line, framework,
source}]` (`framework` is the pattern's name; `method` upper-cased; a handler outside any method is the
file node, made for a generic-walker file that has none); its `mounts` facts (key
present on files with a mount) are `[{path, target, line, framework,
source, composed}]`, `target` the matched name or null, `composed` (present when above 0) the number of the
file's routes whose path the scanner prefixed with it (`references/stack.md`). Two patterns giving the same
route (method, path, handler) or table (table, line, in) give one fact,
named after the pattern listed first (packs before `stack.yaml`).

A file a queue pattern matched carries a `queues` fact (the key is absent when nothing matched): `[{line, in,
delivery, pattern, source}]`, `in` the innermost method around the match, else the file; `summary.md` lists them
per module as `in-process queues`. Two patterns matching at one (line, in) give one fact.

A file a table pattern matched carries a `tables` fact in `structure.json`
(the key is absent when nothing matched): `[{table, line, in, kind, pattern,
source}]`, `in` the enclosing method id (`kind: access`), else the enclosing
class id (`kind: defined`: an ORM mapping; in a generic-walker language one class defines one table, so when
patterns name different tables on it the pattern listed first keeps its facts: JPA `@Table(name)` over
`@Entity(name)`), else the file id (`access`);
`source` is `pack` or `stack.yaml`. `summary.md` prints them per module as
`- **tables (patterns):** orders (repo/OrderRepo.java:12 defined on Order)`.

Packs per language. Each also has an `ignore` list: the standard library and
the wiring of the frameworks it covers (dependency injection, config,
annotations), whose IO parts are `imports` entries instead. When several
`imports` prefixes name one import, the longest wins
(`jakarta.ws.rs.client` is `http-out` inside `jakarta.ws.rs`, `http-in`).

| Pack | Routes | Tables | Library kinds (`imports`) | `ignore` |
|---|---|---|---|---|
| `python.yaml` | FastAPI (code rule) | SQLAlchemy and Flask-SQLAlchemy `__tablename__`, SQLModel, Django `db_table` | DB drivers, SQLAlchemy, BigQuery, Mongo, Redis, Kafka, RabbitMQ, Pub/Sub, HTTP clients, FastAPI/Flask (`http-in`), aiohttp (`http`), websockets, gRPC, boto3, GCS, PySpark | Airflow and Flyte (read by code rules); the standard library is ignored in code |
| `scala.yaml` | tapir (code rule), zio-http | Quill `query[T]`, `querySchema[T]("t")` | Quill, doobie, Skunk, Slick, ScalikeJDBC, zio-jdbc, sttp, tapir, zio-http, Kafka, Redis, gRPC, AWS, Spark; `effects`: ZIO types | `scala`, `java`, `javax`, `zio` |
| `java.yaml`, `kotlin.yaml` | Spring MVC/WebFlux, JAX-RS (jakarta and javax), Micronaut (annotated; Feign, `@HttpExchange`, `@RegisterRestClient`, Micronaut `@Client` interfaces skipped); Kotlin also Ktor (regex, `route("/x")` mounts) | JPA `@Table(name)`, `@Entity(name)` (jakarta and javax); Kotlin also Exposed `object X : Table("x")`, `object Xs : Table()` (`Xs`) | JDBC, Spring JDBC/Data/JPA/R2DBC, Hibernate, jOOQ, MyBatis, Exposed, Micronaut Data, Quarkus ORM, BigQuery; Mongo, Spring Data Mongo/Cassandra/Elasticsearch; Kafka, Spring Kafka/AMQP/JMS/Cloud Stream, RabbitMQ, Pub/Sub, MicroProfile messaging; Jedis, Lettuce, Redisson, Spring Data Redis; OkHttp, RestTemplate, WebClient, Retrofit, `java.net.http`, OpenFeign, JAX-RS/Micronaut/Quarkus/MicroProfile clients, Ktor client; Spring WebSocket; JMS; Ktor routing (`http-in`), websockets; AWS, GCS; gRPC | the standard library (`java`, `javax`, `jdk`; Kotlin `kotlin`), `org.springframework`, `io.micronaut`, `io.quarkus`, Jakarta EE wiring (`jakarta.inject`, `jakarta.enterprise`, `jakarta.validation`, …), `org.eclipse.microprofile`; Kotlin also `io.ktor` |
| `typescript.yaml`, `javascript.yaml` | NestJS (annotated; `setGlobalPrefix` a mount), Express (`app.use` a mount), Koa router (`use`/`prefix` mounts), Fastify (`register` prefix a mount) | TypeORM `@Entity`, Prisma `prisma.<model>`, Sequelize `define` / `tableName`, sequelize-typescript | pg, mysql2, Prisma, TypeORM, Sequelize, Knex, Drizzle, Mongo, Mongoose; kafkajs, amqplib, BullMQ, NestJS microservices, Pub/Sub; ioredis, redis; axios, node-fetch, got, undici; Express, Koa, Fastify, `@nestjs/core` (`http-in`); NestJS websockets; AWS SDK v3, `@google-cloud`; gRPC | Node built-ins (`node:`, `fs`, `path`, …), `@nestjs` |
| `go.yaml` | `net/http` `HandleFunc`/`Handle`, Gin, Echo, Chi (groups and `Route`/`Mount` are mounts) | gorm `TableName()` | `database/sql`, pgx, lib/pq, gorm, sqlx, BigQuery; Mongo; sarama, kafka-go, amqp091, Pub/Sub; go-redis; resty; `net/http` (`http`), Gin/Echo/Chi (`http-in`); AWS, GCP; gRPC | none: the standard library (paths without a host) is ignored in code |
| `csharp.yaml` | ASP.NET controllers (annotated, `[controller]` token, `~/` absolute), minimal APIs `app.MapGet`, `MapGroup` mounts | EF `[Table("x")]`, `ToTable("x")` | EF Core, Dapper, Npgsql, SqlClient, BigQuery; MongoDB.Driver; Confluent.Kafka, RabbitMQ.Client, Pub/Sub; StackExchange.Redis, Extensions caching; `System.Net.Http`, `Microsoft.Extensions.Http`; ASP.NET MVC/Builder (`http-in`), SignalR; AWS, Azure, GCP; Grpc | `System`, `Microsoft.AspNetCore`, `Microsoft.Extensions` |
| `rust.yaml` | Axum `.route("/x", get(h))`, chained `get(a).put(b)` one route each (`nest` a mount), actix-web attributes and `.route("/x", get().to(h))` (`scope` and `resource` mounts) | none | sqlx, diesel, tokio-postgres; rdkafka, lapin; redis; reqwest; Axum, actix-web (`http-in`); AWS SDKs; tonic | `std`, `core`, `alloc` |
| `ruby.yaml` | Rails `get "/x", to: "c#a"`, `resources`/`resource` (expanded to their actions; handled by the controller action when it is in the repo), Sinatra `get "/x" do` | ActiveRecord `self.table_name = "x"` | ActiveRecord, pg, mysql2; Sidekiq, Kafka, Bunny; redis; Faraday, HTTParty, `net/http`; Sinatra, Rails (`http-in`) | common standard-library requires (`json`, `set`, `time`, …) |
| `php.yaml` | Laravel `Route::get`/`match` (`Route::prefix` a mount; no `use` needed: the global `Route` alias), Symfony `#[Route]` (annotated) | Eloquent `protected $table`, Doctrine `ORM\Table(name)` | PDO, Doctrine DBAL/ORM, Laravel DB; php-amqplib, Enqueue, Laravel Queue, Symfony Messenger, Pub/Sub; Predis, `Redis`, Laravel Redis; Guzzle, Laravel Http, Symfony HttpClient; Laravel/Symfony routing (`http-in`); AWS, GCP; Grpc | `Illuminate`, `Symfony` (PHP's standard library is global, not namespaced) |
| `modules.yaml` | build files per ecosystem (Modules above), not a language pack | | | |

Every pack regex entry runs only on files that import its `when` prefix,
except ten whose files usually import nothing, each with a tight regex:
Rails routes, `resources` and `resource` (`config/routes.rb`), ActiveRecord
`self.table_name`, gorm `TableName()`, ASP.NET minimal APIs and `MapGroup`
(implicit usings), and Laravel `Route::` calls and prefixes (the global
`Route` alias).

## Audit

`audit.py REPO [--out-dir OUT] [--full-audit]` checks the written map, writes `audit.md` and
prints one summary line. It always exits 0. The drawing checks run
`viewer/dist/audit.mjs` on Node 18+; without it they are skipped and the line
says why (`VIZ_AUDIT=0` skips them too). A failed drawing check is a **map
limit**: reported, never fixed, never on the map.

The summary line is one of:

```
Map audit: no limits, no findings, no content warnings
Map limits: 2 (see OUT/audit.md) · findings: 1 cycle · content warnings: 3
Map limits: not checked (Node not found; see OUT/audit.md) · findings: 0 cycles · content warnings: 0
map audit: failed: <first line of the error>
```

with ` · audit errors: N` appended when a content check itself broke, and
` · N floors not checked (audit budget; --full-audit checks every floor)` when floors
were past the budget. `audit.md`
has a header (drawing checks run, failed, accepted, and advisories when any; content warnings; findings;
audit errors when any), then only the sections that have entries: Map limits, Drawing advisories,
Accepted, Stale acceptances, Notes not understood, Audit errors, Content
warnings, Findings, Measured (no threshold yet), Not checked.

| Id | Row | Fails when |
|---|---|---|
| `lines.failed` | 9 | more than 1% of a floor's routes failed, or any route on a floor with fewer than 100 routes |
| `lines.plugged` | 9 | a line end is not plugged into a box side, dock or pad |
| `lines.trunks` | 9 | the trunk rules fail |
| `lines.under` | 2 | an underground run lacks an entrance or exit piece |
| `lines.mid-side` | 13 | a line end sits in a side's outer tile and turns on the tile next to the box, while that side's middle tile is free (a straight run from a corner is allowed by the router's design) |
| `lines.plate-wall` | 30 | a junction plate tile is next to (sharing an edge with) a machine box |
| `lines.lane-drop` | — | a line turns sideways next to a lane (in a gap between lanes, or on the row along a lane's edge) on its way to its lane, over it, where going straight on to the lane is free |
| `lines.gap-stub` | — | a line runs along a gap between lanes where another line passes under it and under a lane in one underground run: that line's stub ends on it |
| `lines.lane-gap` | — | the lines along a gap between lanes take more rows than the gap has rows next to no lane (a gap of two rows has none) |
| `text.cut` | 5 | a name, sub line or signature is cut from the front |
| `text.over-line` | 7, 8, 45 | a zone name, a `used by N` badge or a messaging label overlaps a line tile (the base's and each layer's) or a machine box; a lane's name (at an estimated width) overlaps a line tile or a drone or flight path; a messaging plate is not checked against its own flight |
| `zone.narrow` | 26 | a zone is narrower than its label |
| `pads.corridor` | 32 | a drone pad takes a corridor tile |
| `travel.long` | 25 | a rail train takes over 3 s, or a drone flight over 5 s (guards against a future speed change) |
| `flights.overlap` | — | two flight paths run within 3 px of each other (their dots touch) for a tile or more on open floor (outside every box), after paths into one hub that would run together got their own landing points on its edge: a group larger than the edge holds, sharing points, or paths into different hubs |
| `flights.in-line` | — | an **advisory**, not a map limit: two paths into one hub whose pads are in line with it (one machine straight behind another) still run together on open floor with their landing points spread over the whole edge, as the far pad is too far from the hub for the edge to part them |
| `flights.hidden` | — | an **advisory**, not a map limit: a flight path runs 8 px or more (a dot and its gap) under the face of a box that is neither its machine's nor its hub's (a machine, hub, store or door, a dock, a waiting stack; not the shadow); paths are drawn under the machines, so that stretch is hidden |
| `lost.relation` | 40 | a relation that belongs on the floor is in neither the base nor a layer |
| `floor.wide` | 46 | a floor is more than twice as wide, for its height, as the 1440×900 Fit canvas, and its names do not read at Fit (a row that should wrap) |
| `zone.strip` | 47 | the outside world (6 externals or more) is a strip: its long side holds over twice the items of a near-square grid |

A floor whose plan throws is one `plan.crashed` limit. What an advisory check
(`flights.in-line`, `flights.hidden`) finds is a look that is known and kept
for now: it is listed under Drawing advisories, never counts as a map limit
and leaves the summary line as it is; an acceptance still moves it to
Accepted. The checks run from the
largest floor down within a budget counted in boxes, not time (about 30 s on
the largest maps known), so a map gives the same result on every run and
machine; floors past it are listed by floor code under "Not checked", with the
command that checks them, and do not fail. `--full-audit` (on `audit.py` or
`assemble.py`) checks every floor with no budget and a longer timeout.

- **Measured, never failing:** `crowd.congestion`, `crowd.spacing`,
  `fit.readable` (numbers until real maps give thresholds). Each shows its
  worst 5 floors, then `… N more`: highest congestion, highest spread, least
  room between the fit zoom and the names/codes switch zoom.
- **Content warnings:** `ext.missing` (a config key that looks like an
  outside endpoint names nothing on the map), `external.unused` (an `external` node that no relation starts or
  ends at), `deployable.unscanned` (a deployable folder in `summary.md` § Not scanned, a Dockerfile's or a compose
  service's build context whose source is mostly or wholly unscanned, that no service cites a file inside of or is
  named like the compose service of, and no `problems` entry names), `queue.missing` (an
  `in-process queues` creation site in `summary.md` that no in-process-queue
  cites in `evidence` and no `problems` entry names as `file:line`), `data.two-way-call` (a `request` or `ext-call`
  with `data: both`: a call's reply is not data moving back), `module.empty` (a service or
  library with no file or package under it; a service with runtime relations of its own is one the scanner
  cannot read and does not warn) and `example.missing` (an entry
  point with no example, or with a key that has none; one line each; a
  root route `GET /` under a mount stays a key of its own beside the
  relation's `GET /v1`), `route.file-handler` (routes of a file whose handler is the file: no entry point, so
  no example) and `route.setup-handler` (a method that registers 3 or more routes itself and is the handler of
  some of them), each cleared by a `problems` entry naming the handler id or one of those routes' `file:line`,
  and `pin.few` (fewer pins, counting
  `unpinned`, than 3 or the number of entry points, whichever is fewer) are fixed in `meaning.json`;
  `name.container` (a node named like its parent) is reported, not fixed: a
  scanner or viewer labelling gap; `pin.start-missing` (a pin whose start is
  not in the map) is reported for the user to decide.
- **Findings:** a cycle between services; events through a topic do not count.
  One line per group of services that reach each other: its shortest loop,
  the relations on it, and the group's other services
  (`orders → billing → orders (…) (also in this group: shipping)`).
- **Audit errors** (`audit.error`): a content check crashed. Not a content
  warning and not counted as one; listed in its own section.
- **Acceptances** in `map-notes.md` move a map limit, or a drawing advisory, to "Accepted":
  ```
  - accept <check id> <floor code or *>  — <reason>
  ```
  The reason is optional; `*` matches every floor; floor codes match in any
  case. An acceptance that matches no limit is listed as stale; an `accept`
  line that does not parse is listed under "Notes not understood". Every map
  limit in `audit.md` carries the line to paste.
