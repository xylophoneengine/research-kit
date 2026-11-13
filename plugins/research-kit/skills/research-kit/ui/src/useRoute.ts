import { useCallback, useEffect, useState } from "react";
import { formatRoute, parseRoute, type Route } from "@/lib/ledger";

export function useRoute(): {
  route: Route;
  open: (id: string | null) => void;
  patch: (p: Partial<Route>) => void;
} {
  const [route, setRoute] = useState<Route>(() => parseRoute(location.hash));

  useEffect(() => {
    const on = (): void => setRoute(parseRoute(location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  // always start from location.hash, never from a captured route: callers
  // may run several updates in one tick (patch q, then open)
  const open = useCallback((id: string | null): void => {
    location.hash = formatRoute({ ...parseRoute(location.hash), e: id }); // history step
  }, []);

  const patch = useCallback((p: Partial<Route>): void => {
    const next: Route = { ...parseRoute(location.hash), ...p };
    history.replaceState(null, "", formatRoute(next)); // no history step
    setRoute(next);
  }, []);

  return { route, open, patch };
}
