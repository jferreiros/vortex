// Silhouette-style replacements for the pathway/pattern shapes' emoji —
// full-colour platform emoji (🩺, 🧪, 📋…) read as too detailed once every
// shape shows only one glyph. Hand-drawn in the same line-icon language as
// Sidebar.jsx and Analytics.jsx (viewBox 24, single stroke, no fill),
// styled after Lucide/Feather's outline set. Keyed by the emoji character
// data/shapeTypes.json and data/patternShapes.json already store, so the
// JSON stays untouched — this only swaps what renders for it.

const GLYPHS = {
  // Calls
  "🆕": <path d="M12 3.5l1.8 5.6L19 11l-5.2 1.9L12 18.5l-1.8-5.6L5 11l5.2-1.9z" />,
  "↩️": (
    <>
      <path d="M9 8L4 13l5 5" />
      <path d="M4 13h11a5 5 0 0 0 0-10h-1" />
    </>
  ),
  "📞": (
    <path d="M6.6 3.5c.7 1.6 1.8 3 3.2 4.1l-2 2.4a13 13 0 0 0 5.9 5.9l2.4-2a13 13 0 0 1 4.1 3.2c.5.5.5 1.4-.1 1.9l-1.3 1.1a2.6 2.6 0 0 1-2.2.6C10.9 19.6 4.4 13.1 3.3 6.4a2.6 2.6 0 0 1 .6-2.2L5 3c.5-.6 1.4-.6 1.9-.1z" />
  ),
  "⏳": (
    <>
      <path d="M6.5 3h11M6.5 21h11" />
      <path d="M7.5 3c0 5 4 6.5 4.5 8-.5 1.5-4.5 3-4.5 8M16.5 3c0 5-4 6.5-4.5 8 .5 1.5 4.5 3 4.5 8" />
    </>
  ),
  "🩺": (
    <>
      <path d="M6 3v6.5a3.8 3.8 0 0 0 7.6 0V3" />
      <path d="M9.8 15.2a4.6 4.6 0 0 0 9.2 0v-2.1" />
      <circle cx="19.6" cy="10.4" r="1.9" />
    </>
  ),
  "💳": (
    <>
      <rect x="3" y="6" width="18" height="13" rx="2" />
      <path d="M3 10.5h18" />
      <path d="M6.5 15h4" />
    </>
  ),
  "🧪": <path d="M9.5 3h5M10.3 3v9.6a3.9 3.9 0 1 0 3.4 0V3" />,
  // Messages
  "📝": (
    <>
      <rect x="4.5" y="3" width="14" height="18" rx="2" />
      <path d="M8 8h7M8 12h7M8 16h4.5" />
    </>
  ),
  "💬": <path d="M4 5h16v11.5H8.5L4 20.5z" />,
  "📖": (
    <path d="M3 5.5c3-1.6 6-1.6 9 0v14c-3-1.6-6-1.6-9 0zM21 5.5c-3-1.6-6-1.6-9 0v14c3-1.6 6-1.6 9 0z" />
  ),
  "📄": (
    <>
      <path d="M6.5 2.5h9l4 4v15h-13z" />
      <path d="M15.5 2.5v4h4" />
    </>
  ),
  "✍️": (
    <>
      <path d="M14.5 4.5l4 4-9.5 9.5H5v-4z" />
      <path d="M3 20.5c1.5-1.5 3-1.5 4.5 0" />
    </>
  ),
  "🔗": (
    <>
      <path d="M9.5 14.5l5-5" />
      <path d="M8 11.5l-1.8 1.8a3.6 3.6 0 0 0 5.1 5.1l1.8-1.8" />
      <path d="M16 12.5l1.8-1.8a3.6 3.6 0 0 0-5.1-5.1L11 7.4" />
    </>
  ),
  "🔄": (
    <>
      <path d="M20 11.5A8 8 0 0 0 6.3 6.2" />
      <path d="M4 12.5a8 8 0 0 0 13.7 5.3" />
      <path d="M20 4.5v5.5h-5.5" />
      <path d="M4 19.5V14h5.5" />
    </>
  ),
  // Visits
  "🏥": (
    <>
      <rect x="4" y="9.5" width="16" height="11.5" rx="1.2" />
      <path d="M9 21V9.5M9 3.5v6M6 6.5h6" />
      <path d="M13.5 13.5h3M15 12v3" />
    </>
  ),
  "🚫": (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M6.4 6.4l11.2 11.2" />
    </>
  ),
  "⚕️": (
    <>
      <path d="M4 20l6.5-6.5" />
      <path d="M13 11.5l4-4 3.2 3.2-4 4z" />
      <path d="M16.2 6.2l1.6-1.6" />
    </>
  ),
  "💉": (
    <>
      <path d="M18.5 2.5l3 3" />
      <path d="M18 6.5L6.5 18l-3 4.5 4.5-3L19.5 8z" />
      <path d="M14.5 6.5l3 3M12.5 8.5l3 3" />
    </>
  ),
  "📋": (
    <>
      <rect x="5" y="4.2" width="14" height="17" rx="1.8" />
      <rect x="9" y="2.2" width="6" height="3.6" rx="0.9" />
      <path d="M8.5 11h7M8.5 14.6h5" />
    </>
  ),
  "💻": (
    <>
      <rect x="4" y="4.5" width="16" height="10.5" rx="1.2" />
      <path d="M2 19.5h20" />
    </>
  ),
  "🚑": (
    <>
      <path d="M12 3.5L21.5 20h-19z" />
      <path d="M12 9.5V14" />
      <circle cx="12" cy="17" r="0.9" fill="currentColor" stroke="none" />
    </>
  ),
  "⚙️": (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </>
  ),
  // Conditions
  "⌛": (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7v5l3.2 2" />
    </>
  ),
  "🔇": (
    <>
      <path d="M9 9.2v5.6h3.6l4.4 4V5.2l-4.4 4z" />
      <path d="M2.5 2.5l19 19" />
    </>
  ),
  "🧭": (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M14.8 9.2l-2 4.8-4.8 2 2-4.8z" />
    </>
  ),
  // History-only extras (patternShapes.json)
  "📅": (
    <>
      <rect x="3.5" y="5" width="17" height="15" rx="2.2" />
      <path d="M3.5 9.7h17M8 3v4M16 3v4" />
    </>
  ),
  "🔁": (
    <>
      <path d="M17 2.5l4 4-4 4" />
      <path d="M21 6.5H8.5a4 4 0 0 0-4 4v1" />
      <path d="M7 21.5l-4-4 4-4" />
      <path d="M3 17.5h12.5a4 4 0 0 0 4-4v-1" />
    </>
  ),
  "❌": (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9 9l6 6M15 9l-6 6" />
    </>
  ),
  // Entry point trigger
  "🛎️": (
    <>
      <path d="M12 4a6.5 6.5 0 0 0-6.5 6.5v2.3c0 .6-.2 1.2-.6 1.7L4 16h16l-.9-1.5a2.8 2.8 0 0 1-.6-1.7v-2.3A6.5 6.5 0 0 0 12 4z" />
      <path d="M9.5 19a2.6 2.6 0 0 0 5 0" />
    </>
  ),
};

// A type nobody's mapped yet still shows its emoji rather than a blank
// bubble — better an unstyled glyph than nothing while the set grows.
export default function ShapeIcon({ emoji, className }) {
  const glyph = GLYPHS[emoji];
  if (!glyph) return <span className={className}>{emoji}</span>;
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {glyph}
    </svg>
  );
}
