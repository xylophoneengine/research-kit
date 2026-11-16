import { expect, test } from "vitest";
import { typeClasses } from "./typeColor";
import {
  NONE,
  age,
  backlinks,
  BOARD_COLS,
  boardCol,
  byId,
  byType,
  entryDay,
  shortDay,
  stageGroups,
  eventDay,
  evMeta,
  exactHit,
  facets,
  formatRoute,
  labelIndex,
  labelOf,
  linkify,
  matches,
  pinExact,
  clickSort,
  parseRoute,
  projectName,
  sortBy,
  sortDefault,
  sortGroups,
  STATUSES,
  stageCodeOf,
  stageCodes,
  visible,
  type Entry,
  type Ev,
  type Ledger,
} from "./ledger";

const base = {
  note: "", links: [], refs: [], started: "", extra: {}, lines: [],
  created: "2026-11-13T09:00:00+01:00", updated: "2026-11-13T09:00:00+01:00",
};
const t1: Entry = { ...base, id: "T-1", type: "task", title: "first", status: "running",
  owner: "x", stage: "", started: "2026-11-13T12:05:00+01:00" };
const t2: Entry = { ...base, id: "T-2", type: "task", title: "second", status: "open",
  owner: "", stage: "S-1" };
const d1: Entry = { ...base, id: "D-1", type: "decision", title: "pick one",
  status: "done", owner: "user", stage: "", links: ["T-1", "X-9"],
  note: "see T-1 and UTF-8, AB-12 <b>",
  extra: { source: "old.md", legacy_id: "D-07", date: "2026-10-01" } };
const s1: Entry = { ...base, id: "S-1", type: "stage", title: "stage one",
  status: "open", owner: "lead", stage: "" };
const addOfD1: Ev = { line: 3, ts: "2026-11-13T10:00:00+01:00", who: "lead",
  ev: "add", id: "D-1", f: {} };
const setOfT1: Ev = { line: 4, ts: "2026-11-13T12:05:00+01:00", who: "lead",
  ev: "set", id: "T-1", f: { status: "running" } };
const L: Ledger = {
  repo: "/r", entries: [t1, t2, d1, s1], events: [addOfD1, setOfT1],
  types: { task: "T", stage: "S", decision: "D" },
};
const route = parseRoute;
const ids = (es: Entry[]): string[] => es.map((e) => e.id);

test("route round trip", () => {
  const h = "#/board?status=done&type=task,debt&stage=S-1,-&owner=user&q=a%20b&e=D-1";
  expect(formatRoute(parseRoute(h))).toBe(h);
  expect(parseRoute("")).toMatchObject({ tab: "list", status: null, e: null, q: "" });
  expect(parseRoute("#/DF-14")).toMatchObject({ tab: "list", e: "DF-14" });
  expect(parseRoute("#/nope?status=all")).toMatchObject({ tab: "list", status: [] });
});
test("matches", () => {
  expect(matches(d1, "d-07")).toBe(true);      // legacy id
  expect(matches(d1, "OLD.MD")).toBe(true);    // source
  expect(matches(d1, "utf-8")).toBe(true);     // note
  expect(matches(d1, "zzz")).toBe(false);
});
test("id-only search: id prefix or exact label, terms split on spaces and commas", () => {
  const t12: Entry = { ...base, id: "T-12", type: "task", title: "twelve", status: "open",
    owner: "x", stage: "", extra: { legacy_id: "03b/W1" } };
  const L12: Ledger = { ...L, entries: [t1, t12, d1] };
  const r = (q: string): string[] => ids(visible(L12, { ...route("#/board"), q, idOnly: true }));
  expect(r("T-1")).toEqual(["T-1", "T-12"]);              // prefix: T-12 too
  expect(r("t-12, D-1 03B/W1")).toEqual(["T-12", "D-1"]);
  expect(r("D-07")).toEqual(["D-1"]);                     // legacy_id of d1
  expect(r("pick")).toEqual([]);                          // no substring match
  expect(r(" , ")).toEqual([]);
  expect(r("")).toEqual(["T-1", "T-12", "D-1"]);          // empty query: all
  expect(ids(visible(L12, { ...route("#/list?q=T-12"), idOnly: true }))).toEqual(["T-12"]);
  expect(matches(t12, "tw", false)).toBe(true);           // toggle off: fuzzy as before
  expect(parseRoute("#/list?idonly=1").idOnly).toBe(true);
  expect(formatRoute(parseRoute("#/list?q=T-1&idonly=1"))).toBe("#/list?q=T-1&idonly=1");
  expect(formatRoute(parseRoute("#/list"))).toBe("#/list");
});
test("projectName: last path segment, any separator", () => {
  expect(projectName("/srv/work/research-kit-ui")).toBe("research-kit-ui");
  expect(projectName("/a/b/proj/")).toBe("proj");
  expect(projectName("C:\\work\\proj\\")).toBe("proj");
  expect(projectName("/")).toBe("/");
  expect(projectName("")).toBe("");
});
test("column sorts live in the route; header click cycles; pinning stays", () => {
  const mk = (id: string, o: Partial<Entry>): Entry =>
    ({ ...base, id, type: "task", title: id, status: "open", owner: "", stage: "", ...o });
  const a = mk("T-1", { owner: "zed", title: "beta", created: "2026-11-01T10:00:00+01:00" });
  const b = mk("T-2", { owner: "amy", title: "alpha", created: "2026-11-03T10:00:00+01:00" });
  const c = mk("T-3", { owner: "", title: "gamma", status: "running",
    created: "2026-11-02T10:00:00+01:00", started: "2026-11-04T10:00:00+01:00" });
  const bad = mk("T-4", { owner: "bob", title: "delta", created: "not a date" });
  const LC: Ledger = { ...L, entries: [a, b, c, bad] };
  const s = (h: string): string[] => ids(visible(LC, route(`#/list?status=all&${h}`)));
  expect(s("sort=owner")).toEqual(["T-3", "T-2", "T-4", "T-1"]);               // "" first
  expect(s("sort=owner&dir=desc")).toEqual(["T-1", "T-4", "T-2", "T-3"]);
  expect(s("sort=title")).toEqual(["T-2", "T-1", "T-4", "T-3"]);
  expect(s("sort=status")).toEqual(["T-1", "T-2", "T-4", "T-3"]);              // open < running
  expect(s("sort=age")).toEqual(["T-3", "T-2", "T-1", "T-4"]);                 // youngest first; running by start; bad date last
  expect(s("sort=age&dir=desc")).toEqual(["T-1", "T-2", "T-3", "T-4"]);        // oldest first; bad date still last
  expect(s("sort=title&q=t-4")).toEqual(["T-4"]);
  expect(ids(pinExact(sortBy([a, b, c, bad], "title", false), "t-3"))).toEqual(["T-3", "T-2", "T-1", "T-4"]);
  expect(clickSort("default", false, "id")).toEqual({ sort: "id", desc: false });
  expect(clickSort("id", false, "id")).toEqual({ sort: "id", desc: true });
  expect(clickSort("id", true, "id")).toEqual({ sort: "default", desc: false });
  expect(clickSort("id", true, "owner")).toEqual({ sort: "owner", desc: false });
});
test("sortBy: a missing timestamp sorts last for updated, created and age, both directions; ties keep the incoming order", () => {
  const mk = (id: string, upd: string): Entry =>
    ({ ...base, id, type: "task", title: id, status: "done", owner: "", stage: "", updated: upd,
      created: upd });
  const none = mk("T-3", "");
  const none2 = mk("T-4", "");
  const x = mk("T-1", "2026-11-01T10:00:00+01:00");
  const y = mk("T-2", "2026-11-01T10:00:00+01:00");
  const old = mk("T-5", "2026-10-01T10:00:00+01:00");
  for (const k of ["updated", "created"] as const) {
    expect(ids(sortBy([none, none2, x, old], k, false))).toEqual(["T-5", "T-1", "T-3", "T-4"]);
    expect(ids(sortBy([none, none2, x, old], k, true))).toEqual(["T-1", "T-5", "T-3", "T-4"]);
  }
  expect(ids(sortBy([none, none2, x, old], "age", false))).toEqual(["T-1", "T-5", "T-3", "T-4"]);
  expect(ids(sortBy([none, none2, x, old], "age", true))).toEqual(["T-5", "T-1", "T-3", "T-4"]);
  expect(ids(sortBy([x, y, none], "updated", false))).toEqual(["T-1", "T-2", "T-3"]);
  expect(ids(sortBy([y, x], "updated", false))).toEqual(["T-2", "T-1"]); // tie: unchanged
  expect(ids(sortBy([x, y, none], "updated", true))).toEqual(["T-1", "T-2", "T-3"]); // tie kept, none last
  expect(ids(sortBy([y, x], "updated", true))).toEqual(["T-2", "T-1"]);
  expect(ids(sortBy([x, y, none], "default", true))).toEqual(["T-3", "T-2", "T-1"]); // default desc reverses
});
test("sort: key and direction, kept in the route, list tab only", () => {
  const mk = (id: string, upd: string, cre: string): Entry =>
    ({ ...base, id, type: "task", title: id, status: "done", owner: "", stage: "",
      updated: upd, created: cre });
  const a = mk("T-10", "2026-11-01T10:00:00+01:00", "2026-10-03T10:00:00+01:00");
  const b = mk("T-2", "2026-11-03T10:00:00+01:00", "2026-10-02T10:00:00+01:00");
  const c = mk("D-5", "2026-11-02T10:00:00+01:00", "2026-10-01T10:00:00+01:00");
  const LS: Ledger = { ...L, entries: [a, b, c] };
  const s = (h: string): string[] => ids(visible(LS, route(h)));
  const all = "status=all";
  expect(s(`#/list?${all}`)).toEqual(["T-2", "D-5", "T-10"]);               // default (same type: by number)
  expect(s(`#/list?${all}&dir=desc`)).toEqual(["T-10", "D-5", "T-2"]);
  expect(s(`#/list?${all}&sort=id`)).toEqual(["D-5", "T-2", "T-10"]);       // prefix, then number
  expect(s(`#/list?${all}&sort=id&dir=desc`)).toEqual(["T-10", "T-2", "D-5"]);
  expect(s(`#/list?${all}&sort=updated`)).toEqual(["T-10", "D-5", "T-2"]);
  expect(s(`#/list?${all}&sort=updated&dir=desc`)).toEqual(["T-2", "D-5", "T-10"]);
  expect(s(`#/list?${all}&sort=created`)).toEqual(["D-5", "T-2", "T-10"]);
  expect(s(`#/board?${all}&sort=id`)).toEqual(["D-5", "T-2", "T-10"]);      // the board follows the sort
  expect(s(`#/board?${all}&sort=id&dir=desc`)).toEqual(["T-10", "T-2", "D-5"]);
  expect(s(`#/board?${all}`)).toEqual(["T-2", "D-5", "T-10"]);              // nothing in the hash: as before
  expect(s(`#/stages?${all}&sort=id`)).toEqual(["T-2", "D-5", "T-10"]);     // stages and timeline ignore it
  expect(s(`#/timeline?${all}&sort=id`)).toEqual(["T-2", "D-5", "T-10"]);
  expect(s(`#/list?${all}&sort=id&q=t-2`)).toEqual(["T-2"]);
  expect(ids(pinExact(sortBy([a, b, c], "id", true), "d-5"))).toEqual(["D-5", "T-10", "T-2"]);
  expect(route("#/list?sort=bogus")).toMatchObject({ sort: "default", desc: false });
  expect(formatRoute(route("#/list?sort=updated&dir=desc"))).toBe("#/list?sort=updated&dir=desc");
  expect(formatRoute(route("#/list"))).toBe("#/list");                      // old links unchanged
});
test("visible: default status only without a query (Review Focus 1)", () => {
  expect(ids(visible(L, route("#/list")))).toEqual(["T-1", "T-2", "S-1"]);
  expect(ids(visible(L, route("#/list?q=D-1")))).toEqual(["D-1"]);
  expect(ids(visible(L, route("#/list?q=D-1&status=open")))).toEqual([]);
  expect(ids(visible(L, route("#/board")))).toEqual(["T-1", "T-2", "S-1", "D-1"]);
  expect(ids(visible(L, route("#/list?owner=-")))).toEqual(["T-2"]);   // S-1 owner "lead"
  expect(ids(visible(L, route("#/list?status=all")))).toEqual(["T-1", "T-2", "S-1", "D-1"]);
});
test("exact id match comes first (search ranking)", () => {
  const t3: Entry = { ...base, id: "T-3", type: "task", title: "third", status: "open",
    owner: "x", stage: "", note: "relates to D-1" };
  const L3: Ledger = { ...L, entries: [t3, d1] };
  expect(ids(visible(L3, route("#/board?q=d-1")))).toEqual(["D-1", "T-3"]);
  expect(ids(pinExact([t3, d1], "D-1"))).toEqual(["D-1", "T-3"]);
});
test("backlinks and unknown links (Review Focus 3)", () => {
  expect(backlinks(L).get("T-1")).toEqual(["D-1"]);
  expect(backlinks(L).has("X-9")).toBe(true);   // harmless; never rendered as entry
  expect(byId(L).has("X-9")).toBe(false);
});
test("facets include NONE for empty values", () => {
  expect(facets(L).owner).toContain(NONE);
  expect(facets(L).stage).toEqual(expect.arrayContaining(["S-1", NONE]));
});
test("linkify links only existing ids, keeps text raw (Review Focus 2)", () => {
  expect(linkify("see T-1 and UTF-8, AB-12 <b>", new Set(["T-1"]))).toEqual(
    ["see ", { id: "T-1" }, " and UTF-8, AB-12 <b>"]);
});
test("age and eventDay", () => {
  expect(age(t1, new Date("2026-11-13T14:05:00+01:00"))).toBe("2h");  // from started 12:05
  expect(eventDay(addOfD1, d1)).toBe("2026-10-01");
  expect(eventDay(setOfT1, t1)).toBe("2026-11-13");
});

const st = (id: string, title: string): Entry => ({ ...base, id, type: "stage", title, status: "open", owner: "", stage: "" });
const stages = [st("S-7", "03b-software-parser"), st("S-8", "07-paper-plan"), st("S-3", "05-a"), st("S-4", "05-b"), s1];
const codes = stageCodes(stages);
const sids = new Set(["S-7", "S-8", "T-1"]);

test("stageCodes: leading NN / NNx of a stage title; a claimed-twice code is dropped", () => {
  expect(Object.fromEntries(codes)).toEqual({ "03b": "S-7", "07": "S-8" });
  expect(codes.has("05")).toBe(false);          // S-3 and S-4 both claim it
  expect(stageCodes([t1, d1]).size).toBe(0);    // only stage entries count
});
test("linkify with codes: stage code and W label hits", () => {
  // changed on purpose: a pure-digit code ("07") links only after the word "stage"
  expect(linkify("stage 03b and 07, W6b (DS236) see T-1", sids, codes)).toEqual([
    "stage ", { id: "S-7", text: "03b" }, " and 07, ",
    { label: "W6b" }, " (DS236) see ", { id: "T-1" }]);
  expect(linkify("03b: done. 03b.", sids, codes)).toEqual(
    [{ id: "S-7", text: "03b" }, ": done. ", { id: "S-7", text: "03b" }, "."]);
});
test("linkify with codes: no hit inside a date, time, version, id, longer token", () => {
  const t = "on 2026-11-13 at 15:39, v1.03b, T-07, 03bx, 1007, 3.07, W6bx, AW6, 07-08, a/07";
  expect(linkify(t, sids, codes)).toEqual([t]);
});
test("linkify with codes: an ambiguous code stays plain", () => {
  expect(linkify("phase 05 done", sids, codes)).toEqual(["phase 05 done"]);
});
test("linkify without codes keeps the old meaning: ids only, no labels or codes", () => {
  expect(linkify("W6b 03b T-1", sids)).toEqual(["W6b 03b ", { id: "T-1" }]);
});

test("typeClasses: seven distinct builtin colours, one fallback for declared types", () => {
  const builtin = ["task", "decision", "deferred", "fetch", "debt", "handoff", "stage"];
  expect(new Set(builtin.map((t) => typeClasses(t).text)).size).toBe(7);
  expect(typeClasses("experiment")).toBe(typeClasses("whatever"));
  expect(builtin.map((t) => typeClasses(t)).includes(typeClasses("experiment"))).toBe(false);
});

test("evMeta: kit, sid cut to 8, rules; parts omitted when absent, none for empty rules", () => {
  const ev: Ev = { line: 1, ts: "2026-11-13", who: "lead", ev: "add", id: "T-1", f: {} };
  expect(evMeta({ ...ev, kit: "0.2.0", sid: "abcdef0123456789", rules: { "AGENTS.md": "2026-11-14a", "pm/k.md": "x" } }))
    .toBe("kit=0.2.0 sid=abcdef01 rules=AGENTS.md:2026-11-14a,pm/k.md:x");
  expect(evMeta({ ...ev, kit: "0.2.0", sid: "abc" })).toBe("kit=0.2.0 sid=abc");
  expect(evMeta(ev)).toBe("");
  expect(evMeta({ ...ev, rules: {} })).toBe("rules=none");
});

// labels: kit 0.2.0 names an entry by extra.legacy_id; "<stage code>/<work item>"
const lab = (id: string, legacy: string, stage = ""): Entry =>
  ({ ...base, id, type: "task", title: `t ${id}`, status: "open", owner: "", stage, extra: { legacy_id: legacy } });
const w1 = lab("T-11", "03b/W1", "S-7");
const w2 = lab("T-12", "03b/W2", "S-7");
const x2 = lab("T-13", "09/W2");
const lbs = labelIndex([w1, w2, x2, lab("T-14", "dup"), lab("T-15", "dup"), t1]);
const sids2 = new Set(["S-7", "S-8", "T-1", "T-11", "T-12", "T-13"]);

test("stageCodeOf / stageCodes follow the kit rule: title up to the first dash", () => {
  expect(stageCodeOf("paper-plan")).toBe("paper");
  expect(stageCodeOf("03b-software-parser")).toBe("03b");
  expect(stageCodeOf("stage one")).toBeUndefined();
  expect(stageCodeOf("-x")).toBeUndefined();
  expect(Object.fromEntries(stageCodes([st("S-1", "alpha-run"), st("S-2", "no dash")]))).toEqual({ alpha: "S-1" });
});
test("labelOf and labelIndex: unique labels only", () => {
  expect(labelOf(w1)).toBe("03b/W1");
  expect(labelOf(t1)).toBe("");
  expect(Object.fromEntries(lbs)).toEqual({ "03b/W1": "T-11", "03b/W2": "T-12", "09/W2": "T-13" });
  expect(lbs.has("dup")).toBe(false);
});
test("linkify: an exact label links to its entry, longest label first, text stays the label", () => {
  expect(linkify("done 03b/W1, then 09/W2.", sids2, codes, lbs)).toEqual([
    "done ", { id: "T-11", text: "03b/W1" }, ", then ", { id: "T-13", text: "09/W2" }, "."]);
  const longer = new Map([...lbs, ["03b/W1.x", "T-12"]]);
  expect(linkify("03b/W1.x", sids2, codes, longer)).toEqual([{ id: "T-12", text: "03b/W1.x" }]);
  const t = "a/03b/k1 03b/k1x v03b/k1 2026-03b/k1";  // path, longer word, version, date
  expect(linkify(t, sids2, codes, new Map([["03b/k1", "T-11"]]))).toEqual([t]);
});
test("linkify: an id wins over a label of the same text", () => {
  expect(linkify("see T-1", sids2, codes, new Map([["T-1", "T-12"]]))).toEqual(["see ", { id: "T-1" }]);
});
test("linkify: a bare work item resolves by the entry's own stage code", () => {
  expect(linkify("do W2 now", sids2, codes, lbs, "03b")).toEqual(
    ["do ", { id: "T-12", text: "W2" }, " now"]);
  expect(linkify("do W2 now", sids2, codes, lbs, "09")).toEqual(
    ["do ", { id: "T-13", text: "W2" }, " now"]);
});
test("linkify: a bare work item resolves by the one label ending in /item", () => {
  expect(linkify("do W1", sids2, codes, lbs)).toEqual(["do ", { id: "T-11", text: "W1" }]);
  expect(linkify("do W1", sids2, codes, lbs, "09")).toEqual(["do ", { id: "T-11", text: "W1" }]);
});
test("linkify: an ambiguous or unknown work item stays a search link", () => {
  expect(linkify("do W2", sids2, codes, lbs)).toEqual(["do ", { label: "W2" }]);   // 03b/W2 and 09/W2
  expect(linkify("do W2", sids2, codes, lbs, "05")).toEqual(["do ", { label: "W2" }]);
  expect(linkify("do W9", sids2, codes, lbs, "03b")).toEqual(["do ", { label: "W9" }]);
});
test("linkify: a pure-digit stage code links only after the word stage", () => {
  expect(linkify("Stage 07 and STAGE  03b, 12 entries", sids2, codes, lbs)).toEqual([
    "Stage ", { id: "S-8", text: "07" }, " and STAGE  ", { id: "S-7", text: "03b" }, ", 12 entries"]);
  const c12 = new Map([...codes, ["12", "S-8"]]);
  expect(linkify("12 entries, stage 12", sids2, c12, lbs)).toEqual(
    ["12 entries, stage ", { id: "S-8", text: "12" }]);
});
test("search: a label query finds the entry; an exact label ranks first like an exact id", () => {
  const ln: Ledger = { ...L, entries: [t1, w1, w2, x2] };
  expect(ids(visible(ln, route("#/board?q=03b/w"))).sort()).toEqual(["T-11", "T-12"]);
  expect(matches(w1, "3B/w1")).toBe(true);
  const other: Entry = { ...base, id: "T-20", type: "task", title: "mentions 09/W2", status: "open", owner: "", stage: "" };
  const l2: Ledger = { ...L, entries: [other, x2] };
  expect(ids(visible(l2, route("#/board?q=09/w2")))).toEqual(["T-13", "T-20"]);
  expect(ids(pinExact([other, x2], "09/W2"))).toEqual(["T-13", "T-20"]);
});
test("linkify: a letters-only stage code never links, even after the word stage", () => {
  const c = new Map([["software", "S-7"], ["v2", "S-8"], ["03b", "S-7"]]);
  expect(linkify("software stage software, v2 and 03b", sids2, c)).toEqual([
    "software stage software, ", { id: "S-8", text: "v2" }, " and ", { id: "S-7", text: "03b" }]);
});
test("exactHit: id first, else a unique exact label, case-insensitive", () => {
  const dup = [lab("T-30", "same"), lab("T-31", "same")];
  expect(exactHit([w1, w2], "t-11")?.id).toBe("T-11");
  expect(exactHit([w1, w2], " 03B/w2 ")?.id).toBe("T-12");
  expect(exactHit(dup, "same")).toBeUndefined();
  expect(exactHit([w1, w2], "03b")).toBeUndefined();
  expect(exactHit([w1], "")).toBeUndefined();
});

// ---- timeline layout ----
test("entryDay: extra.date of an imported entry, else created, else empty", () => {
  expect(entryDay(d1)).toBe("2026-10-01");
  expect(entryDay(t2)).toBe("2026-11-13");
  expect(entryDay({ ...d1, extra: { date: "Oct 2026" } })).toBe("2026-11-13"); // bad date: created
  expect(entryDay({ ...t1, created: "garbage" })).toBe("");
  expect(shortDay("2026-11-03")).toBe("Nov 03");
  expect(shortDay("")).toBe("?");
});

test("stageGroups: stages by id number, unstaged last, items by day", () => {
  const s2: Entry = { ...s1, id: "S-2", title: "03b-software-parser", status: "done",
    created: "2026-11-02T09:00:00+01:00", updated: "2026-11-09T09:00:00+01:00" };
  const s10: Entry = { ...s1, id: "S-10", created: "2026-11-20T09:00:00+01:00" };
  const late: Entry = { ...t2, id: "T-5", created: "2026-11-15T09:00:00+01:00" };
  const early: Entry = { ...t2, id: "T-3", created: "2026-11-14T09:00:00+01:00" };
  const inS2: Entry = { ...t2, id: "T-6", stage: "S-2", created: "2026-11-04T09:00:00+01:00" };
  const all = [s10, s1, s2, late, early, inS2, d1];
  const g = stageGroups(all, all);
  expect(g.map((x) => x.key)).toEqual(["S-1", "S-2", "S-10", ""]); // 2 before 10
  expect(g[0].items.map((e) => e.id)).toEqual(["T-3", "T-5"]);
  expect(g[0].live).toBe(true);
  expect([g[1].first, g[1].last, g[1].live]).toEqual(["2026-11-02", "2026-11-09", false]);
  expect(g[3].items.map((e) => e.id)).toEqual(["D-1"]);
  expect(g[3].stage).toBeNull();
  expect(stageGroups(all, [s1]).map((x) => x.key)).toEqual(["S-1"]); // no unstaged group
  // a filter that hides the stage entries keeps the stages that hold visible items
  expect(stageGroups(all, [inS2]).map((x) => x.key)).toEqual(["S-2"]);
  // the route sort orders the items inside each group; the stage path keeps its order
  const keys = (gs: ReturnType<typeof stageGroups>): string[] => gs.map((x) => x.key);
  const first = (gs: ReturnType<typeof stageGroups>): string[] => gs[0].items.map((e) => e.id);
  expect(first(sortGroups(g, "default", false))).toEqual(["T-3", "T-5"]);      // as today
  expect(first(sortGroups(g, "id", true))).toEqual(["T-5", "T-3"]);
  expect(first(sortGroups(g, "default", true))).toEqual(["T-5", "T-3"]);       // reverses today's order
  expect(first(sortGroups(g, "created", true))).toEqual(["T-5", "T-3"]);
  expect(keys(sortGroups(g, "id", true))).toEqual(["S-1", "S-2", "S-10", ""]);
});

test("boardCol: deferred column holds open and running deferred entries only", () => {
  const e = (type: string, status: string): Entry => ({ ...t1, type, status });
  expect(boardCol(e("task", "open"))).toBe("open");
  expect(boardCol(e("task", "running"))).toBe("running");
  expect(boardCol(e("deferred", "open"))).toBe("deferred");
  expect(boardCol(e("deferred", "running"))).toBe("deferred");
  expect(boardCol(e("deferred", "done"))).toBe("done");
  expect(boardCol(e("deferred", "dropped"))).toBe("dropped");
  expect(boardCol(e("task", "shelved"))).toBe("shelved");
  expect(boardCol(e("decision", "superseded"))).toBe("superseded");
  // every column the board lists is reachable
  expect(new Set(["open", "running", "done", "dropped", "superseded", "shelved"].map((s) => boardCol(e("task", s)))).size).toBe(6);
  expect(BOARD_COLS).toHaveLength(8);
});

test("byType: builtin order first, declared types after by name", () => {
  const mk = (id: string, type: string): Entry => ({ ...t1, id, type });
  const g = byType([mk("X-1", "zeta"), mk("D-1", "decision"), mk("T-1", "task"), mk("T-2", "task"), mk("A-1", "alpha")]);
  expect(g.map((x) => x.type)).toEqual(["task", "decision", "alpha", "zeta"]);
  expect(g[0].items).toHaveLength(2);
});


test("id-only search: a prefix of an id lists every id that starts with it (T-34)", () => {
  const mk = (id: string, extra: Entry["extra"] = {}): Entry => ({ ...t1, id, extra });
  const es = [mk("DB-3"), mk("DB-30"), mk("DB-31"), mk("DB-4"), mk("T-1"), mk("T-2", { legacy_id: "03b/W1" })];
  const r = (q: string): string[] => es.filter((e) => matches(e, q, true)).map((e) => e.id);
  expect(r("db-")).toEqual(["DB-3", "DB-30", "DB-31", "DB-4"]);
  expect(r("DB-3")).toEqual(["DB-3", "DB-30", "DB-31"]);
  expect(r("db-30")).toEqual(["DB-30"]);
  expect(r("db-3, t-")).toEqual(["DB-3", "DB-30", "DB-31", "T-1", "T-2"]); // each term is a prefix
  expect(r("03b/w1")).toEqual(["T-2"]);                    // labels stay exact
  expect(r("03b")).toEqual([]);                            // a label prefix is not a match
  expect(es.filter((e) => matches(e, "db-3", false)).map((e) => e.id)).toEqual(["DB-3", "DB-30", "DB-31"]); // text mode unchanged
});

test("id-only search with exact on: the whole id or label, as before the prefix change (T-34)", () => {
  const t12: Entry = { ...base, id: "T-12", type: "task", title: "twelve", status: "open",
    owner: "x", stage: "", extra: { legacy_id: "03b/W1" } };
  const L12: Ledger = { ...L, entries: [t1, t12, d1] };
  const r = (q: string): string[] =>
    ids(visible(L12, { ...route("#/board"), q, idOnly: true, exact: true }));
  expect(r("T-1")).toEqual(["T-1"]);                      // not T-12
  expect(r("t-12, D-1 03B/W1")).toEqual(["T-12", "D-1"]);
  expect(r("D-07")).toEqual(["D-1"]);                     // legacy_id of d1
  expect(r("03b")).toEqual([]);
  expect(matches(t12, "T-1", true, false)).toBe(true);    // exact off: prefix
  expect(matches(t12, "tw", false, true)).toBe(true);     // not in id mode: exact is ignored
  expect(parseRoute("#/list?idonly=1").exact).toBe(false);
  expect(parseRoute("#/list?q=T-1&idonly=1&exact=1")).toMatchObject({ idOnly: true, exact: true });
  expect(formatRoute(parseRoute("#/list?q=T-1&idonly=1&exact=1"))).toBe("#/list?q=T-1&idonly=1&exact=1");
  expect(formatRoute(parseRoute("#/list?q=T-1&idonly=1"))).toBe("#/list?q=T-1&idonly=1");
});

test("status planned: own status, never open (T-45)", () => {
  const p: Entry = { ...s1, id: "P-1", status: "planned", extra: { queue: "3/2", follows: "S-1" } };
  const LP: Ledger = { ...L, entries: [...L.entries, p] };
  expect(STATUSES).toContain("planned");
  expect(BOARD_COLS).toContain("planned");
  expect(boardCol(p)).toBe("planned");
  expect(ids(visible(LP, route("#/list")))).toEqual(["T-1", "T-2", "S-1"]); // default open+running filter
  expect(ids(visible(LP, route("#/list?status=planned")))).toEqual(["P-1"]);
  expect(ids(visible(LP, route("#/list?status=all")))).toContain("P-1");
  expect(sortDefault([p, t2], LP.types).map((e) => e.id)).toEqual(["T-2", "P-1"]); // after open
  expect(stageGroups(LP.entries, LP.entries).find((g) => g.key === "P-1")?.live).toBe(false);
});
