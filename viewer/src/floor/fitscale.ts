// The zoom that fits a floor in the canvas: shared by the scene's Fit and the readability test.

/** Floor bounds `w`×`h` px in a `screenW`×`screenH` canvas, `bottomInset` px kept clear at the bottom. Inside floors keep
 *  a 120 px pad round them; every floor keeps 60 px for its title and a 0.94 margin. Unclamped. */
export function fitScale(w: number, h: number, screenW: number, screenH: number, site: boolean, bottomInset = 0): number {
  const pad = site ? 0 : 120;
  return Math.min(screenW / (w + pad), (screenH - bottomInset) / (h + pad + 60)) * 0.94;
}

/** The Fit zoom's limits: the scene never fits a floor further out than FIT_MIN or further in than FIT_MAX. */
export const FIT_MIN = 0.12, FIT_MAX = 1.4;
export const clampFit = (s: number) => Math.max(FIT_MIN, Math.min(FIT_MAX, s));
/** The zoom the scene's Fit picks (`fitScale`, clamped): what the map audit measures against the names/codes switch. */
export function fitZoom(w: number, h: number, screenW: number, screenH: number, site: boolean, bottomInset = 0): number {
  return clampFit(fitScale(w, h, screenW, screenH, site, bottomInset));
}
