import { ArrowUpDownIcon, ChevronDownIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DEFAULT_ORDER, SORT_KEYS, type Route, type SortKey, type SortTab } from "@/lib/ledger";

// sort key and direction (list, board and the timeline's storyline); both live in the route
export function SortMenu({
  tab,
  route,
  patch,
}: {
  tab: SortTab;
  route: Pick<Route, "sort" | "desc">;
  patch: (p: Partial<Route>) => void;
}) {
  const def = DEFAULT_ORDER[tab];
  const arrow = route.desc ? "↓" : "↑";
  // `default` ascending is "no sort set": no arrow. `default` descending reverses that order.
  const label = route.sort !== "default" ? `${route.sort} ${arrow}` : route.desc ? "default ↓" : "default";
  const state =
    route.sort !== "default"
      ? `sort: ${route.sort}, ${route.desc ? "descending" : "ascending"}`
      : `sort: default${route.desc ? ", reversed" : ""} (${def})`;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" aria-label={state} title={state}>
          <ArrowUpDownIcon />
          <span className="text-xs">{label}</span>
          <ChevronDownIcon />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel>sort by</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={route.sort} onValueChange={(v) => patch({ sort: v as SortKey })}>
          {SORT_KEYS.map((k) => (
            <DropdownMenuRadioItem key={k} value={k}>
              {k === "default" ? (
                <span className="flex max-w-56 flex-col">
                  default
                  <span className="text-xs whitespace-normal text-muted-foreground">{def}</span>
                </span>
              ) : (
                k
              )}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup
          value={route.desc ? "desc" : "asc"}
          onValueChange={(v) => patch({ desc: v === "desc" })}
        >
          <DropdownMenuRadioItem value="asc">ascending</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="desc">
            descending{route.sort === "default" ? " (reverses default)" : ""}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
