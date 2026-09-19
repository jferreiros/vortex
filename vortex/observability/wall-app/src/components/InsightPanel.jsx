import { useEffect, useState } from "react";
import { useTransition, useSpring, animated } from "@react-spring/web";
import { derivePatient, deriveCare, deriveZone, patientRule, careRule, zoneRule } from "../lib/insights";
import { INTENT_LABEL, STATUS_LABEL } from "../lib/labels";
import { formatClock } from "../lib/dates";

const ACCEPTED_STATUSES = new Set(["accepted", "duplicate"]);

function buildCards(items, intent) {
  const cards = [];
  if (intent) {
    cards.push({ id: "intent", title: "Intención actual", value: INTENT_LABEL[intent] || intent, rule: null });
  }
  const patient = derivePatient(items);
  if (patient) {
    cards.push({
      id: "patient",
      title: "Paciente / seguro",
      value: patient.insurer || (patient.hasVisitedBefore ? "Paciente habitual" : "Paciente nuevo"),
      rule: patientRule(patient),
    });
  }
  const care = deriveCare(items);
  if (care) {
    cards.push({
      id: "care",
      title: "Especialidad y tipo de cita",
      value: [care.specialtyId, care.appointmentTypeName].filter(Boolean).join(" · ") || "—",
      rule: careRule(care),
    });
  }
  const zone = deriveZone(items);
  if (zone) {
    cards.push({
      id: "zone",
      title: "Zona y proveedor",
      value: [zone.location, zone.provider].filter(Boolean).join(" · ") || "—",
      rule: zoneRule(zone),
    });
  }
  return cards;
}

function FinalActionCard({ call }) {
  const [, tick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const pop = useSpring({
    opacity: call ? 1 : 0.4,
    transform: call && !call.live ? "scale(1)" : "scale(0.97)",
    config: { tension: 240, friction: 22 },
  });

  if (!call) {
    return (
      <animated.div style={pop} className="final-action">
        <span className="final-action-title">Acción final</span>
        <span className="final-action-value muted">—</span>
      </animated.div>
    );
  }

  const actions = call.actions || [];
  const accepted = actions.some((a) => ACCEPTED_STATUSES.has(a?.result?.status));
  const duplicateBlocked = actions.some((a) => a?.result?.status === "duplicate");
  const endedMs = call.ended_at ? new Date(call.ended_at).getTime() : null;
  const windowSecs = call.submit_window_secs ?? 30;
  const submitElapsed = !call.live && endedMs ? (Date.now() - endedMs) / 1000 : 0;
  const submitRemaining = windowSecs - submitElapsed;
  const showCountdown = !call.live && !accepted && submitRemaining > -8;

  const label = call.live ? "En curso…" : STATUS_LABEL[call.status] || call.status || "—";

  return (
    <animated.div style={pop} className={`final-action ${accepted ? "done" : ""}`}>
      <span className="final-action-title">Acción final</span>
      <span className="final-action-value">{label}</span>
      {call.decline_reason && <span className="final-action-note">Motivo: {call.decline_reason}</span>}
      {duplicateBlocked && <span className="final-action-note warn">Envío duplicado bloqueado</span>}
      {showCountdown && (
        <span className={`final-action-countdown ${submitRemaining < 10 ? "warn" : ""}`}>
          Ventana de envío: {submitRemaining > 0 ? formatClock(submitRemaining) : "expirada"}
        </span>
      )}
    </animated.div>
  );
}

// The right pane: pieces of info as they're extracted from the tool feed,
// each paired with the rule behind it, ending in the always-visible final
// action card at the bottom.
export default function InsightPanel({ items, intent, call }) {
  const cards = buildCards(items, intent);

  const transitions = useTransition(cards, {
    keys: (card) => card.id,
    from: { opacity: 0, transform: "translateX(26px) scale(0.94)" },
    enter: { opacity: 1, transform: "translateX(0px) scale(1)" },
    update: { opacity: 1, transform: "translateX(0px) scale(1)" },
    config: { tension: 250, friction: 24 },
  });

  return (
    <aside className="insight-panel">
      <div className="insight-list">
        {cards.length === 0 && <p className="insight-empty">Sin información extraída todavía.</p>}
        {transitions((style, card) => (
          <animated.div style={style} className="insight-card">
            <span className="insight-title">{card.title}</span>
            <span className="insight-value">{card.value}</span>
            {card.rule && <span className="insight-rule">Regla: {card.rule}</span>}
          </animated.div>
        ))}
      </div>
      <FinalActionCard call={call} />
    </aside>
  );
}
