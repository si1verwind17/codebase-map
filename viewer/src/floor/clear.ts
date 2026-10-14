// Emptying a layer must free what it held: removeChildren() alone keeps every Graphics and Text alive.
import type { Container } from "pixi.js";

/** Remove and destroy every child except those in `keep` (e.g. a part still travelling). */
export function clearLayer(layer: Container, keep: (Container | undefined)[] = []): void {
  const spare = new Set(keep.filter(Boolean));
  for (const child of layer.removeChildren()) {
    if (spare.has(child)) layer.addChild(child);
    else child.destroy({ children: true });
  }
}
