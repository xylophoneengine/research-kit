import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// the status badge: running is filled, open is red (white on red-600 is 4.8:1,
// on red-700 6.5:1), staged is amber, the rest are plain outlines. `children` overrides the text.
export function StatusBadge({
  status,
  className,
  children,
}: {
  status: string;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <Badge
      variant={status === "running" ? "default" : "outline"}
      className={cn(
        status === "open" && "border-transparent bg-red-600 text-white dark:bg-red-700",
        // staged (done, not landed): amber, apart from running (filled), open (red) and done (outline)
        status === "staged" && "border-transparent bg-amber-200 text-amber-900 dark:bg-amber-900 dark:text-amber-100",
        className,
      )}
    >
      {children ?? status}
    </Badge>
  );
}
