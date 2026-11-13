import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  NONE,
  STATUSES,
  byId,
  facets,
  type Ledger,
  type Route,
} from "@/lib/ledger";

type Key = "status" | "type" | "stage" | "owner";

// the status filter that visible() applies when route.status is null
function effectiveStatus(r: Route): string[] {
  return r.status ?? (r.tab === "list" && !r.q.trim() ? ["open", "running"] : []);
}

function Multi({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: { value: string; text: string }[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          {label}
          {selected.length > 0 && (
            <span className="text-muted-foreground">({selected.length})</span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto">
        {options.map((o) => (
          <DropdownMenuCheckboxItem
            key={o.value}
            checked={selected.includes(o.value)}
            onSelect={(ev) => ev.preventDefault()} // keep the menu open
            onCheckedChange={(on) =>
              onChange(on ? [...selected, o.value] : selected.filter((s) => s !== o.value))
            }
          >
            {o.text}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Filters({
  ledger,
  route,
  patch,
}: {
  ledger: Ledger;
  route: Route;
  patch: (p: Partial<Route>) => void;
}) {
  const f = facets(ledger);
  const ids = byId(ledger);
  const plain = (vs: string[]) =>
    vs.map((v) => ({ value: v, text: v === NONE ? "(none)" : v }));
  const stages = f.stage.map((v) => ({
    value: v,
    text: v === NONE ? "(none)" : `${v} ${ids.get(v)?.title.slice(0, 50) ?? ""}`.trim(),
  }));
  const set = (k: Key) => (v: string[]) => patch({ [k]: v });
  const any =
    route.status !== null || route.type.length > 0 ||
    route.stage.length > 0 || route.owner.length > 0;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Multi
        label="status"
        options={plain(STATUSES)}
        selected={effectiveStatus(route)}
        onChange={set("status")}
      />
      <Multi label="type" options={plain(f.type)} selected={route.type} onChange={set("type")} />
      <Multi label="stage" options={stages} selected={route.stage} onChange={set("stage")} />
      <Multi label="owner" options={plain(f.owner)} selected={route.owner} onChange={set("owner")} />
      {any && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => patch({ status: null, type: [], stage: [], owner: [] })}
        >
          clear
        </Button>
      )}
    </div>
  );
}
