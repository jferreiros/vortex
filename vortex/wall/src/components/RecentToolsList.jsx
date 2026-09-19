import { useTransition, animated } from "@react-spring/web";
import { toolMeta } from "../lib/tools";

const RECENT_COUNT = 6;

// Shown in the square whenever no tool is running right now: the last few
// calls, newest first, name + ms — a quiet summary instead of a live demo.
export default function RecentToolsList({ items, IconComponent }) {
  const recent = items.slice(-RECENT_COUNT).reverse();

  const transitions = useTransition(recent, {
    keys: (item) => item.id,
    from: { opacity: 0, transform: "translateX(-14px)" },
    enter: { opacity: 1, transform: "translateX(0px)" },
    leave: { opacity: 0, transform: "translateX(14px)" },
    config: { tension: 260, friction: 26 },
  });

  return (
    <div className="recent-tools">
      <div className="recent-tools-title">Recent tools used</div>
      <div className="recent-tools-list">
        {recent.length === 0 && <span className="recent-tools-empty">Todavía no hay tools.</span>}
        {transitions((style, item) => {
          const meta = toolMeta(item.tool);
          const ms = typeof item.ms === "number" ? Math.round(item.ms) : null;
          return (
            <animated.div style={style} className={`recent-tool-row status-${item.status}`}>
              <span className="recent-tool-name">
                {IconComponent ? <IconComponent name={item.tool} size={16} /> : meta.icon} {meta.label}
              </span>
              <span className={`recent-tool-ms ${ms !== null && ms > 1200 ? "slow" : ""}`}>
                {item.status === "running" ? "…" : ms !== null ? `${ms} ms` : "—"}
              </span>
            </animated.div>
          );
        })}
      </div>
    </div>
  );
}
