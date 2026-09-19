import { useRef, useState } from "react";
import "./charts.css";

const W = 560;
const H = 200;
const PAD_L = 28;
const PAD_B = 20;
const PAD_T = 12;
const PAD_R = 8;

const DATE_FMT = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short" });

// One line, total call volume, spanning every day the (mock) data has —
// no fixed "last 7 days" window. Single series: no legend box needed, the
// section title already says what's plotted. Hover shows a crosshair +
// tooltip, per the dataviz skill's interaction rules for line charts.
export default function VolumeTrendChart({ data }) {
  const rootRef = useRef(null);
  const [hoverIndex, setHoverIndex] = useState(null);

  const max = Math.max(...data.map((d) => d.total));
  const min = Math.min(...data.map((d) => d.total));
  const plotH = H - PAD_T - PAD_B;
  const plotW = W - PAD_L - PAD_R;
  const span = Math.max(1, max - min);

  const xAt = (i) => PAD_L + (i / (data.length - 1)) * plotW;
  const yAt = (v) => PAD_T + plotH - ((v - min) / span) * plotH;

  const linePath = data.map((d, i) => `${i === 0 ? "M" : "L"}${xAt(i)},${yAt(d.total)}`).join(" ");
  const areaPath = `${linePath} L${xAt(data.length - 1)},${PAD_T + plotH} L${xAt(0)},${PAD_T + plotH} Z`;

  const yTicks = [min, (min + max) / 2, max].map((v) => Math.round(v));

  function handleMove(e) {
    const rect = rootRef.current.getBoundingClientRect();
    const relX = ((e.clientX - rect.left) / rect.width) * W;
    const idx = Math.round(((relX - PAD_L) / plotW) * (data.length - 1));
    setHoverIndex(Math.max(0, Math.min(data.length - 1, idx)));
  }

  const hovered = hoverIndex != null ? data[hoverIndex] : null;
  const labelStep = Math.ceil(data.length / 6);

  return (
    <div className="chart-root" ref={rootRef}>
      <svg
        className="chart-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Volumen total de llamadas por día"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {yTicks.map((t, i) => {
          const y = yAt(t);
          return (
            <g key={i}>
              <line x1={PAD_L} x2={W - PAD_R} y1={y} y2={y} className="chart-gridline" />
              <text x={PAD_L - 6} y={y + 3} textAnchor="end" className="chart-axis-text">
                {t}
              </text>
            </g>
          );
        })}

        <path d={areaPath} fill="var(--series-booking)" opacity="0.1" />
        <path d={linePath} fill="none" stroke="var(--series-booking)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

        {data.map(
          (d, i) =>
            i % labelStep === 0 && (
              <text key={i} x={xAt(i)} y={H - 4} textAnchor="middle" className="chart-axis-text">
                {DATE_FMT.format(d.date)}
              </text>
            ),
        )}

        {hovered && (
          <>
            <line x1={xAt(hoverIndex)} x2={xAt(hoverIndex)} y1={PAD_T} y2={PAD_T + plotH} className="chart-gridline" />
            <circle cx={xAt(hoverIndex)} cy={yAt(hovered.total)} r="5" fill="var(--series-booking)" stroke="#fff" strokeWidth="2" />
          </>
        )}
      </svg>

      {hovered && (
        <div className="chart-tooltip" style={{ left: xAt(hoverIndex) * (rootRef.current?.clientWidth / W || 1), top: yAt(hovered.total) * (rootRef.current?.clientHeight / H || 1) - 10 }}>
          <span className="chart-tooltip-title">{DATE_FMT.format(hovered.date)}</span>
          <div className="chart-tooltip-row">{hovered.total} llamadas</div>
        </div>
      )}
    </div>
  );
}
