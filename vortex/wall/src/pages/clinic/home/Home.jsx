import { useMemo, useState } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import StatTile from "../../../components/ui/StatTile";
import Modal from "../../../components/ui/Modal";
import Placeholder from "../../../components/ui/Placeholder";
import HourlyStackedChart from "./charts/HourlyStackedChart";
import VolumeTrendChart from "./charts/VolumeTrendChart";
import OccupancyCalendar from "./charts/OccupancyCalendar";
import PersonalitiesRail from "./PersonalitiesRail";
import { useHomeOverview, useOccupancy, withDate, formatDuration } from "./useHomeData";
import "./home.css";

// Every number on this page is read from synthetic-data/ through
// /api/wall/home-overview and /api/wall/occupancy (see
// vortex/observability/home_overview.py) — nothing here is generated
// client-side. "Llamadas hoy" has no drill-down button, so it takes the
// `large` treatment to fill the vertical space the others spend on a button.
function statsFor(overview) {
  const s = overview?.stats;
  return [
    { key: "calls", label: "Llamadas hoy", value: s ? s.calls_today : "—", large: true },
    {
      key: "resolved",
      label: "Resueltas por el agente",
      value: s?.resolved_pct != null ? s.resolved_pct : "—",
      unit: s?.resolved_pct != null ? "%" : "",
      button: "Ver desglose",
    },
    {
      key: "escalated",
      label: "Escaladas a un médico",
      value: s?.escalated_pct != null ? s.escalated_pct : "—",
      unit: s?.escalated_pct != null ? "%" : "",
      button: "Ver motivos",
    },
    { key: "duration", label: "Duración media", value: formatDuration(s?.median_duration_s), button: "Ver uso de tiempo" },
  ];
}

function OccupancyCard({ sites, specialties }) {
  const [site, setSite] = useState("");
  const [specialty, setSpecialty] = useState("");
  const occ = useOccupancy({ site, specialty });
  const week = useMemo(() => withDate(occ?.week), [occ]);

  return (
    <Card padding="lg">
      <SectionHeader
        eyebrow="Agenda"
        title="Tasa de ocupación"
        subtitle="Huecos ocupados frente a disponibles, por centro y especialidad."
        action={
          <div className="occupancy-filters">
            <select className="ui-select" value={site} onChange={(e) => setSite(e.target.value)}>
              <option value="">Todos los centros</option>
              {sites.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select className="ui-select" value={specialty} onChange={(e) => setSpecialty(e.target.value)}>
              <option value="">Todas las especialidades</option>
              {specialties.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        }
      />

      {!occ ? (
        <Placeholder kind="chart" ratio="21/9" label="Calculando ocupación…" />
      ) : (
        <div className="occupancy-body">
          <div className="occupancy-left">
            <OccupancyCalendar week={week} />
            <div className="occupancy-headline">
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 5v14M5 12l7 7 7-7" />
              </svg>
              <span className="occupancy-headline-value">{occ.weekAvgPct}%</span>
              <span className="occupancy-headline-label">de ocupación media esta semana</span>
            </div>
          </div>

          <div className="occupancy-divider" />

          <div className="occupancy-right">
            <span className="occupancy-month-kicker">Próximos 30 días</span>
            <span className="occupancy-month-value">{occ.monthPct}%</span>
            <span className="occupancy-month-label">ocupación media prevista</span>
          </div>
        </div>
      )}
    </Card>
  );
}

export default function Home() {
  const overview = useHomeOverview();
  const stats = useMemo(() => statsFor(overview), [overview]);
  const daily = useMemo(() => withDate(overview?.daily_call_volume), [overview]);
  const hourly = overview?.hourly_action_volume ?? [];
  const newClients = overview?.stats?.new_patients_registered ?? 0;
  const sites = overview?.sites ?? [];
  const specialties = overview?.specialties ?? [];
  const [openStat, setOpenStat] = useState(null);
  const activeStat = stats.find((s) => s.key === openStat) || null;

  return (
    <div className="home-page">
      <SectionHeader
        eyebrow="Resumen"
        title="Hola de nuevo"
        subtitle="Esto es lo que ha hecho el agente hoy en Clínica Arenal."
        action={
          <div className="home-header-stat">
            <span className="home-header-stat-value">+{newClients}</span>
            <span className="home-header-stat-label">Nuevos pacientes registrados</span>
          </div>
        }
      />

      <PersonalitiesRail />

      <Card padding="lg" className="home-stats">
        {stats.map((s) => (
          <StatTile key={s.key} {...s} onOpenDetail={() => setOpenStat(s.key)} />
        ))}
      </Card>

      <Modal open={Boolean(activeStat)} title={activeStat?.label} onClose={() => setOpenStat(null)} />

      <OccupancyCard sites={sites} specialties={specialties} />

      <div className="home-grid">
        <Card padding="lg" className="home-grid-main">
          <SectionHeader eyebrow="Actividad" title="Volumen de llamadas por hora" subtitle="Última semana, por tipo de acción." />
          {overview ? <HourlyStackedChart data={hourly} /> : <Placeholder kind="chart" ratio="21/8" label="Calculando volumen por hora…" />}
        </Card>

        <Card padding="lg" className="home-grid-side">
          <SectionHeader eyebrow="Tendencia" title="Volumen total de llamadas" subtitle="Todos los días con datos." />
          {daily.length > 1 ? (
            <VolumeTrendChart data={daily} />
          ) : (
            <Placeholder kind="chart" ratio="21/8" label="Calculando tendencia diaria…" />
          )}
        </Card>
      </div>
    </div>
  );
}
