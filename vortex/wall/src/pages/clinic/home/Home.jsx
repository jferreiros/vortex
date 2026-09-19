import { useMemo, useState } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import StatTile from "../../../components/ui/StatTile";
import Modal from "../../../components/ui/Modal";
import HourlyStackedChart from "./charts/HourlyStackedChart";
import VolumeTrendChart from "./charts/VolumeTrendChart";
import OccupancyCalendar from "./charts/OccupancyCalendar";
import { SITES, SPECIALTIES, hourlyActionVolume, dailyCallVolume, occupancy, newClientsRegistered } from "./mockData";
import "./home.css";

// PLACEHOLDER DATA — see mockData.js. Every number on this page is a
// deterministic mock; swap the imports above for real endpoints later,
// the layout and chart components don't need to change. "Llamadas hoy" has
// no drill-down button, so it takes the `large` treatment to fill the
// vertical space the others spend on a button.
const STATS = [
  { key: "calls", label: "Llamadas hoy", value: 47, large: true },
  { key: "resolved", label: "Resueltas por el agente", value: 81, unit: "%", button: "Ver desglose" },
  { key: "escalated", label: "Escaladas a un médico", value: 6, unit: "%", button: "Ver motivos" },
  { key: "duration", label: "Duración media", value: "1:42", button: "Ver uso de tiempo" },
];

function OccupancyCard() {
  const [site, setSite] = useState("");
  const [specialty, setSpecialty] = useState("");
  const occ = useMemo(() => occupancy({ site, specialty }), [site, specialty]);

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
              {SITES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select className="ui-select" value={specialty} onChange={(e) => setSpecialty(e.target.value)}>
              <option value="">Todas las especialidades</option>
              {SPECIALTIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        }
      />

      <div className="occupancy-body">
        <div className="occupancy-left">
          <OccupancyCalendar week={occ.week} />
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
          <span className="occupancy-month-kicker">Mes que viene</span>
          <span className="occupancy-month-value">{occ.monthPct}%</span>
          <span className="occupancy-month-label">ocupación media prevista</span>
        </div>
      </div>
    </Card>
  );
}

export default function Home() {
  const hourly = useMemo(() => hourlyActionVolume(), []);
  const daily = useMemo(() => dailyCallVolume(), []);
  const newClients = useMemo(() => newClientsRegistered(), []);
  const [openStat, setOpenStat] = useState(null);
  const activeStat = STATS.find((s) => s.key === openStat) || null;

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

      <Card padding="lg" className="home-stats">
        {STATS.map((s) => (
          <StatTile key={s.key} {...s} onOpenDetail={() => setOpenStat(s.key)} />
        ))}
      </Card>

      <Modal open={Boolean(activeStat)} title={activeStat?.label} onClose={() => setOpenStat(null)} />

      <OccupancyCard />

      <div className="home-grid">
        <Card padding="lg" className="home-grid-main">
          <SectionHeader eyebrow="Actividad" title="Volumen de llamadas por hora" subtitle="Por tipo de acción." />
          <HourlyStackedChart data={hourly} />
        </Card>

        <Card padding="lg" className="home-grid-side">
          <SectionHeader eyebrow="Tendencia" title="Volumen total de llamadas" subtitle="Todos los días con datos." />
          <VolumeTrendChart data={daily} />
        </Card>
      </div>
    </div>
  );
}
