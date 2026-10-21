// The factory floor, drawn with PixiJS: keylined machines, belts, pipes, drone paths, tracks, the bus.
// The scene's state lives in one SceneState (state.ts); the camera (camera.ts), the shared drawing helpers (draw.ts),
// the factory drawing (factory-draw.ts), the labels (labels.ts), the pointer wiring (wiring.ts), selection and lighting
// (selection.ts) and the floor transitions and travel (transitions.ts) are plain functions over it. This class is the
// shell: it draws a floor in order, runs the movers and the ticker, and delegates the rest.
import type { Model } from "../model/model";
import { floorLayers, type LayerId } from "../model/layers";
import type { Rect } from "../route/types";
import { clearLayer } from "./clear";
import { at } from "./movers";
import { floorPrefix } from "./names";
import { C, F } from "./palette";
import { toGeometry } from "../factory/layout";
import { planJob } from "../factory/plan-job";
import { flightKeepOff } from "../factory/flights";
import { createRunner, idleScheduler, nextFloors, type Deadline, type Runner, type Scheduler } from "./precompute";
import { mainPlanner, type Planner } from "./planner";
import type { RailLine, TrainPath } from "../factory/rail-place";
import { createState, type SceneEvents, type SceneState, type Target } from "./state";
import * as cam from "./camera";
import { drawFactory, zoomBadges } from "./factory-draw";
import { linesRead, measuring, syncLabels, textsRead, wordsRead } from "./labels";
import * as selection from "./selection";
import * as transitions from "./transitions";
import { pauseWhenHidden } from "./visibility";

export type { SceneEvents, Target } from "./state";

export class FloorScene {
  /** Every field the scene keeps between frames; the modules share this one object. */
  private readonly s: SceneState;

  /** Plans the nearby floors one idle slice at a time (precompute.ts). */
  private readonly precompute: Runner;
  /** True while something else is moving (App's travelling flag: a floor move); no plan runs then. */
  idleGate: () => boolean = () => false;
  /** Plans the floors not shown yet (planner.ts): made on the first `show`, for its model. */
  private planner: Planner | null = null;
  private plannerFor: Model | null = null;
  /** Plan jobs asked of the planner and not yet answered, on the canvas as `data-plan-jobs` (tests wait for 0). */
  private jobs = 0;
  private gone = false;
  private unpause = () => {};   // undoes the hidden-tab pause (init)
  /** The floor `ready` last waited for a plan for: its `show` reports no plan hit. */
  private waited: string | null = null;
  /** The floors whose bundles and door landings the page's model holds already (`warm`), for `warmedFor`. */
  private warmed = new Set<string>();
  private warmedFor: Model | null = null;

  constructor(events: SceneEvents, private readonly schedule: Scheduler = idleScheduler, private readonly planners: (m: Model) => Planner = mainPlanner) {
    this.s = createState(events);
    this.precompute = createRunner({
      schedule,
      busy: () => this.idleGate() || !!this.s.traveller || !!this.s.tween || this.s.fading !== null,
      planned: (c) => this.s.plans.has(c),
      plan: (c) => {
        const model = this.s.model;
        if (!model) return;
        return this.ask(model, c, false).then(() => this.showPlans(), () => this.showPlans());
      },
      warm: (c) => !!this.s.model && this.warm(this.s.model, c),
      onSettled: () => this.showPlans(),
    });
  }

  /** Works out floor `c`'s bundles and its doors' landings on the page's model, as `show`, its first draw and the
   *  inspector need them: the worker's model caches its own and cannot share them, so entering a floor would pay for
   *  them in the press task. True when there was work to do. */
  private warm(model: Model, c: string): boolean {
    if (this.warmedFor !== model) { this.warmed.clear(); this.warmedFor = model; }
    if (this.warmed.has(c) || !model.floor(c)) return false;
    this.warmed.add(c);
    const b = model.bundles(c);
    for (const d of b.doors) model.doorLanding(c, d.anchor);
    return true;
  }

  get app() { return this.s.app; }
  /** One path per rail on this floor, platform to buffer stop (the trains run them). */
  get trainPaths(): TrainPath[] { return this.s.trainPaths; }
  /** Screen pixels kept clear at the bottom (room for a bottom panel), so focus centres above it. */
  get bottomInset() { return this.s.bottomInset; }
  set bottomInset(px: number) { this.s.bottomInset = px; }

  async init(host: HTMLElement) {
    await this.app.init({ resizeTo: host, background: C.page, antialias: true, resolution: window.devicePixelRatio || 1, autoDensity: true });
    this.app.canvas.setAttribute("role", "img");
    this.app.canvas.setAttribute("aria-label", "Factory floor of the code map; use the floor list for keyboard access");
    host.appendChild(this.app.canvas);
    this.app.stage.addChild(this.s.world, this.s.overlay);   // overlay: the box that carries the reader between floors
    for (const l of Object.values(this.s.layers)) this.s.world.addChild(l);
    this.app.stage.eventMode = "static";
    this.app.stage.hitArea = this.app.screen;
    cam.setupCamera(this.s);
    this.app.ticker.add((t) => this.tick(t.deltaMS));
    if (!this.gone) this.unpause = pauseWhenHidden(document, this.app.ticker);   // no motion, and no catch-up jump, while the tab is hidden (none once destroyed)
  }

  setReducedMotion(on: boolean) {
    this.s.reduced = on;
    if (this.s.model) this.draw();
  }

  show(model: Model, container: string, fade = false) {
    this.s.model = model;
    this.s.container = container;
    this.warm(model, container);   // a no-op when idle time did it; marks it done when it did not (the draw needs it all)
    const b = model.bundles(container);
    this.s.doors = new Map(b.doors.map((d) => [d.id, d]));
    this.s.bundles = b.bundles;
    this.s.layered = b.layered;
    this.s.floorLayers = floorLayers(model, container);
    this.s.layer = null;   // a floor change resets to the base
    // tests: this floor's plan was ready, not waited for (`ready`) nor made here
    this.app.canvas.dataset.planHit = String(this.s.plansFor === model && this.s.plans.has(container) && this.waited !== container);
    this.waited = null;
    const plan = this.planOf(model, container, b);
    this.s.tf = plan.tf;
    this.s.geo = toGeometry(plan.tf);
    this.s.routes = plan.routes;
    this.s.selected = null;
    this.draw();
    cam.fit(this.s, false);
    this.s.depthQuietUntil = performance.now() + 600;
    if (fade) transitions.startFade(this.s, 380);
    this.plannerOf(model);   // after the first floor is drawn: the worker starts once the page shows something
    this.queueNearby();
  }

  /** Floor `container` of `model` planned and cached, so `show` draws it at once: at once when it is cached, else from
   *  the planner ahead of any queued floor. The camera reads "moving" while it waits (the old floor stays drawn and
   *  moving). A plan that fails is left to `show`, which plans it here and fails as it always did. */
  async ready(model: Model, container: string): Promise<void> {
    if (this.s.plansFor === model && this.s.plans.has(container)) return;
    this.app.canvas.dataset.camera = "moving";
    this.waited = container;
    this.s.planWaits++;   // a camera ease ending meanwhile leaves the flag at "moving" (camera.ts): the show that follows rests it
    const unwarm = this.warmWhileIdle(model, container);   // the main thread idles while the worker plans
    try { await this.ask(model, container, true); } catch { /* show plans it */ } finally { this.s.planWaits--; unwarm(); }
  }

  /** `warm` floor `c` in an idle slice that has time left (the scene's scheduler), trying again until it runs; returns
   *  a way to cancel it. */
  private warmWhileIdle(model: Model, c: string): () => void {
    let cancel = () => {};
    const slice = (d?: Deadline) => {
      if (d && !(d.timeRemaining() > 0)) { cancel = this.schedule(slice); return; }
      cancel = () => {};
      this.warm(model, c);
    };
    cancel = this.schedule(slice);
    return () => cancel();
  }

  /** Floor `container`'s plan from the planner, cached when it is still for the scene's model. */
  private async ask(model: Model, container: string, urgent: boolean): Promise<void> {
    const planner = this.plannerOf(model);
    this.jobs++;
    this.showJobs();
    try {
      const plan = await planner.plan(container, urgent);
      if (this.s.plansFor === model && !this.gone) this.s.plans.set(container, plan);
    } finally {
      this.jobs--;
      this.showJobs();
    }
  }

  private plannerOf(model: Model): Planner {
    if (!this.planner || this.plannerFor !== model) {
      this.planner?.dispose();
      this.planner = this.planners(model);
      this.plannerFor = model;
    }
    this.app.canvas.dataset.planner = this.planner.where;   // tests: the worker started (or the page fell back)
    return this.planner;
  }

  private showJobs() {
    if (!this.gone) this.app.canvas.dataset.planJobs = String(this.jobs);
  }

  // A model change always makes a new scene that calls show(), so the queue never outlives its model.
  /** This floor's plan, from the cache when it is there (planning is slow on busy floors: once per container and model).
   *  Planned here, on the main thread, only when no one waited for it (`ready`): the first floor, a node test. */
  private planOf(model: Model, container: string, b = model.bundles(container)) {
    if (this.s.plansFor !== model) { this.s.plans.clear(); this.s.plansFor = model; }
    let plan = this.s.plans.get(container);
    if (!plan) { plan = planJob(model, container, b); this.s.plans.set(container, plan); }
    return plan;
  }

  /** Plan the floors one step from this one while the viewer is idle, the selected machine's floor first. Without a
   *  worker, the selected floor and the parent only: planning on the main thread is the freeze the worker avoids. */
  private queueNearby() {
    const { model, container, selected } = this.s;
    if (!model) return;
    const limit = this.plannerOf(model).where === "main" ? 0 : undefined;
    this.precompute.start(nextFloors(model, container, selected?.type === "node" ? selected.id : undefined, limit));
    this.showPlans();
  }

  /** Floors planned and floors still queued, on the canvas for tests. */
  private showPlans() {
    this.app.canvas.dataset.plans = String(this.s.plans.size);
    this.app.canvas.dataset.plansQueued = String(this.precompute.pending);
  }

  /** The keys of this floor's rails that a train runs (stand-in `rail:` keys among them), for the default lit set
   *  (floor/lit.ts). */
  railKeys(): string[] {
    return selection.railKeys(this.s);
  }

  /** Which bundles carry moving parts (App's `defaultLit` with nothing selected, a selection's lines otherwise). */
  light(keys: Iterable<string>) {
    selection.light(this.s, keys);
    this.buildMovers();
  }

  /** A node picked (on the floor, from the find list, the inspector) whose lines on this floor
   *  are all in an extra layer opens that layer, so its lines show; a node with any base line leaves the layer as is. */
  select(t: Target) {
    const open = t?.type === "node" ? selection.layerOnlyOf(this.s, t.id) : undefined;
    selection.select(this.s, t);
    if (t?.type === "node") this.queueNearby();   // the selected machine's floor goes first
    if (open && open !== this.s.layer) this.setLayer(open);
    else this.showLayer();
  }

  /** Whether `t` has no line left to see once layer `layer` closes (the App then clears the selection). */
  liveOnlyIn(t: Target, layer: LayerId): boolean { return selection.liveOnlyIn(this.s, t, layer); }

  /** A trace runs (spec §3.2): `items` are the items on this floor it passes through (trace/floor.ts), null when it
   *  closes or a selection takes the floor (spec S2). The camera does not move. Nothing to change: no restyle. */
  setTrace(items: ReadonlySet<string> | null) {
    if (!items && !this.s.traced && !this.s.traceHover && !this.s.traceMarked.size) return;
    this.s.traced = items;
    if (!items) { this.s.traceHover = null; this.s.traceMarked = new Set(); }   // a closed trace leaves no ring behind
    selection.restyle(this.s);
  }

  /** The item standing for the trace pane's hovered row wears the selection ring (null: none). */
  hoverTrace(id: string | null) {
    if (this.s.traceHover === id) return;
    this.s.traceHover = id;
    selection.restyle(this.s);
  }

  /** The item wearing the picked mark for the running trace (spec A1): the row pointed at in the pane, else its focus,
   *  lifted to this floor (trace/floor.ts `traceMarks`); [] for none. `follow`: a new mark out of view brings the camera
   *  to it — false when the ring only returns to the focus (a detail closed), which leaves the floor where it is. */
  markTrace(ids: readonly string[], follow = true) {
    const now = this.s.traceMarked;
    if (ids.length === now.size && ids.every((id) => now.has(id))) return;
    const fresh = ids.filter((id) => !now.has(id));
    this.s.traceMarked = new Set(ids);
    selection.restyle(this.s);
    // a new mark out of view (owner comment 60: a clicked row seemed to do nothing): the camera pans to it at the same
    // zoom; one in view leaves the camera still. Never while the floor changes or the camera already moves: those
    // moves place the camera themselves.
    const id = fresh.at(-1);
    if (follow && id && !this.s.tween && !this.idleGate() && cam.inView(this.s, id) === false) cam.panTo(this.s, id, true);
  }

  /** What the camera keeps in view as the canvas shrinks: the floor's selected box, else the trace's first mark (its
   *  focus when on this floor). */
  private keptInView(): string | undefined {
    const sel = this.s.selected;
    if (sel?.type === "node") return sel.id;
    for (const id of this.s.traceMarked) if (this.s.geo?.machines.has(id)) return id;
    return undefined;
  }

  private centreKept = false;
  /** The next size change keeps the zoom and the world point at the canvas centre (the inspector shown or hidden,
   *  audit row 65), rather than the top-left corner and the selection in view. */
  keepCentre() {
    this.centreKept = true;
  }

  /** The host changed size (the trace pane opened, closed or its divider moved): resize the canvas, keep the zoom. The
   *  selection, or the trace's focus, in view before and covered now is centred again at the same zoom, at once.
   *  `recentre` (the pane restored from maximized): centred whenever it is not wholly in view, wherever it was before. */
  resize(opts: { recentre?: boolean } = {}) {
    const keep = this.keptInView();
    const was = keep !== undefined && cam.inView(this.s, keep) === true;
    const w0 = this.app.screen.width, h0 = this.app.screen.height;
    this.app.resize();
    const dw = this.app.screen.width - w0, dh = this.app.screen.height - h0;
    if (this.centreKept && (dw || dh)) {   // the inspector shown or hidden: the same zoom, the same point at the centre
      this.centreKept = false;
      if (!this.s.tween) { this.s.world.position.set(this.s.world.x + dw / 2, this.s.world.y + dh / 2); cam.markZoom(this.s); }
      return;
    }
    if (keep && (was || opts.recentre) && cam.inView(this.s, keep) === false && !this.s.tween && !this.idleGate()) cam.panTo(this.s, keep, false);
  }

  /** Show or hide the dotted flight paths (and their hit areas). Drones still fly; a selected path stays visible. */
  setDronePaths(on: boolean) {
    this.s.dronePaths = on;
    selection.applyDronePaths(this.s);
  }

  /** On F0: show or hide the code-dependency conduits. Kept across floors; drawn only on F0. */
  setCodeLinks(on: boolean) {
    this.s.codeLinks = on;
    selection.applyCodeLinks(this.s);
    if (measuring()) { linesRead(this.s); this.s.textsZoom = 0; delete this.app.canvas.dataset.textsZoom; }   // tests: the conduits' paths as now drawn
  }

  /** Show one of this floor's extra layers (spec §15), or the base (null). Moving parts follow it. */
  setLayer(id: LayerId | null) {
    selection.setLayer(this.s, id);
    if (measuring()) { linesRead(this.s); this.s.textsZoom = 0; delete this.app.canvas.dataset.textsZoom; }   // tests: the lines and words of the layer now shown
    this.buildMovers();
    this.showLayer();
  }

  /** The shown layer for the App (button and legend) and its facts on the canvas for tests: `data-layer` (the id, absent
   *  on the base), `data-layers` (each extra layer as `id:count`), `data-used-by` (each badge as `item:N`),
   *  `data-peek` (a box selected on the base: how many of its layer lines are drawn over it, absent when none),
   *  `data-layer-lit` (the shown layer's lines at full strength), `data-base-alpha` (the strongest base line view, as
   *  drawn), `data-base-lit` (with a layer shown: the base lines at full strength, by key) and `data-machines-dim`
   *  (buildings drawn under full strength; `data-dimmed` names them). */
  private showLayer() {
    const st = this.s, ds = this.app.canvas.dataset;
    st.events.layer?.(st.layer, selection.layerLines(st));
    if (st.layer) ds.layer = st.layer; else delete ds.layer;
    const peek = selection.peekCount(st);
    if (peek) ds.peek = String(peek); else delete ds.peek;
    ds.layers = st.floorLayers.map((l) => `${l.id}:${l.count}`).join(" ");
    ds.usedBy = st.floorLayers.filter((l) => l.usedBy > 0).map((l) => `${l.item}:${l.usedBy}`).join(" ");
    const shown = st.layer ? st.layerViews.get(st.layer) : undefined;
    ds.layerLit = String(shown ? [...shown.lineViews.values()].filter((vs) => vs.length && vs.every((v) => v.alpha === 1)).length : 0);
    let base = 0;
    for (const vs of st.lineViews.values()) for (const v of vs) base = Math.max(base, v.alpha);
    ds.baseAlpha = String(base);
    // the base lines at full strength under a shown layer (a selected box's own), by key
    if (shown) ds.baseLit = [...st.lineViews].filter(([, vs]) => vs.length && vs.every((v) => v.alpha === 1)).map(([k]) => k).sort().join(" ");
    else delete ds.baseLit;
    const dim = [...st.machineViews].filter(([, v]) => v.alpha < 1).map(([id]) => id).sort();
    ds.dimmed = dim.join(" ");
    ds.machinesDim = String(dim.length);
  }

  /** One part carried along the line from `from` to `to` (both items on this floor), then `done`.
   *  `straight`: along the straight centre-to-centre line (the dotted implements link), no route and no ghost connector. */
  travel(from: string, to: string, done?: () => void, payload?: string, opts: { straight?: boolean } = {}) {
    transitions.travel(this.s, from, to, done, payload, opts);
  }

  travelTo(from: string, to: string, payload?: string, opts: { straight?: boolean } = {}): Promise<void> {
    return transitions.travelTo(this.s, from, to, payload, opts);
  }

  /** Zoom toward a building before going inside it. */
  zoomInto(id: string): Promise<void> {
    return transitions.zoomInto(this.s, id);
  }

  /** Go inside `building` (on this floor) to `container` (transitions.ts), once its plan is ready. */
  async enter(model: Model, container: string, building?: string): Promise<void> {
    await this.ready(model, container);
    if (!this.gone) await transitions.enter(this.s, (m, c) => this.show(m, c), model, container, building);
  }

  /** Come out to `container`, shrinking this page back into its building on the floor above (transitions.ts), once its
   *  plan is ready. */
  async leave(model: Model, container: string, from?: string): Promise<void> {
    await this.ready(model, container);
    if (!this.gone) await transitions.leave(this.s, (m, c) => this.show(m, c), model, container, from);
  }

  focusTo(id: string, zoom: number): Promise<void> {
    return cam.focusTo(this.s, id, zoom);
  }

  /** The zoom that fits this floor; kept so a travelling part can stay in view. */
  fitScaleFor() {
    return cam.fitScaleFor(this.s);
  }

  /** The host changed size without a window resize (a side panel opened or closed): resize, then fit. */
  fit(animate = true) {
    cam.fit(this.s, animate);
  }

  /** Zoom toward a machine (used before entering it, and to follow a travelling part). */
  focus(id: string, zoom = 1.6, done?: () => void) {
    cam.focus(this.s, id, zoom, done);
  }

  machineRect(id: string): Rect | undefined {
    return this.s.geo?.machines.get(id);
  }

  /** `a` and `b` are joined by a dotted implements link on this floor (a travelling part may follow it). */
  hasImplementsLink(a: string, b: string): boolean {
    return selection.implementsLink(this.s, a, b);
  }

  bundleKeysOf(id: string): string[] {
    return selection.bundleKeysOf(this.s, id);
  }

  /** A stand-in rail (`rail:` key) or a yard (`yard:<source>`) as the inspector shows it. */
  railLine(key: string): RailLine | undefined {
    return selection.railLine(this.s, key);
  }

  // ------------------------------------------------------------------ drawing
  private draw() {
    const { model, geo, tf } = this.s;
    if (!model || !geo || !tf) return;
    const cut = this.s.traveller;   // a part from the floor being replaced: finish its caller, then free it
    this.s.traveller = null;
    cut?.done?.();
    for (const l of Object.values(this.s.layers)) clearLayer(l);
    this.s.layers.frame.clear();
    this.s.machineViews.clear();
    this.s.lineViews.clear();
    this.s.droneViews.clear();
    this.s.conduits = [];   // their layer was just cleared
    this.s.usedBadges = [];
    this.s.highlights.clear();
    this.s.hoverRings.clear();
    this.s.implLinks = [];
    this.s.implViews.clear();
    this.s.flights = [];
    this.s.covered = new Set();
    this.s.msgSmalls = [];
    this.s.replicaTags = new Map();
    this.s.railExtra = new Map();
    this.s.webhookDocks = [];
    this.s.railZoomed = () => {};
    this.s.trunkTip = { hide: () => {}, shownAt: null };   // its card went with the cleared layers
    this.s.dockTip = { hide: () => {}, shownAt: null };    // and the dock's
    this.s.trainPaths = [];
    delete this.app.canvas.dataset.railTip;
    delete this.app.canvas.dataset.dockTip;
    delete this.app.canvas.dataset.trunkTip;
    this.s.openTabs.clear();
    this.s.doorHints.clear();
    this.s.nameTags.clear();
    this.s.codeParts = [];
    this.s.minName = 14;
    this.s.tagWanted.clear();
    this.s.zoomLabels = [];
    this.s.layers.overlay.clear();
    this.s.smoke = null;
    this.s.sharedPrefix = floorPrefix(model, [...geo.machines.values()].filter((m) => m.kind !== "door").map((m) => m.id));
    drawFactory(this.s, model, geo, tf, () => selection.restyle(this.s));
    this.buildMovers();
    selection.restyle(this.s);
    this.s.labelZoom = 0;
    this.s.labelScaled = 0;
    this.s.textsZoom = 0;
    syncLabels(this.s, true);
    zoomBadges(this.s, this.s.world.scale.x);
    wordsRead(this.s);
    selection.setLayer(this.s, this.s.layer);   // a redraw keeps the shown layer (a floor change has reset it)
    selection.applyCodeLinks(this.s);
    if (measuring()) linesRead(this.s);
    this.showLayer();
  }

  // ------------------------------------------------------------------ motion
  private buildMovers() {
    const tr = this.s.traveller;   // a part on its way keeps going while the lit lines change
    clearLayer(this.s.layers.motion, tr ? [tr.g, tr.tag, tr.temp] : []);
    const land = this.s.tf?.landing;
    if (this.s.layer !== null && !this.s.selected) {   // a layer shows, nothing selected: its lines alone carry parts
      const l = this.s.layerViews.get(this.s.layer);
      this.s.motion.build({ routes: l?.routes ?? [], bundles: l?.bundles ?? [], lit: this.s.lit, covered: new Set(), reduced: this.s.reduced });
    } else if (this.s.layer !== null) {   // and a selection: its lines, layer and base alike, as restyle lights them
      const l = this.s.layerViews.get(this.s.layer);   // (layer and base keys never overlap: model.bundles splits them)
      this.s.motion.build({
        routes: [...this.s.routes, ...(l?.routes ?? [])], bundles: [...this.s.bundles, ...(l?.bundles ?? [])], lit: this.s.lit,
        covered: this.s.covered, reduced: this.s.reduced, trains: this.s.trainPaths,
        ...(land ? { drones: { flights: this.s.flights, messaging: land.messaging, stacks: land.stacks, keepOff: flightKeepOff(this.s.tf!) } } : {}),
        tags: this.s.replicaTags,
      });
    } else this.s.motion.build({
      routes: this.s.routes, bundles: this.s.bundles, lit: this.s.lit, covered: this.s.covered, reduced: this.s.reduced,
      trains: this.s.trainPaths,
      ...(land ? { drones: { flights: this.s.flights, messaging: land.messaging, stacks: land.stacks, keepOff: flightKeepOff(this.s.tf!) } } : {}),
      tags: this.s.replicaTags,
    });
    this.showMotion();
  }

  /** The drone clock and count on the canvas, for tests: written on every build, then about once a
   *  second as the drones fly (`ms`: the frame's time), never every frame. */
  private showMotion(ms?: number) {
    const ds = this.app.canvas.dataset;
    if (!this.s.tf) { delete ds.droneClock; delete ds.drones; delete ds.trains; delete ds.lit; return; }
    if (ms !== undefined) {
      this.s.motionShown += ms;
      if (this.s.motionShown < 1000) return;
    }
    this.s.motionShown = 0;
    const clock = this.s.motion.clock.toFixed(1), n = String(this.s.motion.drones), trains = String(this.s.motion.trains);
    if (ds.droneClock !== clock) ds.droneClock = clock;
    if (ds.drones !== n) ds.drones = n;
    if (ds.trains !== trains) ds.trains = trains;   // scheduled trains, running or waiting at an end; parked ones (Still motion) excluded
    const shown = this.s.layer === null ? [] : (this.s.layerViews.get(this.s.layer)?.bundles ?? []);   // the shown layer's while one shows,
    const lines = this.s.layer === null ? this.s.bundles : this.s.selected ? [...this.s.bundles, ...shown] : shown;   // with the base's under a selection
    if (ms === undefined) ds.lit = String(lines.filter((b) => this.s.lit.has(b.key)).length);   // lines lit on this floor (tests read it): on build only
  }

  private tick(ms: number) {
    if (this.s.tf && this.s.world.scale.x !== this.s.labelZoom) {   // a float compare per frame; the work runs only when the zoom moved
      syncLabels(this.s);
      selection.zoomConduits(this.s);
      zoomBadges(this.s, this.s.world.scale.x);
    } else if (this.s.tf && this.s.textsZoom !== this.s.labelZoom && measuring()) textsRead(this.s);   // tests: once the zoom rests, the words as they settled
    cam.stepTween(this.s, ms);
    const w = this.s.world;   // the trunk and dock cards stand on the floor: a camera move hides them
    for (const tip of [this.s.trunkTip, this.s.dockTip]) {
      const at = tip.shownAt;
      if (at && (at[0] !== w.x || at[1] !== w.y || at[2] !== w.scale.x)) tip.hide();
    }
    if (this.s.fading !== null) {           // cross-fade in a freshly shown floor
      this.s.fading = Math.min(1, this.s.fading + ms / this.s.fadeMs);
      this.s.world.alpha = 1 - Math.pow(1 - this.s.fading, 3);
      if (this.s.fading >= 1) this.s.fading = null;
    }
    if (this.s.traveller) {
      const tr = this.s.traveller;
      tr.t = Math.min(1, tr.t + ms / tr.ms);
      const e = tr.t < 0.5 ? 2 * tr.t * tr.t : 1 - Math.pow(-2 * tr.t + 2, 2) / 2;
      const total = tr.lengths[tr.lengths.length - 1];
      const g = tr.g.clear();
      for (let k = 5; k >= 0; k--) {        // a short fading trail behind the part
        const p = at(tr.pts, tr.lengths, total * e - k * 9);
        g.rect(p.x - 6, p.y - 6, 12, 12).fill({ color: C.yellow, alpha: k ? 0.16 * (6 - k) / 6 : 1 });
      }
      const p = at(tr.pts, tr.lengths, total * e);
      g.rect(p.x - 7, p.y - 7, 14, 14).fill(C.yellow).stroke({ width: 2, color: C.ink });
      tr.tag?.position.set(p.x + 12, p.y - 26);
      if (tr.t >= 1) { const d = tr.done; tr.g.destroy(); tr.tag?.destroy(); tr.temp?.destroy(); this.s.traveller = null; d?.(); }
    }
    if (this.s.smoke && !this.s.smoke.destroyed) {
      const g = this.s.smoke.clear();
      if (!this.s.reduced && this.s.tf) {
        this.s.smokeT = (this.s.smokeT + ms) % 3200;
        const s = this.s.world.scale.x, sw = this.app.screen.width, sh = this.app.screen.height;
        for (const c of this.s.chimneys) {
          if (this.s.idle.has(c.id)) continue;   // an unrelated factory rests while another is selected
          const sx = this.s.world.x + c.x * s, sy = this.s.world.y + c.y * s;
          if (sx < -60 || sy < -60 || sx > sw + 60 || sy > sh + 60) continue;   // off screen: no work
          for (let k = 0; k < 2; k++) {
            const t = (this.s.smokeT / 3200 + k / 2) % 1;
            g.circle(c.x, c.y - 4 - t * 24, 3 + t * 6).fill({ color: F.rule, alpha: 0.9 * (1 - t) });
          }
        }
      }
    }
    if (this.s.reduced) return;
    this.s.motion.tick(ms);
    this.showMotion(ms);
  }

  destroy() {
    this.gone = true;
    this.unpause();
    this.precompute.stop();   // a queued idle slice must not touch the app once it is gone
    this.planner?.dispose();  // the worker ends; a floor change still waiting on it goes on to nothing (enter, leave)
    this.app.destroy(true, { children: true });
  }
}
