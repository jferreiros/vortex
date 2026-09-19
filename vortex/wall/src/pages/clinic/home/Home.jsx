import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import StatTile from "../../../components/ui/StatTile";
import Placeholder from "../../../components/ui/Placeholder";
import "./home.css";

// Placeholder overview numbers — illustrative only, not wired to real
// call-log aggregation yet. Replace with a real stats endpoint later; the
// StatTile/Card layout below does not need to change when that happens.
const STATS = [
  { label: "Llamadas hoy", value: 47, trend: 12 },
  { label: "Resueltas por el agente", value: 81, unit: "%", trend: 4 },
  { label: "Escaladas a un médico", value: 6, unit: "%", trend: -2, invert: true },
  { label: "Duración media", value: "1:42", trend: -8, invert: true },
];

export default function Home() {
  return (
    <div className="home-page">
      <SectionHeader
        eyebrow="Resumen"
        title="Hola de nuevo"
        subtitle="Esto es lo que ha hecho el agente hoy en Clínica Arenal."
      />

      <Card padding="lg" className="home-stats">
        {STATS.map((s) => (
          <StatTile key={s.label} {...s} />
        ))}
      </Card>

      <div className="home-grid">
        <Card padding="lg" className="home-grid-main">
          <SectionHeader eyebrow="Actividad" title="Volumen de llamadas por hora" />
          {/* PLACEHOLDER: future analytics visualization — hourly call volume chart */}
          <Placeholder kind="chart" ratio="16/7" label="Gráfico de volumen por hora (próximamente)" />
        </Card>

        <Card padding="lg" className="home-grid-side">
          <SectionHeader eyebrow="En vivo" title="Últimas decisiones" />
          <div className="home-decision-list">
            {["Cita reservada", "Escalada · síntoma no cubierto", "Sin acción · fuera de horario"].map((label, i) => (
              <div className="home-decision-row" key={i}>
                <span className="home-decision-dot" />
                <span>{label}</span>
                <span className="home-decision-time">hace {(i + 1) * 6} min</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card padding="lg">
        <SectionHeader eyebrow="Tendencia" title="Últimos 7 días" subtitle="Llamadas totales frente a resueltas por el agente." />
        {/* PLACEHOLDER: future analytics visualization — 7-day trend line */}
        <Placeholder kind="chart" ratio="21/6" label="Gráfico de tendencia semanal (próximamente)" />
      </Card>
    </div>
  );
}
