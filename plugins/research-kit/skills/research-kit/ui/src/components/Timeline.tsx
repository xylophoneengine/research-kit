import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Log } from "@/components/timeline/Log";
import { Storyline } from "@/components/timeline/Storyline";
import { SortMenu } from "@/components/SortMenu";
import type { TimelineProps } from "@/components/timeline/parts";
import type { Route } from "@/lib/ledger";

const KEY = "rk-ui-timeline";
const VIEWS = ["timeline", "log"] as const;
type View = (typeof VIEWS)[number];

// an older stored value (storyline, dots, atlas) falls back to the timeline
function load(): View {
  try {
    const v = localStorage.getItem(KEY);
    return VIEWS.find((x) => x === v) ?? "timeline";
  } catch {
    return "timeline"; // storage blocked
  }
}

function save(v: View): void {
  try {
    localStorage.setItem(KEY, v);
  } catch {
    // storage blocked: the choice just does not persist
  }
}

export function Timeline({
  patch,
  ...p
}: TimelineProps & { patch: (p: Partial<Route>) => void }) {
  const [view, setView] = useState<View>(load);
  const pick = (v: View): void => {
    setView(v);
    save(v);
  };
  return (
    <div className="flex flex-col">
      <div className="flex gap-1 p-3 pb-0">
        {VIEWS.map((v) => (
          <Button
            key={v}
            size="sm"
            variant={view === v ? "default" : "outline"}
            aria-pressed={view === v}
            onClick={() => pick(v)}
          >
            {v}
          </Button>
        ))}
        {view === "timeline" && <SortMenu tab="timeline" route={{ sort: p.sort, desc: p.desc }} patch={patch} />}
      </div>
      {view === "timeline" && <Storyline {...p} />}
      {view === "log" && <Log entries={p.entries} events={p.events} ledgerIds={p.ledgerIds} />}
    </div>
  );
}
