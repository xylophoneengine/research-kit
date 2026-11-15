export type Entry = {
  id: string; type: string; title: string; status: string;
  owner: string; stage: string; note: string; links: string[]; refs: string[];
  created: string; updated: string; started: string;
  extra: Record<string, string | boolean>; lines: number[];
};
export type Ev = {
  line: number; ts: string; who: string; ev: "add" | "set";
  id: string; f: Record<string, unknown>;
  kit?: string; sid?: string; rules?: Record<string, string>;
};
export type Ledger = {
  repo: string; entries: Entry[]; events: Ev[];
  types: Record<string, string>;
};
export type Tab = "list" | "board" | "stages" | "timeline";
export type Route = {
  tab: Tab; status: string[] | null; type: string[];
  stage: string[]; owner: string[]; q: string; idOnly: boolean;
  sort: SortKey; desc: boolean; e: string | null;
};
// the table's columns (same names), then the two timestamps that have no column
export const SORT_KEYS = [
  "default", "id", "label", "type", "status", "title", "owner", "stage", "age",
  "updated", "created",
] as const;
export type SortKey = (typeof SORT_KEYS)[number];
// what `default` means on each tab that has the sort menu (the one place for these texts)
export type SortTab = "list" | "board" | "timeline";
export const DEFAULT_ORDER: Record<SortTab, string> = {
  list: "status (running, open, rest), then type, then id",
  board: "newest update first",
  timeline: "oldest day first (imported date, else created), then id; no day last",
};

export const NONE = "-"; // filter token for an empty owner / stage
export const STATUSES = ["open", "running", "done", "dropped", "superseded", "shelved"];

export const BOARD_COLS = ["running", "open", "deferred", "shelved", "done", "dropped", "superseded"];

// Board column of an entry: its status, except that an open or running
// `deferred` entry goes to the "deferred" column (it is parked, not open).
export function boardCol(e: Entry): string {
  return e.type === "deferred" && (e.status === "open" || e.status === "running")
    ? "deferred"
    : e.status;
}

const TABS: readonly string[] = ["list", "board", "stages", "timeline"];
const ID_ONLY = /^[A-Z]{1,3}-[1-9][0-9]*$/;
const ID_TOKEN = /\b[A-Z]{1,3}-[1-9][0-9]*\b/g;

export async function fetchLedger(): Promise<Ledger> {
  const res = await fetch("/api/ledger", { cache: "no-store" });
  const text = await res.text();
  if (!res.ok) {
    let msg = text;
    try {
      const j: unknown = JSON.parse(text); // server sends {"error": "..."}
      if (j && typeof j === "object" && "error" in j) msg = String(j.error);
    } catch {
      // not JSON: keep the raw text
    }
    throw new Error(msg || `HTTP ${res.status}`);
  }
  return JSON.parse(text) as Ledger;
}

function dec(v: string): string {
  try {
    return decodeURIComponent(v);
  } catch {
    return v; // malformed %-escape typed into the URL: keep it raw
  }
}

export function parseRoute(hash: string): Route {
  const body = hash.replace(/^#\/?/, "");
  const cut = body.indexOf("?");
  const path = cut < 0 ? body : body.slice(0, cut);
  const parts: string[] = cut < 0 ? [] : body.slice(cut + 1).split("&");
  // raw values, not URLSearchParams: lists use "," as separator and are
  // decoded per element
  const raw = (k: string): string | undefined => {
    for (const p of parts) {
      const i = p.indexOf("=");
      if ((i < 0 ? p : p.slice(0, i)) === k) return i < 0 ? "" : p.slice(i + 1);
    }
    return undefined;
  };
  const multi = (k: string): string[] =>
    (raw(k) ?? "").split(",").filter((s) => s !== "").map(dec);
  const status = raw("status");
  const eq = raw("e");
  return {
    tab: TABS.includes(path) ? (path as Tab) : "list",
    status: !status ? null : status === "all" ? [] : multi("status"),
    type: multi("type"),
    stage: multi("stage"),
    owner: multi("owner"),
    q: dec(raw("q") ?? ""),
    idOnly: raw("idonly") === "1",
    sort: SORT_KEYS.find((k) => k === raw("sort")) ?? "default",
    desc: raw("dir") === "desc",
    e: eq ? dec(eq) : ID_ONLY.test(path) ? path : null,
  };
}

export function formatRoute(r: Route): string {
  const enc = (a: string[]): string => a.map(encodeURIComponent).join(",");
  const p: string[] = [];
  if (r.status !== null) p.push(`status=${r.status.length ? enc(r.status) : "all"}`);
  if (r.type.length) p.push(`type=${enc(r.type)}`);
  if (r.stage.length) p.push(`stage=${enc(r.stage)}`);
  if (r.owner.length) p.push(`owner=${enc(r.owner)}`);
  if (r.q) p.push(`q=${encodeURIComponent(r.q)}`);
  if (r.idOnly) p.push("idonly=1");
  if (r.sort !== "default") p.push(`sort=${r.sort}`);
  if (r.desc) p.push("dir=desc");
  if (r.e) p.push(`e=${encodeURIComponent(r.e)}`);
  return `#/${r.tab}${p.length ? "?" + p.join("&") : ""}`;
}

// last segment of the repo path; "/" or "" keep the path as is
export function projectName(repo: string): string {
  return repo.split(/[\\/]/).filter(Boolean).pop() ?? repo;
}

export function byId(l: Ledger): Map<string, Entry> {
  return new Map(l.entries.map((e) => [e.id, e]));
}

export function backlinks(l: Ledger): Map<string, string[]> {
  const m = new Map<string, string[]>();
  for (const e of l.entries) {
    for (const t of new Set(e.links)) {
      const a = m.get(t);
      if (a) a.push(e.id);
      else m.set(t, [e.id]);
    }
  }
  return m;
}

// idOnly: the query is a list of ids / labels (split on spaces and commas);
// an entry matches when its id or label equals one of them exactly
export function matches(e: Entry, q: string, idOnly = false): boolean {
  const n = q.trim().toLowerCase();
  if (!n) return true;
  if (idOnly) {
    const terms = n.split(/[\s,]+/).filter(Boolean);
    return terms.includes(e.id.toLowerCase()) || terms.includes(labelOf(e).toLowerCase());
  }
  const hay = [e.id, e.title, e.note, e.extra.legacy_id, e.extra.source];
  return hay.some((h) => typeof h === "string" && h.toLowerCase().includes(n));
}

function pick(sel: string[], v: string): boolean {
  return sel.length === 0 || sel.includes(v === "" ? NONE : v);
}

export function visible(l: Ledger, r: Route): Entry[] {
  const q = r.q.trim();
  const st: string[] | null =
    r.status ?? (r.tab === "list" && !q ? ["open", "running"] : null);
  const out = l.entries.filter(
    (e) =>
      (st === null || st.length === 0 || st.includes(e.status)) &&
      (r.type.length === 0 || r.type.includes(e.type)) &&
      pick(r.stage, e.stage) &&
      pick(r.owner, e.owner) &&
      matches(e, q, r.idOnly),
  );
  // the sort (header click and menu alike) applies on the list and board tabs; the others keep the default order
  const s = r.tab === "list" || r.tab === "board" ? sortBy(sortDefault(out, l.types), r.sort, r.desc) : sortDefault(out, l.types);
  return pinExact(s, q);
}

// a click on column `col`: ascending, then descending, then the default order
export function clickSort(sort: SortKey, desc: boolean, col: SortKey): { sort: SortKey; desc: boolean } {
  if (sort !== col) return { sort: col, desc: false };
  return desc ? { sort: "default", desc: false } : { sort: col, desc: true };
}

// `es` is in default order; ties of a key keep it, also when descending; `default` descending reverses all
export function sortBy(es: Entry[], key: SortKey, desc: boolean): Entry[] {
  const day = (e: Entry): number => Date.parse(key === "created" ? e.created : e.updated) || 0;
  const pre = (id: string): string => id.slice(0, id.lastIndexOf("-"));
  const text = (f: (e: Entry) => string) => (a: Entry, b: Entry): number =>
    f(a).localeCompare(f(b), undefined, { numeric: true });
  // the age column as it always sorted: ascending = youngest first (running: since
  // it started), an entry without a usable timestamp last
  const ageKey = (e: Entry): number => {
    const t = Date.parse(e.status === "running" && e.started ? e.started : e.created);
    return Number.isNaN(t) ? Infinity : -t;
  };
  const cmp: Record<SortKey, (a: Entry, b: Entry) => number> = {
    default: () => 0,
    id: (a, b) => pre(a.id).localeCompare(pre(b.id)) || num(a.id) - num(b.id),
    label: text(labelOf),
    type: text((e) => e.type),
    status: text((e) => e.status),
    title: text((e) => e.title),
    owner: text((e) => e.owner),
    stage: text((e) => e.stage),
    age: (a, b) => (ageKey(a) < ageKey(b) ? -1 : ageKey(a) > ageKey(b) ? 1 : 0),
    updated: (a, b) => day(a) - day(b),
    created: (a, b) => day(a) - day(b),
  };
  if (key === "default") return desc ? [...es].reverse() : [...es]; // its comparator ties everything
  return [...es].sort((a, b) => (desc ? -1 : 1) * cmp[key](a, b));
}

// an entry whose id or label equals the query (case-insensitive) goes first; stable otherwise
export function pinExact(es: Entry[], q: string): Entry[] {
  const n = q.trim().toLowerCase();
  if (!n) return es;
  const exact = (e: Entry): boolean => e.id.toLowerCase() === n || labelOf(e).toLowerCase() === n;
  return [...es.filter(exact), ...es.filter((e) => !exact(e))];
}

// the entry the query names exactly (case-insensitive): its id, else its label if
// only one entry has it
export function exactHit(es: Entry[], q: string): Entry | undefined {
  const n = q.trim().toLowerCase();
  if (!n) return undefined;
  const byLabel = es.filter((e) => labelOf(e).toLowerCase() === n);
  return es.find((e) => e.id.toLowerCase() === n) ?? (byLabel.length === 1 ? byLabel[0] : undefined);
}

// an entry's label: the string in extra.legacy_id ("" when it has none)
export function labelOf(e: Entry): string {
  const l = e.extra.legacy_id;
  return typeof l === "string" ? l : "";
}

function num(id: string): number {
  return Number(id.slice(id.lastIndexOf("-") + 1));
}

export function sortDefault(es: Entry[], types: Record<string, string>): Entry[] {
  const order: string[] = Object.keys(types);
  const rank = (e: Entry): number =>
    e.status === "running" ? 0 : e.status === "open" ? 1 : 2;
  const tIdx = (e: Entry): number => {
    const i = order.indexOf(e.type);
    return i < 0 ? order.length : i;
  };
  return [...es].sort(
    (a, b) => rank(a) - rank(b) || tIdx(a) - tIdx(b) || num(a.id) - num(b.id),
  );
}

export function facets(l: Ledger): { type: string[]; stage: string[]; owner: string[] } {
  const nat = (a: string, b: string): number =>
    a.localeCompare(b, undefined, { numeric: true });
  const vals = (f: (e: Entry) => string): string[] => {
    const s = new Set(l.entries.map(f));
    const out = [...s].filter((v) => v !== "").sort(nat);
    return s.has("") ? [...out, NONE] : out;
  };
  const order: string[] = Object.keys(l.types);
  const type = [...new Set(l.entries.map((e) => e.type))].sort(
    (a, b) => {
      const ia = order.indexOf(a);
      const ib = order.indexOf(b);
      return (ia < 0 ? order.length : ia) - (ib < 0 ? order.length : ib) || nat(a, b);
    },
  );
  return { type, stage: vals((e) => e.stage), owner: vals((e) => e.owner) };
}

// `text` is set for a stage code, label or work item: the link shows it, the target is the entry
export type Seg = string | { id: string; text?: string } | { label: string };

// key -> entry id, a key claimed twice is dropped: no guessing
function unique(pairs: Iterable<[string, string]>): Map<string, string> {
  const m = new Map<string, string | null>();
  for (const [k, id] of pairs) m.set(k, m.has(k) ? null : id);
  return new Map([...m].filter((kv): kv is [string, string] => kv[1] !== null));
}

// A stage's code is its title up to the first "-" ("07b-software-parser" -> "07b"),
// the kit's rule (ledger._matches); a title without "-" has no code for the UI.
export function stageCodeOf(title: string): string | undefined {
  const i = title.indexOf("-");
  return i > 0 ? title.slice(0, i) : undefined;
}

// code -> stage id; a code that two stages claim is dropped
export function stageCodes(entries: Entry[]): Map<string, string> {
  return unique(
    entries.flatMap((e): [string, string][] => {
      const c = e.type === "stage" ? stageCodeOf(e.title) : undefined;
      return c ? [[c, e.id]] : [];
    }),
  );
}

// label -> entry id, for labels held by exactly one entry
export function labelIndex(entries: Entry[]): Map<string, string> {
  return unique(entries.flatMap((e): [string, string][] => (labelOf(e) ? [[labelOf(e), e.id]] : [])));
}

const RICH = /(\b[A-Z]{1,3}-[1-9][0-9]*\b)|(\bW[0-9]+[a-z]?\b)/g;
// a candidate word for a label or stage code: labels may hold / . _ -
const WORD = /[A-Za-z0-9_][A-Za-z0-9_./-]*/g;
const MAX_NAME = 64; // labels and codes longer than this are not looked up
const AFTER_STAGE = /\bstage\s+$/i;

// a name must stand alone: not part of a longer number or word, a date
// (2026-11-13), a time (15:39), a version (1.07b), a path or an id (T-07)
function standalone(t: string, i: number, n: number): boolean {
  const side = (c: string | undefined, beyond: string | undefined): boolean =>
    c === undefined ||
    !(/[\w/\\-]/.test(c) || ((c === "." || c === ":") && beyond !== undefined && /[0-9]/.test(beyond)));
  return side(t[i - 1], t[i - 2]) && side(t[i + n], t[i + n + 1]);
}

// Splits text into plain strings and links. Without `codes` and `labels`: only
// existing entry ids become {id}. Otherwise, in this order of precedence:
// an id -> {id}; a standalone known label (longest first) -> {id, text: label};
// a bare work item (W6b) -> the entry labelled "<own>/W6b" (`own`: stage code of
// the entry whose text this is), else the one label ending in "/W6b", else {label}
// (a search term); a standalone stage code -> {id: stage id, text: code}, a
// pure-digit code only right after the word "stage".
export function linkify(
  text: string,
  ids: Set<string>,
  codes?: Map<string, string>,
  labels?: Map<string, string>,
  own?: string,
): Seg[] {
  const hits: { at: number; end: number; seg: Seg }[] = [];
  const add = (at: number, end: number, seg: Seg): void => void hits.push({ at, end, seg });
  if (!codes && !labels) {
    for (const m of text.matchAll(ID_TOKEN)) {
      if (ids.has(m[0])) add(m.index ?? 0, (m.index ?? 0) + m[0].length, { id: m[0] });
    }
  } else {
    const cd = codes ?? new Map<string, string>();
    const lb = labels ?? new Map<string, string>();
    for (const m of text.matchAll(WORD)) {
      const at = m.index ?? 0;
      for (let n = Math.min(m[0].length, MAX_NAME); n > 0; n--) {
        const sub = m[0].slice(0, n);
        const id = lb.get(sub) ?? cd.get(sub);
        if (!id || ids.has(sub) || !standalone(text, at, n)) continue;
        if (!lb.has(sub)) {
          // a code links only if it has a digit; a pure-digit one only after "stage"
          if (!/[0-9]/.test(sub)) continue;
          if (/^[0-9]+$/.test(sub) && !AFTER_STAGE.test(text.slice(0, at))) continue;
        }
        add(at, at + n, { id, text: sub });
        break;
      }
    }
    for (const m of text.matchAll(RICH)) {
      const at = m.index ?? 0;
      const end = at + m[0].length;
      if (hits.some((h) => at < h.end && h.at < end)) continue;
      if (m[1]) {
        if (ids.has(m[1])) add(at, end, { id: m[1] });
        continue;
      }
      const item = m[2];
      let id = own === undefined ? undefined : lb.get(`${own}/${item}`);
      if (!id) {
        const suf = [...lb].filter(([l]) => l.endsWith(`/${item}`));
        if (suf.length === 1) id = suf[0][1];
      }
      add(at, end, id ? { id, text: item } : { label: item });
    }
  }
  hits.sort((a, b) => a.at - b.at);
  const out: Seg[] = [];
  let last = 0;
  for (const h of hits) {
    if (h.at > last) out.push(text.slice(last, h.at));
    out.push(h.seg);
    last = h.end;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function parseTs(ts: string): Date {
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ts);
  // a date-only value counts from local midnight (Date() would read it as UTC)
  return d ? new Date(+d[1], +d[2] - 1, +d[3]) : new Date(ts);
}

export function age(e: Entry, now: Date): string {
  const ts = e.status === "running" && e.started ? e.started : e.created;
  const then = parseTs(ts);
  if (Number.isNaN(then.getTime())) return "?";
  const secs = Math.max(Math.floor((now.getTime() - then.getTime()) / 1000), 0);
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h`;
  return `${Math.floor(secs / 86400)}d`;
}

export function eventDay(ev: Ev, entry: Entry | undefined): string {
  const d = ev.ev === "add" ? entry?.extra.date : undefined;
  return typeof d === "string" ? d : ev.ts.slice(0, 10);
}

// kit, sid and rules of an event as one line ("" when it has none); mirrors ledger._meta
export function evMeta(ev: Ev): string {
  const parts: string[] = [];
  if (ev.kit !== undefined) parts.push(`kit=${ev.kit}`);
  if (ev.sid !== undefined) parts.push(`sid=${ev.sid.slice(0, 8)}`);
  if (ev.rules !== undefined) {
    const r = Object.entries(ev.rules).map(([f, s]) => `${f}:${s}`).join(",");
    parts.push(`rules=${r || "none"}`);
  }
  return parts.join(" ");
}

// ---- timeline layout (pure; times are epoch ms) ----

const CLOSED = new Set(["done", "dropped", "superseded", "shelved"]);

function push<T>(m: Map<string, T[]>, k: string, v: T): void {
  const l = m.get(k);
  if (l) l.push(v);
  else m.set(k, [v]);
}

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// "Nov 13" for "2026-11-13"; "?" for anything else
export function shortDay(day: string): string {
  return DAY_RE.test(day) ? `${MONTHS[+day.slice(5, 7) - 1] ?? "?"} ${day.slice(8, 10)}` : "?";
}

// The day an entry sits on: extra.date of an imported entry, else the day it
// was created; "" when neither is a YYYY-MM-DD day.
export function entryDay(e: Entry): string {
  const d = e.extra.date;
  for (const s of [typeof d === "string" ? d : "", e.created.slice(0, 10)]) {
    if (DAY_RE.test(s)) return s;
  }
  return "";
}

export type Group = {
  key: string; // stage id, "" for the unstaged group
  stage: Entry | null;
  items: Entry[]; // by entryDay, then id number
  first: string; // earliest day of the stage and its items, "" when none
  last: string; // latest day; a closed stage counts its own update day too
  live: boolean; // the stage is not closed
};

// One group per stage by id number, then "unstaged" (stage "" and not a stage)
// when it has entries. `all` supplies the stages, `entries` (filtered) the
// items; a stage is listed when it is in `entries` or has an item there.
export function stageGroups(all: Entry[], entries: Entry[]): Group[] {
  const items = new Map<string, Entry[]>();
  for (const e of entries) {
    if (e.type !== "stage") push(items, e.stage, e);
  }
  const shown = new Set(entries.filter((e) => e.type === "stage").map((e) => e.id));
  const make = (key: string, stage: Entry | null): Group => {
    const its = [...(items.get(key) ?? [])].sort(
      (a, b) =>
        (entryDay(a) || "~").localeCompare(entryDay(b) || "~") || num(a.id) - num(b.id),
    );
    const live = stage !== null && !CLOSED.has(stage.status);
    const days = [...its, ...(stage ? [stage] : [])].map(entryDay);
    if (stage && !live && DAY_RE.test(stage.updated.slice(0, 10))) days.push(stage.updated.slice(0, 10));
    const real = days.filter(Boolean).sort();
    return { key, stage, items: its, first: real[0] ?? "", last: real[real.length - 1] ?? "", live };
  };
  const stages = all
    .filter((e) => e.type === "stage" && (shown.has(e.id) || items.has(e.id)))
    .sort((a, b) => num(a.id) - num(b.id))
    .map((s) => make(s.id, s));
  return items.has("") ? [...stages, make("", null)] : stages;
}

// the route sort inside every group (the stage path keeps its order); `default`
// ascending keeps the groups' own chronological order, `default` descending reverses it
export function sortGroups(gs: Group[], key: SortKey, desc: boolean): Group[] {
  return gs.map((g) => ({ ...g, items: sortBy(g.items, key, desc) }));
}

export const TYPE_ORDER = ["task", "decision", "deferred", "debt", "fetch", "handoff"];

// entries split by type: builtin types in TYPE_ORDER, declared ones after by name
export function byType(items: Entry[]): { type: string; items: Entry[] }[] {
  const m = new Map<string, Entry[]>();
  for (const e of items) push(m, e.type, e);
  const rank = (t: string): number => {
    const i = TYPE_ORDER.indexOf(t);
    return i < 0 ? TYPE_ORDER.length : i;
  };
  return [...m]
    .map(([type, its]) => ({ type, items: its }))
    .sort((a, b) => rank(a.type) - rank(b.type) || a.type.localeCompare(b.type));
}
