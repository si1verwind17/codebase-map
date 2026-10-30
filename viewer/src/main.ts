import fontUrl from "@fontsource-variable/archivo/files/archivo-latin-wdth-normal.woff2?url";
import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";
import { THEME } from "./floor/palette";

document.documentElement.dataset.theme = THEME;

async function start() {
  try {
    const face = new FontFace("Archivo", `url(${fontUrl})`, { weight: "100 900", stretch: "62% 125%" });
    document.fonts.add(await face.load());
  } catch {
    /* the system sans stands in; layout does not depend on the face */
  }
  // the map's text leaves the page as it is read, and App takes it once: after parsing only the model holds the map
  const el = document.getElementById("code-map");
  let raw: string | null = el?.textContent?.trim() ?? "";
  if (el) el.textContent = "";
  if (!raw || raw.startsWith("/*")) raw = null;
  const initial = () => { const t = raw; raw = null; return t; };
  mount(App, { target: document.getElementById("app")!, props: { initial } });
}

start();
