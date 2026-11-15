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
  stage: string[]; owner: string[]; q: string; e: string | null;
};

export const NONE = "-"; // filter token for an empty owner / stage
export const STATUSES = ["open", "running", "done", "dropped", "superseded", "shelved"];

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
  if (r.e) p.push(`e=${encodeURIComponent(r.e)}`);
  return `#/${r.tab}${p.length ? "?" + p.join("&") : ""}`;
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

export function matches(e: Entry, q: string): boolean {
  const n = q.trim().toLowerCase();
  if (!n) return true;
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
      matches(e, q),
  );
  return pinExact(sortDefault(out, l.types), q);
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

const DAY = 86_400_000;
export const CLOSED = new Set(["done", "dropped", "superseded", "shelved"]);
const p2 = (n: number): string => String(n).padStart(2, "0");

export type Span = { start: number; end: number }; // end >= start

// Bar of an entry: start = created (an imported entry: extra.date when
// `dated`), end = updated for a closed status, else `now`. null when the start
// is no valid date; a closed entry with a bad `updated` gets a zero-length bar.
export function spanOf(e: Entry, now: number, dated = true): Span | null {
  const d = dated ? e.extra.date : undefined;
  const start = parseTs(typeof d === "string" ? d : e.created).getTime();
  if (Number.isNaN(start)) return null;
  const upd = CLOSED.has(e.status) ? parseTs(e.updated).getTime() : now;
  return { start, end: Number.isNaN(upd) ? start : Math.max(upd, start) };
}

// a range is never narrower than a day, so percent maths never divides by 0
function widen(s: Span): Span {
  const pad = Math.max(DAY - (s.end - s.start), 0) / 2;
  return { start: s.start - pad, end: s.end + pad };
}

// earliest start to latest end; null when there is no valid span
export function rangeOf(spans: (Span | null)[]): Span | null {
  let r: Span | null = null;
  for (const s of spans) {
    if (s) r = r ? { start: Math.min(r.start, s.start), end: Math.max(r.end, s.end) } : s;
  }
  return r && widen(r);
}

// the window of one span with a little air on both sides
export function zoomRange(s: Span, pad = 0.05): Span {
  const p = (s.end - s.start) * pad;
  return widen({ start: s.start - p, end: s.end + p });
}

export function pct(r: Span, t: number): number {
  return Math.min(100, Math.max(0, ((t - r.start) / (r.end - r.start)) * 100));
}

// css left / width in percent of `r`; clipped to it
export function box(r: Span, s: Span): { left: number; width: number } {
  const left = pct(r, s.start);
  return { left, width: pct(r, s.end) - left };
}

export function dayOf(t: number): string {
  const d = new Date(t);
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
}

// axis labels: month starts for a long range, else six even ticks (with the
// time of day when the range is under three days)
export function ticks(r: Span): { t: number; label: string }[] {
  const len = r.end - r.start;
  if (len > 90 * DAY) {
    const out: { t: number; label: string }[] = [];
    let d = new Date(r.start);
    d = new Date(d.getFullYear(), d.getMonth() + 1, 1);
    while (d.getTime() < r.end) {
      out.push({ t: d.getTime(), label: `${d.getFullYear()}-${p2(d.getMonth() + 1)}` });
      d = new Date(d.getFullYear(), d.getMonth() + 1, 1);
    }
    const stride = Math.ceil(out.length / 8);
    return out.filter((_, i) => i % stride === 0);
  }
  return Array.from({ length: 6 }, (_, i) => {
    const t = r.start + (len * i) / 5;
    const d = new Date(t);
    const hm = len < 3 * DAY ? ` ${p2(d.getHours())}:${p2(d.getMinutes())}` : "";
    return { t, label: dayOf(t).slice(5) + hm };
  });
}

export type Lane = {
  key: string; // stage id, "" for the unstaged lane
  stage: Entry | null;
  items: { e: Entry; span: Span | null }[]; // by start
  span: Span | null;
};

// One lane per stage entry (oldest first), then "unstaged" when it has entries.
// An entry of a stage that is not in `entries` (filtered out) is left out.
export function buildLanes(entries: Entry[], now: number): Lane[] {
  const at = (s: Span | null): number => (s ? s.start : Number.MAX_SAFE_INTEGER);
  const lanes: Lane[] = entries
    .filter((e) => e.type === "stage")
    .map((e) => ({ key: e.id, stage: e, items: [], span: spanOf(e, now, false) }))
    .sort((a, b) => at(a.span) - at(b.span));
  const un: Lane = { key: "", stage: null, items: [], span: null };
  const by = new Map(lanes.map((l) => [l.key, l]));
  for (const e of entries) {
    if (e.type === "stage") continue;
    const lane = e.stage === "" ? un : by.get(e.stage);
    lane?.items.push({ e, span: spanOf(e, now) });
  }
  for (const l of [...lanes, un]) l.items.sort((a, b) => at(a.span) - at(b.span));
  un.span = rangeOf(un.items.map((i) => i.span));
  return un.items.length ? [...lanes, un] : lanes;
}
