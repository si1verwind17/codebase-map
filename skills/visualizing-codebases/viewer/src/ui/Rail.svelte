<script lang="ts">
  import type { Target } from "../floor/scene";
  import { type Model } from "../model/model";
  import { floorPrefix, shownName } from "../floor/names";
  import Floors from "./Floors.svelte";
  import type { ShownPin } from "../trace/pins";
  import { loadRailFolds, saveRailFolds, type RailSection } from "./viewpref";

  let {
    model, container, target, commentCount, problems, reduced = $bindable(), busy = false, pins = [],
    onGo, onTrace, onUnpin, onReveal, onExport, onClear, onProblems,
  }: {
    model: Model; container: string; target: Target; commentCount: number; problems: number; reduced: boolean; busy?: boolean; pins?: ShownPin[];
    onGo: (c: string) => void; onReveal: (id: string) => void; onExport: () => void; onClear: () => void; onProblems: () => void;
    onTrace: (p: ShownPin) => void; onUnpin: (id: string) => void;
  } = $props();

  let query = $state("");
  let results = $derived(model.search(query, 12));
  let path = $derived(model.path(container));
  let items = $derived(
    Object.keys(model.floor(container)?.items ?? {}).sort((a, b) => (model.codes.get(a) ?? a).localeCompare(model.codes.get(b) ?? b, undefined, { numeric: true })),
  );
  let meta = $derived(model.map.meta);
  // the same short names the floor draws: drop the prefix every item here shares
  let prefix = $derived(floorPrefix(model, items));   // the same prefix the floor drops
  const short = (id: string) => shownName(model, id, prefix);
  /** Allow line breaks after `.`, `_` and `/` only, so a long identifier wraps at its parts, never mid-word. */
  const breakable = (s: string) => s.replace(/([._/])/g, "$1\u200b");

  // each section folds to its heading and count (spec S8), remembered per browser; blocked storage: for this visit only
  const store = () => { try { return window.localStorage; } catch { return null; } };
  let folded = $state(loadRailFolds(store()));
  function toggle(s: RailSection) {
    const next = new Set(folded);
    if (!next.delete(s)) next.add(s);
    folded = next;
    saveRailFolds(store(), next);
  }
</script>

<nav class="rail" aria-label="Map navigation">
  <header>
    <h1>{meta.repo}</h1>
    <p class="commit">commit <code>{meta.commit.slice(0, 10)}</code></p>
  </header>

  <Floors {model} {container} {target} {busy} {onGo} />

  <section>
    <h2 class="tab"><button class="fold" aria-expanded={!folded.has("find")} aria-controls="rail-find" onclick={() => toggle("find")}>{@render chevron(folded.has("find"))}Find</button></h2>
    <div id="rail-find" hidden={folded.has("find")}>
      <input type="search" placeholder="Name or code (S2·P3)" bind:value={query} aria-label="Find a node by name or code" />
      {#if query}
        <ul class="list">
          {#each results as id}
            <li><button class="item" onclick={() => onReveal(id)}><span class="code">{model.codes.get(id)}</span><span class="name">{breakable(model.itemName(id))}</span><span class="kind">{model.kindOf(id)}</span></button></li>
          {:else}
            <li class="none">Nothing matches “{query}”.</li>
          {/each}
        </ul>
      {/if}
    </div>
  </section>

  <section class:grow={!folded.has("floor")}>
    <h2 class="tab"><button class="fold" aria-expanded={!folded.has("floor")} aria-controls="rail-floor" onclick={() => toggle("floor")}>{@render chevron(folded.has("floor"))}On this floor ({items.length})</button></h2>
    <ul id="rail-floor" class="list" hidden={folded.has("floor")}>
      {#each items as id}
        <li>
          <button class="item" class:sel={target?.type === "node" && target.id === id} onclick={() => onReveal(id)}>
            <span class="code">{model.codes.get(id)}</span><span class="name">{breakable(short(id))}</span><span class="kind">{model.kindOf(id)}</span>
          </button>
        </li>
      {/each}
    </ul>
  </section>

  <section class="pins">
    <h2 class="tab"><button class="fold" aria-expanded={!folded.has("pins")} aria-controls="rail-pins" onclick={() => toggle("pins")}>{@render chevron(folded.has("pins"))}Pinned traces ({pins.length})</button></h2>
    <ul id="rail-pins" class="list" hidden={folded.has("pins")}>
      <!-- keyed by origin too: a pin made here and a later map pin can share a slug -->
      {#each pins as p ((p.local ? "l:" : "m:") + p.id)}
        <li class="pin" class:missing={p.missing}>
          <button class="pin-start" onclick={() => onTrace(p)} disabled={p.missing} title={p.missing ? "Its start is not in this map" : `Trace ${p.direction} from ${model.label(p.start)}`}>
            <svg class="play" viewBox="0 0 8 10" aria-hidden="true"><path d="M0 0 L8 5 L0 10 Z" fill="currentColor" /></svg>
            <span class="name" title={p.title}>{p.title}</span>
            <span class="kind">{p.missing ? "start not in this map" : p.direction}</span>
          </button>
          <button class="unpin" onclick={() => onUnpin(p.id)} aria-label="Unpin {p.title}" title="Unpin">×</button>
        </li>
      {:else}
        <li class="none">No pinned traces. Trace a node from the inspector, then pin it.</li>
      {/each}
    </ul>
  </section>

  <footer>
    <div class="save">
      <button class="primary" onclick={onExport} disabled={!commentCount} title="Save your comments and pin changes as export-comment.md for the agent">Save for the agent ({commentCount})</button>
      <button class="clear" onclick={onClear} disabled={!commentCount} title="Delete every comment and pin change, e.g. once the agent has handled the export">Clear</button>
    </div>
    <div class="row">
      <button onclick={onProblems}>Problems ({problems})</button>
      <label><input type="checkbox" bind:checked={reduced} /> Still motion</label>
    </div>
  </footer>
</nav>

{#snippet chevron(shut: boolean)}
  <svg class="chev" viewBox="0 0 10 10" aria-hidden="true"><path d={shut ? "M3 1 L7 5 L3 9" : "M1 3 L5 7 L9 3"} fill="none" stroke="currentColor" stroke-width="1.8" /></svg>
{/snippet}

<style>
  .rail { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: var(--page-deep); }
  header { padding: 14px 14px 10px; border-bottom: 1px solid var(--ink); background: var(--ink); color: var(--paper); }
  h1 { margin: 0; font-size: 22px; font-stretch: 70%; font-weight: 800; letter-spacing: -0.01em; line-height: 1.1; overflow-wrap: anywhere; }
  .commit { margin: 4px 0 0; color: #cfd8e0; font-size: 12px; }
  .commit code { color: var(--paper); }
  section { padding: 10px 12px 8px; border-bottom: 1px solid var(--rule); }
  section.grow { flex: 1; overflow: auto; }
  /* a section heading is its fold button: the ink tab, a chevron, the name and its count */
  .tab .fold { all: unset; display: inline-flex; align-items: center; gap: 5px; padding: 1px 6px; cursor: pointer; }
  .tab .fold:hover { background: var(--paper); color: var(--ink); box-shadow: inset 0 0 0 1px var(--ink); }   /* ink on paper: blue is for what is picked only */
  .tab .fold:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
  .chev { width: 8px; height: 8px; flex: none; }
  footer { margin-top: auto; }   /* the floor list folded: the footer stays at the foot */
  .tab { display: inline-block; margin: 0 0 6px; padding: 0; background: var(--ink); color: var(--paper); font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 700; }
  button { display: flex; align-items: baseline; gap: 6px; width: 100%; text-align: left; background: none; border: 0; padding: 4px 4px; min-width: 0; }
  button:hover { background: var(--paper); }
  .sel { background: var(--paper); font-weight: 700; outline: 1px solid var(--ink); outline-offset: -1px; }
  .code { flex: none; font-size: 10px; font-weight: 700; background: var(--ink); color: var(--paper); padding: 0 4px; white-space: nowrap; }
  .item { flex-wrap: wrap; }
  .name { flex: 1 1 auto; overflow-wrap: break-word; }
  .kind { flex: none; margin-left: auto; color: var(--slate); font-size: 11px; white-space: nowrap; }
  .list { list-style: none; margin: 0; padding: 0; }
  .none { color: var(--slate); padding: 4px; }
  input[type="search"] { width: 100%; border: 1px solid var(--ink); background: var(--paper); padding: 6px 8px; }
  input[type="search"]::placeholder { color: var(--slate); }
  footer { padding: 10px 12px 12px; border-top: 1px solid var(--ink); display: grid; gap: 8px; }
  .primary { justify-content: center; background: var(--ink); color: var(--paper); font-weight: 700; padding: 8px; }
  .primary:hover { background: var(--blue); }
  .save { display: flex; gap: 6px; }
  .save .primary { flex: 1; }
  .clear { width: auto; border: 1px solid var(--ink); background: var(--paper); padding: 4px 8px; font-weight: 600; }
  .clear:disabled { opacity: 0.4; cursor: default; }
  button:disabled { cursor: default; }
  .primary:disabled { background: var(--shade); color: var(--slate); cursor: default; }
  .play { width: 8px; height: 10px; flex: none; align-self: center; }
  .pins .list { max-height: 30vh; overflow: auto; }
  .pin { display: flex; align-items: baseline; }
  .pin-start { flex: 1; flex-wrap: wrap; }
  /* ▶ and the title on one line, a long title cut short (whole on hover); the direction on the line below */
  .pin-start .name { flex: 1 1 0; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pin-start .kind { flex-basis: 100%; padding-left: 14px; }
  .pin.missing .name { color: var(--slate); }
  .unpin { width: auto; flex: none; padding: 0 6px; font-weight: 700; }
  .unpin:hover { background: var(--yellow); }
  .row { display: flex; gap: 8px; align-items: center; }
  .row button { width: auto; border: 1px solid var(--ink); background: var(--paper); padding: 4px 8px; }
  .row label { display: flex; gap: 4px; align-items: center; font-size: 12px; }
</style>
