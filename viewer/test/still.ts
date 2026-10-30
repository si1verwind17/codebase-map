// Still motion sits in the rail's Settings panel: open it, set the box, close the panel again (Esc closes only the panel).
import type { Page } from "playwright-core";

export async function setStill(page: Page, on: boolean) {
  await page.getByRole("button", { name: "Settings" }).click();
  const box = page.getByLabel("Still motion");
  if (on) await box.check(); else await box.uncheck();
  await page.keyboard.press("Escape");
}
