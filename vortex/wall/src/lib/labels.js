export const STATUS_LABEL = {
  live: "On call",
  booked: "Appointment booked",
  registered: "Patient registered",
  rescheduled: "Appointment rescheduled",
  cancelled: "Appointment cancelled",
  refused: "No action",
  escalated: "Escalated",
  ended: "Ended",
};

export const LANGUAGE_LABEL = {
  es: "Spanish",
  ca: "Catalan",
  eu: "Basque",
  gl: "Galician",
  en: "English",
  fr: "French",
  pt: "Portuguese",
};

export const SPECIALTY_LABEL = {
  general_practice: "General practice",
  paediatrics: "Paediatrics",
  dermatology: "Dermatology",
  orthopaedics: "Orthopaedics",
  gynaecology: "Gynaecology",
  physiotherapy: "Physiotherapy",
};

export const LOCATION_LABEL = {
  centro: "Arenal Centro",
  norte: "Arenal Norte",
  sur: "Arenal Sur",
};

export const INTENT_LABEL = {
  book: "Book appointment",
  register: "Register patient",
  reschedule: "Reschedule appointment",
  cancel: "Cancel appointment",
  "no-action": "No action",
  escalate: "Escalate",
  question: "Question",
};

// The closed, 18-value `reason` vocabulary from /api/v1/submit — see
// .claude/skills/submit-action. Every no-action or escalate carries one of
// these; the live feeds show the label so the reviewer sees which rule bit
// without opening the call.
export const REASON_LABEL = {
  not_eligible_age: "Age outside range for the specialty",
  referral_required: "Missing required referral",
  provider_not_in_network: "Provider outside the insurer's network",
  specialty_not_covered: "Specialty not covered by insurance",
  location_not_covered: "Site not covered by insurance",
  insurer_referral_required: "Insurer requires a prior referral",
  allowance_exhausted: "Annual allowance exhausted for this appointment",
  provider_on_leave: "Provider on leave on those dates",
  location_hours: "Site closed at that time",
  type_not_offered: "The site doesn't offer that appointment type",
  patient_history: "The patient's history rules it out",
  no_availability: "No slots available in the requested window",
  clinic_closed: "Clinic closed that day",
  patient_not_found: "Patient not found in the directory",
  provider_not_found: "Provider not found",
  caller_not_authorised: "The caller is not authorised for the patient",
  out_of_scope: "Out of scope for the line",
  medical_emergency: "Medical emergency symptoms",
};

// The phase a live call is in. Two vocabularies reach this: the board's own
// four stages (explain.STAGES -> "Listen", "Identify", "Decide", "Submit")
// and the demo feed's freer phrases ("Talking", "Waitlist offer"). Both are
// shown to a Spanish-speaking clinic, so both are mapped here, and anything
// unmapped falls through unchanged rather than becoming a blank chip.
export const PHASE_LABEL = {
  Listen: "Listening",
  Identify: "Identifying",
  Decide: "Deciding",
  Submit: "Submitting",
  Listening: "Listening",
  Talking: "Talking",
  "Confirming slot": "Confirming slot",
  "Waitlist offer": "Offering slot",
  Escalated: "Escalated",
  Reminder: "Reminder",
};

export function phaseView(call) {
  const raw = String(call?.phase || "").trim();
  return { key: raw, label: PHASE_LABEL[raw] || raw || "On call" };
}
