import { expect, test } from "vitest";
import { typeClasses } from "./typeColor";
import {
  NONE,
  age,
  backlinks,
  byId,
  eventDay,
  facets,
  formatRoute,
  linkify,
  matches,
  pinExact,
  parseRoute,
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
const stages = [st("S-7", "07b-software-parser"), st("S-8", "07-paper-plan"), st("S-3", "05-a"), st("S-4", "05-b"), s1];
const codes = stageCodes(stages);
const sids = new Set(["S-7", "S-8", "T-1"]);

test("stageCodes: leading NN / NNx of a stage title; a claimed-twice code is dropped", () => {
  expect(Object.fromEntries(codes)).toEqual({ "07b": "S-7", "07": "S-8" });
  expect(codes.has("05")).toBe(false);          // S-3 and S-4 both claim it
  expect(stageCodes([t1, d1]).size).toBe(0);    // only stage entries count
});
test("linkify with codes: stage code and W label hits", () => {
  expect(linkify("stage 07b and 07, W6b (DS236) see T-1", sids, codes)).toEqual([
    "stage ", { id: "S-7", text: "07b" }, " and ", { id: "S-8", text: "07" }, ", ",
    { label: "W6b" }, " (DS236) see ", { id: "T-1" }]);
  expect(linkify("07b: done. 07b.", sids, codes)).toEqual(
    [{ id: "S-7", text: "07b" }, ": done. ", { id: "S-7", text: "07b" }, "."]);
});
test("linkify with codes: no hit inside a date, time, version, id, longer token", () => {
  const t = "on 2026-11-13 at 15:39, v1.07b, T-07, 07bx, 1007, 3.07, W6bx, AW6, 07-08, a/07";
  expect(linkify(t, sids, codes)).toEqual([t]);
});
test("linkify with codes: an ambiguous code stays plain", () => {
  expect(linkify("phase 05 done", sids, codes)).toEqual(["phase 05 done"]);
});
test("linkify without codes keeps the old meaning: ids only, no labels or codes", () => {
  expect(linkify("W6b 07b T-1", sids)).toEqual(["W6b 07b ", { id: "T-1" }]);
});

test("typeClasses: seven distinct builtin colours, one fallback for declared types", () => {
  const builtin = ["task", "decision", "deferred", "fetch", "debt", "handoff", "stage"];
  expect(new Set(builtin.map((t) => typeClasses(t).text)).size).toBe(7);
  expect(typeClasses("experiment")).toBe(typeClasses("whatever"));
  expect(builtin.map((t) => typeClasses(t)).includes(typeClasses("experiment"))).toBe(false);
});
