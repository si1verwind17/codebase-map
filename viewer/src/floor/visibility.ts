// The hidden-tab pause: the ticker stops while the page is hidden and starts again when it shows. Browsers already stop
// animation frames in a hidden tab and Pixi caps a frame's elapsed time, but the explicit pause guarantees motion never
// jumps to catch up on return, and covers a page embedded where frames keep coming. Motion never pauses after idle:
// it is part of the reviewed look.

/** The part of `document` the pause reads (a fake in tests). */
export interface VisibilitySource {
  readonly visibilityState: DocumentVisibilityState;
  addEventListener(t: "visibilitychange", f: () => void): void;
  removeEventListener(t: "visibilitychange", f: () => void): void;
}

/** Stops `ticker` while `doc` is hidden (at once if it already is) and starts it when it shows; a repeated event in the
 *  same state does nothing. Returns the undo, which removes the listener only: it does not restart a ticker it
 *  stopped, as it is meant for `destroy`. */
export function pauseWhenHidden(doc: VisibilitySource, ticker: { start(): void; stop(): void }): () => void {
  let hidden = false;
  const sync = () => {
    const now = doc.visibilityState === "hidden";
    if (now === hidden) return;
    hidden = now;
    if (hidden) ticker.stop(); else ticker.start();
  };
  doc.addEventListener("visibilitychange", sync);
  sync();
  return () => doc.removeEventListener("visibilitychange", sync);
}
