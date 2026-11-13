import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { TypeBadge } from "@/components/TypeBadge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { age, parseRoute, type Entry } from "@/lib/ledger";

type Col = "id" | "type" | "status" | "title" | "owner" | "stage" | "age";
const COLS: Col[] = ["id", "type", "status", "title", "owner", "stage", "age"];
type Sort = { col: Col; dir: 1 | -1 } | null;

function ageMs(e: Entry, now: Date): number {
  const t = Date.parse(e.status === "running" && e.started ? e.started : e.created);
  return Number.isNaN(t) ? Infinity : now.getTime() - t;
}

function inField(t: EventTarget | null): boolean {
  return (
    t instanceof Element &&
    t.closest("input,textarea,select,[contenteditable],[role=menu],[role=dialog]") !== null
  );
}

export function EntryTable({
  entries,
  selected,
  onSelect,
  onStep,
}: {
  entries: Entry[];
  selected: string | null;
  onSelect: (id: string) => void; // click: a history step
  onStep: (id: string) => void; // arrow keys: replace the current history entry
}) {
  const [sort, setSort] = useState<Sort>(null); // local, not in the URL
  const now = new Date();
  const rows = useMemo(() => {
    if (!sort) return entries; // default order from visible()
    const t = new Date();
    const val = (e: Entry): string | number =>
      sort.col === "age" ? ageMs(e, t) : e[sort.col];
    return [...entries].sort((a, b) => {
      const x = val(a);
      const y = val(b);
      const c =
        typeof x === "number" && typeof y === "number"
          ? x - y
          : String(x).localeCompare(String(y), undefined, { numeric: true });
      return c * sort.dir;
    });
  }, [entries, sort]);

  // asc, then desc, then back to the default order
  const header = (c: Col): void =>
    setSort((s) =>
      !s || s.col !== c ? { col: c, dir: 1 } : s.dir === 1 ? { col: c, dir: -1 } : null,
    );

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
              onClick={() => header(c)}
            >
              {c}
              {sort?.col === c ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
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
            <TableCell>
              <TypeBadge type={e.type} />
            </TableCell>
            <TableCell>
              <Badge variant={e.status === "running" ? "default" : "outline"}>{e.status}</Badge>
            </TableCell>
            <TableCell className="max-w-0 w-full truncate" title={e.title}>
              {e.title}
            </TableCell>
            <TableCell>{e.owner}</TableCell>
            <TableCell>{e.stage}</TableCell>
            <TableCell>{age(e, now)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
