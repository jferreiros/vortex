import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import Switch from "../../../components/ui/Switch";
import Button from "../../../components/ui/Button";
import "./settings.css";

// Placeholder groups — the real set of controllable decisions/thresholds
// isn't defined yet. This establishes the section/row/description shape
// so wiring real settings later is a data change, not a layout change.
const GROUPS = [
  {
    title: "Reglas de decisión",
    description: "Qué puede hacer el agente sin intervención humana.",
    rows: [
      { label: "Reservar citas automáticamente", desc: "Sin confirmación de un miembro del equipo.", defaultChecked: true },
      { label: "Registrar pacientes nuevos", desc: "Crear una ficha nueva cuando no hay coincidencia.", defaultChecked: true },
      { label: "Permitir cancelaciones por teléfono", desc: "Sin verificación adicional de identidad.", defaultChecked: false },
    ],
  },
  {
    title: "Escalado",
    description: "Cuándo el agente debe pasar la llamada a una persona.",
    rows: [
      { label: "Escalar síntomas no cubiertos por triaje", desc: "Cualquier síntoma fuera de la lista conocida.", defaultChecked: true },
      { label: "Notificar al equipo por Discord al escalar", desc: "Aviso inmediato en el canal del equipo.", defaultChecked: true },
      { label: "Escalar tras dos silencios seguidos", desc: "El paciente no responde dos veces seguidas.", defaultChecked: false },
    ],
  },
  {
    title: "Idiomas",
    description: "En qué idiomas puede atender el agente la llamada.",
    rows: [
      { label: "Español", desc: "Idioma por defecto.", defaultChecked: true },
      { label: "Català", desc: "", defaultChecked: true },
      { label: "Euskara", desc: "", defaultChecked: false },
      { label: "Galego", desc: "", defaultChecked: false },
    ],
  },
];

export default function Settings() {
  return (
    <div className="settings-page">
      <SectionHeader
        eyebrow="Configuración"
        title="Comportamiento del agente"
        subtitle="Estos controles definen qué puede decidir Vortex por sí solo y cuándo debe avisar a alguien."
        action={<Button variant="primary">Guardar cambios</Button>}
      />

      <div className="settings-groups">
        {GROUPS.map((group) => (
          <Card padding="lg" key={group.title} className="settings-group">
            <div className="settings-group-head">
              <h3>{group.title}</h3>
              <p>{group.description}</p>
            </div>
            <div className="settings-rows">
              {group.rows.map((row) => (
                <div className="settings-row" key={row.label}>
                  <div>
                    <span className="settings-row-label">{row.label}</span>
                    {row.desc && <span className="settings-row-desc">{row.desc}</span>}
                  </div>
                  <Switch defaultChecked={row.defaultChecked} label={row.label} />
                </div>
              ))}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
