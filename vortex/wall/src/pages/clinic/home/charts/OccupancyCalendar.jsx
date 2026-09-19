import "./charts.css";

// Sequential blue ramp (magnitude encoding), light -> dark = low -> high
// occupancy. Same hue family as the trend line's blue is fine here: the
// two never appear in the same chart, so there's no identity clash.
const RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];

function stepFor(pct) {
  const idx = Math.min(RAMP.length - 1, Math.floor((pct / 100) * RAMP.length));
  return RAMP[idx];
}

// No hover tooltip: every cell already shows its own day, date and % —
// hovering wouldn't reveal anything the cell doesn't already say.
export default function OccupancyCalendar({ week }) {
  return (
    <div className="chart-root occupancy-calendar">
      <div className="occupancy-grid">
        {week.map((day, i) => (
          <div
            key={i}
            className="occupancy-cell"
            style={{ background: stepFor(day.pct), color: day.pct > 55 ? "#fff" : "var(--color-ink)" }}
          >
            <span className="occupancy-cell-day">{day.label}</span>
            <span className="occupancy-cell-date">{day.date.getDate()}</span>
            <span className="occupancy-cell-pct">{day.pct}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
