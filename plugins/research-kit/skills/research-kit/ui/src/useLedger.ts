import { useCallback, useEffect, useRef, useState } from "react";
import { fetchLedger, type Ledger } from "@/lib/ledger";

export function useLedger(): {
  ledger: Ledger | null;
  error: string | null;
  reload: () => void;
} {
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  const reload = useCallback((): void => {
    const mine = ++seq.current;
    fetchLedger().then(
      (l) => {
        if (mine !== seq.current) return; // a newer request is in flight
        setLedger(l);
        setError(null);
      },
      (err: unknown) => {
        if (mine !== seq.current) return;
        // keep the previous ledger: last good data stays on screen
        setError(err instanceof Error ? err.message : String(err));
      },
    );
  }, []);

  useEffect(() => {
    reload();
    window.addEventListener("focus", reload);
    return () => window.removeEventListener("focus", reload);
  }, [reload]);

  return { ledger, error, reload };
}
