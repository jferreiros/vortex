import { toolMeta } from "./tools";
import { derivePatient, deriveCare, deriveZone, patientRule, careRule, zoneRule } from "./insights";
import { INTENT_LABEL, STATUS_LABEL } from "./labels";

// Shared derivations, pulled out of the original App/LeftPane/InsightPanel so
// every design concept reads the same call state the same way. Presentation
// differs per concept; the rules that produce "what is true right now" do not.

const ACCEPTED_STATUSES = new Set(["accepted", "duplicate"]);

export function derivePhase(items, call) {
  if (call && !call.live && call.ended_at) return "ended";
  if (items.length === 0) return "connecting";
  const last = items[items.length - 1];
  if (last.type === "tool") return last.status === "running" ? "working" : "thinking";
  if (last.type === "turn") return last.role === "assistant" ? "speaking" : "listening";
  return "connecting";
}

// Which tool deserves the spotlight right now, and what shape that takes:
// a big stage demo, a generic live inputs/outputs view, or (nothing running)
// a quiet list of recent calls.
export function deriveToolFocus(items) {
  const lastItem = items.length ? items[items.length - 1] : null;
  const showLive = lastItem?.type === "tool";
  if (showLive) {
    const meta = toolMeta(lastItem.tool);
    return { mode: meta.big ? "stage" : "live", tool: lastItem, meta };
  }
  return { mode: "recent", recent: items.filter((it) => it.type === "tool") };
}

export function buildInsightCards(items, intent) {
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

export function deriveFinalAction(call) {
  if (!call) {
    return { label: "—", muted: true, accepted: false, duplicateBlocked: false, showCountdown: false };
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
  return { label, muted: false, accepted, duplicateBlocked, showCountdown, submitRemaining, live: call.live };
}
