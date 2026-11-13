import { Badge } from "@/components/ui/badge";
import { typeClasses } from "@/lib/typeColor";

// the type badge, coloured per type; status badges keep their own look
export function TypeBadge({ type }: { type: string }) {
  return (
    <Badge variant="outline" className={typeClasses(type).badge}>
      {type}
    </Badge>
  );
}
