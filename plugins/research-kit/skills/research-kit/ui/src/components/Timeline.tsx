import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { IdLink, Linked } from "@/components/IdLink";
import { typeClasses } from "@/lib/typeColor";
import {
  CLOSED,
  box,
  buildLanes,
  dayOf,
  eventDay,
  rangeOf,
  ticks,
  zoomRange,
  type Entry,
  type Ev,
  type Lane,
  type Span,
} from "@/lib/ledger";

const PAGE = 200;

export function Timeline({
  entries,
  events,
  ledgerIds,
  onSelect,
}: {
  entries: Entry[];
  events: Ev[];
  ledgerIds: Set<string>;
  onSelect: (id: string) => void;
}) {
  const [view, setView] = useState<"lanes" | "log">("lanes");
  return (
    <div>
      <div className="flex gap-1 p-3 pb-0">
        {(["lanes", "log"] as const).map((v) => (
          <Button
            key={v}
            size="sm"
            variant={view === v ? "default" : "outline"}
            aria-pressed={view === v}
            onClick={() => setView(v)}
          >
            {v}
          </Button>
        ))}
      </div>
      {view === "lanes" ? (
        <Lanes entries={entries} ledgerIds={ledgerIds} onSelect={onSelect} />
      ) : (
        <Log entries={entries} events={events} ledgerIds={ledgerIds} />
      )}
    </div>
  );
}

const LEFT = "w-56 shrink-0 min-w-0";

function tip(e: Entry, s: Span | null): string {
  const when = s ? `${dayOf(s.start)} to ${dayOf(s.end)}` : "no valid date";
  return `${e.id} ${e.title}\n${e.status}\n${when}`;
}

// a bar on the shared axis `r`, never narrower than 3px
function Bar({ r, s, cls, title }: { r: Span; s: Span | null; cls: string; title: string }) {
  if (!s) return null;
  const { left, width } = box(r, s);
  return (
    <div
      title={title}
      className={"absolute top-1/2 h-3 min-w-[3px] -translate-y-1/2 rounded-sm " + cls}
      style={{ left: `${left}%`, width: `${width}%` }}
    />
  );
}

// the plot area of one row: vertical tick lines plus its bar
function Track({ r, children }: { r: Span; children: React.ReactNode }) {
  return (
    <div className="relative mx-8 h-6 flex-1 overflow-hidden">
      {ticks(r).map((k) => (
        <div
          key={k.t}
          className="absolute top-0 bottom-0 border-l border-border/50"
          style={{ left: `${box(r, { start: k.t, end: k.t }).left}%` }}
        />
      ))}
      {children}
    </div>
  );
}

function Lanes({
  entries,
  ledgerIds,
  onSelect,
}: {
  entries: Entry[];
  ledgerIds: Set<string>;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [shown, setShown] = useState<Record<string, number>>({});
  // "now" is fixed per render of the entries; running bars end there
  const lanes = useMemo(() => buildLanes(entries, Date.now()), [entries]);

  const full = useMemo(
    () => rangeOf(lanes.flatMap((l) => [l.span, ...l.items.map((i) => i.span)])),
    [lanes],
  );
  const only = open.size === 1 ? lanes.find((l) => open.has(l.key)) : undefined;
  const r = (only?.span && zoomRange(only.span)) || full;

  const toggle = (key: string): void =>
    setOpen((o) => {
      const n = new Set(o);
      if (!n.delete(key)) n.add(key);
      return n;
    });

  if (!r) return <p className="p-3 text-xs text-muted-foreground">nothing to show</p>;

  return (
    <div className="p-3 text-xs">
      <div className="mb-1 flex">
        <div className={LEFT} />
        <div className="relative mx-8 h-4 flex-1">
          {ticks(r).map((k) => (
            <span
              key={k.t}
              className="absolute -translate-x-1/2 font-mono text-[10px] whitespace-nowrap text-muted-foreground"
              style={{ left: `${box(r, { start: k.t, end: k.t }).left}%` }}
            >
              {k.label}
            </span>
          ))}
        </div>
      </div>
      {lanes.map((l) => (
        <LaneRows
          key={l.key}
          lane={l}
          r={r}
          isOpen={open.has(l.key)}
          toggle={() => toggle(l.key)}
          n={shown[l.key] ?? PAGE}
          more={() => setShown({ ...shown, [l.key]: (shown[l.key] ?? PAGE) + PAGE })}
          ledgerIds={ledgerIds}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

function LaneRows({
  lane,
  r,
  isOpen,
  toggle,
  n,
  more,
  ledgerIds,
  onSelect,
}: {
  lane: Lane;
  r: Span;
  isOpen: boolean;
  toggle: () => void;
  n: number;
  more: () => void;
  ledgerIds: Set<string>;
  onSelect: (id: string) => void;
}) {
  const s = lane.stage;
  const live = s !== null && !CLOSED.has(s.status);
  const bar = s ? (live ? "bg-primary" : "bg-muted-foreground/40") : "bg-muted-foreground/30";
  const stop = (e: React.SyntheticEvent): void => e.stopPropagation();
  return (
    <div className="border-t">
      <div className="flex cursor-pointer items-center hover:bg-muted/50" onClick={toggle}>
        <div className={LEFT + " flex items-center gap-1"}>
          <button
            type="button"
            aria-expanded={isOpen}
            aria-label={isOpen ? "collapse" : "expand"}
            className="w-4 shrink-0 text-muted-foreground"
            onClick={(e) => {
              stop(e);
              toggle();
            }}
          >
            {isOpen ? "▾" : "▸"}
          </button>
          {s ? (
            <>
              <span onClick={stop}>
                <IdLink id={s.id} ledgerIds={ledgerIds} />
              </span>
              <span className="truncate" title={s.title}>
                {s.title}
              </span>
            </>
          ) : (
            <span className="font-semibold">unstaged</span>
          )}
          <span className="ml-auto shrink-0 pr-2 text-muted-foreground">{lane.items.length}</span>
        </div>
        <Track r={r}>
          <Bar
            r={r}
            s={lane.span}
            cls={bar}
            title={s ? tip(s, lane.span) : `unstaged\n${lane.items.length} entries`}
          />
        </Track>
      </div>
      {isOpen &&
        lane.items.slice(0, n).map(({ e, span }) => (
          <div
            key={e.id}
            className="flex cursor-pointer items-center hover:bg-muted/50"
            onClick={() => onSelect(e.id)}
          >
            <div className={LEFT + " flex items-center gap-1 pl-5"}>
              <span onClick={stop}>
                <IdLink id={e.id} ledgerIds={ledgerIds} />
              </span>
              <span className="truncate" title={e.title}>
                {e.title}
              </span>
            </div>
            <Track r={r}>
              <Bar r={r} s={span} cls={typeClasses(e.type).bar} title={tip(e, span)} />
            </Track>
          </div>
        ))}
      {isOpen && lane.items.length > n && (
        <Button className="my-2 ml-5" variant="outline" size="sm" onClick={more}>
          show {PAGE} more
        </Button>
      )}
    </div>
  );
}

function Log({
  entries,
  events,
  ledgerIds,
}: {
  entries: Entry[];
  events: Ev[];
  ledgerIds: Set<string>;
}) {
  const [n, setN] = useState(PAGE);
  const rows = useMemo(() => {
    const by = new Map(entries.map((e) => [e.id, e]));
    const ms = (s: string): number => {
      const t = Date.parse(s);
      return Number.isNaN(t) ? 0 : t;
    };
    return events
      .filter((v) => by.has(v.id))
      .map((v) => ({ v, e: by.get(v.id) as Entry, day: eventDay(v, by.get(v.id)) }))
      .sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : ms(b.v.ts) - ms(a.v.ts)));
  }, [entries, events]);

  let last = "";
  return (
    <div className="p-3">
      <p className="mb-2 text-xs text-muted-foreground">
        imported entries sit on their original date when known
      </p>
      {rows.slice(0, n).map(({ v, e, day }) => {
        const head = day !== last;
        last = day;
        // an add placed by extra.date has no meaningful time of day
        const placed = v.ev === "add" && typeof e.extra.date === "string";
        return (
          <div key={v.line}>
            {head && <h3 className="mt-3 mb-1 text-xs font-semibold">{day}</h3>}
            <div className="flex gap-2 text-xs">
              <span className="w-10 shrink-0 font-mono text-muted-foreground">
                {placed ? "" : v.ts.slice(11, 16)}
              </span>
              <span className="w-12 shrink-0">{v.who}</span>
              <span className="min-w-0">
                <IdLink id={e.id} ledgerIds={ledgerIds} /> <Linked text={e.title} ledgerIds={ledgerIds} />{" "}
                <span className="text-muted-foreground">
                  {v.ev === "add" ? "added" : Object.keys(v.f).join(", ")}
                </span>
              </span>
            </div>
          </div>
        );
      })}
      {rows.length > n && (
        <Button className="mt-3" variant="outline" size="sm" onClick={() => setN(n + PAGE)}>
          show {PAGE} more
        </Button>
      )}
    </div>
  );
}
