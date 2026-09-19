import { useState } from "react";
import Card from "../../../components/ui/Card";
import Pills from "../../../components/ui/Pills";
import "./settings.css";

const PERMISSIONS = [
  { key: "canBook", label: "Reservar citas" },
  { key: "canReschedule", label: "Reprogramar" },
  { key: "canCancel", label: "Cancelar" },
  { key: "canRegister", label: "Registrar paciente" },
  { key: "canInfo", label: "Información" },
  { key: "canEscalate", label: "Escalar urgencias" },
];

const PERM_DEFAULTS = Object.fromEntries(PERMISSIONS.map((p) => [p.key, true]));
const PERM_KEY = "vortex.clinic.permissions";

function loadPerms() {
  try {
    const raw = JSON.parse(localStorage.getItem(PERM_KEY) || "null");
    if (raw && typeof raw === "object") return { ...PERM_DEFAULTS, ...raw };
  } catch {
    /* keep defaults */
  }
  return { ...PERM_DEFAULTS };
}

export default function PermissionsCard() {
  const [perms, setPerms] = useState(loadPerms);

  const setPerm = (key, allowed) => {
    setPerms((prev) => {
      const next = { ...prev, [key]: allowed };
      localStorage.setItem(PERM_KEY, JSON.stringify(next));
      return next;
    });
  };

  return (
    <Card padding="lg" className="agent-panel">
      <section className="agent-block">
        <h3>Qué puede hacer</h3>
        <div className="agent-perm-grid">
          {PERMISSIONS.map((p) => (
            <div className="agent-perm-item" key={p.key}>
              <span>{p.label}</span>
              <Pills
                name={p.label}
                value={perms[p.key]}
                options={[
                  { value: false, label: "No" },
                  { value: true, label: "Sí" },
                ]}
                onChange={(value) => setPerm(p.key, value)}
              />
            </div>
          ))}
        </div>
      </section>
    </Card>
  );
}
