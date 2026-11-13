export type Entry = {
  id: string; type: string; title: string; status: string;
  owner: string; stage: string; note: string; links: string[]; refs: string[];
  created: string; updated: string; started: string;
  extra: Record<string, string | boolean>; lines: number[];
};
export type Ev = {
  line: number; ts: string; who: string; ev: "add" | "set";
  id: string; f: Record<string, unknown>;
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
export const STATUSES = ["open", "running", "done", "dropped", "superseded"];

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

// an entry whose id equals the query (case-insensitive) goes first; stable otherwise
export function pinExact(es: Entry[], q: string): Entry[] {
  const n = q.trim().toLowerCase();
  if (!n) return es;
  return [...es.filter((e) => e.id.toLowerCase() === n), ...es.filter((e) => e.id.toLowerCase() !== n)];
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

// `text` is set for a stage code: the link shows the code, the target is the stage
export type Seg = string | { id: string; text?: string } | { label: string };

// A stage's code is the leading "NN" or "NNx" of its title ("07b-software-parser"
// -> "07b"). A code that two stages claim is dropped: no guessing.
export function stageCodes(entries: Entry[]): Map<string, string> {
  const m = new Map<string, string | null>();
  for (const e of entries) {
    const c = e.type === "stage" ? /^([0-9]{2}[a-z]?)-/.exec(e.title)?.[1] : undefined;
    if (c) m.set(c, m.has(c) ? null : e.id);
  }
  return new Map([...m].filter((kv): kv is [string, string] => kv[1] !== null));
}

const RICH = /(\b[A-Z]{1,3}-[1-9][0-9]*\b)|(\bW[0-9]+[a-z]?\b)|([0-9]{2}[a-z]?)/g;

// a stage code must stand alone: not part of a longer number or word, a date
// (2026-11-13), a time (15:39), a version (1.07b), a path or an id (T-07)
function standalone(t: string, i: number, n: number): boolean {
  const side = (c: string | undefined, beyond: string | undefined): boolean =>
    c === undefined ||
    !(/[\w/\\-]/.test(c) || ((c === "." || c === ":") && beyond !== undefined && /[0-9]/.test(beyond)));
  return side(t[i - 1], t[i - 2]) && side(t[i + n], t[i + n + 1]);
}

// Splits text into plain strings and links. Without `codes`: only existing
// entry ids become {id}. With `codes` (stage code -> stage id, see stageCodes):
// a standalone stage code also becomes {id: <stage id>, text: <code>} and a work-item label
// (W6, W6b) becomes {label}; labels are search terms, never entry links.
export function linkify(text: string, ids: Set<string>, codes?: Map<string, string>): Seg[] {
  const out: Seg[] = [];
  let last = 0;
  const hit = (m: RegExpMatchArray, seg: Seg): void => {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    out.push(seg);
    last = at + m[0].length;
  };
  if (!codes) {
    for (const m of text.matchAll(ID_TOKEN)) if (ids.has(m[0])) hit(m, { id: m[0] });
  } else {
    for (const m of text.matchAll(RICH)) {
      if (m[1]) {
        if (ids.has(m[1])) hit(m, { id: m[1] });
      } else if (m[2]) {
        hit(m, { label: m[2] });
      } else if (m[3]) {
        const stage = codes.get(m[3]);
        if (stage && standalone(text, m.index ?? 0, m[3].length)) hit(m, { id: stage, text: m[3] });
      }
    }
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
