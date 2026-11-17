export type Entry = {
  id: string; type: string; title: string; status: string;
  owner: string; stage: string; note: string; links: string[]; refs: string[];
  created: string; updated: string; started: string;
  extra: Record<string, string | boolean>; lines: number[];
  shown?: string; // the kit's status to display (an open entry of a planned stage: planned); see shownStatus
};
export type Ev = {
  line: number; ts: string; who: string; ev: "add" | "set";
  id: string; f: Record<string, unknown>;
  kit?: string; sid?: string; rules?: Record<string, string>;
};
export type Ledger = {
  repo: string; entries: Entry[]; events: Ev[];
  types: Record<string, string>;
  // from the kit: planned stage ids in queue order and their `~NN` strings;
  // missing from an older kit
  plan?: { queue: string[]; forecast: Record<string, string> };
};
export type Tab = "list" | "board" | "stages" | "timeline";
export type Route = {
  tab: Tab; status: string[] | null; type: string[];
  stage: string[]; owner: string[]; q: string; idOnly: boolean; exact: boolean;
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
// A facet list that holds ALL means "all, also what comes later": it restricts nothing.
// Only `Filters` reads the raw list (to show the checks); everyone else reads `narrowed`.
export const ALL = "*";
export function narrowed(sel: string[]): string[] {
  return sel.includes(ALL) ? [] : sel;
}
export const STATUSES = ["open", "running", "staged", "done", "dropped", "superseded", "shelved", "planned"];

export const BOARD_COLS = ["running", "open", "deferred", "planned", "shelved", "staged", "done", "dropped", "superseded"];

// The status shown for an entry (badge, filter, counts, board, sort): the kit's
// `shown`, which differs from `status` for an open entry in a planned or shelved
// stage; `status` when the kit sends none. Nothing is inherited here.
export function shownStatus(e: Entry): string {
  return e.shown ?? e.status;
}

// [status, entries shown with it] for each status in STATUSES that has entries
export function statusCounts(es: Entry[]): [string, number][] {
  return STATUSES.map((s): [string, number] => [s, es.filter((e) => shownStatus(e) === s).length]).filter(
    ([, n]) => n > 0,
  );
}

// Board column of an entry: its shown status, except that an open or running
// `deferred` entry goes to the "deferred" column (it is parked, not open).
export function boardCol(e: Entry): string {
  const s = shownStatus(e);
  return e.type === "deferred" && (s === "open" || s === "running") ? "deferred" : s;
}

// Board columns that are off until the user switches them on by hand
export const BOARD_FOLDED = ["shelved", "dropped", "superseded"];

// Is board column `col` shown? A hand choice (`choice[col]`) wins; else the default:
// off for BOARD_FOLDED, on for `planned` only when `planned` (the entries of the whole
// ledger shown as planned, before any filter) is above 0, on for every other column.
export function colShown(col: string, planned: number, choice: Record<string, boolean>): boolean {
  const c = choice[col];
  if (c !== undefined) return c;
  if (BOARD_FOLDED.includes(col)) return false;
  return col === "planned" ? planned > 0 : true;
}

// The hand choices an old stored value (the array of hidden columns) stands for: of
// BOARD_FOLDED a column missing from it was switched on, of the other columns one in
// it was switched off. `planned` missing is no choice (it was on by default).
export function choiceFromFolded(folded: string[]): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  for (const c of BOARD_COLS) {
    if (BOARD_FOLDED.includes(c)) {
      if (!folded.includes(c)) out[c] = true;
    } else if (folded.includes(c)) {
      out[c] = false;
    }
  }
  return out;
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
    exact: raw("exact") === "1",
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
  if (r.idOnly && r.exact) p.push("exact=1"); // exact belongs to id mode
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

// the kit's stage title form NN[letter]-<kind>-<topic> (ledger.STAGE_RE)
const STAGE_RE = /^[0-9]{2,}[a-z]?-[a-z][a-z0-9]*-[A-Za-z0-9_.-]+$/;

// The number a stage shows in the Stages table: the kit's forecast string as sent
// (`~02`) for a planned stage ("" when `forecast` lacks it), else the NN[letter]
// code of its title ("03b-paper-x" -> "03b"), "" when the title is not in the kit's
// stage form ("2026-retro" has none). Nothing is computed.
export function stageNumber(e: Entry, forecast: Record<string, string> | undefined): string {
  if (e.status === "planned") return forecast?.[e.id] ?? "";
  return STAGE_RE.test(e.title) ? (stageCodeOf(e.title) ?? "") : "";
}

// Stages by number (the "~" ignored): NN, then letter (none before b); `dir` -1
// reverses that. Stages without a number come last, by id number in the same
// direction. Ties by id number. Does not change its input.
export function orderStages(
  stages: Entry[],
  forecast: Record<string, string> | undefined,
  dir: 1 | -1,
): Entry[] {
  const key = (e: Entry): [number, string] | null => {
    const m = /^~?(\d+)([a-z]?)$/.exec(stageNumber(e, forecast));
    return m ? [Number(m[1]), m[2]] : null;
  };
  return stages
    .map((e) => ({ e, k: key(e) }))
    .sort((a, b) => {
      if (a.k && b.k) {
        const c = a.k[0] - b.k[0] || (a.k[1] < b.k[1] ? -1 : a.k[1] > b.k[1] ? 1 : 0);
        if (c) return c * dir;
      } else if (a.k || b.k) {
        return a.k ? -1 : 1;
      }
      return (num(a.e.id) - num(b.e.id)) * dir;
    })
    .map((x) => x.e);
}

// The Stages table's body rows: `null` (the "unstaged / backlog" row) first under both
// directions, then the stage entries by number (orderStages; `dir` orders them only).
export function stageRows(
  all: Entry[],
  forecast: Record<string, string> | undefined,
  dir: 1 | -1,
): (Entry | null)[] {
  return [null, ...orderStages(all.filter((e) => e.type === "stage"), forecast, dir)];
}

// the hint above the Stages table while a stage filter is set (it only marks rows)
export const stageFilterHint = (n: number): string =>
  `stage filter set (${n}): the marked rows are in it; this tab lists every stage`;

// A board column's entries with the stages grouped: the stage entries in no. order
// (orderStages, lowest first), each followed directly by the entries of that stage in
// the incoming order (the caller's sort); entries whose stage card is not in `es` come
// last in their order.
export function underStages(es: Entry[], forecast: Record<string, string> | undefined): Entry[] {
  const stages = orderStages(es.filter((e) => e.type === "stage"), forecast, 1);
  const rest = es.filter((e) => e.type !== "stage");
  const own = (s: Entry): Entry[] => rest.filter((e) => e.stage === s.id);
  const placed = new Set(stages.flatMap(own));
  return [...stages.flatMap((s) => [s, ...own(s)]), ...rest.filter((e) => !placed.has(e))];
}

// the earlier titles of entry `id` from its events (in file order), newest first;
// each with the day it was replaced. `stage-open` (planned name -> NN name) is no
// rename, not listed: an event that sets `status: "open"` and turns a title without
// the stage form into one with it (STAGE_RE).
export function earlierTitles(events: Ev[], id: string): { title: string; until: string }[] {
  const out: { title: string; until: string }[] = [];
  let cur: string | null = null;
  for (const ev of events) {
    const t = ev.id === id ? ev.f.title : undefined;
    if (typeof t !== "string") continue;
    const opened = ev.f.status === "open" && STAGE_RE.test(t) && cur !== null && !STAGE_RE.test(cur);
    if (cur !== null && t !== cur && !opened) {
      out.push({ title: cur, until: ev.ts.slice(0, 10) });
    }
    cur = t;
  }
  return out.reverse();
}

// the one text for what id mode matches (id button, exact button, palette hint)
export const idHint = (exact: boolean): string =>
  `ids match ${exact ? "whole" : "by prefix"}, labels match whole`;

// the search box placeholder; `exact` belongs to id mode
export const searchPlaceholder = (idOnly: boolean, exact: boolean): string =>
  !idOnly ? "search id, title, note..." : exact ? "whole ids and labels" : "id prefixes, whole labels";

// the detail pane's `stored:` line: "" unless the stored and the shown status differ;
// the stage is named only when its status is the shown one (it explains the difference)
export function storedLine(e: Entry, stage: Entry | undefined): string {
  const shown = shownStatus(e);
  if (shown === e.status) return "";
  return stage && stage.status === shown
    ? `stored: ${e.status} (stage ${stage.id} is ${shown})`
    : `stored: ${e.status}`;
}

// idOnly: the query is a list of ids / labels (split on spaces and commas);
// an entry matches when its id starts with one of them (equals one, with `exact`)
// or its label equals one exactly
export function matches(e: Entry, q: string, idOnly = false, exact = false): boolean {
  const n = q.trim().toLowerCase();
  if (!n) return true;
  if (idOnly) {
    const terms = n.split(/[\s,]+/).filter(Boolean);
    const id = e.id.toLowerCase();
    return terms.some((t) => (exact ? id === t : id.startsWith(t))) || terms.includes(labelOf(e).toLowerCase());
  }
  const hay = [e.id, e.title, e.note, e.extra.legacy_id, e.extra.source];
  return hay.some((h) => typeof h === "string" && h.toLowerCase().includes(n));
}

function pick(sel: string[], v: string): boolean {
  return sel.length === 0 || sel.includes(v === "" ? NONE : v);
}

// the list's status filter when the route names none: the kit's open list (staged is
// work done but not landed; the red open badge does not count it)
export const DEFAULT_STATUS = ["open", "running", "staged"];

// the entries of the Stages table's "unstaged / backlog" row: no stage, and a stage
// entry is never backlog
export function backlog(es: Entry[]): Entry[] {
  return es.filter((e) => e.stage === "" && e.type !== "stage");
}

export function visible(l: Ledger, r: Route): Entry[] {
  const q = r.q.trim();
  const st: string[] | null =
    r.status ?? (r.tab === "list" && !q ? DEFAULT_STATUS : null);
  const sSt = st && narrowed(st);
  const sType = narrowed(r.type);
  const sStage = narrowed(r.stage); // `*` restricts nothing: stage entries stay in too
  const sOwner = narrowed(r.owner);
  const out = l.entries.filter(
    (e) =>
      (sSt === null || sSt.length === 0 || sSt.includes(shownStatus(e))) &&
      (sType.length === 0 || sType.includes(e.type)) &&
      (sStage.length === 0 || e.type !== "stage" || e.stage !== "") && // a stage entry is never "-" (see backlog)
      pick(sStage, e.stage) &&
      pick(sOwner, e.owner) &&
      matches(e, q, r.idOnly, r.exact),
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
  // the timestamp of the age / updated / created column; NaN when missing or unusable
  const stamp = (e: Entry): number =>
    Date.parse(
      key === "age" ? (e.status === "running" && e.started ? e.started : e.created)
        : key === "created" ? e.created : e.updated,
    );
  const pre = (id: string): string => id.slice(0, id.lastIndexOf("-"));
  const text = (f: (e: Entry) => string) => (a: Entry, b: Entry): number =>
    f(a).localeCompare(f(b), undefined, { numeric: true });
  const cmp: Record<SortKey, (a: Entry, b: Entry) => number> = {
    default: () => 0,
    id: (a, b) => pre(a.id).localeCompare(pre(b.id)) || num(a.id) - num(b.id),
    label: text(labelOf),
    type: text((e) => e.type),
    status: text(shownStatus),
    title: text((e) => e.title),
    owner: text((e) => e.owner),
    stage: text((e) => e.stage),
    age: (a, b) => stamp(b) - stamp(a), // ascending = youngest first (running: since it started)
    updated: (a, b) => stamp(a) - stamp(b),
    created: (a, b) => stamp(a) - stamp(b),
  };
  if (key === "default") return desc ? [...es].reverse() : [...es]; // its comparator ties everything
  const dated = key === "age" || key === "updated" || key === "created";
  // a missing timestamp sorts last in both directions
  const miss = (e: Entry): number => (dated && Number.isNaN(stamp(e)) ? 1 : 0);
  return [...es].sort((a, b) => miss(a) - miss(b) || (desc ? -1 : 1) * (miss(a) ? 0 : cmp[key](a, b)));
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
    shownStatus(e) === "running" ? 0 : shownStatus(e) === "open" ? 1 : 2;
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
    const live = stage !== null && !CLOSED.has(stage.status) && stage.status !== "planned";
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

// The span text of a stage block. A planned stage has no dates: `queue <k> of <n>` (its
// 1-based place in the kit's `queue`), "" when the queue lacks it (older kit). Else
// "no date", "Nov 02 – now" or "Nov 02 – Nov 09".
export function stageSpan(g: Group, queue: string[] | undefined): string {
  if (g.stage?.status === "planned") {
    const k = queue?.indexOf(g.stage.id) ?? -1;
    return queue && k >= 0 ? `queue ${k + 1} of ${queue.length}` : "";
  }
  if (!g.first) return "no date";
  return `${shortDay(g.first)} – ${g.live ? "now" : shortDay(g.last)}`;
}

// What a stage block's reveal reaches: the stage itself, or one card and its place
// (`idx`) among the items of its type.
export type Reveal = { card: false } | { card: true; type: string; idx: number };

// null: the selection is not in this block (`holds` false) or there is none. The stage
// itself when the selection is the stage or a card the filters hide.
export function revealTarget(items: Entry[], selected: string | null, holds: boolean): Reveal | null {
  if (!holds || selected === null) return null;
  const e = items.find((x) => x.id === selected);
  if (!e) return { card: false };
  const idx = items.filter((x) => x.type === e.type).findIndex((x) => x.id === selected);
  return { card: true, type: e.type, idx };
}

// Equal keys = no new reveal. A reveal is due on a change of the selection, the sort
// key or direction, or of whether the block holds the selected card (a filter was
// cleared); not on a reload, typing, or a filter change that leaves the card in place.
export function revealKey(items: Entry[], selected: string | null, sort: SortKey, desc: boolean): string {
  const held = selected !== null && items.some((x) => x.id === selected);
  return JSON.stringify([selected, sort, desc, held]);
}

// A block's reveal state: `key` (equal keys = no new reveal) and whether the block
// held the selected card last time.
export type RevealState = { key: string; held: boolean };

// The next reveal state from the last one (the caller keeps it; undefined at mount).
// The key changes on a change of the selection, the sort key or direction, and when
// the selected card comes back into the block (held false -> true, all else equal);
// not when it leaves (typing, a filter, a reload), nor on a reload that keeps it.
export function nextReveal(
  prev: RevealState | undefined,
  items: Entry[],
  selected: string | null,
  sort: SortKey,
  desc: boolean,
): RevealState {
  const held = selected !== null && items.some((x) => x.id === selected);
  const base = JSON.stringify([selected, sort, desc]);
  // the key is `<base>#<n>`; n counts the returns of the card under the same base
  const n = prev?.key.startsWith(`${base}#`) ? Number(prev.key.slice(base.length + 1)) : -1;
  const next = n < 0 ? 0 : held && !prev?.held ? n + 1 : n;
  return { key: `${base}#${next}`, held };
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
