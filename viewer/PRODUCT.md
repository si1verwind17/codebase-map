# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

Desktop browsers, 1024 px wide and up. Phones and narrow windows are not
supported (owner decision, 2026-10-04): the floor needs the room.

## Stack

TypeScript + Svelte for panels and controls, PixiJS (WebGL) for the animated
factory floor, bundled by Vite into one self-contained HTML file. The skill
ships that file prebuilt; whoever opens it needs no Node, server or network
(the map data is embedded, or loaded from a file the user picks when large).

## Users

- **Primary:** a developer reviewing a codebase they did not write line by
  line — most often code an LLM agent produced — who wants the concept and
  the top-level shape without reading every file, then wants to point at
  what is wrong.
- **Also first-class:** strangers who installed the public plugin and open a
  map of their own repo. Nothing in the viewer may assume knowledge of the
  author's projects or vocabulary.

## Product Purpose

Turn `code-map.json` (produced by the visualizing-codebases scanner) into a
zoomable map a person can read: services and how they interact, the APIs,
events, streams and DB access on each interaction, the classes and methods
inside, the data moving between methods, and traces: the computed lineage
around a chosen node, upstream and downstream, with labelled example values. Success: a reviewer spots a structural problem
(wrong dependency direction, side effects in the wrong order, an overloaded
class, a guessed interaction) faster than by reading code, and sends precise
feedback to the agent that wrote it.

## Positioning

The map is generated from the repository at one commit, every line traces to
`file:line` evidence, and guesses are visibly marked as guesses. It is not a
hand-drawn architecture diagram and not a call graph dump: it shows runtime
interactions between deployables, side effects, and data lineage, at the
zoom level the reviewer chooses.

## Operating Context

- Opened locally from the repo (`docs/viz-code/`), typically right after an
  agent finished a change or before merging one.
- The reviewer alternates between the map and their editor/agent session.
- Feedback loop: comments made on a node are exported for the agent, which
  edits the code; the scanner then refreshes the map incrementally.

## Capabilities and Constraints

- **Input:** `code-map.json`, schema version 1 (format reference:
  `../format.md`). Nodes on floors — service/library/datastore/external/topic
  → package/table → class/file → method — plus relations, pinned traces, examples
  (one per entry point and per data type), files and problems. Every relation carries evidence and a
  confidence (`confirmed` or `inferred` with `why`).
- **Scale:** a real two-language repo produced ~1,600 nodes (1,061 methods,
  394 classes, 6 services) and 50–80 relations. Individual classes reach 43
  methods.
- **Interaction kinds the map must distinguish:** request/response, event
  (via a topic hub), stream (websocket, possibly bidirectional), batch job,
  DB read, DB write, external call, and code dependency (never drawn as
  runtime traffic).
- **Owner decisions already made:** Factorio-inspired metaphor — request =
  belt, event = drone through a topic hub, stream = pipe, batch = train,
  datastore = warehouse; Factorissimo-style nested floors entered by zooming,
  2D not 3D; at most one line between two things per floor; private helpers hidden by default; a trace pane under the floor
  that shows only the lineage around a chosen node.
- **Traces:** a trace is computed, not authored: from any box — a method, table,
  topic, external or datastore, a service, library, package, file or class
  through the entry points inside it (else its boundary methods), or a line
  through both its ends — the viewer walks
  the map's relations upstream, downstream or both, two hops to start, and
  draws the lineage in a pane under the floor. Boxes per service or library
  hold rows of methods with the data line; inside a box calls read as an
  indented call tree, across boxes arrows run orthogonally and route below
  boxes they skip. A side with more than 5 neighbours shows the total first
  and "show all N"; calls into another library fold into one box; a loop is
  marked; a hop known only to a service, library or class is a row "entry
  method not known". A detail panel on the pane's right shows the entry
  point's or the data types' example values, always labelled "example values,
  not computed", else the type's fields, else the signature. Traces worth
  keeping are pinned, and pin changes are exported with the comments for the
  agent to apply. The floor and the pane show one subject: a trace clears the
  selection, any box clicked on the floor re-targets it (the trace's own box
  keeps it), and a row clicked in the pane is marked on the floor (or its
  floor named). Blue marks what is picked in both, one ring on the floor at a
  time, and the inspector shows that item without selecting it. The pane pans and zooms like the floor; Show on floor travels
  one floor at a time. The rail lists Find, On this floor and Pinned traces,
  each foldable.
- **Navigation:** a floor switcher (F0 site … Fn) shows where the reader is
  and opens the selected building; double-click and zoom both enter and leave
  floors symmetrically. Lines leaving a floor end at doors on its frame;
  databases appear inside buildings as the same named warehouse and bus lane
  as on the site floor.
- **Comments:** attached to a node id; kept in browser storage while working;
  exported as `export-comment.md` in the map's output folder
  (`docs/viz-code/` by default), gitignored: comments are transient review
  feedback, spent once the agent acts on them. Markdown, one block per
  comment (node id, kind, `file:line`, map commit, text), grouped by
  service. Saved straight into that folder where the browser allows it,
  downloaded under the same name otherwise. The skill tells agents to read
  it first when it exists.
- **Undecided:** how comments re-anchor after a rescan beyond the scanner's
  orphan report; the production-line layout algorithm (to be proven on real
  maps); machine icon sourcing.

## Brand Commitments

None beyond the owner's direction: the factory metaphor must be memorable and
immediately understandable, icon-rich and animated — not plain boxes and
lines.

## Evidence on Hand

- The parking-city demo map (`../demo/parking-city/docs/viz-code/code-map.json`).
- The scanner's own test fixture (a small Scala + Python repo) in
  `../tests/meaning_fixture.py`.
- No user testimonials, screenshots or usage data exist; do not invent any.

## Product Principles

1. **Truth over beauty.** Every visual element maps to a fact in the map;
   guesses look like guesses; nothing decorative implies traffic that is not
   there.
2. **One floor at a time.** Never show everything; the reviewer chooses depth.
3. **The metaphor must teach itself.** A stranger understands belt vs drone vs
   pipe within a minute, with a legend that is never far away.
4. **Review leads to feedback.** Any node can be commented on, and the comment
   reaches the agent with enough context to act.
5. **Same map, same layout.** Positions stay stable across rescans so the
   reviewer's mental map survives.

## Accessibility & Inclusion

Motion is meaningful, so it needs a reduced-motion mode that keeps meaning
(static direction markers instead of moving items). Kinds must not be
distinguished by color alone. Keyboard navigation between floors and nodes.
