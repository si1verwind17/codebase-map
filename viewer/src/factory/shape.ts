// A piece's geometry, apart from drawing so it can be tested: centre, the two edges it joins, their shared corner.
import { OPP, STEP, T, type Piece } from "./tiles";

export type V = [number, number];

export function shape(p: Piece) {
  const x = p.x * T, y = p.y * T, cx = x + T / 2, cy = y + T / 2;
  const inEdge = [...STEP[OPP[p.in]]] as V;    // travelling east enters through the west edge
  const outEdge = [...STEP[p.out]] as V;
  const straight = p.in === p.out;
  const corner: V = [x + (inEdge[0] + outEdge[0] > 0 ? T : 0), y + (inEdge[1] + outEdge[1] > 0 ? T : 0)];
  const edge = (e: V): V => [cx + (e[0] * T) / 2, cy + (e[1] * T) / 2];
  return { x, y, cx, cy, inEdge, outEdge, straight, corner, edge };
}
