import { useState } from "react";
import "./ui.css";

// Uncontrolled by default (local state) — these are placeholder settings
// with no backend to persist to yet. Pass `checked`/`onChange` to control.
export default function Switch({ defaultChecked = false, checked, onChange, label }) {
  const [internal, setInternal] = useState(defaultChecked);
  const isOn = checked ?? internal;

  function toggle() {
    if (onChange) onChange(!isOn);
    else setInternal((v) => !v);
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={isOn}
      aria-label={label}
      className={`ui-switch ${isOn ? "on" : ""}`}
      onClick={toggle}
    >
      <span className="ui-switch-thumb" />
    </button>
  );
}
