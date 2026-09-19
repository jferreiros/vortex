// Watches the tool-call feed and pulls out the pieces of info worth
// pinning in the right pane, each paired with the rule that produced it.
// Real backend fields win when present (PatientRecord.note,
// AppointmentTypeRecord.guidance, EligibilityVerdict.note); otherwise a
// plain-language fallback explains the same heuristic the rules lane uses.

function latestFinishedByTool(items, toolNames, pick) {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const item = items[i];
    if (item.type !== "tool" || item.status === "running") continue;
    if (!toolNames.includes(item.tool)) continue;
    const value = pick(item);
    if (value) return value;
  }
  return null;
}

export function derivePatient(items) {
  return latestFinishedByTool(items, ["find_patient", "build_registration"], (item) => {
    const result = item.result || {};
    const record = result.patient || (result.status ? null : result);
    if (!record || typeof record !== "object") return null;
    if (!record.insurer && record.has_visited_before === undefined && !record.referrals) return null;
    return {
      insurer: record.insurer || null,
      hasVisitedBefore: Boolean(record.has_visited_before),
      note: record.note || null,
      referrals: record.referrals || [],
    };
  });
}

export function deriveCare(items) {
  return latestFinishedByTool(items, ["find_slots", "prepare_booking", "triage"], (item) => {
    const result = item.result || {};
    const args = item.args || {};
    const appointmentType = result.appointment_type || null;
    const specialtyId = args.specialty_id || result.specialty_id || null;
    if (!appointmentType && !specialtyId) return null;
    return {
      specialtyId,
      appointmentTypeName: appointmentType?.name || null,
      guidance: appointmentType?.guidance || null,
    };
  });
}

export function deriveZone(items) {
  return latestFinishedByTool(items, ["find_slots", "prepare_booking"], (item) => {
    const result = item.result || {};
    const slot = Array.isArray(result.slots) && result.slots.length ? result.slots[0] : null;
    const location = result.location_name || slot?.location_id || null;
    const provider = result.provider_name || slot?.provider_name || null;
    if (!location && !provider) return null;
    return { location, provider };
  });
}

export function patientRule(patient) {
  if (!patient) return null;
  if (patient.note) return patient.note;
  if (patient.hasVisitedBefore) {
    return "Ya tiene historial con la clínica: se le trata como paciente habitual.";
  }
  return "No hay visitas previas registradas: se le trata como paciente nuevo.";
}

export function careRule(care) {
  if (!care) return null;
  if (care.guidance) return care.guidance;
  return "Primera vez pidiendo esta especialidad, así que se asigna revisión inicial (first review).";
}

export function zoneRule(zone) {
  if (!zone) return null;
  return "Hueco más cercano disponible con este proveedor.";
}

// cancel/reschedule never guess which appointment: the id comes straight
// off prepare_cancel/prepare_reschedule's own args, then list_appointments
// (read earlier in the same call) fills in when/where/who for display.
export function deriveAppointment(items) {
  const appointmentId = latestFinishedByTool(
    items,
    ["prepare_cancel", "prepare_reschedule"],
    (item) => item.args?.appointment_id || null,
  );
  if (!appointmentId) return null;

  const appointments = latestFinishedByTool(items, ["list_appointments"], (item) => {
    const list = item.result?.appointments;
    return Array.isArray(list) && list.length ? list : null;
  });
  const match = appointments?.find((a) => a.appointment_id === appointmentId) || null;

  return {
    appointmentId,
    start: match?.start || null,
    locationId: match?.location_id || null,
    providerId: match?.provider_id || null,
  };
}

export function appointmentRule() {
  return "El appointment_id viene de /patients/{id}/appointments, nunca de lo que dice quien llama.";
}

// The new slot a reschedule is moving into — straight off prepare_reschedule's
// own args, which already carries the full Slot the patient will land on.
export function deriveNewSlot(items) {
  return latestFinishedByTool(items, ["prepare_reschedule"], (item) => {
    const slot = item.args?.slot;
    if (!slot || !slot.start) return null;
    return {
      start: slot.start,
      locationId: slot.location_id || null,
      providerId: slot.provider_id || null,
    };
  });
}

export function newSlotRule() {
  return "El hueco que se moverá a esta cita en cuanto se confirme.";
}
