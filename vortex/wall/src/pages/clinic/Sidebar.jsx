import { NavLink, useLocation } from "react-router-dom";

const ICONS = {
  home: (
    <path d="M4 11.5L12 4l8 7.5M6 9.5V20h5v-5.5h2V20h5V9.5" />
  ),
  schedule: (
    <>
      <rect x="3.5" y="5" width="17" height="15" rx="2.2" />
      <path d="M3.5 9.7h17M8 3v4M16 3v4M7.5 13.3h2M11.5 13.3h2M15.5 13.3h2M7.5 17h2" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </>
  ),
  ai: (
    <>
      <circle cx="12" cy="12" r="8.2" />
      <circle cx="9.3" cy="10.3" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="14.7" cy="10.3" r="0.9" fill="currentColor" stroke="none" />
      <path d="M8.6 14.4a4.3 4.3 0 0 0 6.8 0" />
    </>
  ),
  insights: (
    <path d="M4 19V5M4 19h16M8 19v-6M12 19V9M16 19v-9" />
  ),
  analytics: (
    <>
      <path d="M4 5v14h16" />
      <path d="M7.5 15.5l3.5-4.5 3 2.5 4.5-6" />
    </>
  ),
  calls: (
    <path d="M6.6 3.5c.7 1.6 1.8 3 3.2 4.1l-2 2.4a13 13 0 0 0 5.9 5.9l2.4-2a13 13 0 0 1 4.1 3.2c.5.5.5 1.4-.1 1.9l-1.3 1.1a2.6 2.6 0 0 1-2.2.6C10.9 19.6 4.4 13.1 3.3 6.4a2.6 2.6 0 0 1 .6-2.2L5 3c.5-.6 1.4-.6 1.9-.1z" />
  ),
  patternsPathways: (
    <>
      <circle cx="5" cy="6" r="2.2" />
      <circle cx="5" cy="18" r="2.2" />
      <circle cx="19" cy="12" r="2.2" />
      <path d="M7.1 6.9L16.9 11M7.1 17.1L16.9 13" />
    </>
  ),
  close: (
    <path d="M5 5l14 14M19 5L5 19" />
  ),
};

const CLINIC_ITEMS = [
  { to: "/clinic/home", label: "Home", icon: "home" },
  { to: "/clinic/settings", label: "Agent settings", icon: "settings" },
  { to: "/clinic/ai", label: "Agent personalization", icon: "ai" },
  { to: "/clinic/calls", label: "Calls", icon: "calls", also: ["/clinic/live-calls"] },
  { to: "/clinic/insights", label: "Insights", icon: "insights" },
  { to: "/clinic/doctor", label: "Schedule", icon: "schedule" },
  { to: "/clinic/patterns-pathways", label: "Pathways & Patterns", icon: "patternsPathways" },
];

export function NavIcon({ name }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

function Item({ to, icon, label, also = [] }) {
  const location = useLocation();
  return (
    <NavLink
      to={to}
      className={({ isActive }) => {
        const extra = also.some((prefix) => location.pathname.startsWith(prefix));
        return `clinic-sidebar-item ${isActive || extra ? "on" : ""}`;
      }}
    >
      <NavIcon name={icon} />
      <span>{label}</span>
    </NavLink>
  );
}

export default function Sidebar() {
  return (
    <nav className="clinic-sidebar">
      <div className="clinic-sidebar-brand">
        <img className="clinic-sidebar-mark" src="/wall/vorty-face" alt="" />
        <span className="clinic-sidebar-brand-text">
          Vorti
          <small>Clínica Arenal</small>
        </span>
      </div>

      <div className="clinic-sidebar-nav">
        {CLINIC_ITEMS.map((item) => (
          <Item key={item.to} {...item} />
        ))}
      </div>

      <div className="clinic-sidebar-foot">
        <span className="clinic-sidebar-status-dot" />
        <span>Line active</span>
      </div>
    </nav>
  );
}
