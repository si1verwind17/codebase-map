<script lang="ts">
  import type { Target } from "../floor/scene";
  import { numericCollator, type Model } from "../model/model";
  import { floorPrefix, shownName } from "../floor/names";
  import Floors from "./Floors.svelte";
  import type { ShownPin } from "../trace/pins";
  import { loadRailFolds, saveRailFolds, type RailSection } from "./viewpref";
  import { THEME } from "../floor/palette";

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
    Object.keys(model.floor(container)?.items ?? {}).sort((a, b) => numericCollator.compare(model.codes.get(a) ?? a, model.codes.get(b) ?? b)),
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

  // settings rarely changed (theme, still motion) sit behind one button; Esc or a click outside closes them
  let settingsOpen = $state(false);
  let settingsEl: HTMLElement | undefined = $state();
  /** The floor bakes its colours when it draws, so a theme change is saved and the page reloads. */
  function setTheme(t: "light" | "dark") {
    if (t === THEME) return;
    try { localStorage.setItem("viz-theme", t); } catch { /* storage off: nothing to keep */ }
    location.reload();
  }
  function outside(e: PointerEvent) {
    if (settingsOpen && settingsEl && !settingsEl.contains(e.target as Node)) settingsOpen = false;
  }
  function settingsKey(e: KeyboardEvent) {
    if (e.key === "Escape" && settingsOpen) { e.stopPropagation(); settingsOpen = false; }
  }
</script>

<svelte:window onpointerdown={outside} />

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
      <div class="settings" bind:this={settingsEl} onkeydown={settingsKey} role="presentation">
        {#if settingsOpen}
          <div class="settings-panel" id="settings-panel" role="dialog" aria-label="Settings">
            <h2>Theme</h2>
            <div class="themes" role="radiogroup" aria-label="Theme">
              <button role="radio" aria-checked={THEME === "light"} onclick={() => setTheme("light")}>
                <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="3" /><path d="M8 1.5v1.8M8 12.7v1.8M1.5 8h1.8M12.7 8h1.8M3.4 3.4l1.3 1.3M11.3 11.3l1.3 1.3M3.4 12.6l1.3-1.3M11.3 4.7l1.3-1.3" /></svg>
                Light
              </button>
              <button role="radio" aria-checked={THEME === "dark"} onclick={() => setTheme("dark")}>
                <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13.2 10.1A5.6 5.6 0 0 1 5.9 2.8a5.6 5.6 0 1 0 7.3 7.3z" /></svg>
                Dark
              </button>
            </div>
            <h2>Motion</h2>
            <label><input type="checkbox" bind:checked={reduced} /> Still motion</label>
          </div>
        {/if}
        <button class="gear" onclick={() => (settingsOpen = !settingsOpen)} aria-expanded={settingsOpen} aria-controls="settings-panel" title="Settings: theme and motion">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 4h12M2 8h12M2 12h12" /><circle cx="5.5" cy="4" r="1.6" class="knob" /><circle cx="10.5" cy="8" r="1.6" class="knob" /><circle cx="6.5" cy="12" r="1.6" class="knob" /></svg>
          Settings
        </button>
      </div>
    </div>
  </footer>
</nav>

{#snippet chevron(shut: boolean)}
  <svg class="chev" viewBox="0 0 10 10" aria-hidden="true"><path d={shut ? "M3 1 L7 5 L3 9" : "M1 3 L5 7 L9 3"} fill="none" stroke="currentColor" stroke-width="1.8" /></svg>
{/snippet}

<style>
  .rail { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: var(--page-deep); }
  header { padding: 14px 14px 10px; border-bottom: 1px solid var(--ink); background: var(--ink); color: var(--on-ink); }
  h1 { margin: 0; font-size: 22px; font-stretch: 70%; font-weight: 800; letter-spacing: -0.01em; line-height: 1.1; overflow-wrap: anywhere; }
  .commit { margin: 4px 0 0; color: #cfd8e0; font-size: 12px; }
  .commit code { color: var(--on-ink); }
  section { padding: 10px 12px 8px; border-bottom: 1px solid var(--rule); }
  section.grow { flex: 1; overflow: auto; }
  /* a section heading is its fold button: the ink tab, a chevron, the name and its count */
  .tab .fold { all: unset; display: inline-flex; align-items: center; gap: 5px; padding: 1px 6px; cursor: pointer; }
  .tab .fold:hover { background: var(--paper); color: var(--text); box-shadow: inset 0 0 0 1px var(--ink); }   /* ink on paper: blue is for what is picked only */
  .tab .fold:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
  .chev { width: 8px; height: 8px; flex: none; }
  footer { margin-top: auto; }   /* the floor list folded: the footer stays at the foot */
  .tab { display: inline-block; margin: 0 0 6px; padding: 0; background: var(--ink); color: var(--on-ink); font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 700; }
  button { display: flex; align-items: baseline; gap: 6px; width: 100%; text-align: left; background: none; border: 0; padding: 4px 4px; min-width: 0; }
  button:hover { background: var(--paper); }
  .sel { background: var(--paper); font-weight: 700; outline: 1px solid var(--ink); outline-offset: -1px; }
  .code { flex: none; font-size: 10px; font-weight: 700; background: var(--ink); color: var(--on-ink); padding: 0 4px; white-space: nowrap; }
  .item { flex-wrap: wrap; }
  .name { flex: 1 1 auto; overflow-wrap: break-word; }
  .kind { flex: none; margin-left: auto; color: var(--slate); font-size: 11px; white-space: nowrap; }
  .list { list-style: none; margin: 0; padding: 0; }
  .none { color: var(--slate); padding: 4px; }
  input[type="search"] { width: 100%; border: 1px solid var(--ink); background: var(--paper); padding: 6px 8px; }
  input[type="search"]::placeholder { color: var(--slate); }
  footer { padding: 10px 12px 12px; border-top: 1px solid var(--ink); display: grid; gap: 8px; }
  .primary { justify-content: center; background: var(--ink); color: var(--on-ink); font-weight: 700; padding: 8px; }
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
  .unpin:hover { background: var(--yellow); color: var(--ink); }
  .row { display: flex; gap: 8px; align-items: center; }
  .row button { width: auto; border: 1px solid var(--ink); background: var(--paper); padding: 4px 8px; }
  .settings { position: relative; margin-left: auto; }
  .gear { width: auto; display: flex; align-items: center; gap: 5px; border: 1px solid var(--ink); background: var(--paper); padding: 4px 8px; font-weight: 600; }
  .gear[aria-expanded="true"] { background: var(--ink); color: var(--on-ink); }
  .settings svg { width: 14px; height: 14px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
  .knob { fill: var(--paper); }
  .gear[aria-expanded="true"] .knob { fill: var(--ink); }
  .settings-panel { position: absolute; right: 0; bottom: calc(100% + 8px); width: 208px; background: var(--paper); border: 1px solid var(--ink); box-shadow: 6px 6px 0 var(--shade); z-index: 3; padding: 0 0 8px; }
  .settings-panel h2 { font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; margin: 0; padding: 8px 10px 6px; color: var(--slate); }
  .themes { display: flex; margin: 0 10px 4px; }
  .themes button { flex: 1; width: auto; display: flex; align-items: center; justify-content: center; gap: 5px; border: 1px solid var(--ink); background: var(--paper); padding: 5px 6px; font-weight: 600; }
  .themes button + button { margin-left: -1px; }
  .themes button[aria-checked="true"] { background: var(--ink); color: var(--on-ink); }
  .themes button[aria-checked="false"]:hover { background: var(--yellow); color: var(--ink); }
  .settings-panel label { display: flex; gap: 6px; align-items: center; padding: 2px 10px; font-size: 12px; cursor: pointer; }
</style>
