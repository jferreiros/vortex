import { useNavigate } from "react-router-dom";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import { PhaseIcon, ToolIcon } from "../../../lib/icons";
import { toolMeta } from "../../../lib/tools";
import { LANGUAGE_LABEL, PHASE_LABEL, REASON_LABEL, phaseView } from "../../../lib/labels";
import patientTimelines from "../../../data/patientTimelines.json";
import useLiveCalls from "./useLiveCalls";
import "./live-calls.css";

// Placeholder name→id lookup until calls carry a real patient_id — falls
// back to the first mock timeline for anyone not in it.
const PATIENT_ID_BY_NAME = Object.fromEntries(
  patientTimelines.patients.map((p) => [p.name, p.patientId])
);
function patientIdFor(call) {
  if (call?.patient_id) return call.patient_id;
  const name = call?.patient || call;
  return PATIENT_ID_BY_NAME[name] || patientTimelines.patients[0].patientId;
}

function HistoryIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v4h4" />
      <path d="M12 8v4l3 2" />
    </svg>
  );
}

function PhoneIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6.5 3.5h3l1.4 4.2-2.1 1.8a13.5 13.5 0 0 0 5.7 5.7l1.8-2.1 4.2 1.4v3a1.5 1.5 0 0 1-1.6 1.5A16 16 0 0 1 5 5.1a1.5 1.5 0 0 1 1.5-1.6z" />
    </svg>
  );
}

function AlertIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3.5L21.5 20h-19z" />
      <line x1="12" y1="9.5" x2="12" y2="14" />
      <circle cx="12" cy="17" r="0.9" fill="currentColor" stroke="none" />
    </svg>
  );
}

function EscalateIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 19L19 5" />
      <path d="M9 5h10v10" />
    </svg>
  );
}

function ActiveCallCard({ call, onOpen, onOpenHistory }) {
  const view = phaseView(call);
  const phaseKey = call.phaseKey || (view.key.toLowerCase().includes("listen") ? "listening" : call.tool ? "working" : "speaking");
  const phaseLabel = call.phaseLabel || view.label || PHASE_LABEL[call.phase] || call.phase;
  const step = phaseKey === "working" && call.tool ? toolMeta(call.tool) : null;

  return (
    <Card
      padding="lg"
      className="live-call-card"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => e.key === "Enter" && onOpen()}
    >
      <div className="live-call-card-top">
        <span className="live-call-status-dot live" />
        <span className="live-call-status-label">En llamada</span>
        <span className="live-call-duration mono">{call.duration}</span>
        <button
          type="button"
          className="live-call-history-btn"
          onClick={(e) => {
            e.stopPropagation();
            onOpenHistory();
          }}
          title="Ver historial del paciente"
          aria-label="Ver historial del paciente"
        >
          <HistoryIcon />
        </button>
      </div>
      <span className="live-call-patient">{call.patient}</span>
      <span className="live-call-site">{call.site}</span>
      <div className="live-call-card-bottom">
        <span className="live-call-chip">{LANGUAGE_LABEL[call.language] || call.language}</span>
        <span className="live-call-phase">
          {step ? <ToolIcon name={call.tool} size={16} /> : <PhaseIcon phase={phaseKey} size={16} />}
          {step ? step.label : phaseLabel}
        </span>
      </div>
    </Card>
  );
}

function RejectedRow({ call, onOpenHistory }) {
  return (
    <li className="feed-row">
      <span className="feed-row-dot urgent" />
      <div className="feed-row-grid">
        <span className="feed-row-name">{call.patient}</span>
        <span className="feed-row-time mono">{call.time}</span>
        <span className="feed-row-reason">{REASON_LABEL[call.reason] || call.reason}</span>
        <div className="feed-row-actions">
          <button
            type="button"
            className="feed-row-history"
            onClick={onOpenHistory}
            title="Ver historial del paciente"
            aria-label="Ver historial del paciente"
          >
            <HistoryIcon />
          </button>
          <a
            className="feed-row-call"
            href={call.phone ? `tel:${String(call.phone).replace(/\s+/g, "")}` : undefined}
            title={call.phone ? `Devolver llamada a ${call.phone}` : "Sin teléfono"}
            aria-label={call.phone ? `Devolver llamada a ${call.phone}` : "Sin teléfono"}
          >
            <PhoneIcon />
          </a>
        </div>
      </div>
    </li>
  );
}

function EscalatedRow({ call, onOpenHistory }) {
  return (
    <li className="feed-row">
      <span className="feed-row-dot muted" />
      <div className="feed-row-grid">
        <span className="feed-row-name">{call.patient}</span>
        <span className="feed-row-time mono">{call.time}</span>
        <span className="feed-row-reason">{call.reason}</span>
        <button
          type="button"
          className="feed-row-history"
          onClick={onOpenHistory}
          title="Ver historial del paciente"
          aria-label="Ver historial del paciente"
        >
          <HistoryIcon />
        </button>
      </div>
    </li>
  );
}

export default function LiveCalls() {
  const navigate = useNavigate();
  const { calls, rejected, escalated } = useLiveCalls();
  const openCall = (id) => navigate(`/clinic/live-calls/${id}`);
  const openHistory = (call) => navigate(`/clinic/patient-timeline/${patientIdFor(call)}`);

  return (
    <div className="live-calls-page">
      <SectionHeader
        eyebrow={`${calls.length} activas`}
        title="Live Calls"
        subtitle="Llamadas en curso ahora mismo. Selecciona una para ver el detalle completo."
      />

      {calls.length === 0 ? (
        <p className="live-calls-empty">Ninguna llamada en curso.</p>
      ) : (
      <div className="live-calls-grid">
        {calls.map((call) => (
          <ActiveCallCard
            key={call.id}
            call={call}
            onOpen={() => openCall(call.id)}
            onOpenHistory={() => openHistory(call)}
          />
        ))}
      </div>
      )}

      <aside className="feed-panel">
        <div className="feed-half feed-half-rejected">
          <div className="feed-panel-head">
            <span className="feed-panel-title-group urgent">
              <AlertIcon />
              <span className="feed-panel-title">Llamadas rechazadas</span>
            </span>
            <span className="feed-panel-count">{rejected.length}</span>
          </div>
          <ul className="feed-list">
            {rejected.map((call) => (
              <RejectedRow key={call.id} call={call} onOpenHistory={() => openHistory(call)} />
            ))}
          </ul>
        </div>

        <div className="feed-divider" />

        <div className="feed-half feed-half-escalated">
          <div className="feed-panel-head">
            <span className="feed-panel-title-group muted">
              <EscalateIcon />
              <span className="feed-panel-title">Llamadas escaladas</span>
            </span>
            <span className="feed-panel-count">{escalated.length}</span>
          </div>
          <ul className="feed-list">
            {escalated.map((call) => (
              <EscalatedRow key={call.id} call={call} onOpenHistory={() => openHistory(call)} />
            ))}
          </ul>
        </div>
      </aside>
    </div>
  );
}
