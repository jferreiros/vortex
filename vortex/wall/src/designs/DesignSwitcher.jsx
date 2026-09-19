import "./design-switcher.css";

const ORDER = ["original", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"];

// Preview-only chrome: lets whoever is comparing directions jump between
// them without hand-editing the URL. Never rendered on a real, non-preview
// call — see App.jsx's isPreview gate.
export default function DesignSwitcher({ active, onSelect, designs }) {
  return (
    <div className="design-switcher">
      <span className="design-switcher-label">Design lab</span>
      <div className="design-switcher-pills">
        {ORDER.map((key) => (
          <button
            key={key}
            type="button"
            className={`design-switcher-pill ${active === key ? "on" : ""}`}
            onClick={() => onSelect(key)}
          >
            {designs[key].label}
          </button>
        ))}
      </div>
    </div>
  );
}
