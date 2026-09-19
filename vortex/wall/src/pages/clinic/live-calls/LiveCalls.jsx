import { useNavigate } from "react-router-dom";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import { PhaseIcon, ToolIcon } from "../../../lib/icons";
import { toolMeta } from "../../../lib/tools";
import { LANGUAGE_LABEL, REASON_LABEL } from "../../../lib/labels";
import patientTimelines from "../../../data/patientTimelines.json";
import "./live-calls.css";

// Placeholder name→id lookup until calls carry a real patient_id — falls
// back to the first mock timeline for anyone not in it.
const PATIENT_ID_BY_NAME = Object.fromEntries(
  patientTimelines.patients.map((p) => [p.name, p.patientId])
);
function patientIdFor(name) {
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

// PLACEHOLDER: live call feed. There is no "list every active call" endpoint
// yet — vortex/observability's API exposes one call's timeline at a time
// (GET /api/wall/timeline/{call_id}). Only the first row uses the real
// scripted demo (call_id "demo") so clicking through actually works end to
// end; the rest are illustrative cards with no live data behind them yet,
// which is exactly what they should look like until that endpoint exists.
// Only calls still in progress belong here — a call that has ended is either
// rejected or escalated, and moves to the review panel on the right.
const ACTIVE_CALLS = [
  { id: "demo", patient: "Lucía Ruiz López", site: "Arenal Centro", phaseKey: "speaking", phaseLabel: "Hablando", duration: "00:32", language: "es" },
  { id: "call-2", patient: "Sin identificar", site: "Arenal Norte", phaseKey: "listening", phaseLabel: "Escuchando", duration: "00:08", language: "ca" },
  { id: "call-3", patient: "Antonio Pérez Gil", site: "Arenal Centro", phaseKey: "working", tool: "find_slots", duration: "01:14", language: "es" },
  { id: "call-5", patient: "María Torres Vidal", site: "Arenal Sur", phaseKey: "speaking", phaseLabel: "Hablando", duration: "00:51", language: "es" },
];

// "Rechazada" = the agent submitted NO_ACTION. `reason` is one of the closed
// 18-value vocabulary (see .claude/skills/submit-action) — the exact rule
// that bit — plus the moment it happened and a way to ring the caller back.
const REJECTED_CALLS = [
  { id: "rej-1", patient: "Sin identificar", phone: "+34 611 224 578", time: "11:42:07", reason: "no_availability" },
  { id: "rej-2", patient: "Marcos Iglesias Peña", phone: "+34 699 015 332", time: "11:26:51", reason: "location_hours" },
  { id: "rej-3", patient: "Sin identificar", phone: "+34 622 887 140", time: "10:58:19", reason: "out_of_scope" },
];

// "Escalada" = handed off to a human. The reason is the thing worth showing.
const ESCALATED_CALLS = [
  { id: "call-4", patient: "Ana Salas Ferrer", time: "11:39:22", reason: "Síntomas que requieren triaje clínico" },
  { id: "esc-2", patient: "Jorge Nieto Campos", time: "11:15:40", reason: "Solicita cambio fuera de la ventana permitida" },
];

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
  const step = call.phaseKey === "working" && call.tool ? toolMeta(call.tool) : null;

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
          {step ? <ToolIcon name={call.tool} size={16} /> : <PhaseIcon phase={call.phaseKey} size={16} />}
          {step ? step.label : call.phaseLabel}
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
            href={`tel:${call.phone.replace(/\s+/g, "")}`}
            title={`Devolver llamada a ${call.phone}`}
            aria-label={`Devolver llamada a ${call.phone}`}
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
  const openCall = (id) => navigate(`/clinic/live-calls/${id}`);
  const openHistory = (patientName) => navigate(`/clinic/patient-timeline/${patientIdFor(patientName)}`);

  return (
    <div className="live-calls-page">
      <SectionHeader
        eyebrow={`${ACTIVE_CALLS.length} activas`}
        title="Live Calls"
        subtitle="Llamadas en curso ahora mismo. Selecciona una para ver el detalle completo."
      />

      <div className="live-calls-grid">
        {ACTIVE_CALLS.map((call) => (
          <ActiveCallCard
            key={call.id}
            call={call}
            onOpen={() => openCall(call.id)}
            onOpenHistory={() => openHistory(call.patient)}
          />
        ))}
      </div>

      <aside className="feed-panel">
        <div className="feed-half feed-half-rejected">
          <div className="feed-panel-head">
            <span className="feed-panel-title-group urgent">
              <AlertIcon />
              <span className="feed-panel-title">Llamadas rechazadas</span>
            </span>
            <span className="feed-panel-count">{REJECTED_CALLS.length}</span>
          </div>
          <ul className="feed-list">
            {REJECTED_CALLS.map((call) => (
              <RejectedRow key={call.id} call={call} onOpenHistory={() => openHistory(call.patient)} />
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
            <span className="feed-panel-count">{ESCALATED_CALLS.length}</span>
          </div>
          <ul className="feed-list">
            {ESCALATED_CALLS.map((call) => (
              <EscalatedRow key={call.id} call={call} onOpenHistory={() => openHistory(call.patient)} />
            ))}
          </ul>
        </div>
      </aside>
    </div>
  );
}
