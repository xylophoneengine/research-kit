import { useContext, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/StatusBadge";
import { EntryIndex, IdLink, Linked } from "@/components/IdLink";
import { TypeBadge } from "@/components/TypeBadge";
import {
  age,
  backlinks,
  byId,
  earlierTitles,
  evMeta,
  shownStatus,
  stageCodeOf,
  type Entry,
  type Ev,
  type Ledger,
} from "@/lib/ledger";

const pad = (n: number): string => String(n).padStart(2, "0");

// local time "YYYY-MM-DD HH:MM"; a date-only or unparsable value stays as is
function fmtTs(ts: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(ts)) return ts;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// cut at 80 characters, but never inside an id (T-20 would be a different entry)
function cut80(s: string): number {
  let n = 80;
  while (n < 92 && n < s.length && /[A-Za-z0-9-]/.test(s[n - 1]) && /[A-Za-z0-9-]/.test(s[n])) n++;
  return n;
}

function Val({ v, ids, own }: { v: unknown; ids: Set<string>; own?: string }) {
  const [more, setMore] = useState(false);
  const s = typeof v === "string" ? v : JSON.stringify(v);
  const n = cut80(s);
  if (s.length <= n) {
    return (
      <span className="whitespace-pre-wrap">
        <Linked text={s} ledgerIds={ids} own={own} />
      </span>
    );
  }
  return (
    <span className="whitespace-pre-wrap">
      <Linked text={more ? s : s.slice(0, n) + "\u2026"} ledgerIds={ids} own={own} />{" "}
      <button
        type="button"
        className="text-primary hover:underline"
        onClick={() => setMore(!more)}
      >
        {more ? "less" : "more"}
      </button>
    </span>
  );
}

function HistoryLine({ ev, ids, own }: { ev: Ev; ids: Set<string>; own?: string }) {
  const meta = evMeta(ev);
  return (
    <li className="text-xs">
      <span className="font-mono text-muted-foreground">{fmtTs(ev.ts)}</span> {ev.who}{" "}
      <span className="font-semibold">{ev.ev}</span>
      {Object.entries(ev.f).map(([k, v]) => (
        <span key={k} className="ml-2">
          <span className="text-muted-foreground">{k}=</span>
          <Val v={v} ids={ids} own={own} />
        </span>
      ))}
      {meta && (
        <span className="ml-2 text-[10px] text-muted-foreground" title={ev.sid ? `sid=${ev.sid}` : undefined}>
          {meta}
        </span>
      )}
    </li>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-4">
      <h3 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

export function EntryDetail({ ledger, id }: { ledger: Ledger; id: string }) {
  const idx = useMemo(() => byId(ledger), [ledger]);
  const back = useMemo(() => backlinks(ledger), [ledger]);
  const ids = useMemo(() => new Set(idx.keys()), [idx]);
  // which linked rows show their note ("links:D-1", "from:D-1"); per detail view
  const [open, setOpen] = useState<Set<string>>(new Set());
  const { codes } = useContext(EntryIndex);
  const e: Entry | undefined = idx.get(id);
  if (!e) return <p className="p-4 text-sm">no such entry: {id}</p>;

  const toggle = (k: string): void =>
    setOpen((o) => {
      const n = new Set(o);
      if (!n.delete(k)) n.add(k);
      return n;
    });

  const line = (sec: string, x: string) => {
    const t = idx.get(x);
    const k = `${sec}:${x}`;
    const shown = open.has(k);
    return (
      <li key={x} className="text-sm">
        {t && (
          <button
            type="button"
            aria-expanded={shown}
            aria-label={`${shown ? "hide" : "show"} note of ${x}`}
            title={shown ? "hide note" : "show note"}
            className="mr-1 inline-block w-3 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => toggle(k)}
          >
            {shown ? "\u25BE" : "\u25B8"}
          </button>
        )}
        <IdLink id={x} ledgerIds={ids} />
        {t && (
          <>
            {" "}
            <StatusBadge status={shownStatus(t)} /> <Linked text={t.title} ledgerIds={ids} own={own} />
          </>
        )}
        {t && shown && (
          <div className="mt-1 mb-2 ml-4 border-l pl-2 text-xs break-words whitespace-pre-wrap">
            {t.note ? (
              <Linked text={t.note} ledgerIds={ids} own={own} />
            ) : (
              <span className="text-muted-foreground">(no note)</span>
            )}
          </div>
        )}
      </li>
    );
  };
  const stage = e.stage ? idx.get(e.stage) : undefined;
  // stage code of the entry shown (a stage: its own code): resolves a bare work item (W6b)
  const own: string | undefined = stageCodeOf(e.type === "stage" ? e.title : stage?.title ?? "");
  const fields: [string, React.ReactNode][] = [
    ["owner", e.owner || "-"],
    [
      "stage",
      e.stage ? (
        <>
          <IdLink id={e.stage} ledgerIds={ids} /> {stage && <Linked text={stage.title} ledgerIds={ids} own={own} />}
        </>
      ) : (
        "-"
      ),
    ],
    ["created", fmtTs(e.created)],
    ["updated", fmtTs(e.updated)],
    ["age", age(e, new Date())],
  ];
  for (const k of ["reason", "source", "legacy_id", "date"]) {
    const v = e.extra[k];
    if (typeof v !== "string") continue;
    // a label "<stage code>/<item>": the code links to its stage when known
    const cut = v.indexOf("/");
    const sid = k === "legacy_id" && cut > 0 ? codes.get(v.slice(0, cut)) : undefined;
    fields.push([
      k === "legacy_id" ? "label" : k,
      sid ? (
        <>
          <IdLink id={sid} ledgerIds={ids}>
            {v.slice(0, cut)}
          </IdLink>
          {v.slice(cut)}
        </>
      ) : (
        v
      ),
    ]);
  }
  const from = back.get(e.id) ?? [];
  const events = ledger.events.filter((v) => v.id === e.id);

  return (
    <div className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-lg font-semibold">{e.id}</span>
        <TypeBadge type={e.type} />
        <StatusBadge status={shownStatus(e)} />
        {e.extra.imported === true && <Badge variant="outline">imported</Badge>}
      </div>
      {shownStatus(e) !== e.status && (
        <p className="mt-1 text-xs text-muted-foreground">
          stored: {e.status} (stage {e.stage} is {shownStatus(e)})
        </p>
      )}
      <h2 className="mt-2 text-base font-medium">
        <Linked text={e.title} ledgerIds={ids} own={own} />
      </h2>
      {e.type === "stage" &&
        earlierTitles(ledger.events, e.id).map((t) => (
          <p key={t.until + t.title} className="text-xs text-muted-foreground">
            earlier: {t.title} (until {t.until})
          </p>
        ))}
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        {fields.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="break-words">{v}</dd>
          </div>
        ))}
      </dl>
      <Section title="note">
        {e.note ? (
          <p className="break-words whitespace-pre-wrap text-sm">
            <Linked text={e.note} ledgerIds={ids} own={own} />
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">(no note)</p>
        )}
      </Section>
      {e.links.length > 0 && <Section title="links"><ul>{e.links.map((x) => line("links", x))}</ul></Section>}
      {from.length > 0 && <Section title="linked from"><ul>{from.map((x) => line("from", x))}</ul></Section>}
      {e.refs.length > 0 && (
        <Section title="refs">
          <ul>
            {e.refs.map((r, i) => (
              <li key={i} className="break-all font-mono text-xs">{r}</li>
            ))}
          </ul>
        </Section>
      )}
      <Section title="history">
        <ul className="space-y-1">
          {events.map((v) => (
            <HistoryLine key={v.line} ev={v} ids={ids} own={own} />
          ))}
        </ul>
      </Section>
    </div>
  );
}
