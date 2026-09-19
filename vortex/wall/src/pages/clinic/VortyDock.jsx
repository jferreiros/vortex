import { useState } from "react";
import { NavLink } from "react-router-dom";
import { useLiveCalls } from "./live-calls/useLiveCalls";
import "./vorty-dock.css";

/* Vorty, parked in the bottom-right corner of every Clinic View page.

   He is the product's face on the landing page; here he is the way into
   what the line is doing right now. Closed, he is a button that shows a
   badge when calls are in progress. Open, he says how many and offers the
   two places you would go next.

   Deliberately not a chat: the console has no assistant behind it, and a
   text box that answers nothing is worse than no text box. */

export default function VortyDock() {
  const [open, setOpen] = useState(false);
  const calls = useLiveCalls();
  const live = calls.filter((call) => call.status === "live");
  const count = live.length;

  return (
    <div className={`vorty-dock ${open ? "is-open" : ""}`}>
      {open && (
        <div className="vorty-bubble" role="dialog" aria-label="Vorty">
          <button
            type="button"
            className="vorty-bubble-close"
            onClick={() => setOpen(false)}
            aria-label="Cerrar"
          >
            ×
          </button>
          <p className="vorty-bubble-lead">
            {count === 0
              ? "Ahora mismo no hay ninguna llamada en curso."
              : count === 1
                ? "Hay una llamada en curso."
                : `Hay ${count} llamadas en curso.`}
          </p>
          {count > 0 && (
            <ul className="vorty-bubble-calls">
              {live.slice(0, 3).map((call) => (
                <li key={call.id}>
                  <span className="vorty-bubble-name">{call.patient}</span>
                  <span className="vorty-bubble-phase">{call.phase}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="vorty-bubble-links">
            <NavLink to="/clinic/live-calls" onClick={() => setOpen(false)}>
              Ver llamadas
            </NavLink>
            <NavLink to="/clinic/analytics" onClick={() => setOpen(false)}>
              Ver analítica
            </NavLink>
          </div>
        </div>
      )}
      <button
        type="button"
        className="vorty-dock-button"
        onClick={() => setOpen((was) => !was)}
        aria-label={open ? "Cerrar Vorty" : "Abrir Vorty"}
        aria-expanded={open}
      >
        <img src="/wall/avatar2d-animated" alt="" className="vorty-dock-avatar" />
        {count > 0 && !open && <span className="vorty-dock-badge">{count}</span>}
      </button>
    </div>
  );
}
