import { useRef, useState } from "react";
import "./charts.css";

const SERIES = [
  { key: "booking", label: "Reservas", color: "var(--series-booking)" },
  { key: "reschedule", label: "Cambios", color: "var(--series-reschedule)" },
  { key: "cancel", label: "Cancelaciones", color: "var(--series-cancel)" },
];

const W = 560;
const H = 200;
const PAD_L = 28;
const PAD_B = 20;
const PAD_T = 10;

// Stacked bars, one per business hour, coloured by action type. Mark specs
// from the dataviz skill: <=24px-thick bars, 2px surface gap between
// stacked segments and between neighbouring bars, per-bar hover tooltip.
export default function HourlyStackedChart({ data }) {
  const rootRef = useRef(null);
  const [hover, setHover] = useState(null); // { index, x, y }

  const max = Math.max(1, ...data.map((d) => d.booking + d.reschedule + d.cancel));
  const plotH = H - PAD_T - PAD_B;
  const plotW = W - PAD_L;
  const bandW = plotW / data.length;
  const barW = Math.min(24, bandW - 6);
  const gap = 2;

  const yTicks = [0, 0.5, 1].map((f) => Math.round(max * f));

  function showTooltip(e, index) {
    const rect = rootRef.current.getBoundingClientRect();
    setHover({ index, x: e.clientX - rect.left, y: e.clientY - rect.top });
  }

  const hovered = hover ? data[hover.index] : null;

  return (
    <div className="chart-root" ref={rootRef}>
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Volumen de llamadas por hora, por tipo de acción">
        {yTicks.map((t) => {
          const y = PAD_T + plotH - (t / max) * plotH;
          return (
            <g key={t}>
              <line x1={PAD_L} x2={W} y1={y} y2={y} className="chart-gridline" />
              <text x={PAD_L - 6} y={y + 3} textAnchor="end" className="chart-axis-text">
                {t}
              </text>
            </g>
          );
        })}

        {data.map((d, i) => {
          const x = PAD_L + i * bandW + (bandW - barW) / 2;
          let cursorY = PAD_T + plotH;
          const segments = SERIES.map((s) => {
            const value = d[s.key];
            const segH = Math.max(0, (value / max) * plotH - gap);
            cursorY -= (value / max) * plotH;
            return { ...s, value, y: cursorY + gap / 2, h: segH };
          });

          return (
            <g key={d.hour}>
              {segments.map(
                (s) =>
                  s.h > 0 && (
                    <rect
                      key={s.key}
                      x={x}
                      y={s.y}
                      width={barW}
                      height={s.h}
                      rx={2}
                      fill={s.color}
                      opacity={hover && hover.index !== i ? 0.35 : 1}
                    />
                  ),
              )}
              {/* full-height hit target, wider than the bar for an easy hover */}
              <rect
                x={x - 3}
                y={PAD_T}
                width={barW + 6}
                height={plotH}
                fill="transparent"
                onMouseEnter={(e) => showTooltip(e, i)}
                onMouseMove={(e) => showTooltip(e, i)}
                onMouseLeave={() => setHover(null)}
              />
              {i % 2 === 0 && (
                <text x={x + barW / 2} y={H - 4} textAnchor="middle" className="chart-axis-text">
                  {d.hour}h
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {hovered && (
        <div className="chart-tooltip" style={{ left: hover.x, top: hover.y - 10 }}>
          <span className="chart-tooltip-title">{hovered.hour}:00</span>
          {SERIES.map((s) => (
            <div className="chart-tooltip-row" key={s.key}>
              <span className="chart-tooltip-dot" style={{ background: s.color }} />
              {s.label}: {hovered[s.key]}
            </div>
          ))}
        </div>
      )}

      <div className="chart-legend">
        {SERIES.map((s) => (
          <span className="chart-legend-item" key={s.key}>
            <span className="chart-legend-swatch" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
