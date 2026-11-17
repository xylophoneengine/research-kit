import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { typeClasses } from "@/lib/typeColor";
import {
  byType,
  entryDay,
  nextReveal,
  revealTarget,
  shortDay,
  shownStatus,
  sortGroups,
  stageGroups,
  stageSpan,
  type Entry,
  type Group,
  type RevealState,
  type SortKey,
} from "@/lib/ledger";
import { Chev, Id, PAGE, StatusBadge, plural, statusClass, type TimelineProps } from "./parts";

const FIRST_LINE = 40; // cards rendered in a collapsed (one line) branch
const KEY = "rk-ui-timeline-zoom";
// card width and base font size (px) of the branches
const ZOOMS = [
  { w: 120, fs: 10 },
  { w: 150, fs: 11 },
  { w: 180, fs: 12 },
  { w: 220, fs: 13 },
  { w: 260, fs: 14 },
];
const DEFAULT_ZOOM = 2;

function load(): number {
  try {
    const v = Number(localStorage.getItem(KEY));
    return Number.isInteger(v) && v >= 0 && v < ZOOMS.length ? v : DEFAULT_ZOOM;
  } catch {
    return DEFAULT_ZOOM; // storage blocked
  }
}

function save(v: number): void {
  try {
    localStorage.setItem(KEY, String(v));
  } catch {
    // storage blocked: the zoom just does not persist
  }
}

// A vertical path of stage blocks; an open stage drops one branch of entry
// cards per type from the path. No time scale.
export function Storyline({ all, entries, ledgerIds, selected, onSelect, sort, desc, queue }: TimelineProps) {
  const groups = useMemo(
    () => sortGroups(stageGroups(all, entries), sort, desc),
    [all, entries, sort, desc],
  );
  // key of the group that holds the selected entry (a stage holds itself)
  const selKey = useMemo(() => {
    const e = selected === null ? undefined : all.find((x) => x.id === selected);
    return e ? (e.type === "stage" ? e.id : e.stage) : null;
  }, [all, selected]);
  const [zoom, setZoom] = useState<number>(load);
  const pick = (v: number): void => {
    const n = Math.min(ZOOMS.length - 1, Math.max(0, v));
    setZoom(n);
    save(n);
  };
  const z = ZOOMS[zoom];
  const style = { "--w": `${z.w}px`, "--fs": `${z.fs}px` } as React.CSSProperties;
  return (
    <div className="p-4" style={style}>
      <div className="mb-3 flex items-center justify-end gap-2 text-xs text-muted-foreground">
        card size
        <Button size="sm" variant="outline" aria-label="smaller cards" onClick={() => pick(zoom - 1)}>
          -
        </Button>
        <input
          type="range"
          aria-label="card size"
          className="w-32"
          min={0}
          max={ZOOMS.length - 1}
          step={1}
          value={zoom}
          onChange={(ev) => pick(Number(ev.target.value))}
        />
        <Button size="sm" variant="outline" aria-label="larger cards" onClick={() => pick(zoom + 1)}>
          +
        </Button>
      </div>
      {groups.length === 0 ? (
        <p className="text-xs text-muted-foreground">nothing to show</p>
      ) : (
        <div className="ml-2 border-l">
          {groups.map((g) => (
            <Block
              key={g.key}
              g={g}
              holds={g.key === selKey}
              selected={selected}
              sort={sort}
              desc={desc}
              queue={queue}
              ledgerIds={ledgerIds}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// the dot of a stage block: data-dot names it, the class draws it; a planned stage is
// hollow (background fill, solid border), the unstaged group dashed
const DOTS: Record<string, string> = {
  selected: "bg-primary ring-4 ring-primary/25",
  unstaged: "border border-dashed border-muted-foreground bg-background",
  planned: "border border-muted-foreground bg-background",
  live: "bg-primary",
  closed: "bg-muted-foreground/50",
};

function Block({
  g,
  holds,
  selected,
  sort,
  desc,
  queue,
  ledgerIds,
  onSelect,
}: {
  g: Group;
  holds: boolean; // the selected entry is this stage or one of its entries
  selected: string | null;
  sort: SortKey;
  desc: boolean;
  queue: string[] | undefined;
  ledgerIds: Set<string>;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [shown, setShown] = useState<Record<string, number>>({});
  const root = useRef<HTMLDivElement>(null);
  const types = useMemo(() => byType(g.items), [g.items]);

  // When the selection changes to something in this stage: open the stage and,
  // if the card is clipped out of its one-line branch, expand that branch and
  // scroll the card into view. Nothing is closed. It runs again when the key of
  // nextReveal changes: the selection, the sort (the card moved), or the card coming
  // back into this block (a filter cleared); not when it leaves (typing, a filter, a
  // reload), nor on a reload that keeps it (g.items is a new array on each of those).
  // `last` is the state of the last commit, kept by the effect below, not in render.
  const last = useRef<RevealState | undefined>(undefined);
  const reveal = nextReveal(last.current, g.items, selected, sort, desc);
  useEffect(() => {
    last.current = reveal; // every commit, so a card that left is known when it returns
  });
  useEffect(() => {
    const t = revealTarget(g.items, selected, holds);
    if (t === null || selected === null) return;
    const sel = selected;
    if (!t.card) {
      root.current?.scrollIntoView({ block: "nearest" }); // the stage itself
      return;
    }
    setOpen(true);
    const { type, idx } = t;
    const card = (): HTMLElement | null =>
      root.current?.querySelector<HTMLElement>(`[data-eid="${sel}"]`) ?? null;
    const clipped = (el: HTMLElement | null): boolean => {
      const grid = el?.parentElement;
      return !el || !grid || el.getBoundingClientRect().top >= grid.getBoundingClientRect().bottom - 1;
    };
    const frame = requestAnimationFrame(() => {
      if (clipped(card())) {
        const n = (Math.floor(idx / PAGE) + 1) * PAGE;
        setShown((s) => ((s[type] ?? 0) > idx ? s : { ...s, [type]: n }));
      }
      requestAnimationFrame(() => {
        const el = card();
        if (el && !clipped(el)) el.scrollIntoView({ block: "nearest" });
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [reveal.key]); // only the key: g.items is a new array on every reload, keystroke and filter change

  const dot = holds
    ? "selected"
    : !g.stage
      ? "unstaged"
      : g.stage.status === "planned"
        ? "planned"
        : g.live
          ? "live"
          : "closed";
  const span = stageSpan(g, queue);
  return (
    <div ref={root} className="relative pb-5 pl-5">
      <span data-dot={dot} className={"absolute top-2 -left-[5px] size-2.5 rounded-full " + DOTS[dot]} />
      <div
        className={"-ml-2 cursor-pointer rounded-md py-1 pl-2 " + (holds ? "bg-primary/10" : "")}
        onClick={() => setOpen(!open)}
      >
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <Chev open={open} onToggle={() => setOpen(!open)} />
          {g.stage ? (
            <>
              <Id id={g.stage.id} ledgerIds={ledgerIds} />
              <span
                className={"min-w-0 truncate " + (holds ? "font-semibold text-foreground" : statusClass(shownStatus(g.stage)))}
                title={g.stage.title}
              >
                {g.stage.title}
              </span>
              <StatusBadge status={shownStatus(g.stage)} />
            </>
          ) : (
            <span className="font-semibold">unstaged / backlog</span>
          )}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 pl-6 text-xs text-muted-foreground">
          {span && <span className="whitespace-nowrap">{span}</span>}
          <span className="whitespace-nowrap">{g.items.length} entries</span>
          {types.map((t) => (
            <span
              key={t.type}
              className={"rounded border px-1.5 text-[10px] whitespace-nowrap " + typeClasses(t.type).badge}
            >
              {t.type} {t.items.length}
            </span>
          ))}
        </div>
      </div>
      {open && (
        <div className="mt-3">
          {types.length === 0 && <p className="pl-6 text-xs text-muted-foreground">no entries</p>}
          {types.map((t) => (
            <Branch
              key={t.type}
              type={t.type}
              items={t.items}
              n={shown[t.type]}
              selected={selected}
              setN={(v) => {
                const { [t.type]: _drop, ...rest } = shown;
                setShown(v === undefined ? rest : { ...rest, [t.type]: v });
              }}
              ledgerIds={ledgerIds}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// One branch: an elbow from the path to a fixed-width label column, and a grid
// of cards (equal columns, left to right, then the next line). Collapsed, the
// grid is clipped to one line; `n` (undefined = collapsed) is how many cards the
// expanded branch shows.
function Branch({
  type,
  items,
  n,
  setN,
  selected,
  ledgerIds,
  onSelect,
}: {
  type: string;
  items: Entry[];
  selected: string | null;
  n: number | undefined;
  setN: (v: number | undefined) => void;
  ledgerIds: Set<string>;
  onSelect: (id: string) => void;
}) {
  const open = n !== undefined;
  // ponytail: a collapsed grid renders FIRST_LINE cards and clips to one line;
  // a screen wider than FIRST_LINE columns would show a short first line
  const shown = items.slice(0, open ? n : FIRST_LINE);
  return (
    // -ml-[21px]: back to the path line, which is the border of the wrapper
    <div className="relative -ml-[21px] pb-3 pl-9" style={{ fontSize: "var(--fs)" }}>
      <span className="absolute top-0 left-0 h-[0.85em] w-7 rounded-bl-lg border-b border-l" />
      <div className="flex items-start gap-3">
        <div className="flex w-[9em] shrink-0 flex-col items-start gap-1">
          <span
            title={plural(type)}
            className={"rounded border px-1.5 whitespace-nowrap " + typeClasses(type).badge}
          >
            {type} {items.length}
          </span>
          <button
            type="button"
            aria-expanded={open}
            className="text-[0.85em] whitespace-nowrap text-muted-foreground underline-offset-2 hover:underline"
            onClick={() => setN(open ? undefined : PAGE)}
          >
            {open ? "less" : `all ${items.length}`}
          </button>
        </div>
        <div className="min-w-0 flex-1">
          <div
            // p-1 -m-1: room inside the clip box for the selection ring
            className="-m-1 grid gap-2 overflow-hidden p-1"
            style={{
              gridTemplateColumns: "repeat(auto-fill, minmax(var(--w), 1fr))",
              gridAutoRows: "6.5em",
              maxHeight: open ? undefined : "calc(6.5em + 0.5rem)",
            }}
          >
            {shown.map((e) => (
              <Card key={e.id} e={e} on={e.id === selected} ledgerIds={ledgerIds} onSelect={onSelect} />
            ))}
          </div>
          {open && items.length > n && (
            <Button className="mt-2" variant="outline" size="sm" onClick={() => setN(n + PAGE)}>
              show {PAGE} more
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function Card({
  e,
  on,
  ledgerIds,
  onSelect,
}: {
  e: Entry;
  on: boolean; // the entry open in the detail pane
  ledgerIds: Set<string>;
  onSelect: (id: string) => void;
}) {
  return (
    <div
      data-eid={e.id}
      onClick={() => onSelect(e.id)}
      className={
        "relative flex min-w-0 cursor-pointer flex-col justify-between overflow-hidden rounded border py-1.5 pr-2 pl-3 " +
        (on ? "bg-primary/10 ring-2 ring-primary" : "bg-card")
      }
    >
      <span className={"absolute inset-y-0 left-0 w-1 " + typeClasses(e.type).bar} />
      <div className="flex items-baseline justify-between gap-2">
        <Id id={e.id} ledgerIds={ledgerIds} />
        <span className="text-[0.8em] whitespace-nowrap text-muted-foreground">{shortDay(entryDay(e))}</span>
      </div>
      <div className={"line-clamp-2 break-words " + statusClass(shownStatus(e))} title={e.title}>
        {e.title}
      </div>
      <div className="text-[0.8em] text-muted-foreground">{shownStatus(e)}</div>
    </div>
  );
}
