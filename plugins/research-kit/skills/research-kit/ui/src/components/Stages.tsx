import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { IdLink } from "@/components/IdLink";
import { NONE, STATUSES, type Entry, type Route } from "@/lib/ledger";

const num = (id: string): number => Number(id.slice(id.lastIndexOf("-") + 1));

function Counts({ es }: { es: Entry[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {STATUSES.map((s) => {
        const n = es.filter((e) => e.status === s).length;
        return n > 0 ? (
          <Badge key={s} variant="outline">
            {s} {n}
          </Badge>
        ) : null;
      })}
    </div>
  );
}

// `entries` = the entries the filters (except stage) let through; stage rows are always all
// stage entries, so a filter never removes a row, only its counts
export function Stages({
  all,
  entries,
  ledgerIds,
  status,
  patch,
}: {
  all: Entry[];
  entries: Entry[];
  ledgerIds: Set<string>;
  status: string[] | null;
  patch: (p: Partial<Route>) => void;
}) {
  const stages = all.filter((e) => e.type === "stage").sort((a, b) => num(b.id) - num(a.id));
  // keep every active filter so the row's counts and the List agree; null
  // status means "no status filter" here, but on the List it would mean the
  // open + running default, so pin it to "all"
  const go = (stage: string): void => patch({ tab: "list", stage: [stage], status: status ?? [] });
  const noStage = entries.filter((e) => e.stage === ""); // stage entries too: the List shows them
  return (
    <Table className="text-xs">
      <TableHeader>
        <TableRow>
          <TableHead>id</TableHead>
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
              <Badge variant="outline">{st.status}</Badge>
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
