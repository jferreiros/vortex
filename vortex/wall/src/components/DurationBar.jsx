import { useEffect, useState } from "react";
import { formatClock } from "../lib/dates";
import { LANGUAGE_LABEL } from "../lib/labels";

const CALL_CAP_SECONDS = 180;

export default function DurationBar({ call }) {
  const [, tick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  if (!call) return null;

  const startedMs = call.started_at ? new Date(call.started_at).getTime() : null;
  const elapsed = call.live
    ? startedMs
      ? (Date.now() - startedMs) / 1000
      : 0
    : call.duration_ms != null
      ? call.duration_ms / 1000
      : 0;
  const ratio = Math.min(1, elapsed / CALL_CAP_SECONDS);

  return (
    <div className="duration-block">
      <div className="duration-row">
        <span className="duration-label">Duración</span>
        {call.language && (
          <span className="mini-chip">{LANGUAGE_LABEL[call.language] || call.language}</span>
        )}
        {call.idle_count > 0 && <span className="mini-chip warn">{call.idle_count}× silencio</span>}
      </div>
      <div className="duration-track">
        <div className={`duration-fill ${ratio > 0.8 ? "warn" : ""}`} style={{ width: `${ratio * 100}%` }} />
      </div>
      <div className="duration-value mono">
        {formatClock(elapsed)} / {formatClock(CALL_CAP_SECONDS)}
      </div>
    </div>
  );
}
