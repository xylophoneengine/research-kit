import { useEffect } from "react";
import { StatusBadge } from "@/components/StatusBadge";
import { TypeBadge } from "@/components/TypeBadge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DEFAULT_ORDER, age, clickSort, labelOf, parseRoute, type Entry, type SortKey } from "@/lib/ledger";

// the column names are sort keys (see SORT_KEYS)
const COLS = ["id", "label", "type", "status", "title", "owner", "stage", "age"] as const;
type Col = (typeof COLS)[number];
const DEFAULT_HINT = `default order: ${DEFAULT_ORDER.list}`;

function inField(t: EventTarget | null): boolean {
  return (
    t instanceof Element &&
    t.closest("input,textarea,select,[contenteditable],[role=menu],[role=dialog]") !== null
  );
}

export function EntryTable({
  entries,
  sort,
  desc,
  onSort,
  selected,
  onSelect,
  onStep,
}: {
  entries: Entry[]; // in the order of `sort` / `desc` (see visible())
  sort: SortKey;
  desc: boolean;
  onSort: (key: SortKey, desc: boolean) => void; // header click: writes the route
  selected: string | null;
  onSelect: (id: string) => void; // click: a history step
  onStep: (id: string) => void; // arrow keys: replace the current history entry
}) {
  const now = new Date();
  const rows = entries; // already sorted by visible(): the one sort state is in the route

  // asc, then desc, then back to the default order
  // in the default order the triangle sits on its primary key, the status column
  const dflt: Col | null = sort === "default" ? "status" : null;
  const header = (c: Col): void => {
    const n = clickSort(sort, desc, c);
    onSort(n.sort, n.desc);
  };

  // Up / Down walk the rows when focus is not in an input or a menu
  useEffect(() => {
    const on = (ev: KeyboardEvent): void => {
      if (ev.defaultPrevented || ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
      if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
      if (inField(ev.target) || rows.length === 0) return;
      // read the hash, not the prop: key repeat can outrun a re-render
      const cur = parseRoute(location.hash).e;
      const i = rows.findIndex((r) => r.id === cur);
      const j = ev.key === "ArrowDown" ? Math.min(i + 1, rows.length - 1) : Math.max(i - 1, 0);
      ev.preventDefault();
      if (i < 0 && ev.key === "ArrowUp") return;
      if (rows[j].id !== cur) onStep(rows[j].id);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [rows, onStep]);

  useEffect(() => {
    if (selected) {
      document
        .querySelector(`[data-row="${CSS.escape(selected)}"]`)
        ?.scrollIntoView({ block: "nearest" });
    }
  }, [selected]);

  return (
    <Table className="text-xs">
      <TableHeader>
        <TableRow>
          {COLS.map((c) => (
            <TableHead
              key={c}
              className="cursor-pointer select-none"
              aria-sort={
                sort === c ? (desc ? "descending" : "ascending") : dflt === c ? "other" : "none"
              }
              onClick={() => header(c)}
            >
              {/* the button makes the header keyboard sortable; its click bubbles to the th */}
              <button type="button" className="cursor-pointer select-none">
                {c}
                {(sort === c || dflt === c) && (
                  <span
                    className={dflt === c ? "text-muted-foreground" : "text-foreground"}
                    title={dflt === c ? DEFAULT_HINT : undefined}
                  >
                    {/* hollow and muted: the default order; solid: a sort that was chosen */}
                    {dflt === c ? (desc ? " ▽" : " △") : desc ? " ▼" : " ▲"}
                  </span>
                )}
              </button>
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((e) => (
          <TableRow
            key={e.id}
            data-row={e.id}
            data-state={e.id === selected ? "selected" : undefined}
            aria-selected={e.id === selected}
            className="cursor-pointer"
            onClick={() => onSelect(e.id)}
          >
            <TableCell className="font-mono">{e.id}</TableCell>
            <TableCell className="font-mono">{labelOf(e)}</TableCell>
            <TableCell>
              <TypeBadge type={e.type} />
            </TableCell>
            <TableCell>
              <StatusBadge status={e.status} />
            </TableCell>
            <TableCell className="max-w-0 w-full truncate" title={e.title}>
              {e.title}
            </TableCell>
            <TableCell>{e.owner}</TableCell>
            <TableCell>
              {e.stage ||
                (e.type !== "stage" && <span className="text-muted-foreground">unstaged</span>)}
            </TableCell>
            <TableCell>{age(e, now)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
