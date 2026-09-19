import { useRef, useEffect, useState } from "react";
import "./ui.css";

export default function Knob({
  label,
  value,
  min = 0,
  max = 100,
  step = 1,
  onChange,
  disabled = false,
  leftLabel,
  rightLabel,
  previewText,
}) {
  const knobRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);
  const [angle, setAngle] = useState(() => valueToAngle(value, min, max));

  function valueToAngle(v, mn, mx) {
    const normalized = (v - mn) / (mx - mn);
    return -135 + normalized * 270;
  }

  function angleToValue(a, mn, mx) {
    const normalized = (a + 135) / 270;
    const clamped = Math.max(0, Math.min(1, normalized));
    const raw = mn + clamped * (mx - mn);
    return Math.round(raw / step) * step;
  }

  function getAngleFromEvent(e) {
    const rect = knobRef.current.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    return Math.atan2(clientY - centerY, clientX - centerX) * (180 / Math.PI);
  }

  function onMouseDown(e) {
    if (disabled) return;
    e.preventDefault();
    setIsDragging(true);
  }

  useEffect(() => {
    if (isDragging) {
      function onMouseMove(e) {
        const a = getAngleFromEvent(e);
        if (a < -135 || a > 135) return;
        const newValue = angleToValue(a, min, max);
        if (newValue !== value) onChange(newValue);
      }
      function onMouseUp() {
        setIsDragging(false);
      }
      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
      window.addEventListener("touchmove", onMouseMove, { passive: false });
      window.addEventListener("touchend", onMouseUp);
      return () => {
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);
        window.removeEventListener("touchmove", onMouseMove);
        window.removeEventListener("touchend", onMouseUp);
      };
    }
  }, [isDragging, min, max, onChange, value]);

  useEffect(() => {
    setAngle(valueToAngle(value, min, max));
  }, [value, min, max]);

  const radius = 64;
  const strokeWidth = 10;
  const circumference = 2 * Math.PI * (radius - strokeWidth / 2);
  const dashOffset = circumference - (angle + 135) / 270 * circumference;

  return (
    <div className={`ui-knob ${disabled ? "disabled" : ""} ${isDragging ? "dragging" : ""}`} style={{ "--knob-angle": `${angle}deg` }}>
      <div className="ui-knob-track" role="slider" aria-label={label} aria-valuemin={min} aria-valuemax={max} aria-valuenow={value} aria-disabled={disabled} tabIndex={disabled ? -1 : 0} ref={knobRef} onMouseDown={onMouseDown} onTouchStart={onMouseDown} onKeyDown={(e) => {
        if (disabled) return;
        let newVal = value;
        if (e.key === "ArrowRight" || e.key === "ArrowUp") newVal = Math.min(max, value + step);
        else if (e.key === "ArrowLeft" || e.key === "ArrowDown") newVal = Math.max(min, value - step);
        else if (e.key === "Home") newVal = min;
        else if (e.key === "End") newVal = max;
        else return;
        if (newVal !== value) onChange(newVal);
      }}>
        <svg className="ui-knob-svg" viewBox="0 0 128 128">
          <circle className="ui-knob-bg" cx="64" cy="64" r={radius - strokeWidth / 2} strokeWidth={strokeWidth} fill="none" />
          <circle className="ui-knob-progress" cx="64" cy="64" r={radius - strokeWidth / 2} strokeWidth={strokeWidth} fill="none" strokeDasharray={circumference} strokeDashoffset={dashOffset} style={{ transform: `rotate(-135deg)`, transformOrigin: "center" }} />
        </svg>
        <div className="ui-knob-value">{value}</div>
      </div>
      <div className="ui-knob-labels">
        <span className="ui-knob-left-label">{leftLabel}</span>
        <span className="ui-knob-right-label">{rightLabel}</span>
      </div>
      <div className="ui-knob-label">{label}</div>
      {previewText && <div className="ui-knob-preview">{previewText}</div>}
    </div>
  );
}