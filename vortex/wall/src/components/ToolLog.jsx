import { useEffect, useRef, useState } from "react";
import UsedToolCard from "./UsedToolCard";

// The stack that replaced the phase orb: every tool call this turn made,
// oldest at the top, growing downward. Auto-scrolls to the bottom as it
// grows so whichever one is running now stays in view without the jury
// having to scroll for it.
export default function ToolLog({ items, IconComponent }) {
  const tools = items.filter((it) => it.type === "tool");
  const hasRunning = tools.some((t) => t.status === "running");
  const [now, setNow] = useState(() => Date.now());
  const scrollRef = useRef(null);

  useEffect(() => {
    if (!hasRunning) return undefined;
    const id = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(id);
  }, [hasRunning]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [tools.length]);

  return (
    <div className="tool-log" ref={scrollRef}>
      {tools.length === 0 && <p className="tool-log-empty">Todavía no se ha llamado a ninguna tool.</p>}
      {tools.map((tool) => (
        <UsedToolCard key={tool.id} tool={tool} now={now} IconComponent={IconComponent} />
      ))}
    </div>
  );
}
