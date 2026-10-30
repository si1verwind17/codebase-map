<script lang="ts">
  // The trace pane: the lineage around one focus on one page. Boxes and rows are HTML, arrows one SVG above
  // them (it takes clicks on its arrows only, so an arrow inside a box stays visible and the rows stay clickable); positions come from trace/layout.ts. A click on a row or an arrow opens the detail panel on the right.
  import { onMount, tick } from "svelte";
  import type { Model } from "../model/model";
  import type { PinDirection } from "../model/types";
  import { BOX_W, GUTTER, INDENT_LEVELS, ROW_H, pinStartName, startText, traceTitle, type Arrow, type Row, type TraceView } from "../trace/layout";
  import type { TraceState } from "../trace/reach";
  import { ALL_SEEDS, initialState } from "../trace/reach";
  import { DIRECTIONS, defaultTitle, type ShownPin } from "../trace/pins";
  import { EXAMPLE_LABEL, examplesFor, pretty } from "../trace/examples";
  import { floorNote } from "../trace/floor";
  import { PAN_STEP, ZOOM_STEP, fitZoom, intoView, isDrag, wheelZoom, zoomAbout } from "../trace/panzoom";

  let {
    model, container, trace, view, pin, pins, maximized, onTrace, onHover, onPoint, onPin, onUnpin, onMaximize, onClose, onReveal,
  }: {
    model: Model; container: string; trace: TraceState; view: TraceView; pin: ShownPin | undefined; pins: readonly ShownPin[]; maximized: boolean;
    onTrace: (st: TraceState) => void; onHover: (node: string | null) => void; onPoint: (node: string | null) => void;
    onPin: (title: string) => void; onUnpin: (id: string) => void;
    onMaximize: () => void; onClose: () => void; onReveal: (id: string) => void;
  } = $props();

  type Detail = { type: "row"; row: Row } | { type: "arrow"; arrow: Arrow } | null;
  // the detail panel follows the row or arrow by id: a direction, depth or fold change that drops it closes the panel
  let picked = $state<{ type: "row" | "arrow"; id: string } | null>(null);
  let detail = $derived.by<Detail>(() => {
    if (picked?.type === "row") { const row = view.rows.get(picked.id); return row ? { type: "row", row } : null; }
    if (picked?.type === "arrow") { const arrow = view.arrows.find((a) => a.id === picked!.id); return arrow ? { type: "arrow", arrow } : null; }
    return null;
  });
  $effect(() => { if (picked && !detail) picked = null; });   // gone from the view: forgotten, not shown again later
  // the floor marks the row whose detail is open (spec S3); an arrow's detail, or none, marks nothing
  $effect(() => { onPoint(detail?.type === "row" ? detail.row.node : null); });
  let naming = $state<string | null>(null);   // the title of the pin being made; null while not pinning
  // the title field takes the keys as soon as the form opens (`autofocus` does not apply to a form added after load),
  // its words selected so typing replaces the offered title
  let titleField = $state<HTMLInputElement>();
  $effect(() => { if (titleField) { titleField.focus(); titleField.select(); } });

  const DIR_LABEL: Record<PinDirection, string> = { upstream: "Upstream", both: "Both", downstream: "Downstream" };
  // the pane's title: the focus row's qualified label, a container's or a datastore's own name, a line's title
  let focusLabel = $derived(traceTitle(model, view));
  let start = $derived(startText(model, view));   // "service · 2 entry points" (spec A6); null for a single-node start
  const where = (id: string) => { const n = model.nodes.get(id); return n?.file ? `${n.file}${n.line ? ":" + n.line : ""}` : ""; };
  const add = (s: ReadonlySet<string>, x: string) => new Set([...s, x]);
  const expand = (r: Row) => onTrace({ ...trace, expanded: add(trace.expanded, r.id) });
  const showAll = (r: Row, side: number) => onTrace({ ...trace, showAll: add(trace.showAll, `${r.id}|${side}`) });
  const openLibrary = (r: Row) => onTrace({ ...trace, libraries: add(trace.libraries, r.node) });
  function startPin() { naming = defaultTitle(pinStartName(model, view), trace.direction, pins); }
  function submitPin(e: SubmitEvent) {
    e.preventDefault();
    onPin(naming?.trim() || defaultTitle(pinStartName(model, view), trace.direction, pins));
    naming = null;
  }
  function namingKey(e: KeyboardEvent) {
    if (e.key === "Escape") { e.stopPropagation(); naming = null; }
  }
  /** Esc from the App (focus outside the title field): close the pin form, else the detail panel; false when neither
   *  is open, so the App closes the pane. */
  export function escape(): boolean {
    if (naming !== null) { naming = null; return true; }
    if (picked) { picked = null; return true; }
    return false;
  }
  function arrowKey(e: KeyboardEvent, a: Arrow) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); picked = { type: "arrow", id: a.id }; }
  }
  /** The examples the detail shows: a row's own; an arrow's target's, picked by the arrow's key. */
  let blocks = $derived(
    detail?.type === "row" ? (detail.row.kind === "node" ? examplesFor(model, detail.row.node) : [])
    : detail?.type === "arrow" ? examplesFor(model, detail.arrow.edge.to, detail.arrow.edge.key) : [],
  );

  // pan and zoom (spec S6, rulings R1–R5): the sheet scales by `k` inside the scrolling `.graph`, so a pan is its scroll
  // offset. This pane is keyed by the focus: a new focus starts here at 100% with its focus row in view.
  let graphEl = $state<HTMLDivElement>();
  let k = $state(1);
  let dragging = $state(false);
  let press: { id: number; x: number; y: number; left: number; top: number } | null = null;

  async function zoomTo(next: number, px: number, py: number) {
    const el = graphEl;
    if (!el) return;
    const v = zoomAbout({ k, left: el.scrollLeft, top: el.scrollTop }, next, px, py);
    k = v.k;
    await tick();   // the sizer takes its new size first, or the browser clamps the offsets to the old one
    el.scrollLeft = v.left;
    el.scrollTop = v.top;
  }
  async function fit() {
    const el = graphEl;
    if (!el) return;
    k = fitZoom(view.width, view.height, el.clientWidth, el.clientHeight);
    await tick();
    el.scrollLeft = 0;
    el.scrollTop = 0;
  }
  function wheel(e: WheelEvent) {
    if (!e.ctrlKey || !graphEl) return;   // a plain wheel scrolls the pane as a page does
    e.preventDefault();                    // Ctrl+wheel (and a trackpad pinch) zooms the sheet, never the page
    const r = graphEl.getBoundingClientRect();
    void zoomTo(wheelZoom(k, e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY), e.clientX - r.left, e.clientY - r.top);
  }
  onMount(() => {
    const el = graphEl;
    if (!el) return;
    const f = [...view.rows.values()].find((r) => r.focus);
    if (f) { const at = intoView({ x: f.x, y: f.y, w: BOX_W, h: ROW_H }, k, el.clientWidth, el.clientHeight); el.scrollLeft = at.left; el.scrollTop = at.top; }
    el.addEventListener("wheel", wheel, { passive: false });   // Svelte's onwheel is passive: it could not stop the page zoom
    return () => el.removeEventListener("wheel", wheel);
  });
  /** A drag starts on the background only — never on a row, an arrow, a button, a link or a field — after DRAG_SLOP px. */
  const NO_DRAG = "button, input, a, .row, .arrow";
  function pressGraph(e: PointerEvent) {
    if (e.button !== 0 || !graphEl || (e.target as Element).closest(NO_DRAG)) return;
    press = { id: e.pointerId, x: e.clientX, y: e.clientY, left: graphEl.scrollLeft, top: graphEl.scrollTop };
    graphEl.setPointerCapture(e.pointerId);   // from the press, so a drag that leaves the pane keeps panning
  }
  function moveGraph(e: PointerEvent) {
    if (!press || e.pointerId !== press.id || !graphEl) return;
    const dx = e.clientX - press.x, dy = e.clientY - press.y;
    if (!dragging) {
      if (!isDrag(dx, dy)) return;
      dragging = true;
    }
    graphEl.scrollLeft = press.left - dx;
    graphEl.scrollTop = press.top - dy;
  }
  function releaseGraph() { press = null; dragging = false; }
  const PANS: Record<string, [number, number]> = { ArrowLeft: [-PAN_STEP, 0], ArrowRight: [PAN_STEP, 0], ArrowUp: [0, -PAN_STEP], ArrowDown: [0, PAN_STEP] };
  function keyGraph(e: KeyboardEvent) {
    if (!graphEl || e.ctrlKey || e.metaKey || e.altKey || (e.target as Element).closest("input")) return;   // Ctrl+0, Alt+Arrow … are the browser's
    const r = graphEl.getBoundingClientRect();
    if (e.key === "+" || e.key === "=") { e.preventDefault(); void zoomTo(k * ZOOM_STEP, r.width / 2, r.height / 2); }
    else if (e.key === "-" || e.key === "_") { e.preventDefault(); void zoomTo(k / ZOOM_STEP, r.width / 2, r.height / 2); }
    else if (e.key === "0") { e.preventDefault(); void fit(); }
    else if (e.target === graphEl && PANS[e.key]) { e.preventDefault(); graphEl.scrollBy(PANS[e.key][0], PANS[e.key][1]); }
  }
</script>

<section class="trace" class:max={maximized} aria-label="Trace of {focusLabel}">
  <header>
    <span class="tab">Trace</span>
    <h2 title="{focusLabel} — {trace.focus}">{#if model.codes.get(trace.focus)}<span class="code">{model.codes.get(trace.focus)}</span> {/if}{focusLabel}{#if start}<span class="start">{` · ${start}`}</span>{/if}</h2>
    {#if view.start.shown < view.start.total}
      <button class="chip seeds" onclick={() => onTrace({ ...trace, showAll: add(trace.showAll, ALL_SEEDS) })}>show all {view.start.total}</button>
    {/if}
    <span class="count">{view.methods} {view.methods === 1 ? "method" : "methods"} · {view.boxes.length} {view.boxes.length === 1 ? "box" : "boxes"}</span>
    <div class="dir" role="radiogroup" aria-label="Direction">
      {#each DIRECTIONS as d}
        <button role="radio" aria-checked={trace.direction === d} onclick={() => onTrace(initialState(trace.focus, d, trace.line))}>{DIR_LABEL[d]}</button>
      {/each}
    </div>
    <div class="tools">
      <span class="zoom" title="Zoom: Ctrl+wheel or + and −">{Math.round(k * 100)}%</span>
      <button onclick={fit} aria-label="Fit the trace" title="Fit the whole trace in the pane (0)">Fit trace</button>
      {#if pin}
        <button onclick={() => onUnpin(pin!.id)} title="Remove “{pin.title}” from the pinned traces">Unpin</button>
      {:else if model.nodes.has(trace.focus)}
        <button onclick={startPin} title="Keep this trace in the pinned traces">Pin</button>
      {/if}
      <button onclick={onMaximize} aria-pressed={maximized}>{maximized ? "Restore" : "Maximize"}</button>
      <button onclick={onClose}>Close</button>
    </div>
  </header>
  {#if naming !== null}
    <form class="naming" onsubmit={submitPin}>
      <label for="pin-title">Pin title</label>
      <input id="pin-title" bind:this={titleField} bind:value={naming} onkeydown={namingKey} />
      <button type="submit" class="primary">Pin</button>
      <button type="button" onclick={() => (naming = null)}>Cancel</button>
    </form>
  {/if}
  <div class="body">
    <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
    <div class="graph" class:dragging bind:this={graphEl} data-zoom={k} tabindex="0" role="group"
      aria-label="Trace: drag or use the arrow keys to move, Ctrl+wheel or + and − to zoom, 0 to fit"
      onpointerdown={pressGraph} onpointermove={moveGraph} onpointerup={releaseGraph} onpointercancel={releaseGraph}
      onlostpointercapture={releaseGraph} onkeydown={keyGraph}>
      {#if !view.rows.size}
        <p class="none">This node is not in the map.</p>
      {:else}
        <div class="sizer" style="width: {view.width * k}px; height: {view.height * k}px">
        <div class="sheet" class:pointing={picked?.type === "row"} style="width: {view.width}px; height: {view.height}px; transform: scale({k})">
          {#each view.boxes as b (b.key)}
            <div class="box k-{b.kind}" style="left: {b.x}px; top: {b.y}px; width: {b.w}px; height: {b.h}px">
              <div class="bhead"><span class="code">{b.code}</span><span class="bname" title={b.title}>{b.title}</span><span class="bkind">{b.kind}</span></div>
              {#each b.rows as r (r.id)}
                <div class="row" class:focus={r.focus} class:pointed={picked?.type === "row" && picked.id === r.id} class:gap={r.kind === "gap"} class:fold={r.kind === "library"} style="top: {r.y - b.y}px; padding-left: {GUTTER + r.indent}px"
                  role="presentation" onmouseenter={() => onHover(r.node)} onmouseleave={() => onHover(null)}>
                  <button class="rname" title="{r.label} — {r.node}{r.depth > INDENT_LEVELS ? ` · call depth ${r.depth}` : ""}" onclick={() => (picked = { type: "row", id: r.id })}
                    onfocus={() => onHover(r.node)} onblur={() => onHover(null)}>
                    {r.label}{#each r.loops as l}<span class="loop" title="leads back to {view.rows.get(l)?.label ?? l}"> ↺</span>{/each}
                  </button>
                  <span class="sub" title={r.sub}>{r.sub}</span>
                  <span class="chips">
                    {#each r.folds as f}
                      <span class="total">{f.total} {f.word}</span>
                      <button class="chip" onclick={() => showAll(r, f.side)}>show all {f.total}</button>
                    {/each}
                    {#if r.more}<button class="chip more" onclick={() => expand(r)} aria-label="Show {r.more} more beyond {r.label}">+{r.more}</button>{/if}
                    {#if r.kind === "library"}<button class="chip" onclick={() => openLibrary(r)} aria-label="Open {model.label(r.node)}">Open</button>{/if}
                  </span>
                </div>
              {/each}
            </div>
          {/each}
          <!-- after the boxes: Tab reaches the rows in reading order, then the arrows (drawn above the boxes by z-index) -->
          <svg width={view.width} height={view.height} aria-hidden="false" role="group" aria-label="Arrows">
            <defs>
              <marker id="trace-head" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0 0 L8 4 L0 8 Z" fill="context-stroke" />
              </marker>
            </defs>
            {#each view.arrows as a (a.id)}
              <g class="arrow k-{a.kind}" class:dashed={a.dashed} class:sel={detail?.type === "arrow" && detail.arrow.id === a.id}
                role="button" tabindex="0" aria-label={a.title} data-id={a.id}
                onclick={() => (picked = { type: "arrow", id: a.id })} onkeydown={(e) => arrowKey(e, a)}>
                <title>{a.title}</title>
                <path class="hit" d={a.hit} />
                <path class="line" d={a.path} marker-end="url(#trace-head)" />
              </g>
            {/each}
          </svg>
        </div>
        </div>
      {/if}
    </div>
    {#if detail}
      <aside class="detail" aria-label="Trace detail">
        <header>
          {#if detail.type === "row"}
            <span class="code">{model.codes.get(detail.row.node) ?? ""}</span>
            <h3>{detail.row.label}</h3>
            <p class="sub">{model.kindOf(detail.row.node)}{where(detail.row.node) ? ` · ${where(detail.row.node)}` : ""}</p>
          {:else}
            <span class="kind k-{detail.arrow.kind}">{detail.arrow.kind === "implements" ? "implemented by" : detail.arrow.kind}</span>
            <h3>{model.itemName(detail.arrow.edge.from)} → {model.itemName(detail.arrow.edge.to)}</h3>
            <p class="sub">{detail.arrow.title}</p>
          {/if}
          <button class="x" onclick={() => (picked = null)} aria-label="Close the detail">Close</button>
        </header>
        {#if detail.type === "row" && detail.row.kind === "gap"}
          <p class="note">Only the service is known for this hop: the map names no method where it arrives.</p>
        {:else if detail.type === "row" && detail.row.kind === "library"}
          <p class="note">Calls into the shared library {model.label(detail.row.node)}, folded: {detail.row.members.map((m) => model.nodes.get(m)?.name ?? m).join(", ")}.</p>
        {:else if detail.type === "row"}
          {@const sig = model.nodes.get(detail.row.node)?.signature}
          {#if sig}<p class="mono">({sig.params.map((p) => `${p.name}${p.type ? ": " + p.type : ""}`).join(", ")}) → {sig.returns ?? "—"}</p>{/if}
        {:else}
          {@const asig = model.nodes.get(detail.arrow.edge.to)?.signature}
          {#if asig}<p class="mono">({asig.params.map((p) => `${p.name}${p.type ? ": " + p.type : ""}`).join(", ")}) → {asig.returns ?? "—"}</p>{/if}
          {#each detail.arrow.edge.relations as r}
            {#if r.why}<p class="why">Why inferred: {r.why}</p>{/if}
          {/each}
        {/if}
        {#if detail.type === "row" && detail.row.kind !== "library"}
          {@const id = detail.row.node}
          {@const note = floorNote(model, container, id)}
          <div class="acts">
            <button onclick={() => onReveal(id)}>Show on floor</button>
            {#if note}<span class="floor-note">{note}</span>{/if}
            {#if detail.row.node !== trace.focus && detail.row.kind === "node"}
              <button onclick={() => onTrace(initialState(id, trace.direction))}>Trace from here</button>
            {/if}
          </div>
        {/if}
        {#if blocks.length}
          <section class="examples">
            <p class="label">{EXAMPLE_LABEL}</p>
            {#each blocks as x}
              <h4>{x.title}</h4>
              {#if x.kind === "entry"}
                <p class="io">Request</p><pre class="mono">{pretty(x.request)}</pre>
                {#if x.response !== undefined}<p class="io">Response</p><pre class="mono">{pretty(x.response)}</pre>{/if}
              {:else if x.kind === "type"}
                <pre class="mono">{pretty(x.value)}</pre>
              {:else}
                <ul class="fields">{#each x.fields as f}<li class="mono">{f.name}{f.type ? `: ${f.type}` : ""}</li>{/each}</ul>
              {/if}
            {/each}
          </section>
        {/if}
      </aside>
    {/if}
  </div>
</section>

<style>
  .trace { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--page); border-top: 1px solid var(--ink); }
  .trace > header { display: flex; align-items: center; gap: 10px; padding: 6px 10px; background: var(--paper); border-bottom: 1px solid var(--ink); flex-wrap: wrap; }
  .tab { display: inline-block; padding: 1px 6px; background: var(--ink); color: var(--on-ink); font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 700; }
  h2 { margin: 0; font-size: 15px; font-weight: 700; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60ch; }
  h2 .start { font-weight: 600; color: var(--slate); }
  .code { font-size: 10px; font-weight: 700; background: var(--ink); color: var(--on-ink); padding: 1px 5px; vertical-align: middle; }
  .count { color: var(--slate); font-size: 12px; }
  .dir { display: flex; }
  .dir button { border: 1px solid var(--ink); background: var(--paper); padding: 3px 10px; font-weight: 600; margin-left: -1px; }
  .dir button[aria-checked="true"] { background: var(--ink); color: var(--on-ink); }
  .tools { display: flex; gap: 6px; margin-left: auto; }
  .tools button, .naming button, .acts button { border: 1px solid var(--ink); background: var(--paper); padding: 3px 10px; font-weight: 600; }
  .tools button:hover, .naming button:hover, .acts button:hover, .dir button:hover:not([aria-checked="true"]) { background: var(--yellow); color: var(--ink); }
  .tools button[aria-pressed="true"] { background: var(--ink); color: var(--on-ink); }
  .naming { display: flex; align-items: center; gap: 8px; padding: 6px 10px; background: var(--paper); border-bottom: 1px solid var(--rule); }
  .naming label { font-size: 12px; font-weight: 700; }
  .naming input { flex: 1; max-width: 48ch; border: 1px solid var(--ink); padding: 4px 8px; background: var(--paper); }
  .naming .primary { background: var(--ink); color: var(--on-ink); }
  .naming .primary:hover { background: var(--blue); }
  .body { flex: 1; min-height: 0; display: flex; }
  .graph { flex: 1; min-width: 0; overflow: auto; cursor: grab; }
  .graph.dragging { cursor: grabbing; user-select: none; }
  .graph:focus-visible { outline-offset: -2px; }
  /* the scroll extent at this zoom; `clip` makes no second scroll box, so a focused row still scrolls `.graph` */
  .sizer { position: relative; overflow: clip; }
  .none { color: var(--slate); padding: 12px; }
  .sheet { position: relative; transform-origin: 0 0; }
  .row { cursor: default; }
  .zoom { align-self: center; min-width: 4ch; text-align: right; font-size: 12px; color: var(--slate); }
  svg { position: absolute; left: 0; top: 0; overflow: visible; z-index: 1; pointer-events: none; }
  .arrow { cursor: pointer; }
  .arrow .hit { fill: none; stroke: transparent; stroke-width: 10; pointer-events: stroke; }
  .arrow .line { fill: none; stroke: var(--text); stroke-width: 1.6; }
  .arrow.dashed .line { stroke-dasharray: 5 4; }
  .arrow.k-event .line, .arrow.k-hand-off .line { stroke: var(--green); }
  .arrow.k-stream .line { stroke: var(--blue); stroke-width: 2.4; }
  .arrow.k-batch .line { stroke: var(--amber); }
  .arrow.k-db-write .line { stroke: var(--red); }
  .arrow.k-db-read .line { stroke: var(--slate); }
  .arrow.k-implements .line { stroke-dasharray: 1.5 3; }
  .arrow:hover .line, .arrow.sel .line, .arrow:focus-visible .line { stroke: var(--blue); stroke-width: 2.6; }
  .arrow:focus { outline: none; }
  .box { position: absolute; background: var(--paper); border: 1px solid var(--ink); box-shadow: 6px 6px 0 var(--shade); }
  .box.k-library { background: var(--shelf); }
  .box.k-external { background: var(--yellow); color: var(--ink); }
  .bhead { display: flex; align-items: center; gap: 6px; height: 28px; padding: 0 8px; border-bottom: 1px solid var(--ink); }
  .bname { flex: 1; min-width: 0; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bkind { color: var(--slate); font-size: 11px; }
  .k-external .bkind { color: var(--ink); }
  .row { position: absolute; left: 0; right: 0; height: 40px; padding: 3px 8px 3px 14px; display: grid; grid-template-columns: 1fr auto; grid-template-rows: auto auto; column-gap: 6px; }
  .row:hover { background: var(--page); }
  /* blue means picked (spec S5): the focus row on the pale wash with a 2px keyline, the row whose detail is open with
     the keyline alone; yellow is the outside world's only */
  .row.focus { background: var(--picked-wash); box-shadow: inset 0 0 0 2px var(--picked); }
  .row.pointed { box-shadow: inset 0 0 0 2px var(--picked); }
  /* one blue mark (spec A1): while a row is pointed the focus rows keep their wash, the keyline moves to that row */
  .sheet.pointing .row.focus:not(.pointed) { box-shadow: none; }
  .row.gap .rname, .row.gap .sub { font-style: italic; }
  .rname { grid-column: 1; grid-row: 1; min-width: 0; background: none; border: 0; padding: 0; text-align: left; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rname:hover { text-decoration: underline; text-underline-offset: 3px; }
  .sub { grid-column: 1 / -1; grid-row: 2; color: var(--slate); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .focus .sub { color: var(--text); }
  .k-external .sub { color: var(--ink); }
  .loop { font-weight: 700; }
  .chips { grid-column: 2; grid-row: 1; display: flex; gap: 4px; align-items: center; }
  /* the focus row's label takes the whole first line; its chips sit on the second, after the data */
  .row.focus .rname { grid-column: 1 / -1; }
  .row.focus .sub { grid-column: 1; }
  .row.focus .chips { grid-row: 2; }
  .total { font-size: 11px; font-weight: 700; }
  .chip { border: 1px solid var(--ink); background: var(--paper); padding: 0 5px; font-size: 11px; font-weight: 700; line-height: 16px; }
  .chip:hover { background: var(--yellow); color: var(--ink); }
  .detail { width: 320px; flex: none; overflow: auto; background: var(--paper); border-left: 1px solid var(--ink); }
  .detail header { padding: 10px 12px; border-bottom: 1px solid var(--ink); position: relative; }
  .detail h3 { margin: 6px 0 2px; font-size: 16px; overflow-wrap: anywhere; padding-right: 54px; }
  .detail .sub { display: block; white-space: normal; overflow-wrap: anywhere; font-size: 12px; }
  .detail .x { position: absolute; right: 10px; top: 10px; border: 1px solid var(--ink); background: var(--paper); padding: 2px 6px; font-size: 11px; font-weight: 600; }
  .detail .kind { font-size: 10px; font-weight: 700; padding: 0 5px; border: 1px solid var(--ink); }
  .detail > p, .acts, .examples { margin: 0; padding: 8px 12px; }
  .acts { display: flex; gap: 6px; flex-wrap: wrap; }
  .floor-note { align-self: center; font-size: 12px; color: var(--slate); }
  .note, .why { font-size: 12px; }
  .examples { border-top: 1px solid var(--rule); }
  .examples .label { margin: 0 0 6px; font-size: 11px; font-weight: 700; color: var(--slate); text-transform: uppercase; letter-spacing: 0.06em; }
  .examples h4 { margin: 8px 0 4px; font-size: 13px; }
  .io { margin: 4px 0 2px; font-size: 11px; font-weight: 700; }
  pre { margin: 0; padding: 6px 8px; background: var(--page); border: 1px solid var(--rule); max-height: 240px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11.5px; }
  .fields { list-style: none; margin: 0; padding: 0; }
  .fields li { padding: 1px 0; }
</style>
