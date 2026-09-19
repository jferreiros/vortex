import { useEffect } from "react";
import "./ui.css";

// A blank-content popup shell — the caller supplies `title`; the body is
// intentionally empty until the real detail view for each stat exists.
export default function Modal({ open, title, onClose, actions, children }) {
  useEffect(() => {
    if (!open) return undefined;
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="ui-modal-overlay" onClick={onClose}>
      <div className="ui-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ui-modal-head">
          <h3>{title}</h3>
          <button type="button" className="ui-modal-close" onClick={onClose} aria-label="Cerrar">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
        <div className="ui-modal-body">
          {children || <p className="ui-modal-placeholder">Todavía no hay contenido aquí.</p>}
        </div>
        {actions && <div className="ui-modal-actions">{actions}</div>}
      </div>
    </div>
  );
}
