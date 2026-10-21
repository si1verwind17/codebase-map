<script lang="ts">
  import { onDestroy, onMount, tick, untrack } from "svelte";
  import { Comments, saveExport } from "./comments/comments";
  import { FloorScene, type Target } from "./floor/scene";
  import { mainPlanner, workerPlanner } from "./floor/planner";
  import { spawnPlanWorker } from "./floor/spawn-plan-worker";
  import { MapError, Model, SITE } from "./model/model";
  import Inspector from "./ui/Inspector.svelte";
  import Legend from "./ui/Legend.svelte";
  import Rail from "./ui/Rail.svelte";
  import { loadGuideSeen, saveGuideSeen, GUIDE_HREF } from "./ui/fieldguide";
  import { loadDronePaths, saveDronePaths, loadCodeLinks, saveCodeLinks, clampSplit, loadSplit, saveSplit } from "./ui/viewpref";
  import { defaultLit as litDefault, litFor } from "./floor/lit";
  import type { MessagingLegend } from "./factory/flights";
  import type { RailLegend } from "./factory/rail-place";
  import type { StoreLegend } from "./factory/machines";
  import { codeLinkCount } from "./factory/conduits";
  import { floorLayers, layerLabel, listEntry, type LayerId } from "./model/layers";
  import type { LayerLines } from "./floor/state";
  import TracePane from "./ui/TracePane.svelte";
  import { TraceGraph } from "./trace/graph";
  import { initialState, type TraceState } from "./trace/reach";
  import { layoutTrace, pinStartName } from "./trace/layout";
  import { isFocus, ownBox, traceItems, traceKeys, traceMarks, traceSubject } from "./trace/floor";
  import { startFor, traceable, type LineStart } from "./trace/entries";
  import { Pins, defaultTitle, type ShownPin } from "./trace/pins";
  import type { PinDirection } from "./model/types";

  /** The page's own map text (main.ts): given once, then forgotten, so the page keeps no copy of it. */
  let { initial }: { initial: () => string | null } = $props();

  let model = $state<Model | null>(null);
  let error = $state<string | null>(null);
  let container = $state(SITE);
  let target = $state<Target>(null);
  let comments = $state<Comments | null>(null);
  let commentVersion = $state(0);
  let reduced = $state(typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches);
  let showProblems = $state(false);
  let inspectorOpen = $state(true);
  let dronePaths = $state(loadDronePaths(safeStorage()));
  function toggleDronePaths() {
    dronePaths = !dronePaths;
    saveDronePaths(safeStorage(), dronePaths);
    scene?.setDronePaths(dronePaths);
  }
  let codeLinks = $state(loadCodeLinks(safeStorage()));   // F0's code-dependency conduits, off by default
  let codeLinkPairs = $derived(model ? codeLinkCount(model) : 0);   // F0's uses-code pairs: no toggle and no key without one
  let conduitsDrawn = $derived(codeLinks && container === SITE && codeLinkPairs > 0);
  function toggleCodeLinks() {
    codeLinks = !codeLinks;
    saveCodeLinks(safeStorage(), codeLinks);
    scene?.setCodeLinks(codeLinks);
  }
  // layers: the floor's extra layers (one per heavily used item, named by its code), the one shown (the
  // scene's, reset to the base on a floor change), the line kinds it draws (the legend's line rows follow it) and the
  // list's state
  let layers = $derived(model ? floorLayers(model, container) : []);
  let layer = $state<LayerId | null>(null);
  let layerLines = $state<LayerLines | null>(null);
  let layersOpen = $state(false);
  let shownLayer = $derived(layers.find((l) => l.id === layer));
  let layerName = $derived(layerLabel(shownLayer));
  function pickLayer(id: LayerId | null) {
    layersOpen = false;
    const drop = id === null && layer !== null && !!target && !!scene?.liveOnlyIn(target, layer);   // its lines go with the layer
    scene?.setLayer(id);
    if (drop) pick(null);
  }
  /** Collapse or expand the inspector; the floor gets the width back or gives it up at the same zoom, the point at its
   *  centre kept there (audit row 65), once the grid has settled. */
  function toggleInspector() {
    inspectorOpen = !inspectorOpen;
    scene?.keepCentre();
    requestAnimationFrame(() => scene?.resize());
  }
  // the trace pane: what it traces, where it is drawn, the divider's place and whether it fills the screen
  // the trace graph is built on the first trace, not on load: this line alone reads it, and only once `trace` is set
  let graph = $derived(model ? new TraceGraph(model) : null);
  let trace = $state.raw<TraceState | null>(null);
  let traceView = $derived(model && trace && graph ? layoutTrace(model, graph, trace) : null);
  let split = $state(loadSplit(safeStorage()));
  let maximized = $state(false);
  let pins = $state.raw<Pins | null>(null);
  let pinVersion = $state(0);   // bumped on every pin change: the panel and the pane's Pin button follow
  let shownPins = $derived(pinVersion >= 0 && pins ? pins.list() : []);
  let pinChanges = $derived(pinVersion >= 0 && pins ? pins.changes() : 0);
  let tracePin = $derived(pinVersion >= 0 && trace && pins ? pins.find(trace.focus, trace.direction) : undefined);
  let notice = $state<string | null>(null);
  let point = $state<string | null>(null);   // the node of the row whose detail is open in the trace pane: marked on the floor (spec S3)
  const guide = true;   // the field guide (on the project's site): its link under the legend, and the first-visit notice
  let guideNote = $state(false);   // the first-visit notice: shown on a browser's first visit only, marked seen as it appears
  function dismissGuide() { guideNote = false; }
  let messagingKinds = $state<MessagingLegend | null>(null);   // the current factory floor's queue, push, pull, dead-letter and replica kinds
  let railKinds = $state<RailLegend | null>(null);             // and its rail yards, stations and schedule signs
  let storeKinds = $state<StoreLegend | null>(null);           // and its cache and bucket art
  let host = $state<HTMLDivElement>();
  let scene: FloorScene | null = null;
  let mapText: string | null = null;   // the open map's text until the scene hands it to its layout worker

  function open(raw: string) {
    try {
      model = new Model(JSON.parse(raw));
      mapText = raw;
      error = null;
      comments = new Comments(model, safeStorage());
      const m = model;
      pins = new Pins(m.map, (id) => m.nodes.has(id), safeStorage());
      trace = null;
      point = null;
      maximized = false;
      container = SITE;
    } catch (e) {
      model = null;
      mapText = null;
      error = e instanceof MapError ? e.message
        : e instanceof SyntaxError ? "This file could not be read as a code map (it is not valid JSON)."
        : "This file could not be read as a code map of this version; rescan the repository.";
    }
  }

  function safeStorage() {
    try { return window.localStorage; } catch { return null; }
  }

  onMount(async () => {
    if (!loadGuideSeen(safeStorage())) { guideNote = true; saveGuideSeen(safeStorage()); }
    const raw = initial();
    if (raw) open(raw);
    if (model) await mountScene();
  });

  function pick(t: Target) {
    target = t; scene?.select(t);
    // a selection narrows motion to its own lines (a line selected: that line alone); nothing selected: the default
    const keys = t === null ? defaultLit(container) : litFor(model!, container, t, (id) => scene!.bundleKeysOf(id), scene?.railKeys());
    scene?.light(keys);
  }

  /** A pick while the trace pane is open (spec A2, A4, A5): any box re-targets the trace in the same direction (a
   *  container through the seeds inside it), a line traces from both its ends; the box the focus is drawn as on this
   *  floor keeps the trace as it is (depth and folds kept); nothing (empty floor), or a line a trace cannot follow,
   *  leaves the trace. With no trace open: an ordinary pick. `named`: a node picked by name (Find, a link: `reveal`),
   *  which keeps the trace only when it is the focus itself (`isFocus`). */
  function choose(t: Target, named = false) {
    if (!trace || !model) { pick(t); return; }
    if (!t) { pick(null); return; }
    if (named ? isFocus(model, trace, t) : ownBox(model, container, trace, t)) return;
    const s = startFor(model, container, t, (k) => scene?.railLine(k));
    if (s) startTrace(s.focus, trace.direction, s.line);
  }

  async function mountScene() {
    await tick();
    if (!host || !model) return;
    scene?.destroy();   // a map opened over another: the old scene's worker and ticker end
    let text = mapText;   // handed to the worker once, then let go: the scene keeps the factory for its lifetime
    mapText = null;
    scene = new FloorScene({
      // a click on empty floor (the one null pick the scene sends) while a layer shows also returns to the base
      select: (t) => { if (t === null && layer !== null) pickLayer(null); choose(t); },
      enter: (id) => go(id),
      up: () => { const p = model!.path(container); if (p.length > 1) go(p[p.length - 2]); },
      door: (anchor) => viaDoor(anchor),
      messaging: (m) => { messagingKinds = m; },
      rails: (r) => { railKinds = r; },
      storage: (s) => { storeKinds = s; },
      layer: (id, lines) => { layer = id; layerLines = lines; if (id === null) layersOpen = false; },
      openLayer: (id) => pickLayer(id),
    }, undefined, (m) => {
      const t = text;
      text = null;
      return t && typeof Worker === "function" ? workerPlanner(m, t, spawnPlanWorker) : mainPlanner(m);
    });
    // nearby floors are planned, and the camera follows a new mark, only while nothing moves; untracked, so the trace
    // effect (which marks the floor) does not run again each time a move ends
    scene.idleGate = () => untrack(() => travelling);
    await scene.init(host);
    resizeWatch?.disconnect();
    resizeWatch = new ResizeObserver(() => scene?.resize());   // the trace pane opening, closing or its divider moving
    resizeWatch.observe(host);
    scene.setReducedMotion(reduced);
    scene.setDronePaths(dronePaths);
    scene.setCodeLinks(codeLinks);
    show(SITE);
    scene.light(defaultLit(SITE));
  }

  /** What moves on floor `c` while nothing is selected: a running trace's own lines (trace/floor.ts), else
   *  floor/lit.ts's default (every line, every floor, every rail's train on the floor the scene shows). */
  const defaultLit = (c: string): string[] => {
    if (!model) return [];
    if (traceView) return traceKeys(model, c, traceItems(model, c, traceView.nodes));
    return litDefault(model, c, scene?.railKeys());
  };

  let resizeWatch: ResizeObserver | null = null;
  let tracePane = $state<{ escape: () => boolean }>();   // the pane's own Esc: its pin form, then its detail panel

  /** Start a trace on `focus`: any map node or floor group, or a line (`line`); the pane opens below
   *  the floor; the floor keeps its zoom, and the selection is cleared so the floor and the pane show one subject. */
  function startTrace(focus: string, direction: PinDirection = "both", line?: LineStart) {
    if (!model || (!line && !traceable(model, focus))) return;
    trace = initialState(focus, direction, line);
    if (target) { target = null; scene?.select(null); }
  }

  /** The pane's own new state: its direction, depth and folds keep the floor as it is; Trace from here, a new focus,
   *  clears the selection as startTrace does. */
  function retrace(st: TraceState) {
    const refocus = st.focus !== trace?.focus;
    trace = st;
    if (refocus && target) { target = null; scene?.select(null); }
  }

  /** Maximize or Restore the pane. On Restore the floor comes back: once its canvas has its size again (two frames, so
   *  the layout has settled), the trace's focus or the selection is centred at the same zoom if it is not wholly in
   *  view, whatever the floor showed before. */
  function toggleMaximized() {
    maximized = !maximized;
    if (!maximized) requestAnimationFrame(() => requestAnimationFrame(() => scene?.resize({ recentre: true })));
  }

  /** What the inspector shows (audit row 64): with the pane open, the item the floor's blue mark is on (the pointed
   *  row's node, else the trace's focus; a line's trace, its line while this floor has it) — shown, not selected, so the
   *  floor and the pane keep one subject; with the pane closed, the selection (nothing: the floor). */
  let shown = $derived<Target>(trace && model
    ? traceSubject(model, trace, point, (k) => {
        const b = model!.bundles(container);
        return b.bundles.some((x) => x.key === k) || b.layered.some((x) => x.key === k) || !!scene?.railLine(k);
      })
    : target);

  function closeTrace() {
    trace = null;
    point = null;
    maximized = false;
    scene?.hoverTrace(null);
  }

  // the floor follows the trace on whatever floor is shown (read every input first: `scene` is a plain let): the items
  // it passes through stay lit, the pointed row's item (else the focus) wears the picked mark, and its lines move. No
  // selection exists while the pane is open (spec A2: any pick re-targets), so the trace always has the floor.
  let markedFocus: string | null = null;   // the focus the floor last marked: a new one is followed by the camera
  let wasTracing = false;
  $effect(() => {
    const v = traceView, c = container, p = point;
    if (!scene || !model) return;
    scene.setTrace(v ? traceItems(model, c, v.nodes) : null);
    // one blue ring (spec A1): the camera follows a pointed row or a new focus, never the ring going back to the focus
    // when a detail closes (ruling R2)
    const focus = v?.state.focus ?? null;
    scene.markTrace(v ? traceMarks(model, c, v.state.focus, p) : [], p !== null || focus !== markedFocus);
    markedFocus = focus;
    if (v || wasTracing) scene.light(defaultLit(c));
    wasTracing = !!v;
  });

  function hoverRow(node: string | null) {
    scene?.hoverTrace(node && model ? (model.liftTo(container, node) ?? null) : null);
  }

  // an empty title falls back to the start's name (a container's qualified name) and the direction, as the pane's form offers it
  function pinTrace(title: string) {
    if (!pins || !trace || !model || !model.nodes.has(trace.focus)) return;   // a line or a group is not pinned (R6)
    const label = traceView ? pinStartName(model, traceView) : model.itemName(trace.focus);
    pins.add(title, trace.focus, trace.direction, defaultTitle(label, trace.direction, pins.list()));
    pinVersion++;
  }

  function unpin(id: string) {
    pins?.remove(id);
    pinVersion++;
  }

  /** A pinned trace from the panel, in its own direction; one whose start is gone does nothing. */
  function playPin(p: ShownPin) {
    if (!p.missing) startTrace(p.start, p.direction);
  }

  /** The divider: drag it, or focus it and press ↑/↓; the place is remembered (for this visit when storage is blocked). */
  function dragSplit(e: PointerEvent) {
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => { split = clampSplit((window.innerHeight - ev.clientY) / window.innerHeight); };
    // released, cancelled (a touch turned into a scroll) or the capture lost: the drag ends where it is, remembered
    const end = () => {
      el.removeEventListener("pointermove", move);
      for (const t of ["pointerup", "pointercancel", "lostpointercapture"] as const) el.removeEventListener(t, end);
      saveSplit(safeStorage(), split);
    };
    el.addEventListener("pointermove", move);
    for (const t of ["pointerup", "pointercancel", "lostpointercapture"] as const) el.addEventListener(t, end);
  }

  function keySplit(e: KeyboardEvent) {
    const d = e.key === "ArrowUp" ? 0.05 : e.key === "ArrowDown" ? -0.05 : 0;
    if (!d) return;
    e.preventDefault();
    split = clampSplit(split + d);
    saveSplit(safeStorage(), split);
  }

  function show(c: string) {
    container = c;
    scene?.show(model!, c);
  }

  function go(c: string, select?: string) {
    if (!model?.floor(c)) return;
    staged(async () => {
      await moveTo(c, select);
      if (select) { if (!trace) scene?.light(scene.bundleKeysOf(select)); }   // with a trace open `choose` picked, and the trace effect lights the floor
      else {
        target = null;
        scene?.light(defaultLit(c));   // a floor shown with nothing selected moves as it should, wherever we came from
      }
    });
  }

  function reveal(id: string) {
    if (!model) return;
    const c = model.floorOf(id) ?? SITE;
    if (c !== container) { go(c, id); return; }
    const t: Target = { type: "node", id };
    if (trace) { choose(t, true); scene?.focus(id, 1.2); }
    else { target = t; scene?.select(target); scene?.focus(id, 1.2); scene?.light(scene.bundleKeysOf(id)); }
  }

  /** Show on floor (spec S3, S7): to the item's own floor, the camera on it; the trace stays the subject, so nothing is
   *  selected — the item is the pane's pointed row and wears the picked mark. */
  function showOnFloor(id: string) {
    if (!model) return;
    maximized = false;
    const c = model.floorOf(id) ?? SITE;
    if (c === container) { scene?.focus(id, 1.2); return; }
    staged(async () => {
      await walkTo(c);
      const s = scene;
      if (s) await s.focusTo(id, Math.max(1, s.fitScaleFor()));
    });
  }

  const pause = (ms: number) => new Promise<void>((r) => setTimeout(r, reduced ? 0 : ms));
  let travelling = $state(false);   // one move at a time: presses during a move are ignored

  /** Floor `c`'s plan ready (scene.ready) while the side panels stay on this floor, so they change floor with the
   *  canvas; false when the floor, map or scene changed during the wait. */
  async function readyFor(c: string): Promise<boolean> {
    const m = model, s = scene, was = container;
    if (!m || !s) return false;
    await s.ready(m, c);
    return model === m && scene === s && container === was;
  }

  /** Come out to floor `c`: the building we leave takes the place of the floor we were on. */
  async function riseTo(c: string) {
    if (c === container || !model || !scene) return;
    if (!(await readyFor(c))) return;
    const from = model.liftTo(c, container);
    container = c;
    await scene.leave(model, c, from);
  }

  /** Go into floor `c` through the building that holds it on this floor, then settle on `node`. */
  async function diveTo(c: string, node?: string) {
    if (!model || !scene) return;
    if (c !== container) {
      if (!(await readyFor(c))) return;
      const down = model.path(c)[model.path(container).length];
      container = c;
      await scene.enter(model, c, down);
    }
    if (!node) return;
    const t: Target = { type: "node", id: node };
    if (trace) choose(t, true);
    else { target = t; scene.select(t); }
    await scene.focusTo(node, Math.max(1, scene.fitScaleFor()));
  }

  /** Any floor change: out to the shared floor, then in. */
  async function moveTo(c: string, node?: string) {
    if (!model) return;
    const shared = model.commonFloor(container, c);
    await riseTo(shared);
    await diveTo(c, node);
  }

  /** A floor change one floor at a time (spec S7), so each floor crossed is seen: out through each floor up to the floor
   *  both share, then in through each floor down. With Still motion, one cut straight there (ruling R12). */
  async function walkTo(c: string) {
    if (!model || c === container) return;
    // a map opened during an await (a plan's wait, a move, a pause) makes a new model and scene: this walk stops there
    const m = model, s = scene;
    const same = () => model === m && scene === s;
    if (reduced) {   // its plan first (scene.ready): the floor list and camera wait, as they would for the move
      await s?.ready(m, c);
      if (same()) show(c);
      return;
    }
    const shared = m.commonFloor(container, c);
    while (container !== shared) {
      const p = m.path(container), was = container;
      await riseTo(p[p.length - 2]);
      if (!same()) return;
      // riseTo does nothing with no scene (or no floor above): stop rather than loop for ever, so `staged` ends and
      // releases `travelling`
      if (container === was) break;
      await pause(250);
      if (!same()) return;
    }
    const down = m.path(c);
    for (let i = m.path(container).length; i < down.length; i++) {
      await diveTo(down[i]);
      if (!same()) return;
      if (i < down.length - 1) await pause(250);
      if (!same()) return;
    }
  }

  let revealAfter: string | null = null;   // a reveal asked for inside a staged move runs once the move ends
  async function staged(run: () => Promise<void>) {
    if (travelling) return;
    travelling = true;
    try { await run(); } finally {
      travelling = false;
      const id = revealAfter; revealAfter = null;
      if (id) reveal(id);
    }
  }

  /** A door leads somewhere else: rise to the shared floor, carry a part from here to there, then go in floor by floor to
   *  the door back on the far side (Model.doorLanding), where the line comes in; with no such floor, stop at `anchor`. */
  function viaDoor(anchor: string) {
    if (!model || !scene) return;
    staged(async () => {
      const shared = model!.commonFloor(container, model!.floorOf(anchor) ?? SITE);
      const a = model!.liftTo(shared, container) ?? container;
      const b = model!.liftTo(shared, anchor);
      if (!b || a === b) { revealAfter = anchor; return; }
      const land = model!.doorLanding(container, anchor);
      await riseTo(shared);
      await pause(300);
      scene!.select({ type: "node", id: a });
      await scene!.travelTo(a, b);
      if (land) {
        const down = model!.path(land.floor);
        for (let i = model!.path(container).length; i < down.length; i++) { await pause(250); await diveTo(down[i]); }
      }
      if (trace) { pick(null); return; }   // with the trace pane open a door moves the reader only: the trace stays the subject
      const end = land?.door ?? b;
      target = { type: "node", id: end };
      scene!.select(target);
      scene!.light(scene!.bundleKeysOf(end));
    });
  }

  /** Drop every comment (after the agent has handled an export): the next export starts clean. */
  function clearComments() {
    if (!comments || !confirm(`Delete all ${comments.all().length} comments and ${pinChanges} pin changes? Save them for the agent first if it has not seen them.`)) return;
    comments.clear();
    pins?.clear();
    commentVersion++;
    pinVersion++;
  }

  async function exportComments() {
    if (!comments) return;
    const pinsMd = pins?.toMarkdown() ?? "";
    const how = await saveExport(comments.toMarkdown() + (pinsMd ? "\n" + pinsMd : ""));
    notice = how === "saved" ? "Saved export-comment.md into the folder you picked." : how === "downloaded" ? "Downloaded export-comment.md — move it next to code-map.json." : null;
    setTimeout(() => (notice = null), 6000);
  }

  function onFile(e: Event) {
    const f = (e.target as HTMLInputElement).files?.[0];
    if (f) f.text().then(async (t) => { open(t); if (model) await mountScene(); });
  }

  function onKey(e: KeyboardEvent) {
    const el = e.target as HTMLElement | null;
    if (el?.closest("input:not([type=radio]),textarea")) return;
    // Esc closes one thing per press: an open layer (or the open list), else in the trace pane its pin form, then its
    // detail panel, then the pane itself (maximized or not), else the selection, as a click on empty floor does
    if (e.key === "Escape") {
      if (layer !== null || layersOpen) pickLayer(null);
      else if (trace) { if (!tracePane?.escape()) closeTrace(); }
      else if (target) pick(null);
      return;
    }
  }

  // read `reduced` first: `scene` is a plain let, so it alone would leave the effect with nothing to track ("Still motion")
  $effect(() => { const still = reduced; scene?.setReducedMotion(still); });
  onDestroy(() => { resizeWatch?.disconnect(); scene?.destroy(); });
</script>

<svelte:window onkeydown={onKey} />

{#if !model}
  <main class="empty">
    <section class="card">
      <h1>Code map</h1>
      {#if error}
        <p class="err" role="alert">{error}</p>
      {/if}
      <p>Open the <code>code-map.json</code> the visualizing-codebases skill wrote (usually <code>docs/viz-code/</code>).</p>
      <label class="pick">
        <input type="file" accept=".json,application/json" onchange={onFile} />
        <span>Open code-map.json</span>
      </label>
    </section>
  </main>
{:else}
  <div class="shell" class:tracing={!!trace} style="--split: {split}">
    <Rail
      {model}
      {container}
      {target}
      commentCount={commentVersion >= 0 ? (comments?.all().length ?? 0) + pinChanges : 0}
      problems={model.map.problems.length}
      bind:reduced
      onGo={(c) => go(c)}
      onReveal={reveal}
      onExport={exportComments}
      onClear={clearComments}
      pins={shownPins}
      onTrace={playPin}
      onUnpin={unpin}
      busy={travelling}
      onProblems={() => (showProblems = !showProblems)}
    />
    <section class="floor" aria-label="Factory floor">
      <!-- with F0's conduits drawn, its legend swaps the implements key for the code-dependency key when F0 draws no
           implements link (the dotted key would name nothing there), so the open legend stays within its 3-row height; with
           no uses-code pair there is no conduit, no toggle, and the legend is as before. While a layer shows, the legend's
           line rows follow it -->
      <Legend compact={container !== SITE} utility={model.legendUtility() !== null} hasImplements={model.drawsImplements() && !(conduitsDrawn && model.implementLinks(SITE).length === 0)} messaging={messagingKinds} rails={railKinds} storage={storeKinds} codeLinks={conduitsDrawn} lines={layerLines} {guide}>
      {#if guideNote}
        <div class="guide-note" role="region" aria-label="Field guide">
          <span>New here? <a href={GUIDE_HREF} target="_blank" rel="noopener">Read the field guide first</a></span>
          <button onclick={dismissGuide}>Dismiss</button>
        </div>
      {/if}
      </Legend>
      <div class="canvas" bind:this={host}></div>
      {#if layers.length && layersOpen}
        <div class="layers-panel" id="layers-panel" role="dialog" aria-label="Layers">
          <h2>Layers on this floor</h2>
          <label><input type="radio" name="layer" checked={layer === null} onchange={() => pickLayer(null)} /> {layerLabel(null)}</label>
          {#each layers as l (l.id)}
            <label title={l.full}><input type="radio" name="layer" checked={layer === l.id} onchange={() => pickLayer(l.id)} /> {listEntry(l)}</label>
          {/each}
        </div>
      {/if}
      <div class="floor-tools">
        {#if layers.length}
          <!-- the label is the shown layer's name (its item's code) exactly as the list has it; on hover the item's full
               name, or on the base the list's own title -->
          <button class="layers-btn" onclick={() => (layersOpen = !layersOpen)} aria-expanded={layersOpen} aria-controls="layers-panel"
            aria-pressed={layer !== null} title={shownLayer?.full ?? "Layers"}
            aria-label="Layers: {layerName} ({layers.length} extra {layers.length === 1 ? 'layer' : 'layers'})">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2L22 8L12 14L2 8Z" fill="currentColor"/><path d="M4.5 12.2L12 16.8L19.5 12.2L22 13.7L12 19.8L2 13.7Z" fill="currentColor"/><path d="M4.5 16.6L12 21.2L19.5 16.6L22 18.1L12 24L2 18.1Z" fill="currentColor" opacity=".9"/></svg>
            <span class="layer-name">{layerName}</span><span class="badge">{layers.length}</span>
          </button>
        {/if}
        <button onclick={toggleDronePaths} aria-pressed={dronePaths}
          title="Show or hide the dotted flight paths of drone lines">Drone paths</button>
        {#if container === SITE && codeLinkPairs > 0}
          <button onclick={toggleCodeLinks} aria-pressed={codeLinks}
            title="Show or hide thin dotted conduits from each service to the code it uses">Code links</button>
        {/if}
        <button onclick={() => scene?.fit()} title="Fit the floor to the view">Fit</button>
      </div>
      {#if notice}<p class="notice" role="status">{notice}</p>{/if}
    </section>
    <div class="side" class:closed={!inspectorOpen}>
      <button class="collapse" onclick={toggleInspector} aria-expanded={inspectorOpen} aria-controls="inspector"
        title={inspectorOpen ? "Hide the inspector" : "Show the inspector"}>
        <svg viewBox="0 0 10 10" aria-hidden="true"><path d={inspectorOpen ? "M3 1 L7 5 L3 9" : "M7 1 L3 5 L7 9"} fill="none" stroke="currentColor" stroke-width="1.8" /></svg>
        {#if !inspectorOpen}<span>Inspector</span>{/if}
      </button>
      {#if inspectorOpen}
        <div id="inspector" class="side-body">
          <Inspector
            {model}
            {container}
            target={shown}
            {comments}
            version={commentVersion}
            onChange={() => commentVersion++}
            onReveal={reveal}
            onEnter={(id) => go(id)}
            railLine={(k) => scene?.railLine(k)}
            onTrace={(id) => startTrace(id, trace?.direction)}
            traced={trace?.focus}
          />
        </div>
      {/if}
    </div>
    {#if trace && traceView && model}
      <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
      <div class="divider" role="separator" aria-orientation="horizontal" aria-label="Resize the trace pane"
        aria-valuemin={20} aria-valuemax={80} aria-valuenow={Math.round(split * 100)} tabindex="0"
        onpointerdown={dragSplit} onkeydown={keySplit}></div>
      <div class="pane" class:max={maximized}>
        {#key trace.focus}
          <TracePane
            bind:this={tracePane}
            {model}
            {container}
            {trace}
            pins={shownPins}
            view={traceView}
            pin={tracePin}
            {maximized}
            onTrace={retrace}
            onHover={hoverRow}
            onPoint={(n) => (point = n)}
            onPin={pinTrace}
            onUnpin={unpin}
            onMaximize={toggleMaximized}
            onClose={closeTrace}
            onReveal={showOnFloor}
          />
        {/key}
      </div>
    {/if}
    {#if showProblems}
      <aside class="problems" aria-label="Problems the scanner could not resolve">
        <header><h2>Problems</h2><button onclick={() => (showProblems = false)}>Close</button></header>
        <ol>
          {#each model.map.problems as p}
            <li>
              {p.text}
              {#each p.nodes ?? [] as n}
                <button class="link" onclick={() => reveal(n)}>{model.codes.get(n) ?? n}</button>
              {/each}
            </li>
          {/each}
          {#each comments?.orphaned() ?? [] as c}
            <li>Comment on <code>{c.target}</code> is orphaned: that node is not in this map.</li>
          {/each}
        </ol>
      </aside>
    {/if}
  </div>
{/if}

<style>
  .shell { position: relative; display: grid; grid-template-columns: 232px 1fr auto; grid-template-rows: minmax(0, 1fr); height: 100vh; overflow: hidden; }
  .shell.tracing { grid-template-rows: minmax(0, 1fr) 8px calc(var(--split) * 100vh); }
  .shell > :global(nav.rail) { grid-row: 1 / -1; }
  .floor, .side { grid-row: 1; }
  .side { position: relative; width: 312px; height: 100%; min-height: 0; display: flex; flex-direction: column; }
  .divider { grid-column: 2 / -1; grid-row: 2; cursor: row-resize; background: var(--page-deep); border-top: 1px solid var(--ink); touch-action: none; }
  .divider:hover, .divider:focus-visible { background: var(--yellow); }
  .pane { grid-column: 2 / -1; grid-row: 3; min-height: 0; }
  .pane.max { position: fixed; inset: 0; z-index: 20; }
  .side.closed { width: 36px; background: var(--page-deep); }
  .side-body { flex: 1; min-height: 0; }
  .collapse { display: flex; align-items: center; gap: 6px; background: var(--ink); color: var(--paper); border: 0; padding: 6px 10px; font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; }
  .collapse svg { width: 10px; height: 10px; flex: none; }
  .closed .collapse { flex-direction: column; height: 100%; padding: 10px 0; justify-content: flex-start; }
  .closed .collapse span { writing-mode: vertical-rl; }
  .collapse:hover { background: var(--blue); }
  .floor { position: relative; min-width: 0; border-left: 1px solid var(--ink); border-right: 1px solid var(--ink); }
  .canvas { position: absolute; inset: 0; }
  .floor-tools { position: absolute; right: 12px; bottom: 12px; display: flex; gap: 6px; }
  .floor-tools button { background: var(--paper); border: 1px solid var(--ink); padding: 5px 10px; font-weight: 600; box-shadow: 6px 6px 0 var(--shade); }
  .floor-tools button:hover { background: var(--yellow); }
  .floor-tools button[aria-pressed="true"] { background: var(--ink); color: var(--paper); }
  .guide-note { display: flex; align-items: center; gap: 12px; background: var(--paper); border: 1px solid var(--ink); box-shadow: 6px 6px 0 var(--shade); padding: 6px 6px 6px 12px; max-width: 46ch; }   /* in the legend's flow, directly under it */
  .guide-note a { color: var(--blue); text-decoration: underline; text-underline-offset: 3px; font-weight: 700; }
  .guide-note button { background: var(--ink); color: var(--paper); border: 0; padding: 4px 8px; font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; }
  .guide-note button:hover { background: var(--blue); }
  .floor-tools button:disabled { opacity: 0.5; cursor: default; }
  .layers-btn { position: relative; display: flex; align-items: center; gap: 6px; }
  .layers-btn svg { width: 16px; height: 16px; flex: none; }
  .layer-name { max-width: 22ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .layers-btn .badge { position: absolute; top: -9px; right: -9px; min-width: 19px; height: 19px; border-radius: 10px; background: var(--red); color: var(--paper); font-size: 11px; font-weight: 700; display: grid; place-items: center; padding: 0 5px; border: 1.5px solid var(--paper); }
  .layers-panel { position: absolute; right: 12px; bottom: 52px; width: 290px; background: var(--paper); border: 1px solid var(--ink); box-shadow: 6px 6px 0 var(--shade); z-index: 3; }
  .layers-panel h2 { font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; margin: 0; padding: 8px 10px; border-bottom: 1px solid var(--shade); color: var(--slate); }
  .layers-panel label { display: flex; gap: 8px; align-items: center; padding: 8px 10px; cursor: pointer; font-size: 13px; font-weight: 600; }
  .layers-panel label:hover { background: var(--page); }
  .layers-panel input { margin: 0; accent-color: var(--ink); }
  .notice { position: absolute; left: 12px; bottom: 12px; margin: 0; background: var(--ink); color: var(--paper); padding: 8px 12px; max-width: 46ch; }
  .problems { position: absolute; left: 232px; top: 0; bottom: 0; width: 380px; background: var(--paper); border-left: 1px solid var(--ink); overflow: auto; padding: 12px 16px; border-right: 1px solid var(--ink); z-index: 4; }
  .problems header { display: flex; justify-content: space-between; align-items: center; }
  .problems h2 { margin: 0; font-size: 16px; }
  .problems li { margin: 8px 0; }
  .link { background: none; border: 0; color: var(--blue); text-decoration: underline; text-underline-offset: 3px; padding: 0 3px; }
  .empty { display: grid; place-items: center; height: 100vh; }
  .card { background: var(--paper); border: 1px solid var(--ink); padding: 28px 32px; max-width: 520px; box-shadow: 6px 6px 0 var(--shade); }
  .card h1 { margin: 0 0 12px; font-size: 34px; font-stretch: 75%; font-weight: 800; letter-spacing: -0.01em; }
  .err { border: 1px solid var(--red); color: var(--red); padding: 8px 10px; }
  .pick { display: inline-block; margin-top: 8px; }
  .pick input { position: absolute; opacity: 0; width: 1px; }
  .pick span { display: inline-block; background: var(--ink); color: var(--paper); padding: 9px 16px; font-weight: 700; cursor: pointer; }
  .pick:focus-within span { outline: 2px solid var(--blue); outline-offset: 2px; }
  .shell { min-width: 1024px; }
</style>
