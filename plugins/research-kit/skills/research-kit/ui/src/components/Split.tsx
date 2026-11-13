import { useRef, useState } from "react";

const KEY = "rk-ui-split";
const DEFAULT = 55;
const MIN = 25;
const MAX = 75;

function load(): number {
  try {
    const v = Number(localStorage.getItem(KEY));
    return Number.isFinite(v) && v >= MIN && v <= MAX ? v : DEFAULT;
  } catch {
    return DEFAULT; // storage blocked
  }
}

function save(v: number): void {
  try {
    localStorage.setItem(KEY, String(v));
  } catch {
    // storage blocked: the split just does not persist
  }
}

// Left pane | draggable handle | right pane. Pointer events, no library.
export function Split({ left, right }: { left: React.ReactNode; right: React.ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const [pct, setPct] = useState<number>(load);
  const [drag, setDrag] = useState(false);

  const move = (x: number): void => {
    const r = box.current?.getBoundingClientRect();
    if (!r || r.width === 0) return;
    setPct(Math.min(MAX, Math.max(MIN, ((x - r.left) / r.width) * 100)));
  };

  return (
    <div ref={box} className={"flex min-h-0 flex-1 " + (drag ? "select-none" : "")}>
      <div className="min-h-0 min-w-0 overflow-auto" style={{ width: `${pct}%` }}>
        {left}
      </div>
      <div
        role="separator"
        aria-orientation="vertical"
        title="drag to resize, double-click to reset"
        className={
          "w-1.5 shrink-0 cursor-col-resize touch-none border-l transition-colors hover:bg-primary/30 " +
          (drag ? "bg-primary/40" : "")
        }
        onPointerDown={(ev) => {
          ev.currentTarget.setPointerCapture(ev.pointerId);
          setDrag(true);
        }}
        onPointerMove={(ev) => drag && move(ev.clientX)}
        onPointerUp={(ev) => {
          ev.currentTarget.releasePointerCapture(ev.pointerId);
          setDrag(false);
          save(pct);
        }}
        onDoubleClick={() => {
          setPct(DEFAULT);
          save(DEFAULT);
        }}
      />
      <div className="min-h-0 min-w-0 flex-1 overflow-auto">{right}</div>
    </div>
  );
}
