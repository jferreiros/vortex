import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTransition, animated } from "@react-spring/web";
import SectionHeader from "../../../components/ui/SectionHeader";
import Placeholder from "../../../components/ui/Placeholder";
import RecordingCell from "../../../components/RecordingCell";
import { useCalls } from "../../../lib/useCalls";
import { formatClock } from "../../../lib/dates";
import { STATUS_LABEL, REASON_LABEL } from "../../../lib/labels";
import "./calls.css";

// Calls table in the Retell/Hamming pattern: one row per call, newest on
// top. A call that connects slides in with a spring, reads "En curso" with
// a live wave while it runs, and its recording cell swaps to a player plus
// a download link when the call ends and the WAV lands. Rows open the
// existing per-call detail at /clinic/live-calls/:callId.

// Fixed row height: the entrance spring grows the row from 0 so existing
// rows never jump — every cell must fit in these 72px (the media queries
// in calls.css hide the cells that would not).
const ROW_H = 72;

const CHIP_TONE = {
  live: "live",
  booked: "ok",
  registered: "ok",
  rescheduled: "ok",
  cancelled: "ok",
  refused: "warn",
  escalated: "warn",
};

function pad2(n) {
  return String(n).padStart(2, "0");
}

// Today -> "14:32:07"; older -> "24/09 14:32". The log is a same-day tool,
// so the seconds matter more than the date.
function formatStarted(call, now) {
  if (!call.startedAt) return "—";
  const date = new Date(call.startedAt);
  if (Number.isNaN(date.getTime())) return "—";
  const time = `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`;
  const sameDay = date.toDateString() === new Date(now).toDateString();
  return sameDay ? time : `${pad2(date.getDate())}/${pad2(date.getMonth() + 1)} ${time.slice(0, 5)}`;
}

function durationLabel(call, now) {
  if (call.live) {
    if (call.startedMs == null) return "—";
    return formatClock((now - call.startedMs) / 1000);
  }
  if (call.durationMs != null) return formatClock(call.durationMs / 1000);
  return "—";
}

function StatusChip({ call }) {
  const tone = CHIP_TONE[call.status] || "off";
  if (call.live) {
    return (
      <span className="calls-chip live">
        <i className="calls-status-dot live" />
        En curso
      </span>
    );
  }
  const label = STATUS_LABEL[call.status] || call.status || "Terminada";
  const reason = call.declineReason ? REASON_LABEL[call.declineReason] || call.declineReason : null;
  return (
    <span className="calls-chip-wrap">
      <span className={`calls-chip ${tone}`}>
        <i className={`calls-status-dot ${tone}`} />
        {label}
      </span>
      {reason && (
        <span className="calls-chip-reason" title={reason}>
          {reason}
        </span>
      )}
    </span>
  );
}

function OpenIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

export default function Calls() {
  const navigate = useNavigate();
  const { calls, demo, failed } = useCalls();
  const [now, setNow] = useState(() => Date.now());

  // Ticking durations only need a 1s clock while a call is live — ended
  // rows are static and re-render on the next poll anyway.
  const anyLive = calls.some((c) => c.live);
  useEffect(() => {
    if (!anyLive) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [anyLive]);

  const liveCount = calls.filter((c) => c.live).length;
  const openCall = (call) => navigate(`/clinic/live-calls/${demo ? "demo" : call.callId}`);

  const transitions = useTransition(calls, {
    keys: (call) => call.callId,
    // Rows already on screen when the page mounts render in place; only a
    // call that arrives later animates in — one fade+slide, no jump.
    initial: { opacity: 1, height: ROW_H, transform: "translateY(0px)" },
    from: { opacity: 0, height: 0, transform: "translateY(-8px)" },
    enter: { opacity: 1, height: ROW_H, transform: "translateY(0px)" },
    update: { opacity: 1, height: ROW_H, transform: "translateY(0px)" },
    leave: { opacity: 0, height: 0 },
    config: { tension: 280, friction: 34 },
    trail: 30,
  });

  return (
    <div className="calls-page">
      <SectionHeader
        eyebrow={`${calls.length} llamadas${liveCount ? ` · ${liveCount} en curso` : ""}`}
        title="Calls"
        subtitle="Registro de llamadas, más reciente primero. Selecciona una para ver el detalle completo."
      />

      {failed && (
        <div className="calls-notice" role="status">
          No se pudieron cargar las llamadas en vivo — se reintenta cada pocos segundos.
        </div>
      )}
      {demo && (
        <div className="calls-notice demo" role="status">
          Mostrando llamadas de ejemplo — la línea no está conectada.
        </div>
      )}

      {calls.length === 0 ? (
        <Placeholder kind="chart" ratio="21/6" label="Sin llamadas todavía — aparecerán aquí cuando entre una llamada." />
      ) : (
        <div className="calls-table">
          <div className="calls-head">
            <span className="calls-head-cell t-started">Hora</span>
            <span className="calls-head-cell t-caller">Paciente</span>
            <span className="calls-head-cell t-duration">Duración</span>
            <span className="calls-head-cell t-status">Estado</span>
            <span className="calls-head-cell t-rec">Grabación</span>
            <span className="calls-head-cell t-open" aria-hidden="true" />
          </div>
          <div className="calls-body">
            {transitions((style, call) => (
              <animated.div style={style} className="calls-row-anim">
                <div
                  className="calls-row"
                  role="button"
                  tabIndex={0}
                  onClick={() => openCall(call)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      openCall(call);
                    }
                  }}
                >
                  <span className="calls-cell t-started mono">{formatStarted(call, now)}</span>
                  <span className="calls-cell t-caller">
                    <span className={`calls-caller-name ${call.patientName ? "" : "unidentified"}`}>
                      {call.patientName || "Sin identificar"}
                    </span>
                    <span className="calls-caller-phone mono">{call.fromMasked}</span>
                  </span>
                  <span className="calls-cell t-duration mono">{durationLabel(call, now)}</span>
                  <span className="calls-cell t-status">
                    <StatusChip call={call} />
                  </span>
                  <span className="calls-cell t-rec">
                    <RecordingCell call={call} />
                  </span>
                  <span className="calls-cell t-open">
                    <OpenIcon />
                  </span>
                </div>
              </animated.div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
