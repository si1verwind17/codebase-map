# Queues: in-process, in a store, in a job system

Read this when `summary.md` lists `in-process queues`, or the repo has a job or task queue, a list or
stream used as a queue, or a table used as one (SKILL.md § Queues).

## In-process queues

A queue, channel or hub inside one process hands work from one method to
another without a call between them: the producer puts an item on it, a
background task takes it off. `calls` cannot join the two, so a trace stops at
the put and looks complete. Add an `in-process-queue` node (`format.md` → In-process
queues) and `hand-off` relations only where that happens:
no `calls` path leads from the producer to the consumer. A queue one method
fills and drains, a buffer inside a stream, a callback, a future or a
for-comprehension is no hand-off: give its line a `problems` entry instead.

- `summary.md` lists `in-process queues`: each creation site the packs know
  (ZIO `Queue`/`Hub`, Go channels, Kotlin `Channel`, `asyncio.Queue`, Java
  blocking queues, .NET channels; `stack.yaml` adds more under `queues`),
  with the delivery it implies and the method around it. A site whose queue
  the code never puts on or never takes from is left out: a channel only a
  library fills (OS signals), a handle that only reads a queue's size or
  clears it. A wrapper the repo
  defines around one is found by the line inside it: the queue is what the
  code calls the wrapper's instance. A queue the packs cannot see (the
  repo's own type over a stream or a callback) gets a `queues` entry in
  `stack.yaml` for its creation call once you find it, so the next scan and
  the audit track it.
- Find the producers and consumers by following the instance: the value
  passed in, or the type it is injected by (ZLayer, a DI container). Every
  method that puts on it gets a `hand-off` to the queue; the method that
  handles each item it gives out gets one from it: the subscriber, the drain
  loop, or, when the drain only connects the queue to a sink or handler it is
  given, that sink.
- `confirmed` when both ends reach one instance through code you can cite
  (the same injected type, the same constructor argument or value); otherwise
  `inferred` with a `why`.
- `delivery` is `queue` when each item goes to one consumer, `fan-out` when
  every subscriber gets it (a hub, a broadcast channel, an event bus).
- Never a topic: a queue is lost when the process stops and no other service
  sees it. The method ends of its hand-offs are in its service; when a
  library's code puts or takes, credit the service's method that calls it.

## Queues in a store or a job system

A queue that outlives the process is a `topic` backed by the store that holds
it: `topic:<engine>:<name>` with that store's engine, `delivery: queue`, its
`evidence` the line that names the queue:

- A list or stream in a datastore that deployables push to and pop from: the
  push is an `event` to the topic, the pop's handler an `event` from it.
- A job or task queue (enqueue a job, a worker runs it): the queue is the
  topic, each enqueue call an `event` to it, and each job's run method the
  consumer, an `event` from it. Key each relation by its job (`job <name>`),
  both sides: one method enqueuing two jobs on one queue is two relations,
  and each worker consumes its own key. `summary.md`'s `jobs enqueued` lines
  give the enqueue sites, each with the job's definition (`jobs defined`): write
  one `event` per line, from the `←` method, and the consumer from the `→`
  node (its run method: `perform`, `handle`, the task function; for `a class
  of that name`, check the class is the job, then its run method). A line `no
  definition found` is a job the packs do not see defined (or no job: a
  Laravel event also `dispatch`es): read the code. A `jobs defined` line marked
  `scheduled` is a timed run: a `batch` keyed `task <name>`.
- A table used as a queue (rows inserted, then claimed with a lock and
  deleted or updated): a topic backed by the table's datastore; the insert is
  the publish, the claiming method the consumer.
