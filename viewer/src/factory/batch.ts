// src/factory/batch.ts
// The batch picture of one floor, pure: a yard per scheduler, holding a platform per destination it runs jobs on
// and the jobs it runs on itself, signed with a schedule summary. Layout, painting and trains read this; nothing here
// draws. Facts come from the map's batch relations (schedule: cron, "manual" or "on <event>"; job: its name), lifted
// to this floor with the same lift bundles() uses.
import type { Bundle, Model } from "../model/model";
import { SITE } from "../model/model";
import type { Relation } from "../model/types";
import type { TileFloor } from "./layout";

export interface Job { relation: string; job: string; schedule: string[] | null; target: string }   // target = node id
export interface Platform { dest: string; jobs: Job[]; runsPerDay: number | null }                  // dest = item id on this floor
/** source = item id on this floor, or the container id when inner (the scheduler is the floor itself or above it). */
export interface Yard { source: string; platforms: Platform[]; selfJobs: Job[]; sign: string; inner: boolean }
export interface Batch { yards: Yard[] }

const byStr = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
const byJob = (p: Job, q: Job) => byStr(p.job, q.job) || byStr(p.relation, q.relation);

/** `bundles` is taken for symmetry with messaging(); a scheduler's jobs on itself and an inner yard's jobs never form
 *  bundles, so the relations are read from the map with the same lift. */
export function batch(model: Model, container: string, tf: TileFloor, _bundles: Bundle[]): Batch {
  const onSite = container === SITE;
  const lift = (id: string) => model.liftTo(container, id) ?? (onSite ? undefined : model.doorId(model.anchorFor(container, id)));
  const above = new Set(onSite ? [] : model.path(container));   // the container and its ancestors
  const yards = new Map<string, { inner: boolean; dests: Map<string, Job[]>; self: Job[] }>();

  for (const r of model.map.relations) {
    if (r.kind !== "batch") continue;
    const dest = lift(r.to);
    if (!dest || !tf.boxes.has(dest)) continue;
    let source: string | undefined, inner = false;
    if (above.has(r.from) && model.liftTo(container, r.from) === undefined) {
      // an ancestor's job on this floor only when it lands on an item here; the floor's own service may also send one out
      if (r.from !== container && model.liftTo(container, r.to) === undefined) continue;
      source = container; inner = true;
    }
    else {
      source = model.liftTo(container, r.from);
      if (!source || !tf.boxes.has(source)) continue;
    }
    const y = yards.get(source) ?? { inner, dests: new Map<string, Job[]>(), self: [] as Job[] };
    yards.set(source, y);
    const j = jobOf(r);
    if (!inner && dest === source) y.self.push(j);
    else y.dests.set(dest, [...(y.dests.get(dest) ?? []), j]);
  }

  return {
    yards: [...yards.entries()].sort(([p], [q]) => byStr(p, q)).map(([source, y]) => {
      const platforms = [...y.dests.entries()].sort(([p], [q]) => byStr(p, q))
        .map(([dest, jobs]) => ({ dest, jobs: jobs.sort(byJob), runsPerDay: knownRuns(jobs) }));
      const selfJobs = y.self.sort(byJob);
      return { source, platforms, selfJobs, sign: summarise([...selfJobs, ...platforms.flatMap((p) => p.jobs)]), inner: y.inner };
    }),
  };
}

/** A platform's worth of jobs for `dest` from these batch relations (a yard-less station's, its scheduler off the floor). */
export function platformOf(dest: string, relations: Relation[]): Platform {
  const jobs = relations.filter((r) => r.kind === "batch").map(jobOf).sort(byJob);
  return { dest, jobs, runsPerDay: knownRuns(jobs) };
}

function jobOf(r: Relation): Job {
  return { relation: r.id, job: r.job ?? r.key ?? r.id, schedule: r.schedule ?? null, target: r.to };
}

/** Sum of the known runs a day of these jobs, or null when none is known. */
function knownRuns(jobs: Job[]): number | null {
  let sum = 0, any = false;
  for (const j of jobs) for (const s of j.schedule ?? []) {
    const n = runsPerDay(s);
    if (n !== null) { sum += n; any = true; }
  }
  return any ? sum : null;
}

// ---- cron ----

const DOW = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
const MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const DOW_NAME = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

interface Cron { minute: string; hour: string; dom: string; month: string; dow: string }

/** The five fields of a cron line (a six-field line drops its seconds), or null when it is not one. */
function fields(cron: string): Cron | null {
  const f = cron.trim().split(/\s+/).filter(Boolean);
  if (f.length === 6) f.shift();
  if (f.length !== 5) return null;
  const [minute, hour, dom, month, dow] = f;
  return { minute, hour, dom, month, dow };
}

const wild = (f: string) => f === "*" || f === "?";

/** The values a cron field fires on, or null when it does not parse. */
function values(field: string, min: number, max: number, names: string[] = [], nameBase = 0): Set<number> | null {
  const num = (s: string): number | null => {
    const i = names.indexOf(s.toLowerCase());
    if (i >= 0) return i + nameBase;
    if (!/^\d+$/.test(s)) return null;
    const n = Number(s);
    return n >= min && n <= max ? n : null;
  };
  const out = new Set<number>();
  for (const part of field.split(",")) {
    const [base, stepS, extra] = part.split("/");
    if (extra !== undefined || base === "") return null;
    const step = stepS === undefined ? 1 : /^\d+$/.test(stepS) ? Number(stepS) : 0;
    if (step < 1) return null;
    let lo: number | null, hi: number | null;
    if (wild(base)) { lo = min; hi = max; }
    else if (base.includes("-")) {
      const [a, b, more] = base.split("-");
      if (more !== undefined) return null;
      lo = num(a); hi = num(b);
    } else { lo = num(base); hi = stepS === undefined ? lo : max; }
    if (lo === null || hi === null || lo > hi) return null;
    for (let v = lo; v <= hi; v += step) out.add(v);
  }
  return out.size ? out : null;
}

function parse(c: Cron): { minutes: Set<number>; hours: Set<number>; doms: Set<number> | null; months: Set<number> | null; dows: Set<number> | null } | null {
  const minutes = values(c.minute, 0, 59), hours = values(c.hour, 0, 23);
  const doms = wild(c.dom) ? null : values(c.dom, 1, 31);
  const months = wild(c.month) ? null : values(c.month, 1, 12, MON, 1);
  let dows = wild(c.dow) ? null : values(c.dow, 0, 7, DOW);
  if (!minutes || !hours || (!wild(c.dom) && !doms) || (!wild(c.month) && !months) || (!wild(c.dow) && !dows)) return null;
  if (dows?.has(7)) { dows = new Set([...dows].map((d) => d % 7)); }
  return { minutes, hours, doms, months, dows };
}

/** How many times a day a schedule fires: a fraction for a weekly (1/7 per listed weekday) or monthly (1/30 per listed
 *  day) one. Null for "manual", "on <event>" and anything that is not a cron line. */
export function runsPerDay(cron: string): number | null {
  const c = fields(cron);
  const p = c && parse(c);
  if (!p) return null;
  let perDay = p.minutes.size * p.hours.size;
  // cron fires when either day field matches if both are restricted
  if (p.dows && p.doms) perDay *= Math.min(1, p.dows.size / 7 + p.doms.size / 30);
  else if (p.dows) perDay *= p.dows.size / 7;
  else if (p.doms) perDay *= p.doms.size / 30;
  if (p.months) perDay *= p.months.size / 12;
  return perDay;
}

// ---- signs ----

const pad = (n: number) => String(n).padStart(2, "0");
const single = (s: Set<number>) => (s.size === 1 ? [...s][0] : null);
const isDemand = (s: string) => s.trim().toLowerCase() === "manual";
const isEvent = (s: string) => /^on\s+\S/i.test(s.trim());

/** A cron line in words: "daily 02:00", "hourly :05", "every 15 min", "weekly Mon 01:00"; else its runs. */
function phrase(cron: string): string {
  const c = fields(cron);
  const p = c && parse(c);
  if (!c || !p) return cron.trim() || "on demand";
  const m = single(p.minutes), h = single(p.hours);
  const anyDay = !p.doms && !p.dows && !p.months;
  if (anyDay && wild(c.hour)) {
    const step = /^\*\/(\d+)$/.exec(c.minute);
    if (wild(c.minute)) return "every minute";
    if (step && 60 % Number(step[1]) === 0) return `every ${step[1]} min`;   // */45 fires at :00 and :45, not every 45 min
    if (m !== null) return `hourly :${pad(m)}`;
  }
  if (m !== null && h !== null && !p.months) {
    const at = `${pad(h)}:${pad(m)}`;
    if (anyDay) return `daily ${at}`;
    if (p.dows && !p.doms) return `weekly ${[...p.dows].sort((a, b) => a - b).map((d) => DOW_NAME[d]).join(",")} ${at}`;
    if (p.doms && !p.dows) return `monthly day ${[...p.doms].sort((a, b) => a - b).join(",")} ${at}`;
  }
  return rate(runsPerDay(cron) ?? 0) ?? cron.trim();
}

/** A run count as a rate, never 0: per day, else per week, else per month; null when it is nothing at all. */
export function rate(perDay: number): string | null {
  if (perDay >= 1) return `${Math.round(perDay)}×/day`;
  if (Math.round(perDay * 7) >= 1) return `${Math.round(perDay * 7)}×/week`;
  if (Math.round(perDay * 30) >= 1) return `${Math.round(perDay * 30)}×/month`;
  return perDay > 0 ? "<1×/month" : null;
}

/** The yard's sign: one job reads its schedule in words; several read "N jobs · K×/day", with "+ on demand" when some
 *  have no schedule. Never empty, never "0×/day". */
export function summarise(jobs: Job[]): string {
  if (jobs.length === 0) return "no jobs";
  if (jobs.length === 1) {
    const s = (jobs[0].schedule ?? []).filter((x) => x.trim());
    if (s.length === 0 || s.every(isDemand)) return "on demand";
    if (s.length === 1) return isEvent(s[0]) ? s[0].trim().replace(/\s+/g, " ") : phrase(s[0]);
  }
  let sum = 0, known = false, demand = false, events = false;
  for (const j of jobs) {
    const s = (j.schedule ?? []).filter((x) => x.trim());
    if (s.length === 0 || s.every(isDemand)) { demand = true; continue; }
    for (const x of s) {
      const n = runsPerDay(x);
      if (n !== null) { sum += n; known = true; }
      else if (isEvent(x)) events = true;
      else if (isDemand(x)) demand = true;
    }
  }
  const tail = [...(demand ? ["on demand"] : []), ...(events ? ["on events"] : [])];
  const head = known ? rate(sum) : null;
  const what = jobs.length === 1 ? `${(jobs[0].schedule ?? []).length} schedules` : `${jobs.length} jobs`;
  if (head) return [`${what} · ${head}`, ...tail].join(" + ");
  if (tail.length) return `${what} · ${tail.join(" + ")}`;
  return what;
}
