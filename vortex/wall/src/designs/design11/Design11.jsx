import { useEffect, useState } from "react";
import { useSpring, useTransition, animated } from "@react-spring/web";
import { formatClock, formatDateTime } from "../../lib/dates";
import { LANGUAGE_LABEL, INTENT_LABEL, SPECIALTY_LABEL, LOCATION_LABEL } from "../../lib/labels";
import { ToolIcon, PersonIcon } from "../../lib/icons";
import { deriveFinalAction } from "../../lib/derive";
import {
  derivePatient,
  deriveCare,
  deriveZone,
  deriveAppointment,
  deriveNewSlot,
  patientRule,
  careRule,
  zoneRule,
  appointmentRule,
  newSlotRule,
} from "../../lib/insights";
import CountdownRing from "../../components/CountdownRing";
import ToolLog from "../../components/ToolLog";
import "./design11.css";

const CALL_CAP_SECONDS = 180;

function Duration({ call }) {
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
    <div className="d11-duration">
      <div className="d11-duration-head">
        <span className="d11-label">Duración</span>
        <span className="d11-duration-value">
          {formatClock(elapsed)} <span>/ {formatClock(CALL_CAP_SECONDS)}</span>
        </span>
      </div>
      <div className="d11-duration-track">
        <div className={`d11-duration-fill ${ratio > 0.8 ? "warn" : ""}`} style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}

function Chat({ items, language }) {
  const transitions = useTransition(items, {
    keys: (item) => item.id,
    from: { opacity: 0, transform: "translateY(14px)" },
    enter: { opacity: 1, transform: "translateY(0px)" },
    update: { opacity: 1, transform: "translateY(0px)" },
    config: { tension: 290, friction: 30 },
  });

  return (
    <div className="d11-chat">
      <header className="d11-chat-head">
        <span className="d11-chat-head-title">
          <span className="d11-dot-live" />
          Transcripción
        </span>
        {language && <span className="d11-chip">{LANGUAGE_LABEL[language] || language}</span>}
      </header>
      <div className="d11-chat-stream">
        {items.length === 0 && <p className="d11-empty">Esperando a que empiece la llamada…</p>}
        {transitions((style, item) => {
          const isUser = item.role === "user";
          return (
            <animated.div style={style} className={`d11-row ${isUser ? "user" : "assistant"}`}>
              <div className="d11-avatar">
                {isUser ? (
                  <PersonIcon size={34} />
                ) : (
                  <img src="/wall/vorty-face" alt="" />
                )}
              </div>
              <div className={`d11-bubble ${isUser ? "user" : "assistant"}`}>
                <span className="d11-who">{isUser ? "Paciente" : "Agente Vortex"}</span>
                <p>{item.text}</p>
              </div>
            </animated.div>
          );
        })}
      </div>
    </div>
  );
}

// One field of a scaffold box: its own label + value, filled in place the
// moment the tool call that carries it lands — an empty one shows "…"
// rather than disappearing, so the box's shape never jumps around.
function Field({ label, value }) {
  return (
    <div className={`d11-field ${value ? "filled" : ""}`}>
      <span className="d11-field-label">{label}</span>
      <span className="d11-field-value">{value || "…"}</span>
    </div>
  );
}

// A scaffold: a fixed set of fields for one piece of the flow (the
// patient, the zone, the appointment being cancelled...). "Ready" is
// passed in by the caller — the tool that fills this box having returned
// at all, not every one of its fields having a value: a patient with no
// insurer on file is still a found patient, so the card must read as
// filled the moment find_patient lands, not stay dim because one field
// (insurer) is genuinely empty.
function ScaffoldBox({ title, fields, note, ready }) {
  return (
    <div className={`d11-scaffold ${ready ? "ready" : ""}`}>
      <span className="d11-scaffold-title">{title}</span>
      <div className="d11-scaffold-fields">
        {fields.map((f) => (
          <Field key={f.label} label={f.label} value={f.value} />
        ))}
      </div>
      {ready && note && <span className="d11-scaffold-note">{note}</span>}
    </div>
  );
}

// Always on screen, in all three flows: who's on the line and what the
// clinic already knows about them. Fills the moment find_patient (or
// build_registration) returns, whether or not this particular patient
// happens to have an insurer on file.
function PatientScaffold({ items }) {
  const patient = derivePatient(items);
  return (
    <ScaffoldBox
      title="Ficha del paciente"
      ready={Boolean(patient)}
      fields={[
        { label: "Seguro", value: patient?.insurer },
        { label: "Historial", value: patient ? (patient.hasVisitedBefore ? "Habitual" : "Nuevo") : null },
      ]}
      note={patientRule(patient)}
    />
  );
}

// The bounding box around every field this intent asked for — the "why
// are these boxes here" cue: a detection-style dashed frame with the
// intent itself as the little tag sitting on its top edge, same shape a
// computer-vision box draws around what it just found.
function IntentGroup({ intent, children }) {
  return (
    <div className={`d11-intent-group ${intent ? "known" : ""}`}>
      <span className="d11-intent-tag">{intent ? INTENT_LABEL[intent] || intent : "Detectando intención…"}</span>
      <div className="d11-intent-group-body">
        {!intent && <p className="d11-empty">Esperando a que se identifique qué quiere el paciente.</p>}
        {children}
      </div>
    </div>
  );
}

// Book: zona, especialidad y tipo de cita, each its own box so a caller who
// gives the specialty before the site still lights up the right one first.
function BookScaffolds({ items }) {
  const zone = deriveZone(items);
  const care = deriveCare(items);
  return (
    <>
      <ScaffoldBox
        title="Zona"
        ready={Boolean(zone)}
        fields={[
          { label: "Centro", value: zone?.location && (LOCATION_LABEL[zone.location] || zone.location) },
          { label: "Médico", value: zone?.provider },
        ]}
        note={zoneRule(zone)}
      />
      <ScaffoldBox
        title="Especialidad"
        ready={Boolean(care?.specialtyId)}
        fields={[
          {
            label: "Especialidad",
            value: care?.specialtyId && (SPECIALTY_LABEL[care.specialtyId] || care.specialtyId),
          },
        ]}
      />
      <ScaffoldBox
        title="Tipo de cita"
        ready={Boolean(care?.appointmentTypeName)}
        fields={[{ label: "Tipo", value: care?.appointmentTypeName }]}
        note={careRule(care)}
      />
    </>
  );
}

// Cancel and reschedule both start by locating the exact appointment — the
// id comes from the tool call, never from what the caller says (see
// appointmentRule), so this box is identical for both flows and reads as
// filled the moment that id is known, even before list_appointments has
// resolved its date/site/doctor for display.
function AppointmentScaffold({ items, title }) {
  const appt = deriveAppointment(items);
  return (
    <ScaffoldBox
      title={title}
      ready={Boolean(appt)}
      fields={[
        { label: "Fecha", value: appt?.start && formatDateTime(appt.start) },
        { label: "Centro", value: appt?.locationId && (LOCATION_LABEL[appt.locationId] || appt.locationId) },
        { label: "Médico", value: appt?.providerId },
      ]}
      note={appt ? appointmentRule() : null}
    />
  );
}

// Reschedule's second box: the slot it's moving into.
function NewSlotScaffold({ items }) {
  const slot = deriveNewSlot(items);
  return (
    <ScaffoldBox
      title="Nuevo hueco"
      ready={Boolean(slot)}
      fields={[
        { label: "Fecha", value: slot?.start && formatDateTime(slot.start) },
        { label: "Centro", value: slot?.locationId && (LOCATION_LABEL[slot.locationId] || slot.locationId) },
        { label: "Médico", value: slot?.providerId },
      ]}
      note={slot ? newSlotRule() : null}
    />
  );
}

function FinalAction({ call }) {
  const final = deriveFinalAction(call);
  const ratio = final.showCountdown ? Math.max(0, final.submitRemaining) / (call?.submit_window_secs ?? 30) : 1;
  const pop = useSpring({
    opacity: call ? 1 : 0.55,
    transform: call && !call.live ? "scale(1)" : "scale(0.99)",
    config: { tension: 240, friction: 24 },
  });

  return (
    <animated.div style={pop} className={`d11-final ${final.accepted ? "done" : ""}`}>
      <div className="d11-final-top">
        <div>
          <span className="d11-label on-dark">Acción final</span>
          <span className="d11-final-value">{final.label}</span>
        </div>
        {final.showCountdown && (
          <CountdownRing ratio={ratio} size={42} stroke={3} className="d11-ring">
            <span className="mono">{Math.max(0, Math.round(final.submitRemaining))}s</span>
          </CountdownRing>
        )}
      </div>
      {call?.decline_reason && <span className="d11-final-note">Motivo: {call.decline_reason}</span>}
      {final.duplicateBlocked && <span className="d11-final-note warn">Envío duplicado bloqueado</span>}
    </animated.div>
  );
}

export default function Design11({ items, turnItems, intent, call, onBack }) {
  return (
    <div className="design11-root">
      <div className="d11-topbar">
        {onBack && (
          <button type="button" className="d11-back" onClick={onBack}>
            ← Volver a llamadas
          </button>
        )}
        <Duration call={call} />
      </div>

      <div className="d11-shell">
        <aside className="d11-left">
          <div className="d11-col-head">Llamadas a tools</div>
          <ToolLog items={items} IconComponent={ToolIcon} />
        </aside>

        <main className="d11-main">
          <Chat items={turnItems} language={call?.language} />
        </main>

        <aside className="d11-right">
          <div className="d11-col-head">Retrieved information</div>
          <div className="d11-insight-list">
            <PatientScaffold items={items} />
            <IntentGroup intent={intent}>
              {intent === "book" && <BookScaffolds items={items} />}
              {intent === "cancel" && <AppointmentScaffold items={items} title="Cita a anular" />}
              {intent === "reschedule" && (
                <>
                  <AppointmentScaffold items={items} title="Cita actual" />
                  <NewSlotScaffold items={items} />
                </>
              )}
            </IntentGroup>
          </div>
          <FinalAction call={call} />
        </aside>
      </div>
    </div>
  );
}
