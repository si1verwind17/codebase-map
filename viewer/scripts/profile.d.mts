// Types for the part of scripts/profile.mjs that test/perf/model.bench.ts imports.
import type { CodeMap } from "../src/model/types";

export function relationsInside(map: CodeMap): Map<string, number>;
export function pickTargets(map: CodeMap): { service: string; serviceLabel: string; cold: string; coldLabel: string };
