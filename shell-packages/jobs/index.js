// shell-packages/jobs: scheduled jobs that run inside a tool's API, and the one contract every tool uses to show
// them on the console Scheduled jobs tab.
//
// A tool registers each job in code with a daily time in Eastern time. The time lives in code, so a timing change
// is a pull request. The on/off switch and the last run live in the tool's own database (table scheduled_jobs,
// created here on start), so an admin pauses or resumes a job live from the console.
//
// Every TICK_MS the runner claims a due occurrence with one UPDATE that moves last_run_at past the occurrence, so
// two instances never run the same one and a restart never runs it twice. An occurrence missed by more than
// CATCH_UP_MS (the API was down) waits for the next day.
//
// The tool serves GET /jobs and PUT /jobs/:id through jobRoutes() and names that path in its console manifest
// (jobs.path). The console reads it with the tool's own token, the same way it reads What's new.

export const ZONE = "America/New_York";
export const TICK_MS = 5 * 60 * 1000;
export const FIRST_TICK_MS = 2 * 60 * 1000;
export const CATCH_UP_MS = 3 * 60 * 60 * 1000;
const ID_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const AT_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

/**
 * @typedef {{ query: (text: string, params?: unknown[]) => Promise<{ rows: any[] }> }} Db
 * @typedef {{
 *   id: string, name: string, description: string, at: string, source: string,
 *   defaultEnabled?: boolean, run: () => Promise<Record<string, unknown>>
 * }} JobDef
 *   at is "HH:MM" Eastern time, every day. source is the repository path that sets the time.
 * @typedef {{
 *   id: string, name: string, description: string, engine: "app", schedule: string, at: string, zone: string,
 *   source: string, enabled: boolean, updatedBy: string | null, updatedAt: string | null, lastRunAt: string | null,
 *   lastStatus: string | null, lastResult: unknown, finishedAt: string | null, nextRunAt: string | null
 * }} JobView
 */

/** Minutes the zone is ahead of UTC at an instant (negative for Eastern). @param {Date} d */
function zoneOffsetMinutes(d) {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: ZONE, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(d).map((x) => [x.type, x.value]));
  const asUtc = Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour), Number(p.minute), Number(p.second));
  return Math.round((asUtc - Math.floor(d.getTime() / 1000) * 1000) / 60000);
}

/** The Eastern calendar date of an instant. @param {Date} d */
function easternDate(d) {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: ZONE, year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(d).map((x) => [x.type, x.value]));
  return { y: Number(p.year), m: Number(p.month), day: Number(p.day) };
}

/** The instant of HH:MM Eastern on the Eastern date of `now`, plus `addDays`. @param {string} at @param {Date} now @param {number} [addDays] */
export function occurrence(at, now, addDays = 0) {
  const { y, m, day } = easternDate(now);
  const [hh, mm] = at.split(":").map(Number);
  const guess = new Date(Date.UTC(y, m - 1, day + addDays, hh, mm));
  // Read the offset at the guess, then at the corrected instant, so a daylight saving change day lands right.
  const first = new Date(guess.getTime() - zoneOffsetMinutes(guess) * 60000);
  return new Date(guess.getTime() - zoneOffsetMinutes(first) * 60000);
}

/** The next run after `now`. @param {string} at @param {Date} [now] */
export function nextRun(at, now = new Date()) {
  const today = occurrence(at, now);
  return today.getTime() > now.getTime() ? today : occurrence(at, now, 1);
}

/** "Every day at 3:30 AM Eastern". @param {string} at */
export function describeDaily(at) {
  const hh = Number(at.slice(0, 2));
  const mm = Number(at.slice(3, 5));
  const h12 = hh % 12 === 0 ? 12 : hh % 12;
  return `Every day at ${h12}:${String(mm).padStart(2, "0")} ${hh < 12 ? "AM" : "PM"} Eastern`;
}

/** @param {unknown} v */
const iso = (v) => (v instanceof Date ? v.toISOString() : typeof v === "string" ? v : null);

/**
 * One scheduler per API.
 * @param {{ db: Db, tool: string, log?: (msg: string) => void, offEnv?: string }} o
 *   offEnv names the environment variable that stops the runner on an instance when it is "off" (default JOBS).
 */
export function createScheduler(o) {
  if (!o || !o.db || typeof o.db.query !== "function") throw new Error("createScheduler needs a db with query()");
  if (!ID_RE.test(String(o.tool || ""))) throw new Error("createScheduler needs the tool id");
  const log = o.log || ((/** @type {string} */ m) => console.warn(m));
  /** @type {Map<string, JobDef>} */
  const registry = new Map();
  /** @type {Promise<void> | null} */ let ready = null;
  /** @type {ReturnType<typeof setInterval> | null} */ let timer = null;
  /** @type {ReturnType<typeof setTimeout> | null} */ let first = null;

  function ensure() {
    if (!ready) {
      ready = o.db.query(`CREATE TABLE IF NOT EXISTS scheduled_jobs (
        id text PRIMARY KEY, enabled boolean NOT NULL DEFAULT true, updated_by text, updated_at timestamptz,
        last_run_at timestamptz, last_status text, last_result jsonb, finished_at timestamptz)`)
        // skip_until: turning a job on after its time today skips that occurrence without faking a last run.
        .then(() => o.db.query("ALTER TABLE scheduled_jobs ADD COLUMN IF NOT EXISTS skip_until timestamptz"))
        .then(() => undefined);
      ready.catch(() => { ready = null; });
    }
    return ready;
  }

  /** @param {JobDef} job */
  function register(job) {
    if (!ID_RE.test(String(job.id || ""))) throw new Error(`job id ${job.id} must be lowercase kebab-case`);
    if (!AT_RE.test(String(job.at || ""))) throw new Error(`job ${job.id}: at must be HH:MM, Eastern time`);
    if (!job.name || !job.description || !job.source || typeof job.run !== "function") throw new Error(`job ${job.id}: name, description, source and run are required`);
    if (registry.has(job.id)) throw new Error(`job ${job.id} is registered twice`);
    registry.set(job.id, job);
  }

  /** @param {any} r @param {JobDef} j */
  const isOn = (r, j) => (r ? r.enabled === true : j.defaultEnabled !== false);

  /** Every job with its row. A job without a row reads as its default. @returns {Promise<JobView[]>} */
  async function list() {
    await ensure();
    const { rows } = await o.db.query("SELECT id, enabled, updated_by, updated_at, last_run_at, last_status, last_result, finished_at FROM scheduled_jobs");
    const byId = new Map(rows.map((r) => [r.id, r]));
    return [...registry.values()].map((j) => {
      const r = byId.get(j.id);
      const enabled = isOn(r, j);
      return {
        id: j.id, name: j.name, description: j.description, engine: "app", schedule: describeDaily(j.at), at: j.at, zone: ZONE,
        source: j.source, enabled, updatedBy: (r && r.updated_by) || null, updatedAt: iso(r && r.updated_at),
        lastRunAt: iso(r && r.last_run_at), lastStatus: (r && r.last_status) || null, lastResult: (r && r.last_result) || null,
        finishedAt: iso(r && r.finished_at), nextRunAt: enabled ? nextRun(j.at).toISOString() : null,
      };
    });
  }

  /**
   * Turn a job on or off. The caller audits it. Turning a job on never runs a time that already passed today: the
   * first run is the next one shown (nextRunAt), even inside the catch-up window.
   * @param {string} id @param {boolean} enabled @param {string | null} by @param {Date} [now]
   */
  async function setEnabled(id, enabled, by, now = new Date()) {
    const job = registry.get(id);
    if (!job) return false;
    await ensure();
    const due = occurrence(job.at, now);
    // Only a job that was off skips today's passed time. A job with no row reads as its default, so a job that ships
    // on is never skipped by a first switch. A job that is already on keeps its pending run.
    const skip = enabled === true && job.defaultEnabled === false && now.getTime() >= due.getTime() ? due.toISOString() : null;
    // One statement: the switch and the skip of today's passed time land together or not at all.
    await o.db.query(
      `INSERT INTO scheduled_jobs (id, enabled, updated_by, updated_at, skip_until) VALUES ($1, $2, $3, now(), $4)
       ON CONFLICT (id) DO UPDATE SET enabled = EXCLUDED.enabled, updated_by = EXCLUDED.updated_by, updated_at = now(),
         skip_until = CASE WHEN scheduled_jobs.enabled THEN scheduled_jobs.skip_until
                           ELSE COALESCE($5::timestamptz, scheduled_jobs.skip_until) END`,
      [id, enabled === true, by, skip, enabled === true && now.getTime() >= due.getTime() ? due.toISOString() : null],
    );
    return true;
  }

  /** Claim today's occurrence when it is due. True only for the caller whose UPDATE moved last_run_at. @param {JobDef} job @param {Date} now */
  async function claim(job, now) {
    const due = occurrence(job.at, now);
    if (now.getTime() < due.getTime() || now.getTime() - due.getTime() > CATCH_UP_MS) return false;
    await ensure();
    await o.db.query("INSERT INTO scheduled_jobs (id, enabled) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", [job.id, job.defaultEnabled !== false]);
    const { rows } = await o.db.query(
      `UPDATE scheduled_jobs SET last_run_at = $3, last_status = 'running', last_result = NULL, finished_at = NULL
       WHERE id = $1 AND enabled AND (last_run_at IS NULL OR last_run_at < $2) AND (skip_until IS NULL OR skip_until < $2) RETURNING id`,
      [job.id, due.toISOString(), now.toISOString()],
    );
    return rows.length === 1;
  }

  /** Run every due job once. A failure is stored on the job's row, never thrown. @param {Date} [now] */
  async function tick(now = new Date()) {
    /** @type {string[]} */
    const ran = [];
    for (const job of registry.values()) {
      let mine = false;
      try { mine = await claim(job, now); } catch (e) { log(`[jobs] ${job.id}: could not claim: ${/** @type {Error} */ (e).message}`); }
      if (!mine) continue;
      ran.push(job.id);
      let status = "success";
      /** @type {Record<string, unknown>} */ let result;
      try {
        result = (await job.run()) || {};
        if (Number(result.failed) > 0) status = "failure";
      } catch (e) {
        status = "failure";
        result = { error: /** @type {Error} */ (e).message || String(e) };
      }
      let stored;
      try { stored = JSON.stringify(result); } catch (e) {
        status = "failure";
        stored = JSON.stringify({ error: `the run's summary could not be stored: ${/** @type {Error} */ (e).message}` });
      }
      await o.db.query("UPDATE scheduled_jobs SET last_status = $2, last_result = $3::jsonb, finished_at = now() WHERE id = $1", [job.id, status, stored])
        .catch((/** @type {Error} */ e) => log(`[jobs] ${job.id}: could not store the run: ${e.message}`));
    }
    return ran;
  }

  const offEnv = o.offEnv || "JOBS";
  /** Start the runner. The offEnv variable set to "off" stops it on an instance. */
  function start() {
    if (String(process.env[offEnv] || "").toLowerCase() === "off" || timer) return;
    first = setTimeout(() => { void tick(); }, FIRST_TICK_MS);
    timer = setInterval(() => { void tick(); }, TICK_MS);
    if (first.unref) first.unref();
    if (timer.unref) timer.unref();
  }

  function stop() {
    if (first) clearTimeout(first);
    if (timer) clearInterval(timer);
    first = null; timer = null;
  }

  return { tool: o.tool, register, list, setEnabled, claim, tick, start, stop, has: (/** @type {string} */ id) => registry.has(id) };
}

/**
 * GET /jobs and PUT /jobs/:id on a router the tool owns, behind the tool's own gates.
 * @param {{ get: Function, put: Function }} router an express Router
 * @param {{
 *   scheduler: ReturnType<typeof createScheduler>,
 *   read: Function, manage: Function,
 *   canManage: (req: any) => boolean | Promise<boolean>,
 *   caller: (req: any) => { email: string | null },
 *   audit: (req: any, action: string, target: string, details: Record<string, unknown>) => Promise<unknown>,
 *   path?: string,
 * }} o
 */
export function jobRoutes(router, o) {
  const base = o.path || "/jobs";
  router.get(base, o.read, async (/** @type {any} */ req, /** @type {any} */ res, /** @type {any} */ next) => {
    try { res.json({ tool: o.scheduler.tool, canManage: (await o.canManage(req)) === true, jobs: await o.scheduler.list() }); } catch (e) { next(e); }
  });
  router.put(`${base}/:id`, o.manage, async (/** @type {any} */ req, /** @type {any} */ res, /** @type {any} */ next) => {
    try {
      const id = String(req.params.id || "");
      const enabled = req.body && req.body.enabled;
      if (typeof enabled !== "boolean") return res.status(400).json({ error: "enabled must be true or false" });
      if (!o.scheduler.has(id)) return res.status(404).json({ error: "No such job" });
      const before = (await o.scheduler.list()).find((j) => j.id === id);
      const who = o.caller(req).email || null;
      await o.scheduler.setEnabled(id, enabled, who);
      try {
        await o.audit(req, enabled ? "jobs:on" : "jobs:off", `job:${id}`, { before: { enabled: before ? before.enabled : null }, after: { enabled } });
      } catch (e) {
        // No switch without its audit record: put the job back the way it was, then fail the request.
        if (before) await o.scheduler.setEnabled(id, before.enabled, who);
        throw e;
      }
      res.json({ tool: o.scheduler.tool, job: (await o.scheduler.list()).find((j) => j.id === id) });
    } catch (e) { next(e); }
  });
}

// -- Schedules outside an API (console catalog, console-modules/scripts/build-schedules.mjs) -------------------------
// GitHub Actions and Function App timers are cron in UTC. Automation Account schedules are a frequency, an interval
// and a start time in their own time zone. nextScheduled() answers the next run of either after `now`.

const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** One cron field to the set of values it matches. @param {string} f @param {number} lo @param {number} hi */
function cronField(f, lo, hi) {
  /** @type {Set<number>} */
  const out = new Set();
  for (const part of f.split(",")) {
    const m = /^(\*|(\d+)(?:-(\d+))?)(?:\/(\d+))?$/.exec(part.trim());
    if (!m) throw new Error(`cron field ${f} is not supported`);
    const step = m[4] ? Number(m[4]) : 1;
    const from = m[1] === "*" ? lo : Number(m[2]);
    const to = m[1] === "*" ? hi : m[3] !== undefined ? Number(m[3]) : (m[4] ? hi : from);
    if (from < lo || to > hi || from > to || step < 1) throw new Error(`cron field ${f} is out of range`);
    for (let v = from; v <= to; v += step) out.add(v === 7 && hi === 7 ? 0 : v);
  }
  return out;
}

/** Parse a 5-field cron, or a 6-field NCRONTAB whose seconds field is 0. @param {string} expr */
export function parseCron(expr) {
  let f = String(expr).trim().split(/\s+/);
  if (f.length === 6) {
    if (f[0] !== "0") throw new Error(`cron ${expr}: only a seconds field of 0 is supported`);
    f = f.slice(1);
  }
  if (f.length !== 5) throw new Error(`cron ${expr} must have 5 fields`);
  const [mi, h, dom, mon, dow] = /** @type {[string, string, string, string, string]} */ (f);
  return { minute: cronField(mi, 0, 59), hour: cronField(h, 0, 23), dom: cronField(dom, 1, 31), month: cronField(mon, 1, 12), dow: cronField(dow, 0, 7), domAny: dom === "*", dowAny: dow === "*" };
}

/** The next minute after `now` a UTC cron matches. @param {string} expr @param {Date} [now] */
export function nextCron(expr, now = new Date()) {
  const c = parseCron(expr);
  const t = new Date(Math.floor(now.getTime() / 60000) * 60000 + 60000);
  for (let i = 0; i < 366 * 24 * 60; i += 1) {
    const domOk = c.dom.has(t.getUTCDate());
    const dowOk = c.dow.has(t.getUTCDay());
    // Standard cron: when both day fields are restricted, either one matching is enough.
    const dayOk = c.domAny && c.dowAny ? true : c.domAny ? dowOk : c.dowAny ? domOk : domOk || dowOk;
    if (c.minute.has(t.getUTCMinutes()) && c.hour.has(t.getUTCHours()) && c.month.has(t.getUTCMonth() + 1) && dayOk) return t;
    t.setTime(t.getTime() + 60000);
  }
  return null;
}

/** A short English reading of a UTC cron. @param {string} expr */
export function describeCron(expr) {
  const f = String(expr).trim().split(/\s+/);
  const [mi, h, dom, mon, dow] = f.length === 6 ? f.slice(1) : f;
  const two = (/** @type {string | undefined} */ v) => String(v).padStart(2, "0");
  const step = /^\*\/(\d+)$/.exec(String(mi));
  if (step && h === "*" && dom === "*" && mon === "*" && dow === "*") return `Every ${step[1]} minutes`;
  if (/^\d+$/.test(String(mi)) && h === "*" && dom === "*" && mon === "*" && dow === "*") return `Every hour at :${two(mi)}`;
  if (/^\d+$/.test(String(mi)) && /^\d+$/.test(String(h)) && dom === "*" && mon === "*") {
    const at = `${two(h)}:${two(mi)} UTC`;
    if (dow === "*") return `Every day at ${at}`;
    if (/^\d$/.test(String(dow))) return `Every ${DAY_NAMES[Number(dow) % 7]} at ${at}`;
  }
  return `Cron ${expr} (UTC)`;
}

/**
 * @typedef {{ frequency: "Day" | "Hour" | "Week" | "Month", interval?: number, timezone: string, startTime: string,
 *   weekDays?: string[], monthDays?: number[] }} AaSchedule
 */

/** Whole Eastern calendar days from a to b. @param {Date} a @param {Date} b */
function daysApart(a, b) {
  const x = easternDate(a), y = easternDate(b);
  return Math.round((Date.UTC(y.y, y.m - 1, y.day) - Date.UTC(x.y, x.m - 1, x.day)) / 86400000);
}
/** Whole weeks (Sunday to Saturday, Eastern) from a's week to b's week. @param {Date} a @param {Date} b */
function weeksApart(a, b) {
  const x = easternDate(a);
  const sunday = new Date(Date.UTC(x.y, x.m - 1, x.day)).getUTCDay();
  return Math.floor((daysApart(a, b) + sunday) / 7);
}
/** Whole calendar months from a's month to b's month, Eastern. @param {Date} a @param {Date} b */
function monthsApart(a, b) {
  const x = easternDate(a), y = easternDate(b);
  return (y.y - x.y) * 12 + (y.m - x.m);
}

/** The next run of an Automation Account schedule (America/New_York only). @param {AaSchedule} s @param {Date} [now] */
export function nextAutomation(s, now = new Date()) {
  if (s.timezone !== ZONE) throw new Error(`schedule time zone ${s.timezone} is not supported`);
  const start = new Date(s.startTime);
  const interval = Math.max(1, Number(s.interval || 1));
  if (s.frequency === "Hour") {
    const ms = interval * 3600000;
    if (now.getTime() < start.getTime()) return start;
    return new Date(start.getTime() + (Math.floor((now.getTime() - start.getTime()) / ms) + 1) * ms);
  }
  // Day, Week and Month keep the start's Eastern wall time.
  const wall = new Intl.DateTimeFormat("en-US", { timeZone: ZONE, hourCycle: "h23", hour: "2-digit", minute: "2-digit" }).format(start);
  const from = now.getTime() < start.getTime() ? start : now;
  for (let d = 0; d < 400; d += 1) {
    const at = occurrence(wall, from, d);
    if (at.getTime() < from.getTime() || (at.getTime() === from.getTime() && from === now)) continue;
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: ZONE, weekday: "long", day: "numeric" }).formatToParts(at).map((x) => [x.type, x.value]));
    if (s.frequency === "Day" && interval === 1) return at;
    if (s.frequency === "Day" && daysApart(start, at) % interval === 0) return at;
    if (s.frequency === "Week" && (s.weekDays || []).includes(String(parts.weekday)) && weeksApart(start, at) % interval === 0) return at;
    if (s.frequency === "Month" && (s.monthDays || []).includes(Number(parts.day)) && monthsApart(start, at) % interval === 0) return at;
  }
  return null;
}

/** A short English reading of an Automation Account schedule. @param {AaSchedule} s */
export function describeAutomation(s) {
  // Newer ICU puts a narrow no-break space before AM and PM: keep plain ASCII spaces.
  const wall = new Intl.DateTimeFormat("en-US", { timeZone: ZONE, hour: "numeric", minute: "2-digit" }).format(new Date(s.startTime)).replace(/\s/g, " ");
  const n = Number(s.interval || 1);
  if (s.frequency === "Hour") return n === 1 ? `Every hour at :${wall.split(":")[1]?.slice(0, 2)} Eastern` : `Every ${n} hours from ${wall} Eastern`;
  if (s.frequency === "Day") return n === 1 ? `Every day at ${wall} Eastern` : `Every ${n} days at ${wall} Eastern`;
  if (s.frequency === "Week") return `${n === 1 ? "Every" : `Every ${n} weeks on`} ${(s.weekDays || []).join(", ")} at ${wall} Eastern`;
  return `${n === 1 ? "Monthly" : `Every ${n} months`} on day ${(s.monthDays || []).join(", ")} at ${wall} Eastern`;
}

/**
 * The next run of a catalog row after `now`, or null.
 * @param {{ engine: string, cron?: string[], automation?: AaSchedule }} row @param {Date} [now]
 */
export function nextScheduled(row, now = new Date()) {
  if (row.automation) return nextAutomation(row.automation, now);
  const all = (row.cron || []).map((c) => nextCron(c, now)).filter((d) => d instanceof Date);
  return all.length ? new Date(Math.min(...all.map((d) => d.getTime()))) : null;
}
