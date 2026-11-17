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
import {
  NONE,
  backlog,
  narrowed,
  shownStatus,
  stageFilterHint,
  stageNumber,
  stageRows,
  statusCounts,
  type Entry,
  type Route,
} from "@/lib/ledger";

function Counts({ es }: { es: Entry[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {statusCounts(es).map(([s, n]) => (
        <StatusBadge key={s} status={s}>
          {s} {n}
        </StatusBadge>
      ))}
    </div>
  );
}

// `entries` = the entries the filters (except stage) let through; stage rows are always all
// stage entries, so a filter never removes a row, only its counts. The row "unstaged /
// backlog" comes first under both directions, set apart by a divider; the stage rows
// follow by order number (real NN or the kit's forecast, see stageNumber; orderStages),
// planned stages among the opened ones; `forecast` is plan.forecast. A stage filter
// (`stageFilter`, the raw route list) only marks its rows, with one hint line above.
export function Stages({
  all,
  entries,
  ledgerIds,
  status,
  forecast,
  stageFilter,
  patch,
}: {
  all: Entry[];
  entries: Entry[];
  ledgerIds: Set<string>;
  status: string[] | null;
  forecast: Record<string, string> | undefined;
  stageFilter: string[];
  patch: (p: Partial<Route>) => void;
}) {
  const [dir, setDir] = useState<1 | -1>(1); // lowest number first by default
  const marked = narrowed(stageFilter); // `*` marks nothing
  // the attributes of a body row: `key` is the stage id, NONE for the backlog row
  const rowAttrs = (key: string) => ({
    "data-row": key === NONE ? "backlog" : key,
    ...(marked.includes(key) ? { "data-filtered": "true" } : {}),
    className:
      "cursor-pointer" +
      (key === NONE ? " border-b-2" : "") + // the divider below the backlog row
      (marked.includes(key) ? " bg-muted/60 font-medium" : ""),
  });
  // keep every active filter so the row's counts and the List agree; null
  // status means "no status filter" here, but on the List it would mean the
  // open + running + staged default, so pin it to "all"
  const go = (stage: string): void => patch({ tab: "list", stage: [stage], status: status ?? [] });
  return (
    <>
      {marked.length > 0 && (
        <p data-hint="stage-filter" className="px-2 py-1.5 text-xs text-muted-foreground">
          {stageFilterHint(marked.length)}
        </p>
      )}
      <Table className="text-xs">
        <TableHeader>
          <TableRow>
            <TableHead
              className="cursor-pointer select-none"
              title="click to reverse the order"
              onClick={() => setDir(dir === 1 ? -1 : 1)}
            >
              no.{dir === 1 ? " ▲" : " ▼"}
            </TableHead>
            <TableHead>id</TableHead>
            <TableHead>title</TableHead>
            <TableHead>status</TableHead>
            <TableHead>entries</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {stageRows(all, forecast, dir).map((st) =>
            st === null ? (
              <TableRow key={NONE} {...rowAttrs(NONE)} onClick={() => go(NONE)}>
                <TableCell />
                <TableCell />
                <TableCell className="text-muted-foreground">unstaged / backlog</TableCell>
                <TableCell />
                <TableCell>
                  <Counts es={backlog(entries)} />
                </TableCell>
              </TableRow>
            ) : (
              <TableRow key={st.id} {...rowAttrs(st.id)} onClick={() => go(st.id)}>
                <TableCell className="font-mono">{stageNumber(st, forecast)}</TableCell>
                <TableCell onClick={(ev) => ev.stopPropagation()}>
                  <IdLink id={st.id} ledgerIds={ledgerIds} />
                </TableCell>
                <TableCell>{st.title}</TableCell>
                <TableCell>
                  <StatusBadge status={shownStatus(st)} />
                </TableCell>
                <TableCell>
                  <Counts es={entries.filter((e) => e.stage === st.id)} />
                </TableCell>
              </TableRow>
            ),
          )}
        </TableBody>
      </Table>
    </>
  );
}
