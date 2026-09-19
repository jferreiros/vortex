import { dayKey, eachDay, parseDateOnly, weekdayLabel } from "../lib/dates";

// The find_slots detail view: the exact date range that was queried, laid
// out as a small calendar strip with how many slots landed on each day.
export default function StageFindSlots({ tool }) {
  const args = tool.args || {};
  const result = tool.result || {};
  const from = parseDateOnly(args.date_from || args.from);
  const to = parseDateOnly(args.date_to || args.to) || from;
  const days = eachDay(from, to);

  const counts = new Map();
  const slots = Array.isArray(result.slots) ? result.slots : [];
  for (const slot of slots) {
    const start = slot?.start ? new Date(slot.start) : null;
    if (!start || Number.isNaN(start.getTime())) continue;
    const key = dayKey(start);
    counts.set(key, (counts.get(key) || 0) + 1);
  }

  return (
    <div className="stage-details">
      <div className="stage-section">
        <h4>Rango buscado</h4>
        <div className="stage-chips">
          <span className="chip">
            <b>desde</b>: {args.date_from || args.from || "—"}
          </span>
          <span className="chip">
            <b>hasta</b>: {args.date_to || args.to || "—"}
          </span>
          {args.specialty_id && (
            <span className="chip">
              <b>especialidad</b>: {args.specialty_id}
            </span>
          )}
          {args.provider_id && (
            <span className="chip">
              <b>médico</b>: {args.provider_id}
            </span>
          )}
        </div>
      </div>
      <div className="stage-section stage-section-grow">
        <h4>Calendario ({slots.length} huecos)</h4>
        <div className="stage-calendar">
          {days.length === 0 && <span className="stage-empty-inline">Sin rango de fechas.</span>}
          {days.map((day) => {
            const key = dayKey(day);
            const count = counts.get(key) || 0;
            return (
              <div className={`stage-cal-day ${count > 0 ? "has-slots" : "empty"}`} key={key}>
                <span className="stage-cal-weekday">{weekdayLabel(day)}</span>
                <span className="stage-cal-number">{day.getDate()}</span>
                <span className="stage-cal-count">{count > 0 ? count : "—"}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
