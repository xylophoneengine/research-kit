import { Button } from "@/components/ui/button";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@/components/ui/input-group";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { SortMenu } from "@/components/SortMenu";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Board } from "@/components/Board";
import { EntryIndex } from "@/components/IdLink";
import { EntryDetail } from "@/components/EntryDetail";
import { EntryTable } from "@/components/EntryTable";
import { Filters } from "@/components/Filters";
import { Palette } from "@/components/Palette";
import { Split } from "@/components/Split";
import { Stages } from "@/components/Stages";
import { Timeline } from "@/components/Timeline";
import {
  byId,
  exactHit,
  idHint,
  labelIndex,
  projectName,
  shownStatus,
  stageCodes,
  visible,
  type Tab,
} from "@/lib/ledger";
import { MoonIcon, RefreshCwIcon, SearchIcon, SunIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { applyTheme, initialTheme, storeTheme, type Theme } from "@/theme";
import { useLedger } from "@/useLedger";
import { useRoute } from "@/useRoute";

const TAB_NAMES: Tab[] = ["list", "board", "stages", "timeline"];

export default function App() {
  const { ledger, error, reload } = useLedger();
  const { route, open, patch } = useRoute();
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const flip = (): void => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
    storeTheme(next);
  };

  const onEnter = (): void => {
    const hit = ledger && exactHit(ledger.entries, route.q);
    if (!hit) return;
    patch({ q: "" });
    open(hit.id);
  };

  // tab title: whose ledger this is and on which port, once the payload is in
  const repo = ledger?.repo;
  useEffect(() => {
    if (!repo) return;
    document.title = `rk ui · ${projectName(repo)} · :${window.location.port}`;
  }, [repo]);

  // Esc closes the detail pane, unless a dialog (palette) is open and takes the key itself
  useEffect(() => {
    const onKey = (ev: KeyboardEvent): void => {
      if (ev.key === "Escape" && !document.querySelector('[role="dialog"]')) patch({ e: null });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [patch]);

  // Stages counts ignore the stage filter, like the row click that replaces it
  const rows = useMemo(
    () =>
      ledger ? visible(ledger, route.tab === "stages" ? { ...route, stage: [] } : route) : [],
    [ledger, route],
  );
  const index = useMemo(
    () => ({
      entries: ledger ? byId(ledger) : new Map(),
      codes: ledger ? stageCodes(ledger.entries) : new Map(),
      labels: ledger ? labelIndex(ledger.entries) : new Map(),
    }),
    [ledger],
  );
  const ids = useMemo(() => new Set(ledger?.entries.map((e) => e.id)), [ledger]);
  return (
    <EntryIndex.Provider value={index}>
    <div className="flex h-screen flex-col text-sm">
      <header className="flex items-center gap-3 border-b px-3 py-2">
        <HoverCard openDelay={150} closeDelay={80}>
          <HoverCardTrigger asChild>
            <span className="min-w-0 max-w-[30%] truncate font-medium" tabIndex={0}>
              {repo ? projectName(repo) : ""}
              {repo && <span className="sr-only"> ({repo})</span>}
            </span>
          </HoverCardTrigger>
          {repo && (
            <HoverCardContent align="start" className="w-auto max-w-[90vw] font-mono text-xs break-all select-text">
              {repo}
            </HoverCardContent>
          )}
        </HoverCard>
        <InputGroup className="max-w-xs">
          <InputGroupAddon>
            <SearchIcon />
          </InputGroupAddon>
          <InputGroupInput
            placeholder="search id, title, note..."
            value={route.q}
            onChange={(ev) => patch({ q: ev.target.value })}
            onKeyDown={(ev) => ev.key === "Enter" && onEnter()}
          />
          <InputGroupAddon align="inline-end">
            <InputGroupButton
              aria-label={`id: ${idHint(route.exact)}`}
              aria-pressed={route.idOnly}
              title={idHint(route.exact)}
              className={route.idOnly ? "bg-primary text-primary-foreground hover:bg-primary/90" : "text-muted-foreground"}
              onClick={() => patch({ idOnly: !route.idOnly })}
            >
              id
            </InputGroupButton>
            {route.idOnly && (
              <InputGroupButton
                aria-label={`exact match only: ${idHint(route.exact)}`}
                aria-pressed={route.exact}
                title={idHint(route.exact)}
                className={route.exact ? "bg-primary text-primary-foreground hover:bg-primary/90" : "text-muted-foreground"}
                onClick={() => patch({ exact: !route.exact })}
              >
                exact
              </InputGroupButton>
            )}
          </InputGroupAddon>
        </InputGroup>
        {(route.tab === "list" || route.tab === "board") && (
          <SortMenu tab={route.tab} route={route} patch={patch} />
        )}
        <Button variant="outline" size="sm" aria-label="reload" title="reload" onClick={reload}>
          <RefreshCwIcon />
        </Button>
        <Tabs value={route.tab} onValueChange={(v) => patch({ tab: v as Tab })}>
          <TabsList>
            {TAB_NAMES.map((t) => (
              <TabsTrigger key={t} value={t}>
                {t}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <Button
          className="ml-auto"
          variant="outline"
          size="sm"
          aria-label={theme === "dark" ? "switch to light mode" : "switch to dark mode"}
          title={theme === "dark" ? "light mode" : "dark mode"}
          onClick={flip}
        >
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
        </Button>
      </header>
      {ledger && <Palette entries={ledger.entries} idOnly={route.idOnly} exact={route.exact} onOpen={open} />}
      {error && (
        <div role="alert" className="bg-destructive/10 px-3 py-2 text-destructive">
          {error}
        </div>
      )}
      {ledger && (
        <>
          <div className="border-b px-3 py-2">
            <Filters ledger={ledger} route={route} patch={patch} />
          </div>
          <Split
            left={
              <>
                {route.tab === "list" && (
                  <>
                    <div className="px-3 py-1 text-xs text-muted-foreground">
                      {rows.length} of {ledger.entries.length} entries
                    </div>
                    <EntryTable
                      entries={rows}
                      sort={route.sort}
                      desc={route.desc}
                      onSort={(sort, desc) => patch({ sort, desc })}
                      selected={route.e}
                      onSelect={open}
                      onStep={(id) => patch({ e: id })}
                    />
                  </>
                )}
                {route.tab === "board" && (
                  <Board
                    entries={rows}
                    sort={route.sort}
                    desc={route.desc}
                    statusFilter={route.status}
                    forecast={ledger.plan?.forecast}
                    // the whole ledger, before the filters: the planned column stays put while filtering
                    planned={ledger.entries.filter((e) => shownStatus(e) === "planned").length}
                    selected={route.e}
                    onSelect={open}
                  />
                )}
                {route.tab === "stages" && (
                  <Stages
                    all={ledger.entries}
                    entries={rows}
                    ledgerIds={ids}
                    status={route.status}
                    forecast={ledger.plan?.forecast}
                    stageFilter={route.stage}
                    patch={patch}
                  />
                )}
                {route.tab === "timeline" && (
                  <Timeline
                    all={ledger.entries}
                    entries={rows}
                    events={ledger.events}
                    ledgerIds={ids}
                    selected={route.e}
                    onSelect={open}
                    sort={route.sort}
                    desc={route.desc}
                    queue={ledger.plan?.queue}
                    patch={patch}
                  />
                )}
              </>
            }
            right={
              route.e ? (
                <div className="relative">
                  <button
                    type="button"
                    aria-label="close detail"
                    title="close (Esc)"
                    className="absolute right-2 top-2 z-10 px-1 text-muted-foreground hover:text-foreground"
                    onClick={() => patch({ e: null })}
                  >
                    {"\u2715"}
                  </button>
                  <EntryDetail key={route.e} ledger={ledger} id={route.e} />
                </div>
              ) : null
            }
          />
        </>
      )}
    </div>
    </EntryIndex.Provider>
  );
}
