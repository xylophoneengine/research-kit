import { Badge } from "@/components/ui/badge";
import { IdLink } from "@/components/IdLink";
import type { Entry, Ev } from "@/lib/ledger";

// props of every timeline variant: `all` supplies the stages, `entries` is
// the filtered list the variants show
export type TimelineProps = {
  all: Entry[];
  entries: Entry[];
  events: Ev[];
  ledgerIds: Set<string>;
  selected: string | null; // the entry open in the detail pane
  onSelect: (id: string) => void;
};

export const PAGE = 200;

// done is muted, open/running strong, dropped/superseded/shelved faint and struck
export function statusClass(status: string): string {
  if (status === "done") return "text-muted-foreground";
  if (status === "open" || status === "running") return "font-medium";
  return "text-muted-foreground/60 line-through";
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge
      variant={status === "running" ? "default" : "outline"}
      className={"shrink-0 " + (status === "open" || status === "running" ? "" : "text-muted-foreground")}
    >
      {status}
    </Badge>
  );
}

// an id that never wraps; a click on it does not reach the row behind it
export function Id({ id, ledgerIds }: { id: string; ledgerIds: Set<string> }) {
  return (
    <span className="shrink-0 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
      <IdLink id={id} ledgerIds={ledgerIds} />
    </span>
  );
}

export function Chev({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-label={open ? "collapse" : "expand"}
      className="w-4 shrink-0 text-muted-foreground"
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
    >
      {open ? "▾" : "▸"}
    </button>
  );
}

const PLURAL: Record<string, string> = { task: "tasks", decision: "decisions" };
export const plural = (type: string): string => PLURAL[type] ?? type;
