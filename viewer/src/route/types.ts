// The pixel shapes of a floor (rectangles, machines, the geometry the factory layout fills) and of a routed line, shared by the floor scene and the factory router.

export interface Rect { x: number; y: number; w: number; h: number }
export interface Machine extends Rect { id: string; kind: string }
export interface FloorGeometry { machines: Map<string, Machine>; bounds: Rect }

export interface Pt { x: number; y: number }
export interface Route { key: string; points: Pt[]; tap?: string }
