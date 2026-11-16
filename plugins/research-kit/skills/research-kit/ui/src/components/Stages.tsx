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
import { NONE, STATUSES, type Entry, type PlanRow, type Route } from "@/lib/ledger";

const num = (id: string): number => Number(id.slice(id.lastIndexOf("-") + 1));

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

// one table of the plan block: forecast (as the kit sent it), id, title, open entries
function PlanTable({
  title,
  rows,
  ledgerIds,
  go,
}: {
  title: string;
  rows: PlanRow[];
  ledgerIds: Set<string>;
  go: (stage: string) => void;
}) {
  if (rows.length === 0) return null;
  return (
    <>
      <h3 className="px-2 pt-2 text-xs font-semibold uppercase text-muted-foreground">{title}</h3>
      <Table className="text-xs">
        <TableHeader>
          <TableRow>
            <TableHead>forecast</TableHead>
            <TableHead>id</TableHead>
            <TableHead>title</TableHead>
            <TableHead>open entries</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(({ stage, forecast, open }) => (
            <TableRow key={stage.id} className="cursor-pointer" onClick={() => go(stage.id)}>
              <TableCell className="font-mono">{forecast}</TableCell>
              <TableCell onClick={(ev) => ev.stopPropagation()}>
                <IdLink id={stage.id} ledgerIds={ledgerIds} />
              </TableCell>
              <TableCell>{stage.title}</TableCell>
              <TableCell>{open}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
}

// `entries` = the entries the filters (except stage) let through; stage rows are always all
// stage entries, so a filter never removes a row, only its counts. `plan` (see planRows)
// is shown above them and ignores the filters.
export function Stages({
  all,
  entries,
  ledgerIds,
  status,
  plan,
  patch,
}: {
  all: Entry[];
  entries: Entry[];
  ledgerIds: Set<string>;
  status: string[] | null;
  plan: { planned: PlanRow[]; shelved: PlanRow[] };
  patch: (p: Partial<Route>) => void;
}) {
  const [dir, setDir] = useState<1 | -1>(-1); // newest stage first by default
  const stages = all
    .filter((e) => e.type === "stage")
    .sort((a, b) => (num(a.id) - num(b.id)) * dir);
  // keep every active filter so the row's counts and the List agree; null
  // status means "no status filter" here, but on the List it would mean the
  // open + running default, so pin it to "all"
  const go = (stage: string): void => patch({ tab: "list", stage: [stage], status: status ?? [] });
  const noStage = entries.filter((e) => e.stage === ""); // stage entries too: the List shows them
  return (
    <>
    <PlanTable title="Planned" rows={plan.planned} ledgerIds={ledgerIds} go={go} />
    <PlanTable title="Shelved" rows={plan.shelved} ledgerIds={ledgerIds} go={go} />
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
            <TableCell>{st.title}</TableCell>
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
    </>
  );
}
