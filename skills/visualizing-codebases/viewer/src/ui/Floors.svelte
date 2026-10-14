<script lang="ts">
  import type { Target } from "../floor/scene";
  import { SITE, type Model } from "../model/model";

  let { model, container, target, busy = false, onGo }: {
    model: Model; container: string; target: Target; busy?: boolean; onGo: (c: string) => void;
  } = $props();

  let path = $derived(model.path(container));
  let below = $derived(
    target?.type === "node" && model.floor(target.id) && Object.keys(model.floor(target.id)!.items).length ? target.id : null,
  );
</script>

<nav class="floors" aria-label="Floors">
  <h2 class="tab">Floors</h2>
  <ol>
    {#each path as c, i}
      <li>
        <button class:here={c === container} disabled={busy} onclick={() => onGo(c)} aria-current={c === container ? "page" : undefined}
          title={c === SITE ? "Whole system" : model.label(c)}>
          <span class="lvl">F{i}</span><span class="name">{c === SITE ? "Whole system" : model.label(c)}</span>
        </button>
      </li>
    {/each}
    {#if below}
      <li>
        <button class="down" disabled={busy} onclick={() => onGo(below!)} title="Open {model.label(below)}">
          <span class="lvl">F{path.length}</span><span class="name">Open {model.label(below)}</span>
        </button>
      </li>
    {/if}
  </ol>
</nav>

<style>
  .floors { padding: 10px 12px 8px; border-bottom: 1px solid var(--rule); }
  .tab { display: inline-block; margin: 0 0 6px; padding: 1px 6px; background: var(--ink); color: var(--paper); font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 700; }
  ol { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column-reverse; gap: 2px; }
  button { display: flex; gap: 8px; align-items: baseline; width: 100%; border: 1px solid transparent; background: none; padding: 4px 6px; text-align: left; }
  button:hover:not(:disabled) { border-color: var(--ink); }
  button:disabled { cursor: default; }
  button:disabled:not(.here) { opacity: 0.4; } /* busy: a move is under way; .here keeps its highlight */
  .here { background: var(--yellow); border-color: var(--ink); font-weight: 700; }
  .down { border: 1px dashed var(--ink); color: var(--blue); font-weight: 600; }
  .lvl { font-weight: 800; font-stretch: 70%; font-size: 15px; min-width: 24px; }
  .name { min-width: 0; overflow-wrap: anywhere; }
</style>
