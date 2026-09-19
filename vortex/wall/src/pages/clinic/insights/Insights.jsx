import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import Placeholder from "../../../components/ui/Placeholder";
import "./insights.css";

const RANGES = ["7 días", "30 días", "90 días"];

export default function Insights() {
  return (
    <div className="insights-page">
      <SectionHeader
        eyebrow="Analítica"
        title="Insights"
        subtitle="Patrones de decisión y rendimiento del agente a lo largo del tiempo."
        action={
          <div className="insights-range">
            {RANGES.map((r, i) => (
              <button key={r} className={`insights-range-pill ${i === 0 ? "on" : ""}`} type="button">
                {r}
              </button>
            ))}
          </div>
        }
      />

      <div className="insights-bento">
        <Card padding="lg" className="insights-cell wide">
          <SectionHeader eyebrow="Volumen" title="Llamadas a lo largo del tiempo" />
          {/* PLACEHOLDER: future analytics visualization — call volume trend */}
          <Placeholder kind="chart" ratio="21/7" label="Serie temporal de llamadas (próximamente)" />
        </Card>

        <Card padding="lg" className="insights-cell">
          <SectionHeader eyebrow="Decisiones" title="Reparto de acciones" />
          {/* PLACEHOLDER: future analytics visualization — action breakdown */}
          <Placeholder kind="chart" ratio="1/1" label="Reservada · Registrada · Escalada · Sin acción" />
        </Card>

        <Card padding="lg" className="insights-cell">
          <SectionHeader eyebrow="Escalado" title="Motivos de escalado" />
          {/* PLACEHOLDER: future analytics visualization — escalation reasons */}
          <Placeholder kind="chart" ratio="1/1" label="Top motivos (próximamente)" />
        </Card>

        <Card padding="lg" className="insights-cell wide">
          <SectionHeader eyebrow="Rendimiento" title="Duración media por tipo de llamada" />
          {/* PLACEHOLDER: future analytics visualization — duration by call type */}
          <Placeholder kind="chart" ratio="21/6" label="Comparativa por tipo (próximamente)" />
        </Card>
      </div>
    </div>
  );
}
