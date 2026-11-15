import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { byId, exactHit, labelIndex, stageCodes, visible, type Tab } from "@/lib/ledger";
import { useEffect, useMemo } from "react";
import { useLedger } from "@/useLedger";
import { useRoute } from "@/useRoute";

const TAB_NAMES: Tab[] = ["list", "board", "stages", "timeline"];

export default function App() {
  const { ledger, error, reload } = useLedger();
  const { route, open, patch } = useRoute();

  const onEnter = (): void => {
    const hit = ledger && exactHit(ledger.entries, route.q);
    if (!hit) return;
    patch({ q: "" });
    open(hit.id);
  };

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
        <span
          className="min-w-0 max-w-[30%] truncate text-xs text-muted-foreground"
          style={{ direction: "rtl", textAlign: "left" }}
          title={ledger?.repo}
        >
          {"‎" + (ledger?.repo ?? "")}
        </span>
        <Input
          className="max-w-xs"
          placeholder="search id, title, note..."
          value={route.q}
          onChange={(ev) => patch({ q: ev.target.value })}
          onKeyDown={(ev) => ev.key === "Enter" && onEnter()}
        />
        <Button variant="outline" size="sm" onClick={reload}>
          reload
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
      </header>
      {ledger && <Palette entries={ledger.entries} onOpen={open} />}
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
                      selected={route.e}
                      onSelect={open}
                      onStep={(id) => patch({ e: id })}
                    />
                  </>
                )}
                {route.tab === "board" && (
                  <Board
                    entries={rows}
                    statusFilter={route.status}
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
                    patch={patch}
                  />
                )}
                {route.tab === "timeline" && (
                  <Timeline entries={rows} events={ledger.events} ledgerIds={ids} onSelect={open} />
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
