<script lang="ts">
  import type { MessagingLegend } from "../factory/flights";
  import type { RailLegend } from "../factory/rail-place";
  import type { StoreLegend } from "../factory/machines";
  import { GUIDE_HREF } from "./fieldguide";
  import type { LayerLines } from "../floor/state";
  let { compact = false, utility = false, hasImplements = false, messaging = null, rails = null, storage = null, codeLinks = false, lines = null, guide = false, children }: {
    compact?: boolean;
    utility?: boolean;   // the map has a utility with a tab: the entry shows only then
    hasImplements?: boolean;   // some floor draws a dotted link: the entry shows only then
    messaging?: MessagingLegend | null;   // which messaging kinds this floor has: each entry shows only when the floor has one
    rails?: RailLegend | null;            // and which rail parts: a yard, a station, a schedule sign, a train
    storage?: StoreLegend | null;         // and which store art: a cache's chest, a bucket's container yard
    codeLinks?: boolean;                  // the F0 code-dependency overlay is on: its entry shows only then
    children?: import("svelte").Snippet;   // what sits directly under the legend, in its flow (the first-visit notice)
    guide?: boolean;                      // the field guide: its one link, under the toggle
    lines?: LayerLines | null;            // a layer shows: the line rows are its kinds alone (null: the base, every row)
  } = $props();
  /** A line row shows on the base, and in a layer only when the layer draws that kind. */
  const has = (k: keyof LayerLines) => !lines || !!lines[k];
  let chosen = $state<boolean | null>(null);   // the reader's own toggle wins over the floor default
  let open = $derived(chosen ?? !compact);
</script>

{#snippet utilityEntry()}
  <li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="8" y="1" width="24" height="10" fill="#ffffff" stroke="#1b1d21" /></svg>Shared utility (tab)</li>
{/snippet}

<div class="stack">
<div class="legend" class:open>
  <!-- the link sits under the toggle, in the toggle's own column, so it never takes width from the list and the open
       legend keeps its height -->
  <div class="head">
    <button class="toggle" onclick={() => (chosen = !open)} aria-expanded={open}>Legend</button>
    {#if guide}<a class="guide-link" href={GUIDE_HREF} target="_blank" rel="noopener" title="Open the field guide in a new tab">Field guide</a>{/if}
  </div>
  {#if open}
    <!-- dense rows across the floor's width: with the implements and messaging entries it stays as short as the
         three rows it had without them, so Fit's top row is not hidden -->
    <ul class="dense">
      {#if has("belt")}<li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="0" y="0" width="40" height="12" fill="#1b1d21" />{#each [6, 18, 30] as x}<polyline points="{x},3 {x + 4},6 {x},9" fill="none" stroke="#ffffff" stroke-width="1.6" />{/each}</svg>Request (belt)</li>{/if}
      {#if has("pipe")}<li><svg viewBox="0 0 40 12" aria-hidden="true"><line x1="0" y1="6" x2="40" y2="6" stroke="#1b1d21" stroke-width="9" /><line x1="0" y1="6" x2="40" y2="6" stroke="#0055bf" stroke-width="4.5" /><rect x="18" y="1" width="3" height="10" fill="#1b1d21" /></svg>Stream (pipe)</li>{/if}
      {#if has("rail")}<li><svg viewBox="0 0 40 12" aria-hidden="true">{#each [3, 11, 19, 27, 35] as x}<rect x={x} y="1" width="3" height="10" fill="#7a5c00" />{/each}<line x1="0" y1="3.5" x2="40" y2="3.5" stroke="#1b1d21" stroke-width="1.6" /><line x1="0" y1="8.5" x2="40" y2="8.5" stroke="#1b1d21" stroke-width="1.6" /></svg>Batch job (rail)</li>{/if}
      {#if has("drone")}<li><svg viewBox="0 0 40 12" aria-hidden="true"><line x1="0" y1="6" x2="40" y2="6" stroke="#237841" stroke-width="2.5" stroke-dasharray="2 5" stroke-linecap="round" /><rect x="16" y="2" width="8" height="8" fill="#237841" stroke="#1b1d21" /></svg>Event (drone)</li>{/if}
      {#if has("tap")}<li><svg viewBox="0 0 40 12" aria-hidden="true"><line x1="10" y1="0" x2="10" y2="12" stroke="#d01012" stroke-width="5" /><line x1="28" y1="0" x2="28" y2="12" stroke="#5c6b78" stroke-width="5" /></svg>DB write / read</li>{/if}
      {#if has("under")}<li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="0" y="1" width="40" height="10" fill="#1b1d21" /><line x1="0" y1="3.5" x2="40" y2="3.5" stroke="#3a3e45" stroke-width="0.8" /><line x1="0" y1="8.5" x2="40" y2="8.5" stroke="#3a3e45" stroke-width="0.8" /><rect x="8" y="0.5" width="9" height="11" fill="#c9d8e6" stroke="#1b1d21" stroke-width="1" /><rect x="15" y="0.5" width="2.5" height="11" fill="#1b1d21" /><polyline points="12,3.5 14.5,6 12,8.5" fill="none" stroke="#1b1d21" stroke-width="1" /><rect x="23" y="0.5" width="9" height="11" fill="#c9d8e6" stroke="#1b1d21" stroke-width="1" /><rect x="22.5" y="0.5" width="2.5" height="11" fill="#1b1d21" /><polyline points="27,3.5 29.5,6 27,8.5" fill="none" stroke="#1b1d21" stroke-width="1" /></svg>Passes under</li>{/if}
      {#if has("inferred")}<li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="0" y="0" width="40" height="12" fill="#1b1d21" /><rect x="2" y="2" width="36" height="8" fill="none" stroke="#ffffff" stroke-width="1.5" stroke-dasharray="4 3" /></svg>Inferred (dashed edge)</li>{/if}
      {#if has("plate")}<li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="14" y="0" width="12" height="12" fill="#f5cd2f" stroke="#1b1d21" />{#each [18, 22] as x}<line x1={x - 3} y1="12" x2={x + 3} y2="0" stroke="#1b1d21" stroke-width="1.6" />{/each}<line x1="14" y1="9" x2="20" y2="3" stroke="#1b1d21" stroke-width="1.6" /></svg>Splitter / merger</li>{/if}
      {#if has("both")}<li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="0" y="0" width="40" height="12" fill="#1b1d21" /><line x1="0" y1="6" x2="40" y2="6" stroke="#7d8a96" stroke-width="0.8" />{#each [5, 14] as x}<polyline points="{x + 4},1.5 {x},3.5 {x + 4},5.5" fill="none" stroke="#ffffff" stroke-width="1.2" />{/each}{#each [26, 35] as x}<polyline points="{x},6.5 {x + 4},8.5 {x},10.5" fill="none" stroke="#ffffff" stroke-width="1.2" />{/each}</svg>Two-way belt</li>{/if}
      {#if has("failed")}<li><svg viewBox="0 0 40 12" aria-hidden="true"><line x1="0" y1="6" x2="40" y2="6" stroke="#d01012" stroke-width="2" stroke-dasharray="5 4" /></svg>Could not route</li>{/if}
      {#if messaging?.queue}<li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="2" y="0.5" width="16" height="11" fill="#d4ead9" stroke="#1b1d21" /><circle cx="10" cy="6" r="2.6" fill="#237841" stroke="#1b1d21" stroke-width="0.8" />{#each [8, 4.5, 1] as y}<rect x="21" y={y} width="10" height="3" fill="#f5cd2f" stroke="#1b1d21" stroke-width="0.8" />{/each}</svg>Queue (waiting stack)</li>{/if}
      {#if hasImplements && !lines}<li><svg viewBox="0 0 40 12" aria-hidden="true">{#each [2, 8.5, 15, 21.5, 28, 34.5] as x}<circle cx={x + 1.5} cy="6" r="1.5" fill="#1b1d21" />{/each}</svg>Implementation (dotted)</li>{/if}
      {#if messaging?.push}<li><svg viewBox="0 0 40 12" aria-hidden="true"><line x1="0" y1="6" x2="20" y2="6" stroke="#237841" stroke-width="2.5" stroke-dasharray="2 5" stroke-linecap="round" /><rect x="21" y="1" width="18" height="10" fill="#f5cd2f" stroke="#1b1d21" />{#each [23, 29, 35] as x}<line x1={x} y1="10" x2={x + 3} y2="2" stroke="#1b1d21" stroke-width="1.2" />{/each}</svg>Push dock</li>{/if}
      {#if messaging?.webhook}<li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="0" y="0" width="20" height="12" fill="#1b1d21" />{#each [4, 12] as x}<polyline points="{x},3 {x + 4},6 {x},9" fill="none" stroke="#ffffff" stroke-width="1.6" />{/each}<rect x="21" y="1" width="18" height="10" fill="#f5cd2f" stroke="#1b1d21" />{#each [23, 29, 35] as x}<line x1={x} y1="10" x2={x + 3} y2="2" stroke="#1b1d21" stroke-width="1.2" />{/each}</svg>Receiving dock</li>{/if}
      {#if messaging?.pull}<li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="0.5" y="0.5" width="11" height="11" fill="#d4ead9" stroke="#1b1d21" /><path d="M3.5 3 v6 M8.5 3 v6 M3.5 6 h5" stroke="#237841" stroke-width="1.4" /><line x1="15" y1="6" x2="40" y2="6" stroke="#237841" stroke-width="2.5" stroke-dasharray="2 5" stroke-linecap="round" /></svg>Pull</li>{/if}
      {#if messaging?.dead}<li><svg viewBox="0 0 40 12" aria-hidden="true"><line x1="0" y1="6" x2="22" y2="6" stroke="#d01012" stroke-width="2.5" stroke-dasharray="2 5" stroke-linecap="round" /><rect x="24" y="0.5" width="15" height="11" fill="#d4ead9" stroke="#1b1d21" /><rect x="24" y="0.5" width="15" height="2.5" fill="#d01012" /><circle cx="31.5" cy="7" r="2.6" fill="#d01012" stroke="#1b1d21" stroke-width="0.8" /></svg>Dead letters</li>{/if}
      {#if messaging?.replicas}<li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="0" y="0.5" width="40" height="11" fill="#1b1d21" /><text x="20" y="9" font-size="7.5" font-weight="700" text-anchor="middle" fill="#ffffff">3 replicas</text></svg>Replicas</li>{/if}
      {#if rails?.yard}<li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="4" y="0.5" width="32" height="11" fill="#efe3bf" stroke="#1b1d21" /><rect x="6.5" y="3" width="22" height="6" fill="#ffffff" stroke="#1b1d21" stroke-width="0.8" /><rect x="22" y="4" width="5.5" height="4" fill="#1b1d21" /></svg>Rail yard</li>{/if}
      {#if rails?.station}<li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="4" y="1" width="30" height="10" fill="#efe3bf" stroke="#1b1d21" /><line x1="4" y1="4" x2="34" y2="4" stroke="#1b1d21" stroke-width="1.2" /><line x1="4" y1="8" x2="34" y2="8" stroke="#1b1d21" stroke-width="1.2" /><rect x="32" y="2" width="2.5" height="8" fill="#1b1d21" /><circle cx="7" cy="6" r="2" fill="#237841" stroke="#1b1d21" stroke-width="0.6" /></svg>Station</li>{/if}
      {#if rails?.sign}<li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="13" y="0.5" width="11" height="11" fill="#ffffff" stroke="#1b1d21" /><circle cx="18.5" cy="6" r="3.6" fill="none" stroke="#1b1d21" stroke-width="1" /><path d="M18.5 3.6 v2.4 h2" fill="none" stroke="#1b1d21" stroke-width="1" /></svg>Schedule sign</li>{/if}
      {#if rails?.train}<li><svg viewBox="0 0 40 12" aria-hidden="true">{#each [3, 14] as x}<rect x={x} y="2" width="10" height="8" fill="#efe3bf" stroke="#1b1d21" /><rect x={x + 2.5} y="4" width="5" height="4" fill="#f5cd2f" stroke="#1b1d21" stroke-width="0.6" />{/each}<rect x="25" y="1" width="12" height="10" rx="1.5" fill="#1b1d21" /><rect x="31" y="3" width="3.5" height="6" fill="#f5cd2f" /></svg>Train</li>{/if}
      {#if storage?.cache}<li><svg viewBox="0 0 40 12" aria-hidden="true"><rect x="13" y="0.5" width="14" height="11" fill="#c9d8e6" stroke="#1b1d21" /><rect x="13.5" y="2.5" width="13" height="1.6" fill="#ffffff" /><rect x="13.5" y="8.2" width="13" height="1.6" fill="#ffffff" /><rect x="21.5" y="6.5" width="3" height="4" fill="#ffffff" stroke="#1b1d21" stroke-width="0.6" /></svg>Cache</li>{/if}
      {#if storage?.bucket}<li><svg viewBox="0 0 40 12" aria-hidden="true">{#each [[5, 6.5], [21, 6.5], [13, 1]] as [x, y]}<rect x={x} y={y} width="14" height="4.5" fill="#e8eef3" stroke="#1b1d21" stroke-width="0.7" />{#each [3, 6, 9, 12] as r}<line x1={x + r} y1={y + 1} x2={x + r} y2={y + 3.5} stroke="#5c6b78" stroke-width="0.6" />{/each}{/each}<line x1="2" y1="11.5" x2="38" y2="11.5" stroke="#1b1d21" stroke-width="0.8" /></svg>Bucket</li>{/if}
      {#if codeLinks}<li><svg viewBox="0 0 40 12" aria-hidden="true">{#each Array.from({ length: 11 }, (_, i) => 2.5 + i * 3.5) as x}<circle cx={x} cy="6" r="0.75" fill="#5c6b78" />{/each}</svg>Code dependency</li>{/if}
      {#if utility}{@render utilityEntry()}{/if}
    </ul>
  {/if}
</div>
{@render children?.()}
</div>

<style>
  .stack { position: absolute; z-index: 2; left: 12px; right: 12px; top: 12px; display: flex; flex-direction: column; gap: 8px; align-items: flex-start; pointer-events: none; }
  .stack > :global(.guide-note) { pointer-events: auto; }
  .legend { align-self: stretch; display: flex; gap: 8px; align-items: flex-start; pointer-events: none; }
  .legend > * { pointer-events: auto; }   /* the box spans the floor's width; only the toggle and the list take the pointer */
  .toggle { background: var(--ink); color: var(--paper); border: 0; padding: 4px 8px; font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; }
  ul { list-style: none; margin: 0; padding: 6px 10px; display: flex; flex-wrap: wrap; gap: 4px 14px; background: rgb(255 255 255 / 0.92); border: 1px solid var(--ink); max-width: 640px; }
  li { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; white-space: nowrap; }
  svg { width: 40px; height: 12px; flex: none; }
  .head { display: flex; flex-direction: column; align-items: stretch; gap: 4px; flex: none; }
  .guide-link { background: rgb(255 255 255 / 0.92); border: 1px solid var(--ink); padding: 2px 4px; font-size: 11px; font-weight: 700; color: var(--blue); text-decoration: underline; text-underline-offset: 2px; white-space: nowrap; text-align: center; }
  ul.dense { max-width: none; gap: 3px 12px; }
  ul.dense li { line-height: 12px; }
</style>
