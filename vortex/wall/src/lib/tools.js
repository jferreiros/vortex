// `big`  -> gets the full-screen live demo in the bottom stage.
// `keep` -> its finished result is worth keeping on screen as a square
//           "piece of info" in the middle grid. Tools with keep:false only
//           ever show up in the top ticker strip, never in that grid.
export const TOOL_META = {
  find_patient: { label: "Find patient", big: true, keep: true, icon: "🧾" },
  find_slots: { label: "Find slots", big: true, keep: true, icon: "📅" },
  build_registration: { label: "Register patient", big: false, keep: true, icon: "📝" },
  validate_national_id: { label: "Validate DNI/NIE", big: false, keep: false, icon: "🪪" },
  prepare_booking: { label: "Prepare booking", big: false, keep: true, icon: "✅" },
  list_appointments: { label: "List appointments", big: false, keep: true, icon: "📋" },
  prepare_reschedule: { label: "Prepare reschedule", big: false, keep: true, icon: "🔁" },
  prepare_cancel: { label: "Prepare cancellation", big: false, keep: true, icon: "🗑️" },
  triage: { label: "Triage", big: false, keep: false, icon: "🩺" },
  submit_action: { label: "Submit action", big: false, keep: true, icon: "📤" },
};

export function toolMeta(name) {
  return TOOL_META[name] || { label: name, big: false, keep: false, icon: "⌁" };
}
