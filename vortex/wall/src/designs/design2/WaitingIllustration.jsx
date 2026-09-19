// PLACEHOLDER: custom hero illustration — a warm, abstract "reception desk"
// scene shown before the call has produced its first turn. Built from flat
// blob shapes so it drops in cleanly today; swap for a bespoke illustration
// (same viewBox, same rough silhouette weights) whenever one exists.
export default function WaitingIllustration({ className = "" }) {
  return (
    <svg viewBox="0 0 320 220" className={`d2-illustration ${className}`} aria-hidden="true">
      <ellipse cx="160" cy="190" rx="120" ry="14" fill="var(--d2-ink)" opacity="0.06" />
      <path
        d="M60 150 Q40 90 100 70 Q150 52 190 78 Q240 100 232 148 Q226 182 168 188 Q92 196 60 150Z"
        fill="var(--d2-teal)"
        opacity="0.16"
      />
      <circle cx="118" cy="118" r="46" fill="var(--d2-coral)" opacity="0.22" />
      <circle cx="200" cy="108" r="30" fill="var(--d2-gold)" opacity="0.35" />
      <rect x="96" y="96" width="70" height="52" rx="14" fill="var(--d2-card)" stroke="var(--d2-ink)" strokeOpacity="0.1" />
      <path d="M108 118h46M108 130h30" stroke="var(--d2-ink)" strokeOpacity="0.35" strokeWidth="3" strokeLinecap="round" />
      <circle cx="204" cy="96" r="9" fill="var(--d2-plum)" opacity="0.55" />
      <circle cx="222" cy="132" r="5" fill="var(--d2-coral)" />
      <circle cx="78" cy="100" r="4" fill="var(--d2-teal)" />
    </svg>
  );
}
