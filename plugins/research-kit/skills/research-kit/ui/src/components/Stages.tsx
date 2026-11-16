import { useState } from "react";
import { StatusBadge } from "@/components/StatusBadge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { IdLink } from "@/components/IdLink";
import { NONE, STATUSES, orderStages, stageNumber, type Entry, type Route } from "@/lib/ledger";

function Counts({ es }: { es: Entry[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {STATUSES.map((s) => {
        const n = es.filter((e) => e.status === s).length;
        return n > 0 ? (
          <StatusBadge key={s} status={s}>
            {s} {n}
          </StatusBadge>
        ) : null;
      })}
    </div>
  );
}

// `entries` = the entries the filters (except stage) let through; stage rows are always all
// stage entries, so a filter never removes a row, only its counts. Planned stages sit among
// the opened ones by number (see orderStages); `forecast` is the kit's plan.forecast.
export function Stages({
  all,
  entries,
  ledgerIds,
  status,
  forecast,
  patch,
}: {
  all: Entry[];
  entries: Entry[];
  ledgerIds: Set<string>;
  status: string[] | null;
  forecast: Record<string, string> | undefined;
  patch: (p: Partial<Route>) => void;
}) {
  const [dir, setDir] = useState<1 | -1>(-1); // highest number first by default
  const stages = orderStages(
    all.filter((e) => e.type === "stage"),
    forecast,
    dir,
  );
  // keep every active filter so the row's counts and the List agree; null
  // status means "no status filter" here, but on the List it would mean the
  // open + running default, so pin it to "all"
  const go = (stage: string): void => patch({ tab: "list", stage: [stage], status: status ?? [] });
  const noStage = entries.filter((e) => e.stage === ""); // stage entries too: the List shows them
  return (
    <Table className="text-xs">
      <TableHeader>
        <TableRow>
          <TableHead
            className="cursor-pointer select-none"
            title="click to reverse the order"
            onClick={() => setDir(dir === 1 ? -1 : 1)}
          >
            id{dir === 1 ? " \u25B2" : " \u25BC"}
          </TableHead>
          <TableHead>title</TableHead>
          <TableHead>status</TableHead>
          <TableHead>entries</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {stages.map((st) => (
          <TableRow key={st.id} className="cursor-pointer" onClick={() => go(st.id)}>
            <TableCell onClick={(ev) => ev.stopPropagation()}>
              <IdLink id={st.id} ledgerIds={ledgerIds} />
            </TableCell>
            <TableCell>
              {st.status === "planned" && stageNumber(st, forecast) && (
                <span className="font-mono">{stageNumber(st, forecast)} </span>
              )}
              {st.title}
            </TableCell>
            <TableCell>
              <StatusBadge status={st.status} />
            </TableCell>
            <TableCell>
              <Counts es={entries.filter((e) => e.stage === st.id)} />
            </TableCell>
          </TableRow>
        ))}
        <TableRow className="cursor-pointer" onClick={() => go(NONE)}>
          <TableCell />
          <TableCell className="text-muted-foreground">unstaged / backlog</TableCell>
          <TableCell />
          <TableCell>
            <Counts es={noStage} />
          </TableCell>
        </TableRow>
      </TableBody>
    </Table>
  );
}
