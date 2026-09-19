import "./ui.css";

// large: no button below, so the value grows to fill that vertical space —
// used for the one stat in a row that has no detail to drill into.
// button: label for the "open detail" action below the value; onOpenDetail
// fires with no arguments — the caller decides what "detail" means.
export default function StatTile({ label, value, unit, large = false, hint, button, onOpenDetail }) {
  return (
    <div className="ui-stat-tile">
      <span className="ui-stat-label">{label}</span>
      <span className={`ui-stat-value ${large ? "large" : ""}`}>
        {value}
        {unit && <span className="ui-stat-unit">{unit}</span>}
      </span>
      {hint && <span className="ui-stat-hint">{hint}</span>}
      {button && (
        <button type="button" className="ui-stat-button" onClick={onOpenDetail}>
          {button}
        </button>
      )}
    </div>
  );
}
