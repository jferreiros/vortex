import "./ui.css";

// trend: positive number = up (good, unless invert), negative = down.
export default function StatTile({ label, value, unit, trend, invert = false }) {
  const hasTrend = typeof trend === "number";
  const good = hasTrend ? (invert ? trend < 0 : trend > 0) : null;

  return (
    <div className="ui-stat-tile">
      <span className="ui-stat-label">{label}</span>
      <span className="ui-stat-value">
        {value}
        {unit && <span className="ui-stat-unit">{unit}</span>}
      </span>
      {hasTrend && (
        <span className={`ui-stat-trend ${good ? "up" : "down"}`}>
          {trend > 0 ? "↑" : trend < 0 ? "↓" : "·"} {Math.abs(trend)}%
        </span>
      )}
    </div>
  );
}
