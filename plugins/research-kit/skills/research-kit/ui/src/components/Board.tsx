import { useState } from "react";
import { TypeBadge } from "@/components/TypeBadge";
import { Button } from "@/components/ui/button";
import type { Entry } from "@/lib/ledger";

const COLS = ["running", "open", "done"];
const FOLDED = ["dropped", "superseded"];
const PAGE = 30;

const ms = (s: string): number => {
  const t = Date.parse(s);
  return Number.isNaN(t) ? 0 : t;
};

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
  entries: Entry[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [n, setN] = useState(PAGE);
  // newest `updated` first
  const sorted = [...entries].sort((a, b) => ms(b.updated) - ms(a.updated));
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

// `entries` already passed visible(); a set status filter hides the other columns
export function Board({
  entries,
  statusFilter,
  selected,
  onSelect,
}: {
  entries: Entry[];
  statusFilter: string[] | null;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const by = (s: string): Entry[] => entries.filter((e) => e.status === s);
  const shown = (s: string): boolean =>
    !statusFilter || statusFilter.length === 0 || statusFilter.includes(s);
  const cols = COLS.filter(shown);
  const folded = FOLDED.filter(shown);
  return (
    <div className="flex gap-3 p-3">
      {cols.map((s) => (
        <div key={s} className="min-w-0 flex-1">
          <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            {s} ({by(s).length})
          </h3>
          <Cards entries={by(s)} selected={selected} onSelect={onSelect} />
          {s === "done" &&
            folded.map((f) => (
              <details key={f} className="mt-3">
                <summary className="cursor-pointer text-xs text-muted-foreground">
                  {f} ({by(f).length})
                </summary>
                <div className="mt-2">
                  <Cards entries={by(f)} selected={selected} onSelect={onSelect} />
                </div>
              </details>
            ))}
        </div>
      ))}
      {/* done column hidden but dropped/superseded shown: fold them on their own */}
      {!cols.includes("done") && folded.length > 0 && (
        <div className="min-w-0 flex-1">
          {folded.map((f) => (
            <details key={f} className="mb-3">
              <summary className="cursor-pointer text-xs text-muted-foreground">
                {f} ({by(f).length})
              </summary>
              <div className="mt-2">
                <Cards entries={by(f)} selected={selected} onSelect={onSelect} />
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
