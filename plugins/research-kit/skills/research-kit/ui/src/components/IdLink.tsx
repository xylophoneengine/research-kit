import { createContext, useContext } from "react";
import { Badge } from "@/components/ui/badge";
import { TypeBadge } from "@/components/TypeBadge";
import { typeClasses } from "@/lib/typeColor";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { formatRoute, linkify, parseRoute, type Entry } from "@/lib/ledger";

// provided once by App: id -> entry (hover preview, link colour) and stage
// code -> stage id (see stageCodes)
export type Index = { entries: Map<string, Entry>; codes: Map<string, string> };
export const EntryIndex = createContext<Index>({ entries: new Map(), codes: new Map() });

function Preview({ e }: { e: Entry }) {
  const note = e.note.length > 200 ? e.note.slice(0, 200) + "…" : e.note;
  return (
    <div className="space-y-1 text-xs">
      <div className="flex flex-wrap items-center gap-1">
        <span className="font-mono font-semibold">{e.id}</span>
        <TypeBadge type={e.type} />
        <Badge variant={e.status === "running" ? "default" : "outline"}>{e.status}</Badge>
      </div>
      <div className="font-medium break-words">{e.title}</div>
      <div className="text-muted-foreground">
        owner {e.owner || "-"} · stage {e.stage || "-"}
      </div>
      {note && <div className="break-words whitespace-pre-wrap text-muted-foreground">{note}</div>}
    </div>
  );
}

// Keeps the current tab and filters, sets `e`. An id that is not in the
// ledger is plain text plus a muted "unknown". A known id shows a preview
// card after a short hover (plain text inside, no links).
export function IdLink({
  id,
  ledgerIds,
  children,
}: {
  id: string;
  ledgerIds: Set<string>;
  children?: React.ReactNode;
}) {
  const entry = useContext(EntryIndex).entries.get(id);
  if (!ledgerIds.has(id)) {
    return (
      <span>
        {children ?? id} <span className="text-xs text-muted-foreground">unknown</span>
      </span>
    );
  }
  const href = formatRoute({ ...parseRoute(location.hash), e: id });
  const a = (
    <a
      href={href}
      className={"font-mono underline-offset-2 hover:underline " + typeClasses(entry?.type).text}
    >
      {children ?? id}
    </a>
  );
  if (!entry) return a;
  return (
    <HoverCard openDelay={350} closeDelay={80}>
      <HoverCardTrigger asChild>{a}</HoverCardTrigger>
      <HoverCardContent className="w-80">
        <Preview e={entry} />
      </HoverCardContent>
    </HoverCard>
  );
}

// text with every existing entry id turned into an IdLink; the rest stays text
export function Linked({ text, ledgerIds }: { text: string; ledgerIds: Set<string> }) {
  const { codes } = useContext(EntryIndex);
  return (
    <>
      {linkify(text, ledgerIds, codes).map((s, i) =>
        typeof s === "string" ? (
          <span key={i}>{s}</span>
        ) : "label" in s ? (
          <LabelLink key={i} label={s.label} />
        ) : (
          // a stage code keeps its own text; the link and the card are the stage's
          <IdLink key={i} id={s.id} ledgerIds={ledgerIds}>
            {s.text}
          </IdLink>
        ),
      )}
    </>
  );
}

// A work-item label (W6b) is a search term: a click searches for it on the
// List tab and keeps the open entry. No entry is guessed, no hover card.
function LabelLink({ label }: { label: string }) {
  const href = formatRoute({ ...parseRoute(location.hash), tab: "list", q: label });
  return (
    <a
      href={href}
      title={`search for ${label}`}
      className="text-muted-foreground underline decoration-dashed underline-offset-2 hover:text-foreground"
    >
      {label}
    </a>
  );
}
