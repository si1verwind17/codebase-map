// The field guide is published on the project's site; the map links to it and offers it unasked just once per
// browser. Storage can be missing or throw (private windows): then the first-visit notice comes back on the next
// visit, which is harmless.

export const GUIDE_HREF = "https://si1verwind17.github.io/codebase-map/";

const SEEN = "code-map.guide-seen";

/** The first-visit notice shows once: it is marked seen when it is first shown, not when dismissed; blocked storage means it shows every visit. */
export function loadGuideSeen(store: Pick<Storage, "getItem"> | null): boolean {
  try { return store?.getItem(SEEN) === "yes"; } catch { return false; }
}

export function saveGuideSeen(store: Pick<Storage, "setItem"> | null): void {
  try { store?.setItem(SEEN, "yes"); } catch { /* blocked: it lasts for this visit only */ }
}
