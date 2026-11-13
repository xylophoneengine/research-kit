// One colour per builtin entry type, plus a fallback for declared types.
// Full class strings on purpose: Tailwind only keeps classes it can see.
export type TypeClasses = { text: string; badge: string };

const MAP: Record<string, TypeClasses> = {
  task: {
    text: "text-blue-700 dark:text-blue-300",
    badge: "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300",
  },
  decision: {
    text: "text-violet-700 dark:text-violet-300",
    badge: "border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-800 dark:bg-violet-950 dark:text-violet-300",
  },
  deferred: {
    text: "text-amber-700 dark:text-amber-300",
    badge: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300",
  },
  fetch: {
    text: "text-cyan-700 dark:text-cyan-300",
    badge: "border-cyan-200 bg-cyan-50 text-cyan-700 dark:border-cyan-800 dark:bg-cyan-950 dark:text-cyan-300",
  },
  debt: {
    text: "text-red-700 dark:text-red-300",
    badge: "border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300",
  },
  handoff: {
    text: "text-fuchsia-700 dark:text-fuchsia-300",
    badge: "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700 dark:border-fuchsia-800 dark:bg-fuchsia-950 dark:text-fuchsia-300",
  },
  stage: {
    text: "text-emerald-700 dark:text-emerald-300",
    badge: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  },
};

const FALLBACK: TypeClasses = {
  text: "text-slate-600 dark:text-slate-300",
  badge: "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300",
};

export function typeClasses(type: string | undefined): TypeClasses {
  return (type && MAP[type]) || FALLBACK;
}
