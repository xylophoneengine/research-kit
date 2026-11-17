import { useEffect, useState } from "react";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { idHint, labelOf, matches, pinExact, searchPlaceholder, shownStatus, type Entry } from "@/lib/ledger";

// Cmd-K / Ctrl-K: the same search as the header box, over the whole ledger
// (no filters), first 50 hits
export function Palette({
  entries,
  idOnly,
  exact,
  onOpen,
}: {
  entries: Entry[];
  idOnly: boolean; // the header's id toggle
  exact: boolean; // the header's exact toggle (id mode only)
  onOpen: (id: string) => void;
}) {
  const [show, setShow] = useState(false);
  const [input, setInput] = useState("");

  useEffect(() => {
    const on = (ev: KeyboardEvent): void => {
      if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "k") {
        ev.preventDefault();
        setInput("");
        setShow((s) => !s);
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  const hits = pinExact(entries.filter((e) => matches(e, input, idOnly, exact)), input).slice(0, 50);
  return (
    <CommandDialog open={show} onOpenChange={setShow} title="Search" description="Find an entry">
      <Command shouldFilter={false}>
        <CommandInput value={input} onValueChange={setInput} placeholder={searchPlaceholder(idOnly, exact)} />
        {idOnly && (
          <div className="px-3 py-1 text-xs text-muted-foreground">id mode: {idHint(exact)}</div>
        )}
        <CommandList>
          <CommandEmpty>no match</CommandEmpty>
          {hits.map((e) => (
            <CommandItem
              key={e.id}
              value={e.id}
              onSelect={() => {
                onOpen(e.id);
                setShow(false);
              }}
            >
              <span className="font-mono">{e.id}</span>
              {labelOf(e) && <span className="font-mono text-muted-foreground">{labelOf(e)}</span>}
              <span className="text-muted-foreground">{shownStatus(e)}</span>
              <span className="truncate">{e.title}</span>
            </CommandItem>
          ))}
        </CommandList>
      </Command>
    </CommandDialog>
  );
}
