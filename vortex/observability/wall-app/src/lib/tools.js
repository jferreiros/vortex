// `big`  -> gets the full-screen live demo in the bottom stage.
// `keep` -> its finished result is worth keeping on screen as a square
//           "piece of info" in the middle grid. Tools with keep:false only
//           ever show up in the top ticker strip, never in that grid.
export const TOOL_META = {
  find_patient: { label: "Buscar paciente", big: true, keep: true, icon: "🧾" },
  find_slots: { label: "Buscar huecos", big: true, keep: true, icon: "📅" },
  build_registration: { label: "Registrar paciente", big: false, keep: true, icon: "📝" },
  validate_national_id: { label: "Validar DNI/NIE", big: false, keep: false, icon: "🪪" },
  prepare_booking: { label: "Preparar reserva", big: false, keep: true, icon: "✅" },
  list_appointments: { label: "Listar citas", big: false, keep: true, icon: "📋" },
  prepare_reschedule: { label: "Preparar cambio", big: false, keep: true, icon: "🔁" },
  prepare_cancel: { label: "Preparar anulación", big: false, keep: true, icon: "🗑️" },
  triage: { label: "Triaje", big: false, keep: false, icon: "🩺" },
  submit_action: { label: "Enviar acción", big: false, keep: true, icon: "📤" },
};

export function toolMeta(name) {
  return TOOL_META[name] || { label: name, big: false, keep: false, icon: "⌁" };
}
