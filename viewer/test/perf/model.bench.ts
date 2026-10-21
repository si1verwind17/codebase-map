// What the viewer's model and floor planner cost on the synthetic big map (scripts/big_map.py; npm run profile writes
// it to .profile/). Not part of the suite: `npx vitest bench --run test/perf`. Skips without the map.
import { existsSync, readFileSync } from "node:fs";
import { test } from "vitest";
import { Model } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor } from "../../src/factory/plan";
import { methodsIn } from "../../src/trace/entries";
import { pickTargets } from "../../scripts/profile.mjs";

const BIG = new URL("../../.profile/big.code-map.json", import.meta.url);
const map: CodeMap | null = existsSync(BIG) ? JSON.parse(readFileSync(BIG, "utf8")) : null;
const RUNS = { time: 0, iterations: 5, warmupIterations: 1 };   // the slow ones take ~0.5 s: a few runs give a steady median

test.skipIf(!map)("model and planner on the big map", async ({ bench }) => {
  const { service, cold } = pickTargets(map!);   // the busiest service, and its busiest floor
  const warm = new Model(map!);
  const { doors, bundles, layered } = warm.bundles(cold);
  let fresh = warm;
  const anew = { beforeEach: () => { fresh = new Model(map!); } };   // each run on a model that has seen nothing
  const doorShows = () => { for (const d of doors) fresh.doorShows(cold, d.anchor); };
  await bench.compare(
    bench("new Model", () => new Model(map!)),
    bench("bundles, cold", anew, () => fresh.bundles(cold)),
    bench("bundles, warm", () => warm.bundles(cold)),
    bench(`doorShows × ${doors.length} doors, cold`, anew, doorShows),
    bench("planFloor, cold", anew, () => planFloor(fresh, cold, doors, bundles, layered)),
    bench("relationsOf service", () => warm.relationsOf(service)),
    bench("methodsIn service", () => methodsIn(warm, service)),
    bench("search, each prefix of “account”", () => { for (let i = 1; i <= 7; i++) warm.search("account".slice(0, i), 12); }),
    RUNS,
  );
});
