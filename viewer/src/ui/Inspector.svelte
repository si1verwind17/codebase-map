<script lang="ts">
  import type { Comments } from "../comments/comments";
  import type { Target } from "../floor/scene";
  import { SITE, type Model } from "../model/model";
  import { floorLayers, floorLineCount, layersOfRelations } from "../model/layers";
  import type { Relation } from "../model/types";
  import type { RailLine } from "../factory/rail-place";
  import { entryPoints, methodsIn, traceable } from "../trace/entries";

  let {
    model, container, target, comments, version, onChange, onReveal, onEnter, railLine, onTrace, traced,
  }: {
    model: Model; container: string; target: Target; comments: Comments | null; version: number;
    onChange: () => void; onReveal: (id: string) => void; onEnter: (id: string) => void;
    /** a stand-in rail (`rail:` key, from tf.rails.shells) or a yard (`yard:` key), which no bundle carries */
    railLine?: (key: string) => RailLine | undefined;
    /** start a trace on a node (spec §3.1) */
    onTrace?: (id: string) => void;
    /** the open trace's focus: its Trace buttons are disabled ("Already traced"), a press would only restart it and
     *  lose its depth and folds */
    traced?: string;
  } = $props();
  const ALREADY = "Already traced";

  let draft = $state("");
  let key = $derived(target ? (target.type === "node" ? target.id : target.key) : container);
  // a twin (a module this service also deploys) is shown as the package it stands for
  let real = $derived(target?.type === "node" ? (model.twinOf(target.id) ?? target.id) : undefined);
  let twinHome = $derived(target?.type === "node" && model.twinOf(target.id) ? model.path(model.floorOf(real!) ?? SITE)[1] : undefined);
  let node = $derived(real ? model.nodes.get(real) : undefined);
  // a line of an extra layer (spec §15) is a line of this floor too
  const lineOf = (k: string) => { const b = model.bundles(container); return b.bundles.find((x) => x.key === k) ?? b.layered.find((x) => x.key === k); };
  let rail = $derived(target?.type === "bundle" && !lineOf(target.key) ? railLine?.(target.key) : undefined);
  let relations = $derived<Relation[]>(
    target?.type === "node"
      ? model.relationsOf(real!).filter((r) => r.kind !== "calls" || model.floorOf(real!) !== SITE)
      : target?.type === "bundle"
        ? (lineOf(target.key)?.relations ?? rail?.relations ?? [])
        : [],
  );
  let inLayers = $derived(layersOfRelations(model, model.bundles(container)));
  // where a trace can start from this node: itself, its entry points (a service or library) or its methods
  let entries = $derived(node && (node.kind === "service" || node.kind === "library") ? entryPoints(model, node.id) : []);
  let methods = $derived(node && (node.kind === "package" || node.kind === "file" || node.kind === "class") ? methodsIn(model, node.id) : []);
  let notes = $derived(version >= 0 && comments ? comments.for(key) : []);
  let floorCounts = $derived.by(() => {
    const f = model.floor(container);
    const b = model.bundles(container);   // a line in two layers counts once in the total, once in each layer's count
    return { items: Object.keys(f?.items ?? {}).length, lines: floorLineCount(b), inLayers: floorLayers(model, container).map((l) => `${l.count} in ${l.name}`), inferred: b.bundles.filter((x) => x.inferred).length };
  });

  const other = (r: Relation, self: string) => (r.from === self || model.isInside(r.from, self) ? r.to : r.from);
  const where = (id: string) => { const n = model.nodes.get(id); return n?.file ? `${n.file}${n.line ? ":" + n.line : ""}` : ""; };

  function add() {
    if (!comments || !draft.trim()) return;
    comments.add(key, draft);
    draft = "";
    onChange();
  }
</script>

<aside class="insp" aria-label="Inspector">
  {#if target?.type === "node" && node}
    <header>
      <span class="code">{model.codes.get(node.id)}</span>
      <h2>{model.itemName(target.id)}</h2>
      <p class="sub">{node.role ? node.role + " · " : ""}{node.kind}{node.visibility === "private" ? " · private" : ""}</p>
      {#if where(node.id)}<p class="mono where">{where(node.id)}</p>{/if}
      {#if twinHome}<p class="twin">Twin: this service also deploys it; the code sits under {model.codes.get(twinHome)} {model.label(twinHome)}.</p>{/if}
      <div class="acts">
        {#if model.floor(node.id) && Object.keys(model.floor(node.id)!.items).length}
          <button class="open" onclick={() => onEnter(node!.id)}>Open sub-assembly</button>
        {/if}
        {#if onTrace && traceable(model, node.id)}
          <button class="open" onclick={() => onTrace!(node!.id)} disabled={traced === node.id} title={traced === node.id ? ALREADY : undefined}>Trace</button>
        {/if}
      </div>
    </header>
    {#if onTrace && (node.kind === "service" || node.kind === "library")}
      <section class="starts">
        <h3 class="tab">Entry points ({entries.length})</h3>
        {#each entries as e (e.node)}
          <div class="start">
            <button class="link" onclick={() => onReveal(e.node)}>{model.codes.get(e.node) ?? ""} {model.itemName(e.node)}</button>
            <button class="go-trace" onclick={() => onTrace!(e.node)} aria-label="Trace {model.itemName(e.node)}" disabled={traced === e.node} title={traced === e.node ? ALREADY : undefined}>Trace</button>
            <p class="mono keys">{e.keys.join(" · ")}</p>
          </div>
        {:else}
          <p class="none">No request, event, stream or job arrives at a method here in this map.</p>
        {/each}
      </section>
    {:else if onTrace && methods.length}
      <section class="starts">
        <h3 class="tab">Methods ({methods.length})</h3>
        {#each methods as id (id)}
          <div class="start">
            <button class="link" onclick={() => onReveal(id)}>{model.codes.get(id) ?? ""} {model.itemName(id)}</button>
            <button class="go-trace" onclick={() => onTrace!(id)} aria-label="Trace {model.itemName(id)}" disabled={traced === id} title={traced === id ? ALREADY : undefined}>Trace</button>
          </div>
        {/each}
      </section>
    {/if}
    {#if node.signature}
      <section>
        <h3 class="tab">Signature</h3>
        <p class="mono">({node.signature.params.map((p) => `${p.name}${p.type ? ": " + p.type : ""}`).join(", ")}) → {node.signature.returns ?? "—"}</p>
      </section>
    {/if}
    {#if node.summary}<section><h3 class="tab">Summary</h3><p>{node.summary}</p></section>{/if}
    {#if model.implementersOf(node.id).length}
      <section class="impl">
        <h3 class="tab">Implemented by</h3>
        <p>{#each model.implementersOf(node.id) as id, i}{i ? ", " : ""}<button class="link" onclick={() => onReveal(id)}>{model.codes.get(id) ?? ""} {model.itemName(id)}</button>{/each}</p>
      </section>
    {/if}
    {#if model.implementedBy(node.id).length}
      <section class="impl">
        <h3 class="tab">Implements</h3>
        <p>{#each model.implementedBy(node.id) as id, i}{i ? ", " : ""}<button class="link" onclick={() => onReveal(id)}>{model.codes.get(id) ?? ""} {model.itemName(id)}</button>{/each}</p>
      </section>
    {/if}
  {:else if target?.type === "node"}
    <header>
      <span class="code">{model.codes.get(target.id)}</span>
      <h2>{model.itemName(target.id)}</h2>
      <p class="sub">group · {model.groups.get(target.id)?.members.length} inside</p>
      <button class="open" onclick={() => onEnter(target!.id)}>Open sub-assembly</button>
      {#if onTrace}<button class="open" onclick={() => onTrace!(target!.id)} disabled={traced === target.id} title={traced === target.id ? ALREADY : undefined}>Trace</button>{/if}
    </header>
  {:else if target?.type === "bundle" && rail}
    <header>
      <h2>{rail.title}</h2>
      <p class="sub">{rail.sub} · {relations.length} job{relations.length === 1 ? "" : "s"}</p>
    </header>
    {#if rail.jobs.length}
      <section class="jobs">
        <h3 class="tab">Schedules</h3>
        <ul>{#each rail.jobs as j}<li class="mono">{j}</li>{/each}</ul>
      </section>
    {/if}
  {:else if target?.type === "bundle"}
    <header>
      <!-- a rail or yard key from another floor (the floor changed under the selection) has no pair to name -->
      <h2>{target.key.includes("|") ? `${model.label(target.key.split("|")[0])} ↔ ${model.label(target.key.split("|")[1])}` : target.key}</h2>
      <p class="sub">{relations.length} connection{relations.length === 1 ? "" : "s"} on this line</p>
    </header>
  {:else}
    <header>
      <span class="code">{container === SITE ? "SITE" : model.codes.get(container)}</span>
      <h2>{container === SITE ? "Whole system" : model.label(container)}</h2>
      <p class="sub">{floorCounts.items} items · {floorCounts.lines} lines{floorCounts.inLayers.length ? ` (${floorCounts.inLayers.join(", ")})` : ""} · {floorCounts.inferred} with guesses</p>
    </header>
    <section class="help">
      <h3 class="tab">Reading the floor</h3>
      <p>Select a machine or a line to see its connections and the code they come from. Double-click a building, or zoom deep into it, to open it as a sub-assembly. Dashed marks are inferred: the scanner reasoned them, it did not see both ends.</p>
    </section>
  {/if}

  {#if relations.length}
    <section class="rels">
      <h3 class="tab">Connections</h3>
      <ul>
        {#each relations.slice(0, 60) as r}
          <li class:inferred={r.confidence === "inferred"}>
            <div class="rhead">
              <span class="kind k-{r.kind}">{r.kind}</span>
              {#if target?.type === "node"}
                <button class="link" onclick={() => onReveal(other(r, real!))}>{model.codes.get(other(r, real!)) ?? ""} {model.label(other(r, real!))}</button>
              {:else}
                <span>{model.label(r.from)} → {model.label(r.to)}</span>
              {/if}
            </div>
            {#if r.key}<p class="mono">{r.key}</p>{/if}
            {#if r.tables?.length}<p class="mono tables">{r.tables.length} tables: {r.tables.join(", ")}</p>{/if}
            <p class="meta">
              {r.confidence}{r.data ? ` · data ${r.data}` : ""}{r.deployment_dependent ? " · set per deployment" : ""}{r.via ? ` · via ${model.label(r.via)}` : ""}{#if target?.type === "node"}{@const layers = inLayers.get(r.id)}{layers ? ` · in layer ${layers.join(" and ")}` : ""}{/if}
            </p>
            {#if r.why}<p class="why">Why inferred: {r.why}</p>{/if}
            <p class="ev mono">{r.evidence.map((e) => `${e.file}${e.line ? ":" + e.line : ""}`).join("  ·  ")}</p>
          </li>
        {/each}
        {#if relations.length > 60}<li class="more">{relations.length - 60} more not shown — open the sub-assembly to narrow down.</li>{/if}
      </ul>
    </section>
  {/if}

  <section class="notes">
    <h3 class="tab">Export comments</h3>
    {#each notes as c}
      <div class="note-row">
        <p class="note">{c.text}</p>
        <button class="del" onclick={() => { comments?.drop(c); onChange(); }} aria-label="Delete comment" title="Delete this comment">Delete</button>
      </div>
    {/each}
    <label class="sr" for="draft">Comment on {target ? "the selection" : "this floor"}</label>
    <textarea id="draft" rows="3" placeholder="What should the agent change here?" bind:value={draft}></textarea>
    <button class="add" onclick={add} disabled={!draft.trim()}>Add comment</button>
  </section>
</aside>

<style>
  .insp { height: 100%; overflow: auto; background: var(--paper); }
  header { padding: 14px 14px 10px; border-bottom: 1px solid var(--ink); }
  h2 { margin: 6px 0 2px; font-size: 18px; font-stretch: 85%; line-height: 1.15; overflow-wrap: anywhere; }
  .sub { margin: 0; color: var(--slate); }
  .where { margin: 6px 0 0; color: var(--slate); overflow-wrap: anywhere; }
  .code { font-size: 10px; font-weight: 700; background: var(--ink); color: var(--paper); padding: 1px 5px; }
  .open { margin-top: 10px; background: var(--ink); color: var(--paper); border: 0; padding: 6px 12px; font-weight: 700; }
  .open:hover:not(:disabled) { background: var(--blue); }
  .open:disabled, .starts .go-trace:disabled { background: var(--shade); color: var(--slate); border-color: var(--shade); cursor: default; }
  .acts { display: flex; gap: 6px; flex-wrap: wrap; }
  .starts .start { display: grid; grid-template-columns: 1fr auto; gap: 2px 6px; align-items: baseline; padding: 4px 0; border-top: 1px solid var(--rule); }
  .starts .start:first-of-type { border-top: 0; }
  .starts .keys { grid-column: 1 / -1; margin: 0; color: var(--slate); font-size: 11px; overflow-wrap: anywhere; }
  .starts .go-trace { border: 1px solid var(--ink); background: var(--paper); padding: 1px 8px; font-size: 11px; font-weight: 700; }
  .starts .go-trace:hover:not(:disabled) { background: var(--picked); border-color: var(--picked); color: var(--paper); }
  .none { margin: 0; color: var(--slate); }
  section { padding: 10px 14px; border-bottom: 1px solid var(--rule); }
  .tab { display: inline-block; margin: 0 0 6px; padding: 1px 6px; background: var(--ink); color: var(--paper); font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 700; }
  .help p { margin: 0; color: var(--ink); max-width: 60ch; }
  .rels ul { list-style: none; margin: 0; padding: 0; }
  .rels li { padding: 7px 0; border-top: 1px solid var(--rule); }
  .rels li:first-child { border-top: 0; }
  .rels li.inferred { background: repeating-linear-gradient(135deg, transparent 0 6px, rgb(92 107 120 / 0.09) 6px 8px); }
  .rhead { display: flex; gap: 6px; align-items: baseline; }
  .kind { font-size: 10px; font-weight: 700; padding: 0 5px; border: 1px solid var(--ink); white-space: nowrap; }
  .k-db-write { background: var(--red); color: var(--paper); border-color: var(--red); }
  .k-stream { background: var(--blue); color: var(--paper); border-color: var(--blue); }
  .k-event { background: var(--green); color: var(--paper); border-color: var(--green); }
  .k-ext-call { background: var(--yellow); }
  .rels p { margin: 2px 0 0; }
  .impl p { margin: 0; }
  .jobs ul { list-style: none; margin: 0; padding: 0; }
  .jobs li { padding: 2px 0; overflow-wrap: anywhere; }
  .meta { color: var(--slate); font-size: 12px; }
  .why { font-size: 12px; }
  .ev { color: var(--slate); overflow-wrap: anywhere; font-size: 11px; }
  .more { color: var(--slate); }
  .link { background: none; border: 0; padding: 0; color: var(--blue); text-decoration: underline; text-underline-offset: 3px; text-align: left; }
  .notes textarea { width: 100%; border: 1px solid var(--ink); padding: 6px 8px; resize: vertical; background: var(--paper); }
  .notes textarea::placeholder { color: var(--slate); }
  .note { margin: 0 0 6px; padding: 6px 8px; background: var(--yellow); border: 1px solid var(--ink); }
  .add { margin-top: 6px; background: var(--ink); color: var(--paper); border: 0; padding: 6px 12px; font-weight: 700; }
  .add:disabled { background: var(--shade); color: var(--slate); cursor: default; }
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
  .note-row { display: flex; gap: 6px; align-items: flex-start; }
  .note-row .note { flex: 1; min-width: 0; }
  .del { flex: none; border: 1px solid var(--ink); background: var(--paper); padding: 2px 6px; font-size: 11px; font-weight: 600; }
  .del:hover { background: var(--yellow); }
  .twin { margin: 6px 0 0; padding: 4px 8px; background: var(--page); border: 1px dashed var(--ink); }
</style>
