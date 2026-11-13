import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { IdLink, Linked } from "@/components/IdLink";
import { eventDay, type Entry, type Ev } from "@/lib/ledger";

const PAGE = 200;

// placeholder (DF-1): a plain grouped list, replaced after stage 1
export function Timeline({
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
        placeholder; imported entries sit on their original date when known
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
