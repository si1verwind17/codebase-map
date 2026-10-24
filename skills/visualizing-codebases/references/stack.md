# Stack: sorting lines and writing `stack.yaml`

Read this when the Stack section of `summary.md` does not read `nothing unrecognised`, or when a
route or table pattern count looks wrong (SKILL.md § Stack). `OUT` and `SKILL_DIR` are as in SKILL.md.

Sort each line into one group of its language:

| Group | When | Effect on the map |
|---|---|---|
| `imports` | the library talks to the outside world: `{prefix, kind}`, kind one of `sql-db`, `doc-db`, `cache`, `http-out`, `http-in`, `http`, `ws`, `event`, `grpc`, `cloud-sdk`, `spark`, `mail` (sends mail: SMTP or a mail provider's SDK). A vendor SDK that calls its API is `http-out` | the file's `sinks` (listed for you to attach) and the package role |
| `routes` | the library receives requests: a regex or an annotation pattern that finds them (below). A server library usually needs both, `imports` as `http-in` plus a pattern | `routes` facts: matching and the `entry` role |
| `effects` | Scala only: `val`s of these types hold behaviour (`IO`, `Resource`, `Stream`). It does not clear an import line: the library also goes in `ignore`, or in `imports` if it talks out | such a `val` becomes a method node |
| `ignore` | you looked at its use and it neither talks out nor serves: types, schemas, data frames, a webhook signature check, a server that only runs another framework's app (`uvicorn`) | nothing; the line leaves the section |
| `tables` | an ORM or query DSL names tables in code (Quill `query[Order]`, JPA `@Table(name = "orders")`, SQLAlchemy `__tablename__`, Django `db_table`): a regex that finds the name. Its library still goes in `imports` | `tables (patterns)` lines in `summary.md`, to attach (SKILL.md § Side effects) |
| `queues` | a library or the repo's own code makes in-process queues, channels or event buses the packs do not know: a regex for the creation call, with its `delivery` | `in-process queues` lines in `summary.md` (`references/interactions.md`) |
| `jobs` | a job system the packs do not know (or a repo's own job registry): one entry per `side`, `define` (the decorator, base class or marker of a job), `enqueue` (the call that queues one, a `job` group naming the job) or `schedule` (a timed run) | `jobs defined` and `jobs enqueued` lines in `summary.md` (`references/interactions.md`) |

1. Read each example line at the scanned commit before deciding. Write only
   what the repo shows: each pattern is checked against at least one real
   route line, and a library goes into `ignore` only after you looked at how
   it is used. Why: the file is committed and silences the section; a guess
   hides a real side effect for good. A long list (a hundred lines and more):
   read every marked line (looks like a server, datastore, queue or client)
   and each unmarked line's two examples; an unmarked line whose examples
   show only types, UI, test or build tooling goes into `ignore` with the
   others like it in one edit. Report how many lines went in that way.
2. Re-run `extract.py` after each edit. Repeat until the section reads
   `nothing unrecognised`, or until each remaining line is one you cannot
   resolve; report those with the reason (SKILL.md § Run step 7).
3. Check each pattern's count (the `Route patterns` and `Table patterns`
   lines) against the code. When you see routes or tables it misses, fix the
   regex; for a pack pattern, write a `stack.yaml` entry with the pack
   entry's name, which replaces it for this repo (pack regexes expect the
   usual receiver names, such as Express `app.` and `router.`). Never widen a
   pattern to match something that is not one. A line `duplicates <pattern>`
   is information, not a miss: every match of your entry was already that
   pattern's; delete your entry.
   When a library in `imports` is an ORM, look for how it names tables and
   add a `tables` pattern even though no line asks for it.
   For a library no pack knows, search the files that import it for every form
   it declares a route, table or queue with before you trust your pattern: a
   verb with and without its own path, a base path set once for many routes (a
   `mount: true` route entry, below, or composed on the keys), a declaration
   that takes its path from a variable or a method, more than one per
   statement. Count each form's matches; each form the pattern cannot read
   goes into `problems` by name with one `file:line` example (what the map
   shows instead), so the gap is said, not found later. Why: a pattern checked
   against one example misses the other forms silently.
4. Files whose facts a new or changed pattern touches count as changed in
   this run: on an incremental run, review them with the stale facts.

- A server library without routes whose module only starts a server for
  routes defined in another module (a shared module serving tapir
  endpoints) goes into `ignore`; that clears the line. So does a framework
  whose routes the scanner cannot read (Django `urls.py`): say so in the
  report. Only when the library is not also in `imports`: `imports` wins (below),
  so a server library used only for a type (a cookie class, a status constant)
  stays out of `imports`.
- Prefixes match on the language's separator boundaries, in every group and
  in `when`: `.` (Python, Scala, Java, Kotlin, C#), `/` (TypeScript,
  JavaScript, Go, Ruby), `::` (Rust), `\` (PHP). Write a prefix without a
  trailing separator (`java`, `std`; `java.` and `std::` are read the same).
  A prefix ending in a single `:` covers everything after it: `node:` covers
  every `node:*`. Python `from X import Y` is matched as `X.Y`.
- `imports` wins over `ignore`, and when several `imports` prefixes name an
  import the longest decides its kind (`jakarta.ws.rs.client` is `http-out`
  inside `jakarta.ws.rs`, `http-in`). A `stack.yaml` kind replaces a pack's
  kind for the same prefix, and a `stack.yaml` route, table or queue entry named
  like a pack entry replaces that entry; `summary.md` lists both.
- A hand edit between runs that changes an entry (not only comments or
  spacing) makes the next run `full` ("stack.yaml changed
  since the map was made"). Your edits during a run do not: this run's
  assemble stamps them (`meta.stack`).

Format (data only; you create the file, `extract.py` only adds the two
header lines to it if missing and keeps the rest as written):

```yaml
python:
  imports:
    - {prefix: rq, kind: event}
  ignore: [attrs]
  routes:
    - name: bottle
      when: bottle
      path: literal
      regex: '@\w+\.(?P<method>get|post|put|delete)\(\s*["''](?P<path>[^"'']*)["'']'
scala:
  effects: [Future, Route]
  routes:
    - name: pekko-http
      when: org.apache.pekko.http
      path: segments
      method: ANY
      regex: '\bpath\(\s*(?P<path>"[^)]*)\)'
```

- Top-level keys: `python`, `scala`, `java`, `kotlin`, `csharp`, `typescript`,
  `javascript`, `go`, `rust`, `ruby`, `php`, and `exclude` (a list of path
  globs every scan leaves out; `--exclude` writes it). Groups: `imports`, `routes`,
  `effects` (Scala only; under any other language it is an error), `ignore`,
  `tables`. Packs and `stack.yaml` add up; `stack.yaml` removes no pack
  entry, but replaces one of the same name (above).
- A route (`form: regex`, the default): `name` (unique per language;
  `fastapi`, `tapir` and `tapir-client` are taken), `regex` (Python `re` over the whole file, multiline; avoid
  nested quantifiers such as `(\w+\s*)+`: a file whose patterns run over 60 s is skipped, its reason in
  `summary.md`) with a named group `path`; the method from a `method` group, a `methods` group
  (each quoted word is one route), or the entry's `method:`; both groups also
  read a qualified constant by its last part (`http.MethodHead` → `HEAD`,
  `HttpMethod.GET`, `Method::POST`): the method the
  framework serves when the call names none (`GET` for most; `ANY` only where
  it serves every method, as pekko's `path` does); methods are upper-cased
  (`get` → `GET`). A pattern with a
  `methods` group and no `method` group must also set `method:`, the
  fallback for a match where the group is empty. `when`: an import prefix; the pattern runs only on files that
  import it. Without `when` it runs on every file of its language.
  `path: literal` (the default when `path:` is omitted, mounts too) reads a path string (`/users/<int:id>`);
  `segments` reads `/`-separated parts (`Root / "users" / IntVar(id)`).
  `<int:id>`, `<id>`, `:id` and `{id}` all become `{id}`, and so do the
  constraints and markers around a name (`{id:int}`, `{id?}`, `{*id}`,
  `{id...}`, `:id?`, `:id(\d+)`): write keys in that form. The handler is the
  innermost function holding the match, else the next one after it (a
  decorator), else the file (in Scala, its first class; in the other
  languages but Python, the file's node, made when the file has none: never
  the package or an unrelated class). A Scala `val` that
  holds routes (Pekko `val route: Route = ...`) is a function only when its
  type is in `effects`: add that type (`Route`), or the class becomes the
  handler.
  `expand` makes one match several routes: `{index: GET, show: GET /:id,
  update: [PATCH /:id, PUT /:id]}` gives one route per item, its suffix
  appended to the path; optional `only` / `except` groups list the actions
  to keep or drop (any words: `[:index, :show]`, `%i[index]`), and an
  optional `param` group renames the suffixes' `:id` (Rails `param: :slug`).
  The Ruby pack's `rails-resources` / `rails-resource` use it.
  `handler_class` and `handler_method` (both or neither) name the handler by
  convention: templates whose `{group}` or `{group|camel}` fields
  (`line_items` → `LineItems`; `{a,b}` is the first of the groups with a value) are regex groups, or `{action}`, the expanded
  action (`handler_class: '{path|camel}Controller'`, `handler_method:
  '{action}'`). The handler is that method when the module has one class of
  that name (its last `::`, `.` or `/` segment; the segments before it, when
  the template gives any, must end the class's package and outer classes)
  holding it; else the rules below, as when a `nohandler` group matched (an
  option naming another handler).
  An optional `handler` group (`app.get("/x", (?P<handler>[\w.]+))`) names
  the handler by its last `.` or `::` segment (`h.GetOrder` → `GetOrder`):
  among the methods and functions of that name in the module (those the
  file's imports point at when any; for a bare name, free functions over
  methods), the one in the same file, else the same package, else the
  module, is the handler; no match or several at the first level that has
  any give a function of that name nested in the method around the match
  (made a node, `<owner>#<outer>.<name>/<arity>`), else the file: never the
  function that registers the route. A route written on the decorators of a
  nested function (a route in an app factory) is that function's, made a node
  the same way. A pattern with a `handler` group never takes the function below the
  match (that rule is for decorators): an inline handler
  (`app.get("/x", (req, res) => …)`) leaves the group empty; inside a function
  its lambda becomes a node of its own named after the route (`get_x`, holding
  the lambda's calls), at a file's top level the file is its handler. An empty
  group `(?P<handler>)` at the end of the regex is how a route written as a
  block (`get "/x" do`) gets the same rule.
- A mount (`mount: true`): the route entry's regex has a `path` group and an
  optional `target` group, no method. Its matches are not routes: `summary.md`
  lists them per module (`- **mounts:** /v1 → router (file:line)`). The
  scanner joins a mount to the routes of its own file registered on it:
  inside its call or the block after it (`route("/v1") { get(..) }`), chained
  on a mount without a target, or called on a variable bound to one
  (`v1 := r.Group("/v1")`, then `v1.GET(..)`), nested mounts composing
  outward; such a mount reads `composed onto N routes` and those routes'
  paths already hold its prefix. Every other mount you compose with
  the routes of its target (follow the target to the file that defines its
  routes) wherever you write a route's path, such as a `request` key; an
  example's key follows `scripts/examples.py`, which writes the relation's
  spelling when a relation names the route and the bare path when none does (Express
  `app.use("/v1", router)`, Ktor `route("/v1") { }`, Chi `Route`, NestJS
  `setGlobalPrefix`). In `problems` and any other text a route's path is
  composed too; only example keys follow `examples.py`. A bare example key
  under a mount is expected: no problem explains it.
- An annotation route (`form: annotated`; any language but Python and
  Scala) reads the annotations on classes and methods instead of a regex.
  The Java pack's Spring entry, shortened (in `stack.yaml` this name would
  replace it):

  ```yaml
  java:
    routes:
      - name: spring-web
        form: annotated
        when: org.springframework.web.bind.annotation
        prefix: [RequestMapping]          # class annotations whose path is the prefix
        verbs: {GetMapping: GET, PostMapping: POST, RequestMapping: from-method-arg}
        path_args: [value, path, 0]       # where the path is: named arguments, then positions
  ```

  Each method with a `verbs` annotation is one route per path, the class
  prefix joined with the method's path, the method itself the handler.
  `from-method-arg` reads the HTTP method from the argument `method_arg`
  names (default `method`:
  `method = RequestMethod.POST`; a list gives one route each, none `ANY`).
  Optional keys: `method_path` (method annotations whose path is appended,
  JAX-RS `@Path`), `token` (a path token replaced by `class-stem`, the class
  name without `Controller`, or `method-name`: ASP.NET `[controller]`,
  `[action]`), `absolute` (method paths starting with one of these drop the
  class prefix: ASP.NET `/`, `~/`), `skip_class` (class annotations that
  mark an HTTP client: such a class or interface gives no routes; the packs
  set Feign `FeignClient`, Spring `HttpExchange`, MicroProfile
  `RegisterRestClient`, Micronaut `Client`). A path written as a constant is kept as a named segment
  (`{Asset}` from `RouteKey.Asset`) for you to resolve; any other expression gives no route. Spring `${property}` placeholders stay in the
  path as written: resolve them from the config when you match it.
- Rails routes (`config/routes.rb`, `to: "c#a"`, and `resources :users` /
  `resource :profile` expanded to their REST actions, `only:` / `except:` on
  the same line kept) are handled by the controller action
  (`UsersController#index`, `ProfilesController#show`) when the repo has
  that class and method; else, like Sinatra blocks, by the file: then map
  `c#a`, or a resource action, to the controller's method yourself when you
  attach relations and examples. The file is also the handler of a resource
  with `controller:` or `module:` on its line, and of one whose controller
  has an irregular plural (`resource :address`). An enclosing `namespace`,
  `scope module:` or `controller` block is not read: check that the
  controller the scanner chose is the one in that namespace. A resource nested in another or in a
  `namespace` is listed with its own name only (`/posts`, not
  `/users/{user_id}/posts`), and `path:` or options on a following line are
  not read: compose the full path yourself, as for mounts. A
  Grape API's `resource :x do` blocks look the same: in such a repo replace
  both entries in `stack.yaml` with a `when` that nothing imports. A C# `when` holds in every file of a
  project whose files have it as a `global using` or whose `.csproj` has it as
  a `<Using Include>`; implicit usings are not read.
- A table pattern: `name` (unique per language among `tables`), `regex`
  with a named group `table`, optional `when` as for routes:
  `{name: peewee, when: peewee, regex: '\btable_name\s*=\s*["''](?P<table>[^"'']+)["'']'}`.
  A match inside a method is listed as `in <method>` (an access); one on a
  class outside any method as `defined on <class>` (an ORM mapping, not an
  access: find the methods that use the class); elsewhere `in` the file.
  A Django `db_table` inside `class Meta` reads `defined on Meta`: the
  model is the class around `Meta`.
- A queue pattern: `name`, `regex` for the creation call, `delivery`
  (`queue` or `fan-out`), optional `when`:
  `{name: bus, when: acme.events, delivery: fan-out, regex: '\bnew\s+EventBus\s*\('}`.
- An effect: a type name, matched as a `val`'s declared type or a call
  `Name.` / `Name(` in its value; `{name: X, match: type}` matches the type
  only.
- Invalid content stops `extract.py` with exit 2 and names the file, the
  language, the entry and the reason: fix it and rerun.
