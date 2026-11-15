import { EyeOffIcon } from "lucide-react";
import { useState } from "react";
import { TypeBadge } from "@/components/TypeBadge";
import { Button } from "@/components/ui/button";
import { BOARD_COLS, boardCol, sortBy, type Entry, type SortKey } from "@/lib/ledger";

const KEY = "rk-ui-board-folded";
const COLLAPSED = ["shelved", "dropped", "superseded"]; // hidden until the user shows them
const PAGE = 30;

function Card({
  e,
  selected,
  onSelect,
}: {
  e: Entry;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      type="button"
      data-row={e.id}
      onClick={() => onSelect(e.id)}
      className={
        "block w-full rounded-md border p-2 text-left text-xs hover:bg-muted " +
        (selected ? "bg-muted ring-1 ring-ring" : "")
      }
    >
      <div className="flex items-center gap-1">
        <span className="font-mono font-semibold">{e.id}</span>
        <TypeBadge type={e.type} />
      </div>
      <div className="mt-1 line-clamp-2 break-words">{e.title}</div>
      <div className="mt-1 text-muted-foreground">{e.owner || "-"}</div>
    </button>
  );
}

function Cards({
  entries,
  sort,
  desc,
  selected,
  onSelect,
}: {
  entries: Entry[];
  sort: SortKey;
  desc: boolean;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [n, setN] = useState(PAGE);
  // the board's own default: newest `updated` first (descending sort reverses it);
  // any other sort key arrives already applied in `entries` (see visible())
  const sorted = sort === "default" ? sortBy(entries, "updated", !desc) : entries;
  return (
    <div className="space-y-2">
      {sorted.slice(0, n).map((e) => (
        <Card key={e.id} e={e} selected={e.id === selected} onSelect={onSelect} />
      ))}
      {sorted.length > n && (
        <Button variant="outline" size="sm" onClick={() => setN(n + PAGE)}>
          show {PAGE} more
        </Button>
      )}
    </div>
  );
}

function load(): Set<string> {
  try {
    const v: unknown = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (Array.isArray(v) && v.every((x) => typeof x === "string")) return new Set<string>(v);
  } catch {
    // storage blocked or not JSON: use the default
  }
  return new Set(COLLAPSED);
}

function save(s: Set<string>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify([...s]));
  } catch {
    // storage blocked: the choice just does not persist
  }
}

// `entries` already passed visible(). A column gets a chip when its status
// passes the status filter (deferred: when open or running does), even with 0
// entries; a hidden column takes no room on the board.
export function Board({
  entries,
  sort,
  desc,
  statusFilter,
  selected,
  onSelect,
}: {
  entries: Entry[];
  sort: SortKey;
  desc: boolean;
  statusFilter: string[] | null;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [hidden, setHidden] = useState<Set<string>>(load);
  const flip = (c: string): void => {
    const n = new Set(hidden);
    if (!n.delete(c)) n.add(c);
    setHidden(n);
    save(n);
  };
  const pass = (s: string): boolean =>
    !statusFilter || statusFilter.length === 0 || statusFilter.includes(s);
  const cols = BOARD_COLS.filter((c) =>
    c === "deferred" ? pass("open") || pass("running") : pass(c),
  );
  const count = (c: string): number => entries.filter((e) => boardCol(e) === c).length;
  const visibleCols = cols.filter((c) => !hidden.has(c));
  return (
    <div className="p-3">
      <div className="mb-3 flex flex-wrap gap-1.5">
        {cols.map((c) => {
          const on = !hidden.has(c);
          return (
            <button
              key={c}
              type="button"
              aria-pressed={on}
              title={on ? `hide ${c} column` : `show ${c} column`}
              onClick={() => flip(c)}
              className={
                "rounded-full border px-2.5 py-0.5 text-xs " +
                (on
                  ? "bg-secondary font-medium text-secondary-foreground"
                  : "text-muted-foreground hover:bg-muted")
              }
            >
              {c} {count(c)}
            </button>
          );
        })}
      </div>
      {visibleCols.length === 0 && (
        <p className="text-xs text-muted-foreground">all columns hidden</p>
      )}
      <div className="flex gap-3 overflow-x-auto">
        {visibleCols.map((c) => {
          const es = entries.filter((e) => boardCol(e) === c);
          return (
            <div key={c} className="min-w-[12rem] flex-1">
              <div className="mb-2 flex items-center justify-between gap-1 text-xs font-semibold text-muted-foreground uppercase">
                <span>
                  {c} ({es.length})
                </span>
                <button
                  type="button"
                  aria-label={`hide ${c} column`}
                  title={`hide ${c} column`}
                  onClick={() => flip(c)}
                  className="rounded p-0.5 hover:bg-muted hover:text-foreground"
                >
                  <EyeOffIcon className="size-3.5" />
                </button>
              </div>
              <Cards entries={es} sort={sort} desc={desc} selected={selected} onSelect={onSelect} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
