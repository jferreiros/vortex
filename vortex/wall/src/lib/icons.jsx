// A small, coherent line-icon family replacing the emoji the original app
// used as tool/phase markers. One 24x24 stroke grammar (round caps/joins,
// currentColor) so every design concept can restyle these with CSS alone
// (stroke width, color, drop shadow, fill) without redrawing anything.

const base = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

const TOOL_PATHS = {
  find_patient: (
    <>
      <rect x="4" y="4" width="12" height="16" rx="2" />
      <line x1="7.5" y1="8.5" x2="12.5" y2="8.5" />
      <line x1="7.5" y1="12" x2="11" y2="12" />
      <circle cx="16.5" cy="16.5" r="3.2" />
      <line x1="18.8" y1="18.8" x2="21" y2="21" />
    </>
  ),
  find_slots: (
    <>
      <rect x="3.5" y="5" width="17" height="15" rx="2" />
      <line x1="3.5" y1="9.5" x2="20.5" y2="9.5" />
      <line x1="7.5" y1="3" x2="7.5" y2="7" />
      <line x1="16.5" y1="3" x2="16.5" y2="7" />
      <rect x="9.2" y="12" width="4.6" height="4.2" rx="1" fill="currentColor" stroke="none" opacity="0.85" />
    </>
  ),
  build_registration: (
    <>
      <path d="M7 3.5h7l3.5 3.5V20.5h-10.5z" />
      <path d="M14 3.5v3.5h3.5" />
      <line x1="9" y1="12" x2="14.5" y2="12" />
      <line x1="9" y1="15.2" x2="14.5" y2="15.2" />
      <line x1="9" y1="18.4" x2="12.5" y2="18.4" />
    </>
  ),
  validate_national_id: (
    <>
      <path d="M12 3l7 2.6v5.6c0 4.6-2.9 7.8-7 9-4.1-1.2-7-4.4-7-9V5.6z" />
      <path d="M8.7 12.2l2.3 2.3l4.3-4.6" />
    </>
  ),
  prepare_booking: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M8.3 12.3l2.6 2.6l4.8-5.2" />
    </>
  ),
  list_appointments: (
    <>
      <line x1="5" y1="6.5" x2="19" y2="6.5" />
      <line x1="5" y1="12" x2="19" y2="12" />
      <line x1="5" y1="17.5" x2="14" y2="17.5" />
      <circle cx="3" cy="6.5" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="3" cy="12" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="3" cy="17.5" r="0.9" fill="currentColor" stroke="none" />
    </>
  ),
  prepare_reschedule: (
    <>
      <path d="M4.5 9a7.5 7.5 0 0 1 13.6-4.3M19.5 15a7.5 7.5 0 0 1-13.6 4.3" />
      <path d="M18.5 3.5v4.5H14" />
      <path d="M5.5 20.5V16h4.5" />
    </>
  ),
  prepare_cancel: (
    <>
      <path d="M5 7h14" />
      <path d="M9 7V4.8c0-.7.6-1.3 1.3-1.3h3.4c.7 0 1.3.6 1.3 1.3V7" />
      <path d="M6.5 7l.8 12c.05.9.8 1.5 1.7 1.5h6c.9 0 1.65-.6 1.7-1.5l.8-12" />
      <line x1="10.2" y1="11" x2="10.2" y2="16.2" />
      <line x1="13.8" y1="11" x2="13.8" y2="16.2" />
    </>
  ),
  triage: (
    <>
      <path d="M3.5 12.5h4l1.6-3.6l2.2 6.8l1.6-4.2l1.2 2.4h6.4" />
      <path d="M8 6.2c1.2-1.5 3.2-1.7 4.4-.4c1.2-1.3 3.2-1.1 4.4.4c1.3 1.6.9 3.7-1 5.4l-3.4 3-3.4-3c-1.9-1.7-2.3-3.8-1-5.4z" opacity="0.55" />
    </>
  ),
  submit_action: (
    <>
      <path d="M20.5 3.5L3 10.2l6.4 2.6l2.6 6.4z" />
      <path d="M20.5 3.5l-9 9.3" />
    </>
  ),
};

const DEFAULT_PATH = (
  <>
    <path d="M12 3.5l1.8 5.2l5.2 1.8l-5.2 1.8l-1.8 5.2l-1.8-5.2l-5.2-1.8l5.2-1.8z" />
  </>
);

export function ToolIcon({ name, className, size = 22 }) {
  return (
    <svg {...base} width={size} height={size} className={className} aria-hidden="true">
      {TOOL_PATHS[name] || DEFAULT_PATH}
    </svg>
  );
}

const PHASE_PATHS = {
  connecting: (
    <>
      <circle cx="12" cy="17" r="1.1" fill="currentColor" stroke="none" />
      <path d="M8.5 13.8a5 5 0 0 1 7 0" />
      <path d="M5.6 10.9a9.2 9.2 0 0 1 12.8 0" />
    </>
  ),
  thinking: (
    <>
      <circle cx="8" cy="12" r="1.15" fill="currentColor" stroke="none" />
      <circle cx="12.2" cy="12" r="1.15" fill="currentColor" stroke="none" />
      <circle cx="16.4" cy="12" r="1.15" fill="currentColor" stroke="none" />
    </>
  ),
  speaking: (
    <>
      <line x1="6" y1="10.5" x2="6" y2="13.5" />
      <line x1="9.3" y1="8" x2="9.3" y2="16" />
      <line x1="12.6" y1="5.5" x2="12.6" y2="18.5" />
      <line x1="15.9" y1="8" x2="15.9" y2="16" />
      <line x1="19.2" y1="10.5" x2="19.2" y2="13.5" />
    </>
  ),
  working: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.8v2.4M12 17.8v2.4M20.2 12h-2.4M6.2 12H3.8M17.4 6.6l-1.7 1.7M8.3 15.7l-1.7 1.7M17.4 17.4l-1.7-1.7M8.3 8.3L6.6 6.6" />
    </>
  ),
  listening: (
    <>
      <path d="M9 8.5a3 3 0 0 1 6 0v4.2a3 3 0 0 1-6 0z" />
      <path d="M6.5 12v.7a5.5 5.5 0 0 0 11 0V12" />
      <line x1="12" y1="18.2" x2="12" y2="20.5" />
    </>
  ),
  ended: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M8.3 12.3l2.6 2.6l4.8-5.2" />
    </>
  ),
};

export function PhaseIcon({ phase, className, size = 26 }) {
  return (
    <svg {...base} width={size} height={size} className={className} aria-hidden="true">
      {PHASE_PATHS[phase] || PHASE_PATHS.connecting}
    </svg>
  );
}
