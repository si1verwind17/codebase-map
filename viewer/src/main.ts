import fontUrl from "@fontsource-variable/archivo/files/archivo-latin-wdth-normal.woff2?url";
import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";

async function start() {
  try {
    const face = new FontFace("Archivo", `url(${fontUrl})`, { weight: "100 900", stretch: "62% 125%" });
    document.fonts.add(await face.load());
  } catch {
    /* the system sans stands in; layout does not depend on the face */
  }
  const raw = document.getElementById("code-map")?.textContent?.trim() ?? "";
  const initial = raw && !raw.startsWith("/*") ? raw : null;
  mount(App, { target: document.getElementById("app")!, props: { initial } });
}

start();
