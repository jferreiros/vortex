export const STATUS_LABEL = {
  live: "En llamada",
  booked: "Cita reservada",
  registered: "Paciente registrado",
  rescheduled: "Cita movida",
  cancelled: "Cita anulada",
  refused: "Sin acción",
  escalated: "Escalada",
  ended: "Terminada",
};

export const LANGUAGE_LABEL = {
  es: "Español",
  ca: "Català",
  eu: "Euskara",
  gl: "Galego",
  en: "English",
  fr: "Français",
  pt: "Português",
};

export const SPECIALTY_LABEL = {
  general_practice: "Medicina general",
  paediatrics: "Pediatría",
  dermatology: "Dermatología",
  orthopaedics: "Traumatología",
  gynaecology: "Ginecología",
  physiotherapy: "Fisioterapia",
};

export const LOCATION_LABEL = {
  centro: "Arenal Centro",
  norte: "Arenal Norte",
  sur: "Arenal Sur",
};

export const INTENT_LABEL = {
  book: "Agendar cita",
  register: "Registrar paciente",
  reschedule: "Cambiar cita",
  cancel: "Anular cita",
  "no-action": "Sin acción",
  escalate: "Escalar",
  question: "Consulta",
};

// The closed, 18-value `reason` vocabulary from /api/v1/submit — see
// .claude/skills/submit-action. Every no-action or escalate carries one of
// these; the live feeds show the label so the reviewer sees which rule bit
// without opening the call.
export const REASON_LABEL = {
  not_eligible_age: "Edad fuera de rango para la especialidad",
  referral_required: "Falta la derivación necesaria",
  provider_not_in_network: "Médico fuera de la red del seguro",
  specialty_not_covered: "Especialidad no cubierta por el seguro",
  location_not_covered: "Centro no cubierto por el seguro",
  insurer_referral_required: "El seguro exige derivación previa",
  allowance_exhausted: "Cupo anual agotado para esta cita",
  provider_on_leave: "Médico de baja en esas fechas",
  location_hours: "Centro cerrado a esa hora",
  type_not_offered: "El centro no ofrece ese tipo de cita",
  patient_history: "El historial del paciente lo descarta",
  no_availability: "Sin huecos disponibles en la ventana pedida",
  clinic_closed: "Clínica cerrada ese día",
  patient_not_found: "Paciente no encontrado en el directorio",
  provider_not_found: "Médico no encontrado",
  caller_not_authorised: "Quien llama no está autorizado para el paciente",
  out_of_scope: "Fuera del alcance de la línea",
  medical_emergency: "Síntomas de urgencia médica",
};
