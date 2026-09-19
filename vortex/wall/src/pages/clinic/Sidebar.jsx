import { NavLink } from "react-router-dom";

const ICONS = {
  home: (
    <path d="M4 11.5L12 4l8 7.5M6 9.5V20h5v-5.5h2V20h5V9.5" />
  ),
  doctor: (
    <>
      <circle cx="12" cy="8" r="3.2" />
      <path d="M5 19.5c.8-3.2 3.4-5 7-5s6.2 1.8 7 5" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M19.4 13.6a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34a1.7 1.7 0 0 0-1 1.55V19.7a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.1-1.55a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87a1.7 1.7 0 0 0-1.55-1H4.3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 6 9.4a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H10.5a1.7 1.7 0 0 0 1-1.55V3.3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06-.06a1.7 1.7 0 0 0-.34 1.87V9.4a1.7 1.7 0 0 0 1.55 1h.09a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1z" />
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
  liveCalls: (
    <>
      <path d="M6.6 3.5c.7 1.6 1.8 3 3.2 4.1l-2 2.4a13 13 0 0 0 5.9 5.9l2.4-2a13 13 0 0 1 4.1 3.2c.5.5.5 1.4-.1 1.9l-1.3 1.1a2.6 2.6 0 0 1-2.2.6C10.9 19.6 4.4 13.1 3.3 6.4a2.6 2.6 0 0 1 .6-2.2L5 3c.5-.6 1.4-.6 1.9-.1z" />
      <circle cx="18.5" cy="6.5" r="1.4" fill="currentColor" stroke="none" />
    </>
  ),
  patternsPathways: (
    <>
      <circle cx="5" cy="6" r="2.2" />
      <circle cx="5" cy="18" r="2.2" />
      <circle cx="19" cy="12" r="2.2" />
      <path d="M7.1 6.9L16.9 11M7.1 17.1L16.9 13" />
    </>
  ),
};

const CLINIC_ITEMS = [
  { to: "/clinic/home", label: "Home", icon: "home" },
  { to: "/clinic/settings", label: "Ajustes", icon: "settings" },
  { to: "/clinic/ai", label: "IA", icon: "ai" },
  { to: "/clinic/insights", label: "Insights", icon: "insights" },
  { to: "/clinic/analytics", label: "Analytics", icon: "analytics" },
  { to: "/clinic/live-calls", label: "Live Calls", icon: "liveCalls" },
  { to: "/clinic/doctor", label: "Horarios", icon: "doctor" },
  { to: "/clinic/patterns-pathways", label: "Pathways & Patterns", icon: "patternsPathways" },
];

function NavIcon({ name }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

function Item({ to, icon, label }) {
  return (
    <NavLink to={to} className={({ isActive }) => `clinic-sidebar-item ${isActive ? "on" : ""}`}>
      <NavIcon name={icon} />
      <span>{label}</span>
    </NavLink>
  );
}

export default function Sidebar() {
  return (
    <nav className="clinic-sidebar">
      <div className="clinic-sidebar-brand">
        <span className="clinic-sidebar-mark" />
        <span className="clinic-sidebar-brand-text">
          Vortex
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
        <span>Línea activa</span>
      </div>
    </nav>
  );
}
