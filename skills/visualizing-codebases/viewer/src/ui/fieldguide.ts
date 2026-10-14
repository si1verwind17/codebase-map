// The field guide sits beside the map as `field-guide.html`. The map offers it only when that file is there,
// and offers it unasked just once per browser. Storage can be missing or throw (private windows): then the
// first-visit notice comes back on the next visit, which is harmless.

export const GUIDE_HREF = "field-guide.html";

/**
 * Is the guide beside this page? Over http(s) a HEAD `fetch` answers without downloading the file. Under file://
 * a `fetch` or XHR of a sibling is refused in Chromium whatever the file is, so it cannot tell present from
 * absent; a `<link rel=preload as=fetch>` is not subject to that and fires load or error by whether the file
 * opened (checked in Chromium), and it never runs or styles the file, which a stylesheet or script probe would.
 * Any doubt means "no guide".
 */
export function probeGuide(doc: Document = document): Promise<boolean> {
  const web = /^https?:$/.test(doc.location?.protocol ?? "");
  if (web) return fetch(GUIDE_HREF, { method: "HEAD" }).then((r) => r.ok, () => false);
  return new Promise((resolve) => {
    try {
      const link = doc.createElement("link");
      let timer: ReturnType<typeof setTimeout> | undefined;
      const end = (found: boolean) => { clearTimeout(timer); link.remove(); resolve(found); };
      link.rel = "preload";
      link.as = "fetch";
      link.onload = () => end(true);
      link.onerror = () => end(false);
      link.href = GUIDE_HREF;
      doc.head.append(link);
      timer = setTimeout(() => end(false), 5000);   // a probe that never answers is a guide that is not offered
    } catch {
      resolve(false);
    }
  });
}

const SEEN = "code-map.guide-seen";

/** The first-visit notice shows once: it is marked seen when it is first shown, not when dismissed; blocked storage means it shows every visit. */
export function loadGuideSeen(store: Pick<Storage, "getItem"> | null): boolean {
  try { return store?.getItem(SEEN) === "yes"; } catch { return false; }
}

export function saveGuideSeen(store: Pick<Storage, "setItem"> | null): void {
  try { store?.setItem(SEEN, "yes"); } catch { /* blocked: it lasts for this visit only */ }
}
