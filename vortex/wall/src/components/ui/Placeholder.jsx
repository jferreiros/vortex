import "./ui.css";

const GLYPH = {
  chart: (
    <path d="M4 19V5M4 19h16M8 19v-6M12 19V9M16 19v-9" />
  ),
  diagram: (
    <>
      <circle cx="6" cy="6" r="2.4" />
      <circle cx="18" cy="6" r="2.4" />
      <circle cx="12" cy="18" r="2.4" />
      <path d="M8 7.3L10.5 16M16 7.3L13.5 16M8.4 6h7.2" />
    </>
  ),
  illustration: (
    <>
      <rect x="3.5" y="4" width="17" height="14" rx="1.5" />
      <circle cx="8.5" cy="9.5" r="1.6" />
      <path d="M4 16l4.5-4.5L12 15l3-3l5 5" />
    </>
  ),
  avatar: <circle cx="12" cy="12" r="8.5" />,
  icon: <path d="M12 3.5l1.8 5.2l5.2 1.8l-5.2 1.8l-1.8 5.2l-1.8-5.2l-5.2-1.8l5.2-1.8z" />,
};

// A stand-in for any asset that doesn't exist yet: a chart, an
// illustration, a diagram, the hero avatar. Reserves the right size/ratio/
// position so dropping in the real asset later never touches layout.
// Usage: <Placeholder label="Future analytics visualization" kind="chart" ratio="16/9" />
export default function Placeholder({ label, kind = "diagram", ratio, minHeight, className = "" }) {
  return (
    <div
      className={`ui-placeholder ${className}`}
      style={{ aspectRatio: ratio, minHeight }}
    >
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
        {GLYPH[kind] || GLYPH.diagram}
      </svg>
      {label && <span className="ui-placeholder-label">{label}</span>}
    </div>
  );
}
