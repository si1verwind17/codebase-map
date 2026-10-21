// Everything a floor scene holds between frames, in one object the scene's modules share (camera.ts, draw.ts, …).
// The maps and sets here are the scene's own: modules read and write them through this object, never through copies.
import { Application, Container, Graphics } from "pixi.js";
import type { Bundle, Model } from "../model/model";
import { SITE } from "../model/model";
import type { FloorGeometry } from "../route/types";
import type { Pt, Route } from "../route/types";
import { Motion, type ReplicaTag } from "./movers";
import type { TileFloor } from "../factory/layout";
import type { TileRoute } from "../factory/router";
import type { ZoomLabel } from "../factory/ground";
import type { FlightPath, MessagingLabels, MessagingLegend } from "../factory/flights";
import type { RailLabels, RailLegend, TrainPath } from "../factory/rail-place";
import type { StoreLegend } from "../factory/machines";
import type { Piece } from "../factory/tiles";
import type { BadgeSpot, PxRect } from "../factory/clear";
import type { FloorLayer, LayerBundle, LayerId } from "../model/layers";

/** A floor's plan and the messaging worked out from it on its first draw (flight paths, the routes they replace, label
 *  obstacles, placed labels, legend examples): kept per container and model. */
export interface FloorPlan {
  tf: TileFloor;
  routes: TileRoute[];
  msg?: { flights: FlightPath[]; covered: Set<string>; obstacles: PxRect[]; labels?: MessagingLabels; legend?: MessagingLegend | null };
  rail?: RailLabels;   // the sign texts and station labels, placed after the messaging labels on the first draw
  layers?: Partial<Record<LayerId, { routes: TileRoute[] }>>;   // each extra layer's lines (factory/plan.ts)
  badges?: Map<string, BadgeSpot>;   // each `used by N` badge's spot, placed after the labels on the first draw
}

export type Target = { type: "node"; id: string } | { type: "bundle"; key: string } | null;

export interface SceneEvents {
  /** A box or line picked on the floor; null only for a click on empty floor. */
  select(t: Target): void;
  enter(id: string): void;
  up(): void;
  door(anchor: string): void;
  /** The current floor's messaging, for the legend (null on a floor without). */
  messaging?(m: MessagingLegend | null): void;
  /** The current floor's rail parts, for the legend (null on a floor without). */
  rails?(r: RailLegend | null): void;
  /** The current floor's cache and bucket art, for the legend (null on a floor without). */
  storage?(s: StoreLegend | null): void;
  /** The layer shown now (null: the base) and the line kinds it draws, for the layers button and the legend; sent on
   *  every change, a floor change's reset to the base among them. */
  layer?(id: LayerId | null, lines: LayerLines | null): void;
  /** A `used by N` badge was pressed: show that layer. */
  openLayer?(id: LayerId): void;
}

/** The line kinds a shown layer draws, for the legend's line rows (each row only when the layer has it). */
export interface LayerLines { belt?: true; pipe?: true; rail?: true; drone?: true; tap?: true; under?: true; inferred?: true; plate?: true; both?: true; failed?: true }

/** One extra layer as drawn on this floor: its container above the base lines (hidden unless shown), its line views by
 *  bundle key, its routes and its lines. */
export interface LayerView { box: Container; lineViews: Map<string, Container[]>; routes: TileRoute[]; bundles: LayerBundle[]; lines: LayerLines }

export interface SceneState {
  readonly app: Application;
  readonly events: SceneEvents;
  world: Container;
  // moving parts draw above tags: nothing may hide what is travelling
  // conduits: the F0 code-dependency overlay, above the floor and under the lines (their junction plates), machines and tags.
  // layered: the extra layers' lines, above the base lines (a shown layer is never covered by its faint background) and
  // under the selection overlay, machines and tags
  layers: { frame: Graphics; lanes: Container; conduits: Container; lines: Container; layered: Container; overlay: Graphics; machines: Container; tags: Container; motion: Container };
  lineViews: Map<string, Container[]>;
  dronePaths: boolean;
  droneViews: Map<string, Container[]>;   // a drone route's line and hit area, by bundle key
  /** The extra layer shown now (spec §15), null for the base; a floor change resets it. */
  layer: LayerId | null;
  /** This floor's extra layers (model/layers.ts `floorLayers`), its lines kept out of the base, and each hub layer as drawn. */
  floorLayers: FloorLayer[];
  layered: LayerBundle[];
  layerViews: Map<LayerId, LayerView>;
  /** The `used by N` badges on this floor's heavily used items (they keep a readable size as the zoom moves). */
  usedBadges: { view: Container; maxK: number }[];
  /** On F0: the code-dependency overlay is on (the reader's toggle), and its conduits as drawn (built only
   *  while it is on, cleared with the floor). */
  codeLinks: boolean;
  conduits: { user: string; used: string; g: Graphics; points: [{ x: number; y: number }, { x: number; y: number }] }[];
  conduitBlocked: PxRect[];   // the floor labels' boxes the conduits break off around
  conduitZoom: number;        // the zoom the conduits were last painted for
  highlights: Map<string, Graphics>;
  hoverRings: Map<string, Graphics>;   // a trace pane row's hover (thin ink), apart from the picked mark
  implLinks: { key: string; trait: string; impl: string }[];   // trait ↔ implementation on this floor
  implViews: Map<string, Graphics>;
  // messaging: the flight paths drawn instead of the machine→hub drone routes they replace (`covered`)
  flights: FlightPath[];
  covered: Set<string>;
  msgSmalls: { objs: Container[]; size: number }[];   // plates, tags and signs: the 9 px rule, hidden in codes mode
  replicaTags: Map<string, ReplicaTag>;   // `N replicas` tags by their take's tagKey: they pulse as crates land
  webhookDocks: { machine: string; objs: Container[] }[];   // each webhook dock's views (dock, face words): restyle reports them lit or faded
  railExtra: Map<string, Piece[]>;   // a rail's yard link and siding, by its key: the selection highlight covers them
  railZoomed: (z: number) => void;   // the rail hover list keeps its readable size as the zoom moves
  /** The trunk hover card (trunk-hover.ts): hide it, and the camera (x, y, zoom) it was placed for while it shows. */
  trunkTip: CardTip;
  /** The webhook dock's hover card (messaging-paint.ts `paintWebhooks`), hidden by a camera move as the trunk card is. */
  dockTip: CardTip;
  /** One path per rail on this floor, platform to buffer stop (Task 4's trains run them). */
  trainPaths: TrainPath[];
  geo: FloorGeometry | null;
  routes: Route[];
  tf: TileFloor | null;
  plans: Map<string, FloorPlan>;   // planFloor is slow on busy floors: once per container and model
  plansFor: Model | null;
  chimneys: { id: string; x: number; y: number }[];
  windows: Map<string, { lit: Graphics; dark: Graphics }>;
  idle: Set<string>;
  smoke: Graphics | null;
  smokeT: number;
  bundles: Bundle[];
  motion: Motion;
  motionShown: number;   // ms since the drone clock was last written on the canvas
  model: Model | null;
  container: string;
  reduced: boolean;
  selected: Target;
  /** The items a running trace passes through on this floor (null: no trace): they stay lit, the rest fade. */
  traced: ReadonlySet<string> | null;
  /** The item standing for the row hovered in the trace pane: it wears the selection ring. */
  traceHover: string | null;
  /** The items wearing the picked mark for the running trace (its focus, the row pointed at in the pane): the ring. */
  traceMarked: ReadonlySet<string>;
  lit: Set<string>;       // bundle keys that carry moving parts
  machineViews: Map<string, Container>;
  overlay: Container;
  tween: { from: [number, number, number]; to: [number, number, number]; t: number; ms: number; done?: () => void } | null;
  planWaits: number;   // floor changes waiting on a plan (scene.ready): the camera reads "moving" until they end
  fading: number | null;
  doors: Map<string, { anchor: string; side: "in" | "out" }>;
  openTabs: Map<string, Container>;
  doorHints: Map<string, Container>;
  // zoomed far out the machines show their short codes (see syncLabels); a hovered or selected one shows its full name
  nameTags: Map<string, Container>;
  codeParts: { names: Container[]; big: Container; smalls: { objs: Container[]; size: number }[] }[];
  minName: number;               // the smallest machine or door name drawn on this floor, in world px: the codes switch is derived from it
  tagWanted: Set<Container>;   // hovered or selected machines: their full-name tag shows while the roof name is hidden
  zoomLabels: ZoomLabel[];
  codeMode: boolean;
  labelZoom: number;       // the zoom the labels were last synced at
  labelScaled: number;     // and the zoom the zone and lane labels were last resized at
  textsZoom: number;       // and the zoom the words were last measured at (labels.ts `textsRead`, for tests)
  traveller: { pts: Pt[]; lengths: number[]; t: number; ms: number; g: Graphics; done?: () => void; tag?: Container; temp?: Graphics } | null;
  lastTap: { id: string; at: number } | null;
  /** Screen pixels kept clear at the bottom (room for a bottom panel), so focus centres above it. */
  bottomInset: number;
  sharedPrefix: string;
  depthQuietUntil: number;
  fadeMs: number;
}

/** A hover card that stands on the floor: hide it, and the camera (x, y, zoom) it was placed for while it shows (the
 *  scene's tick hides it once the camera moves). */
export interface CardTip { hide(): void; shownAt: [number, number, number] | null }

/** The world's layers, bottom to top: the scene adds them to the world in this order. */
export function createLayers() {
  const layers = { frame: new Graphics(), lanes: new Container(), conduits: new Container(), lines: new Container(), layered: new Container(), overlay: new Graphics(), machines: new Container(), tags: new Container(), motion: new Container() };
  // nothing in the moving parts or the selection overlay takes a click: drawn above the lines' hit areas, they would
  // otherwise catch a press (Pixi tests every shape under the interactive stage) and hand it to the stage, which clears
  layers.motion.eventMode = "none";
  layers.overlay.eventMode = "none";
  layers.conduits.eventMode = "none";   // a conduit has no click and no hover
  return layers;
}

export function createState(events: SceneEvents): SceneState {
  // created in the order the class fields once were: app, world, layers, …, motion, overlay
  const app = new Application();
  const world = new Container();
  const layers = createLayers();
  const motion = new Motion(layers.motion);
  const overlay = new Container();
  return {
    app,
    events,
    world,
    layers,
    lineViews: new Map(),
    dronePaths: true,
    droneViews: new Map(),
    codeLinks: false,
    layer: null,
    floorLayers: [],
    layered: [],
    layerViews: new Map(),
    usedBadges: [],
    conduits: [],
    conduitBlocked: [],
    conduitZoom: 0,
    highlights: new Map(),
    hoverRings: new Map(),
    implLinks: [],
    implViews: new Map(),
    flights: [],
    covered: new Set(),
    msgSmalls: [],
    replicaTags: new Map(),
    webhookDocks: [],
    railExtra: new Map(),
    railZoomed: () => {},
    trunkTip: { hide: () => {}, shownAt: null },
    dockTip: { hide: () => {}, shownAt: null },
    trainPaths: [],
    geo: null,
    routes: [],
    tf: null,
    plans: new Map(),
    plansFor: null,
    chimneys: [],
    windows: new Map(),
    idle: new Set(),
    smoke: null,
    smokeT: 0,
    bundles: [],
    motion,
    motionShown: 0,
    model: null,
    container: SITE,
    reduced: false,
    selected: null,
    traced: null,
    traceHover: null,
    traceMarked: new Set(),
    lit: new Set(),
    machineViews: new Map(),
    overlay,
    tween: null,
    planWaits: 0,
    fading: null,
    doors: new Map(),
    openTabs: new Map(),
    doorHints: new Map(),
    nameTags: new Map(),
    codeParts: [],
    minName: 14,
    tagWanted: new Set(),
    zoomLabels: [],
    codeMode: false,
    labelZoom: 0,
    labelScaled: 0,
    textsZoom: 0,
    traveller: null,
    lastTap: null,
    bottomInset: 0,
    sharedPrefix: "",
    depthQuietUntil: 0,
    fadeMs: 380,
  };
}

export function hasFloor(st: SceneState, id: string) {
  const home = real(st, id);
  return !!st.model?.floor(home) && Object.keys(st.model.floor(home)!.items).length > 0;
}

/** A twin (a module this service also deploys) opens the floor where its code really sits. */
export function real(st: SceneState, id: string) {
  return st.model?.twinOf(id) ?? id;
}
