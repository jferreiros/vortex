import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTransition, animated } from "@react-spring/web";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import StatTile from "../../../components/ui/StatTile";
import { useActiveCalls } from "../../../lib/useActiveCalls";
import { INTENT_LABEL } from "../../../lib/labels";
import { formatClock } from "../../../lib/dates";
import { toolMeta } from "../../../lib/tools";
import { springs } from "../../../theme/theme";
import "./live-calls.css";

// Every active call is one small card on a field. Where the card drifts to
// is the point: each outcome owns a spot around the edge, calls with no
// classified intent sit in the middle, and a re-classification shows up as
// the card physically crossing the field. Anchors are fractions of the
// canvas so the layout survives any panel width.
const ANCHORS = {
  book: { x: 0.13, y: 0.15 },
  register: { x: 0.09, y: 0.55 },
  "no-action": { x: 0.2, y: 0.87 },
  unclassified: { x: 0.5, y: 0.5 },
  escalate: { x: 0.8, y: 0.87 },
  cancel: { x: 0.91, y: 0.55 },
  reschedule: { x: 0.87, y: 0.15 },
};

const ZONE_ORDER = ["book", "register", "no-action", "unclassified", "escalate", "cancel", "reschedule"];

const CARD_W = 152;
const CARD_H = 96;

function anchorKey(intent) {
  return ANCHORS[intent] ? intent : "unclassified";
}

// Cards sharing an intent fan out around their anchor on a golden-angle
// spiral — deterministic per position in the cluster, so a steady board
// doesn't shuffle itself every poll.
function clusterOffset(index) {
  if (index === 0) return { dx: 0, dy: 0 };
  const angle = index * 2.39996;
  const radius = 62 + Math.sqrt(index) * 36;
  return { dx: Math.cos(angle) * radius, dy: Math.sin(angle) * radius * 0.62 };
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function layoutCalls(calls, size) {
  const groups = new Map();
  for (const call of calls) {
    const key = anchorKey(call.intent);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(call);
  }
  const targets = new Map();
  for (const [key, group] of groups) {
    group.sort((a, b) => (a.call_id < b.call_id ? -1 : 1));
    const anchor = ANCHORS[key];
    group.forEach((call, index) => {
      const { dx, dy } = clusterOffset(index);
      targets.set(call.call_id, {
        x: clamp(anchor.x * size.w - CARD_W / 2 + dx, 6, Math.max(6, size.w - CARD_W - 6)),
        y: clamp(anchor.y * size.h - CARD_H / 2 + dy, 6, Math.max(6, size.h - CARD_H - 6)),
      });
    });
  }
  return targets;
}

function useElementSize() {
  const ref = useRef(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, size];
}

// The poll keeps durations honest, but a stalled request shouldn't freeze
// the ticking clocks on screen.
function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

// Phase-driven waveform — simulated, no audio ever leaves the server. Each
// phase gets a different rhythm and amplitude through CSS variables; the
// bars themselves are five identical <i> elements with staggered delays.
function Wave({ phase }) {
  return (
    <span className={`lc-wave lc-wave-${phase || "listening"}`} aria-hidden="true">
      <i />
      <i />
      <i />
      <i />
      <i />
    </span>
  );
}

function CallCard({ call, now, onOpen }) {
  const name = call.name;
  const duration = call.started_ms ? formatClock((now - call.started_ms) / 1000) : "--:--";
  const intent = call.intent && INTENT_LABEL[call.intent] ? call.intent : null;
  const lastTool = call.tools_run[call.tools_run.length - 1];
  const working = call.phase === "working" && lastTool;

  return (
    <button type="button" className="lc-card" onClick={onOpen} title={name || call.from || "Llamada"}>
      <span className="lc-card-top">
        <span className="lc-dot" />
        <span className="lc-duration">{duration}</span>
      </span>
      {/* key={name} re-mounts the label the moment find_patient resolves, so
          the identity flip animates once and never again. */}
      <span key={name || "unknown"} className={`lc-name ${name ? "" : "unknown"}`}>
        {name || call.from || "Llamada entrante"}
      </span>
      <span className="lc-sub">{name ? call.from : "Identificando…"}</span>
      <span className="lc-card-bottom">
        <span className={`lc-intent ${intent || "pending"}`}>{intent ? INTENT_LABEL[intent] : "…"}</span>
        <Wave phase={call.phase} />
      </span>
      {working && <span className="lc-tool">{toolMeta(lastTool).label}…</span>}
    </button>
  );
}

function OutcomeTally({ outcomes }) {
  const entries = ZONE_ORDER.filter((k) => k !== "unclassified" && outcomes[k] > 0);
  return (
    <div className="ui-stat-tile lc-tally">
      <span className="ui-stat-label">Resultados de hoy</span>
      {entries.length === 0 ? (
        <span className="lc-tally-empty">Sin llamadas cerradas aún</span>
      ) : (
        <span className="lc-tally-chips">
          {entries.map((key) => (
            <span key={key} className="lc-tally-chip">
              {INTENT_LABEL[key]}
              <b>{outcomes[key]}</b>
            </span>
          ))}
        </span>
      )}
    </div>
  );
}

export default function LiveCalls() {
  const navigate = useNavigate();
  const { calls, stats, source } = useActiveCalls();
  const now = useNow();
  const [canvasRef, size] = useElementSize();

  const targets = useMemo(() => layoutCalls(calls, size), [calls, size]);
  const zoneCounts = useMemo(() => {
    const counts = {};
    for (const call of calls) counts[anchorKey(call.intent)] = (counts[anchorKey(call.intent)] || 0) + 1;
    return counts;
  }, [calls]);

  const transitions = useTransition(calls, {
    keys: (call) => call.call_id,
    // A new call materialises at the centre — where unclassified calls live —
    // then drifts out to its outcome once intent lands.
    from: () => ({ opacity: 0, scale: 0.5, x: size.w / 2 - CARD_W / 2, y: size.h / 2 - CARD_H / 2 }),
    enter: (call) => {
      const t = targets.get(call.call_id);
      return { opacity: 1, scale: 1, x: t?.x ?? 0, y: t?.y ?? 0 };
    },
    update: (call) => {
      const t = targets.get(call.call_id);
      return t ? { x: t.x, y: t.y } : {};
    },
    leave: { opacity: 0, scale: 0.5 },
    config: springs.gentle,
  });

  return (
    <div className="live-calls-page">
      <SectionHeader
        eyebrow={source === "live" ? "En directo" : source === "mock" ? "Datos de demostración" : "Conectando…"}
        title="Live Calls"
        subtitle="Cada llamada en curso se acerca a su desenlace según se clasifica su intención."
      />

      <Card padding="md" className="lc-stats">
        <StatTile label="En línea ahora" value={calls.length} large />
        <StatTile label="Completadas hoy" value={stats.completed_today} large />
        <OutcomeTally outcomes={stats.outcomes} />
      </Card>

      <div className="lc-canvas" ref={canvasRef}>
        <span className="lc-axis lc-axis-x" />
        <span className="lc-axis lc-axis-y" />

        {ZONE_ORDER.map((key) => {
          const anchor = ANCHORS[key];
          const outX = anchor.x - 0.5;
          const outY = anchor.y - 0.5;
          const len = Math.hypot(outX, outY) || 1;
          const lx = key === "unclassified" ? anchor.x : anchor.x + (outX / len) * 0.075;
          const ly = key === "unclassified" ? anchor.y + 0.13 : anchor.y + (outY / len) * 0.11;
          return (
            <span
              key={key}
              className="lc-zone"
              style={{ left: `${lx * 100}%`, top: `${ly * 100}%` }}
            >
              {key === "unclassified" ? "Sin clasificar" : INTENT_LABEL[key]}
              <b>{zoneCounts[key] || 0}</b>
            </span>
          );
        })}

        {calls.length === 0 && (
          <p className="lc-empty">
            {source === "connecting" ? "Conectando con la línea…" : "No hay llamadas activas en este momento."}
          </p>
        )}

        {transitions((style, call) => (
          <animated.div className="lc-card-pos" style={style}>
            <CallCard call={call} now={now} onOpen={() => navigate(`/clinic/live-calls/${call.call_id}`)} />
          </animated.div>
        ))}
      </div>
    </div>
  );
}
