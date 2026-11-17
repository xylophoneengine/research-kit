import { EyeOffIcon } from "lucide-react";
import { useState } from "react";
import { TypeBadge } from "@/components/TypeBadge";
import { Button } from "@/components/ui/button";
import {
  BOARD_COLS,
  boardCol,
  choiceFromFolded,
  colShown,
  narrowed,
  sortBy,
  underStages,
  type Entry,
  type SortKey,
} from "@/lib/ledger";

// the columns switched by hand, {"<column>": true|false} (true = on the board); the old
// key (an array of hidden columns) is read only while this one is absent, never written
const KEY = "rk-ui-board-cols";
const OLD_KEY = "rk-ui-board-folded";
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
  selected,
  onSelect,
}: {
  entries: Entry[]; // in the column's order
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [n, setN] = useState(PAGE);
  return (
    <div className="space-y-2">
      {entries.slice(0, n).map((e) => (
        <Card key={e.id} e={e} selected={e.id === selected} onSelect={onSelect} />
      ))}
      {entries.length > n && (
        <Button variant="outline" size="sm" onClick={() => setN(n + PAGE)}>
          show {PAGE} more
        </Button>
      )}
    </div>
  );
}

// The hand choices: the new key when it is there (anything but an object of booleans
// counts as none), else the old array migrated (choiceFromFolded), else none.
function load(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw !== null) {
      const v: unknown = JSON.parse(raw);
      const ok =
        typeof v === "object" && v !== null && !Array.isArray(v) &&
        Object.values(v).every((x) => typeof x === "boolean");
      return ok ? (v as Record<string, boolean>) : {};
    }
    const old: unknown = JSON.parse(localStorage.getItem(OLD_KEY) ?? "null");
    if (Array.isArray(old) && old.every((x) => typeof x === "string")) return choiceFromFolded(old);
  } catch {
    // storage blocked or not JSON: no choice
  }
  return {};
}

function save(choice: Record<string, boolean>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(choice));
  } catch {
    // storage blocked: the choice just does not persist
  }
}

// `entries` already passed visible(). A column gets a chip when its status
// passes the status filter (deferred: when open or running does), even with 0
// entries; a column switched off takes no room on the board. Which columns are on:
// colShown, from the hand choices and `planned` (entries of the whole ledger shown
// as planned, before the filters), so an untouched planned column stays put while
// filtering and may stand empty.
export function Board({
  entries,
  sort,
  desc,
  statusFilter,
  forecast,
  planned,
  selected,
  onSelect,
}: {
  forecast: Record<string, string> | undefined; // the kit's plan.forecast, for the stage order
  entries: Entry[];
  sort: SortKey;
  desc: boolean;
  statusFilter: string[] | null;
  planned: number;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [choice, setChoice] = useState<Record<string, boolean>>(load);
  const on = (c: string): boolean => colShown(c, planned, choice);
  const flip = (c: string): void => {
    const n = { ...choice, [c]: !on(c) };
    setChoice(n);
    save(n);
  };
  const sel = statusFilter && narrowed(statusFilter);
  const pass = (s: string): boolean => !sel || sel.length === 0 || sel.includes(s);
  const cols = BOARD_COLS.filter((c) =>
    c === "deferred" ? pass("open") || pass("running") : pass(c),
  );
  const count = (c: string): number => entries.filter((e) => boardCol(e) === c).length;
  const visibleCols = cols.filter(on);
  return (
    <div className="p-3">
      <div className="mb-3 flex flex-wrap gap-1.5">
        {cols.map((c) => {
          const shown = on(c);
          return (
            <button
              key={c}
              type="button"
              aria-pressed={shown}
              title={shown ? `hide ${c} column` : `show ${c} column`}
              onClick={() => flip(c)}
              className={
                "rounded-full border px-2.5 py-0.5 text-xs " +
                (shown
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
          // the board's own default: newest `updated` first (descending sort reverses it);
          // any other sort key arrives already applied in `entries` (see visible())
          const col = entries.filter((e) => boardCol(e) === c);
          const sorted = sort === "default" ? sortBy(col, "updated", !desc) : col;
          // planned and shelved: each stage card, then its entries in that order
          const es = c === "planned" || c === "shelved" ? underStages(sorted, forecast) : sorted;
          return (
            <div key={c} data-col={c} className="min-w-[12rem] flex-1">
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
              <Cards entries={es} selected={selected} onSelect={onSelect} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
