import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// the status badge: running is filled, open is red (white on red-600 is 4.8:1,
// on red-700 6.5:1), the rest are plain outlines. `children` overrides the text.
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
        className,
      )}
    >
      {children ?? status}
    </Badge>
  );
}
