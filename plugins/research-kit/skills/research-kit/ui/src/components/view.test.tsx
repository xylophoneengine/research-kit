// First-paint tests of the viewer's components (T-96): a static render under vitest's
// node environment, no DOM library (design D1, I8). `location`, `window` and
// `localStorage` are stubbed where a component reads them. Not checked here: clicks,
// effects (the reveal), a hand flip of a board column; the lead looks at those.
import type { ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "@/App";
import { Board } from "@/components/Board";
import { Filters } from "@/components/Filters";
import { Stages } from "@/components/Stages";
import { Storyline } from "@/components/timeline/Storyline";
import { parseRoute, type Entry, type Ledger } from "@/lib/ledger";

const base = {
  note: "", links: [], refs: [], started: "", extra: {},
  lines: [], created: "2026-11-13T09:00:00+01:00", updated: "2026-11-13T09:00:00+01:00",
};
const stage = (id: string, status: string, title: string, o: Partial<Entry> = {}): Entry =>
  ({ ...base, id, type: "stage", title, status, owner: "lead", stage: "", ...o });
const task = (id: string, stg: string, o: Partial<Entry> = {}): Entry =>
  ({ ...base, id, type: "task", title: `task ${id}`, status: "open", owner: "x", stage: stg, ...o });

beforeEach(() => {
  vi.stubGlobal("location", { hash: "" });
  vi.stubGlobal("localStorage", undefined); // reads fail and fall back, as with blocked storage
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const store = (items: Record<string, string>): void =>
  void vi.stubGlobal("localStorage", {
    getItem: (k: string): string | null => items[k] ?? null,
    setItem: (): void => {},
  });
// text of a markup piece: tags dropped, white space squeezed
const txt = (s: string): string => s.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
// table rows: each piece starts with the attributes of its <tr
const trs = (html: string): string[] => html.split("<tr").slice(1);
const openTag = (s: string): string => s.slice(0, s.indexOf(">") + 1);
const attr = (tag: string, name: string): string | undefined =>
  new RegExp(`${name}="([^"]*)"`).exec(tag)?.[1];

// ---- Stages ---------------------------------------------------------------------

const S1 = stage("S-1", "open", "01-software-a");
const S2 = stage("S-2", "open", "02-paper-b");
const S3 = stage("S-3", "open", "03-paper-c");
const stagesAll = [S1, S2, S3, task("T-1", "S-1"), task("T-2", ""), task("T-3", "")];

const stages = (o: Partial<ComponentProps<typeof Stages>> = {}): string =>
  renderToStaticMarkup(
    <Stages
      all={stagesAll}
      entries={stagesAll}
      ledgerIds={new Set(stagesAll.map((e) => e.id))}
      status={null}
      forecast={undefined}
      stageFilter={[]}
      patch={() => {}}
      {...o}
    />,
  );

const HINT = (n: number): string =>
  `stage filter set (${n}): the marked rows are in it; this tab lists every stage`;
const hintOf = (html: string): string | undefined =>
  /<p[^>]*data-hint="stage-filter"[^>]*>([^<]*)<\/p>/.exec(html)?.[1];

// R1: a set stage filter hides no row and changes no count; it marks its rows (the
// backlog row for `-`) and one hint line says it is set, above the table
test("stages: a stage filter marks its rows and shows the hint, no row is hidden", () => {
  const html = stages({ stageFilter: ["S-1", "S-3"] });
  for (const t of ["01-software-a", "02-paper-b", "03-paper-c", "unstaged / backlog"]) {
    expect(html, t).toContain(t); // nothing is hidden
  }
  const marks: Record<string, boolean> = {};
  for (const r of trs(html)) {
    const tag = openTag(r);
    const id = attr(tag, "data-row");
    if (id) marks[id] = attr(tag, "data-filtered") === "true";
  }
  expect(marks).toEqual({ backlog: false, "S-1": true, "S-2": false, "S-3": true });
  expect(hintOf(html)).toBe(HINT(2));
  expect(html.indexOf('data-hint="stage-filter"')).toBeLessThan(html.indexOf("<table"));
  // the backlog row is the filtered one for `-`
  const dash = stages({ stageFilter: ["-"] });
  const rows = trs(dash).filter((r) => attr(openTag(r), "data-row") !== undefined);
  expect(rows.filter((r) => attr(openTag(r), "data-filtered") === "true").map((r) => attr(openTag(r), "data-row")))
    .toEqual(["backlog"]);
  expect(hintOf(dash)).toBe(HINT(1));
  // no filter, or all: no hint, no mark
  for (const f of [[], ["*"]]) {
    const plain = stages({ stageFilter: f });
    expect(hintOf(plain), String(f)).toBeUndefined();
    expect(plain, String(f)).not.toContain("data-filtered");
  }
});

// R2: the backlog row is the first body row, the stage rows follow in their order
test("stages: backlog is the first body row", () => {
  const html = stages();
  expect(html.indexOf("unstaged / backlog")).toBeLessThan(html.indexOf("01-software-a"));
  const body = html.slice(html.indexOf("<tbody"));
  expect([...body.matchAll(/data-row="([^"]+)"/g)].map((m) => m[1])).toEqual(["backlog", "S-1", "S-2", "S-3"]);
});

// R7a (guard): a stage is one row of the one table, a planned and a shelved one too
test("stages: each stage is one row", () => {
  const p = stage("S-4", "planned", "paper-d");
  const h = stage("S-5", "shelved", "paper-e");
  const all = [...stagesAll, p, h];
  const html = stages({ all, entries: all, forecast: { "S-4": "~04" } });
  for (const t of ["01-software-a", "02-paper-b", "paper-d", "paper-e"]) {
    expect(html.split(`>${t}<`).length - 1, t).toBe(1);
  }
  expect(trs(html)).toHaveLength(1 + 5 + 1); // head, five stages, the backlog row
});

// R15a (guard): the defaults of the Stages tab
test("stages: defaults", () => {
  const p = stage("S-4", "planned", "paper-d");
  const all = [stage("S-5", "open", "03-paper-e"), S1, S2, p, task("T-1", "S-2"), task("T-2", ""),
    task("T-3", "", { shown: "open" }), task("T-4", "", { status: "done" })];
  const html = stages({ all, entries: all, forecast: { "S-4": "~04" } });
  const heads = [...html.matchAll(/<th[^>]*>([^<]*)<\/th>/g)].map((m) => m[1].trim());
  expect(heads).toEqual(["no. ▲", "id", "title", "status", "entries"]); // ascending first
  const at = ["01-software-a", "02-paper-b", "03-paper-e", "paper-d"].map((t) => html.indexOf(`>${t}<`));
  expect(at.every((i) => i > 0)).toBe(true);
  expect([...at].sort((a, b) => a - b)).toEqual(at); // rows by number, the planned one at its forecast
  const row = (title: string): string => txt(trs(html).find((r) => r.includes(title)) ?? "");
  expect(row("unstaged / backlog")).toMatch(/open 2\b/); // the backlog: T-2 and T-3 ...
  expect(row("unstaged / backlog")).toMatch(/done 1\b/); // ... and T-4; no stage entry in it
  expect(row("unstaged / backlog")).not.toMatch(/open 3\b/);
  expect(row("02-paper-b")).toMatch(/open 1\b/); // T-1
});

// ---- Board ----------------------------------------------------------------------

const board = (o: Partial<ComponentProps<typeof Board>> = {}): string =>
  renderToStaticMarkup(
    <Board
      entries={[]}
      sort="default"
      desc={false}
      statusFilter={null}
      forecast={undefined}
      planned={0}
      selected={null}
      onSelect={() => {}}
      {...o}
    />,
  );
const colsOf = (html: string): string[] => [...html.matchAll(/data-col="([^"]+)"/g)].map((m) => m[1]);
const chips = (html: string): Record<string, boolean> =>
  Object.fromEntries(
    [...html.matchAll(/<button[^>]*aria-pressed="(true|false)"[^>]*>([^<]*)<\/button>/g)].map((m) => [
      m[2].trim().replace(/ \d+$/, ""),
      m[1] === "true",
    ]),
  );
const chipText = (html: string, col: string): string | undefined =>
  [...html.matchAll(/<button[^>]*aria-pressed="[a-z]+"[^>]*>([^<]*)<\/button>/g)]
    .map((m) => m[1].trim())
    .find((t) => t.startsWith(`${col} `));
const rowsIn = (html: string, col: string): string[] => {
  const at = html.indexOf(`data-col="${col}"`);
  if (at < 0) return [];
  const next = html.indexOf('data-col="', at + 1);
  return [...html.slice(at, next < 0 ? undefined : next).matchAll(/data-row="([^"]+)"/g)].map((m) => m[1]);
};

const OFF = ["planned", "shelved", "dropped", "superseded"];

// R3 (D-108, D-112): the planned column is on by default only when the ledger shows
// something planned, whatever the filters; the other defaults stay
test("board: planned column off when the ledger has nothing planned, on when it has, also when the filters leave the column empty", () => {
  const es = [task("T-1", ""), task("T-2", "", { status: "done" })];
  const none = board({ entries: es, planned: 0 });
  expect(colsOf(none)).toEqual(expect.arrayContaining(["running", "open", "deferred", "staged", "done"]));
  for (const c of OFF) expect(colsOf(none), c).not.toContain(c);
  expect(chips(none)).toMatchObject({ planned: false, shelved: false, dropped: false, superseded: false, open: true });
  // something is planned in the ledger but the filters leave none on the board: the column stands, empty
  const empty = board({ entries: es, planned: 2 });
  expect(colsOf(empty)).toContain("planned");
  expect(rowsIn(empty, "planned")).toEqual([]);
  expect(chipText(empty, "planned")).toBe("planned 0"); // the chip keeps the filtered count
  expect(chips(empty).planned).toBe(true);
  // and with a planned entry on the board
  const one = task("T-5", "", { shown: "planned" });
  const full = board({ entries: [...es, one], planned: 1 });
  expect(rowsIn(full, "planned")).toEqual(["T-5"]);
  expect(chipText(full, "planned")).toBe("planned 1");
  for (const c of ["shelved", "dropped", "superseded"]) expect(colsOf(full), c).not.toContain(c);
});

// R3 (D-108, I3): a column switched by hand stays as switched; the old stored value is
// read once; garbage counts as no choice
test("board: a hand choice is read from storage, the old stored value is migrated", () => {
  const es = [task("T-1", "")];
  store({ "rk-ui-board-cols": '{"open":false,"shelved":true}' });
  const hand = board({ entries: es, planned: 0 });
  expect(colsOf(hand)).toContain("shelved");
  expect(colsOf(hand)).not.toContain("open");
  expect(chips(hand)).toMatchObject({ open: false, shelved: true });
  // the old key (an array of the hidden columns), while the new key is absent: superseded was
  // shown by hand; planned was never touched, so the default holds
  store({ "rk-ui-board-folded": '["shelved","dropped"]' });
  const old = board({ entries: es, planned: 0 });
  expect(colsOf(old)).toContain("superseded");
  for (const c of ["planned", "shelved", "dropped"]) expect(colsOf(old), c).not.toContain(c);
  expect(colsOf(board({ entries: es, planned: 3 }))).toContain("planned");
  // the new key wins over the old one
  store({ "rk-ui-board-cols": '{"open":false}', "rk-ui-board-folded": '["done"]' });
  const both = board({ entries: es, planned: 0 });
  expect(colsOf(both)).not.toContain("open");
  expect(colsOf(both)).toContain("done");
  // not an object of booleans: no choice at all
  store({ "rk-ui-board-cols": "[true]" });
  const junk = board({ entries: es, planned: 0 });
  expect(colsOf(junk)).toContain("open");
  expect(colsOf(junk)).not.toContain("planned");
});

// R8a: the planned and shelved columns keep each stage card first (in no. order) and
// order the entries of a group by the sort: newest update first, reversed by desc;
// another sort arrives applied in `entries` and stays
test("board: planned and shelved columns are grouped and follow the sort inside a group", () => {
  store({ "rk-ui-board-folded": "[]" }); // every column on (planned: the count says so)
  const day = (d: string): string => `2026-11-${d}T09:00:00+01:00`;
  const pl = (id: string, stg: string, d: string): Entry =>
    task(id, stg, { shown: "planned", updated: day(d) });
  const sh = (id: string, stg: string, d: string): Entry =>
    task(id, stg, { shown: "shelved", updated: day(d) });
  const entries = [
    pl("T-9", "S-2", "10"), stage("S-2", "planned", "paper-b"), pl("T-4", "S-3", "11"),
    stage("S-3", "planned", "paper-c"), pl("T-3", "S-2", "12"), pl("T-5", "S-3", "13"),
    sh("T-6", "S-6", "10"), stage("S-6", "shelved", "paper-f"), sh("T-7", "S-6", "12"),
  ];
  const fc = { "S-2": "~03", "S-3": "~02" };
  const show = (o: Partial<ComponentProps<typeof Board>>): string =>
    board({ entries, forecast: fc, planned: 5, ...o });
  const up = show({});
  expect(rowsIn(up, "planned")).toEqual(["S-3", "T-5", "T-4", "S-2", "T-3", "T-9"]);
  expect(rowsIn(up, "shelved")).toEqual(["S-6", "T-7", "T-6"]);
  const down = show({ desc: true });
  expect(rowsIn(down, "planned")).toEqual(["S-3", "T-4", "T-5", "S-2", "T-9", "T-3"]);
  expect(rowsIn(down, "shelved")).toEqual(["S-6", "T-6", "T-7"]);
  // sort=id: visible() delivers the entries in id order; a group keeps that order
  const byId = [...entries].sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }));
  expect(rowsIn(show({ sort: "id", entries: byId }), "planned")).toEqual(["S-3", "T-4", "T-5", "S-2", "T-3", "T-9"]);
});

// ---- Filters --------------------------------------------------------------------

// R6: a facet set to all reads (all); a list reads its count
test("filters: a facet set to all reads (all)", () => {
  const ledger: Ledger = {
    repo: "/r", events: [], types: { task: "T", stage: "S", decision: "D" },
    entries: [S1, task("T-1", "S-1"), task("T-2", "", { owner: "user" })],
  };
  const route = parseRoute("#/board?status=*&owner=*&type=task,stage");
  const html = renderToStaticMarkup(<Filters ledger={ledger} route={route} patch={() => {}} />);
  const buttons = [...html.matchAll(/<button[^>]*aria-haspopup="menu"[^>]*>([\s\S]*?)<\/button>/g)].map((m) => txt(m[1]));
  expect(buttons).toEqual(["status (all)", "type (2)", "stage", "owner (all)"]);
});

// ---- Timeline -------------------------------------------------------------------

// R4: a planned stage has the hollow dot (a solid border on the background fill, not
// the dashed dot of the unstaged group), the planned badge, its queue place and no dates
test("timeline: a planned stage has the hollow dot, the badge and its queue place", () => {
  const late = { created: "2026-11-02T09:00:00+01:00", updated: "2026-11-09T09:00:00+01:00" };
  const all = [
    stage("S-1", "open", "01-software-a"), task("T-1", "S-1"),
    stage("S-2", "planned", "paper-b"), stage("S-3", "planned", "paper-c"),
    stage("S-4", "done", "02-paper-d", late), stage("S-5", "planned", "paper-e"),
    task("T-9", ""),
  ];
  const props = {
    all, entries: all, events: [], ledgerIds: new Set(all.map((e) => e.id)),
    onSelect: () => {}, sort: "default" as const, desc: false, queue: ["S-3", "S-2"],
  };
  const render = (selected: string | null): string =>
    renderToStaticMarkup(<Storyline {...props} selected={selected} />);
  const blocks = (html: string): string[] => html.split(/(?=<[^<>]*data-dot=")/).slice(1);
  const dotOf = (b: string): string | undefined => attr(openTag(b), "data-dot");
  const html = render(null);
  const bs = blocks(html);
  expect(bs.map(dotOf)).toEqual(["live", "planned", "planned", "closed", "planned", "unstaged"]);
  const hollow = openTag(bs[1]);
  expect(hollow).toContain("bg-background");
  expect(hollow).toMatch(/\bborder\b/);
  expect(hollow).not.toContain("dashed");
  expect(openTag(bs[5])).toContain("dashed"); // the unstaged dot stays dashed
  expect(txt(bs[1])).toContain("planned"); // the badge
  expect(txt(bs[1])).toContain("queue 2 of 2");
  expect(txt(bs[2])).toContain("queue 1 of 2");
  for (const i of [1, 2, 4]) {
    expect(txt(bs[i]), String(i)).not.toMatch(/Nov \d\d|no date|now/); // no date span
  }
  expect(txt(bs[4])).not.toContain("queue"); // S-5 is not in plan.queue: no span text
  expect(txt(bs[0])).toContain("Nov 13 – now");
  expect(txt(bs[3])).toContain("Nov 02 – Nov 09");
  // the selected block keeps the selection dot
  expect(blocks(render("S-2")).map(dotOf)).toEqual(["live", "selected", "planned", "closed", "planned", "unstaged"]);
});

// ---- Header ---------------------------------------------------------------------

// R11 (guard): the exact button shows only in id mode; it carries its pressed state
// and the label with the hint text
test("header: exact button only in id mode, pressed state and label", () => {
  vi.stubGlobal("window", {});
  const app = (hash: string): string => {
    vi.stubGlobal("location", { hash });
    return renderToStaticMarkup(<App />);
  };
  const exactTag = (html: string): string | undefined =>
    /<button[^>]*aria-label="exact match only: [^"]*"[^>]*>/.exec(html)?.[0];
  expect(exactTag(app("#/list"))).toBeUndefined();
  const prefix = app("#/list?q=T-1&idonly=1");
  const t1 = exactTag(prefix) ?? "";
  expect(attr(t1, "aria-label")).toBe("exact match only: ids match by prefix, labels match whole");
  expect(attr(t1, "aria-pressed")).toBe("false");
  expect(prefix).toContain(">exact</button>");
  const whole = app("#/list?q=T-1&idonly=1&exact=1");
  const t2 = exactTag(whole) ?? "";
  expect(attr(t2, "aria-label")).toBe("exact match only: ids match whole, labels match whole");
  expect(attr(t2, "aria-pressed")).toBe("true");
});
