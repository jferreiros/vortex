import { useState, useEffect, useCallback } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import "./settings.css";

const DEFAULTS = {
  minimumBookingLeadHours: 24,
  patientIdentificationFieldsRequired: 1,
  callTimeCapMinutes: 3,
};

const LEAD_OPTIONS_HOURS = [2, 3, 4, 5, 6, 7, 8, 12, 24, 48, 72, 96];

function leadLabel(hours) {
  return hours < 24 ? `${hours} h` : `${hours / 24} ${hours === 24 ? "día" : "días"}`;
}

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function fromApi(json) {
  if (!json || typeof json !== "object") return DEFAULTS;
  return {
    minimumBookingLeadHours: json.minimumBookingLeadHours ?? DEFAULTS.minimumBookingLeadHours,
    patientIdentificationFieldsRequired:
      json.patientIdentificationFieldsRequired ?? DEFAULTS.patientIdentificationFieldsRequired,
    callTimeCapMinutes: json.callTimeCapMinutes ?? DEFAULTS.callTimeCapMinutes,
  };
}

export default function Settings() {
  const [settings, setSettings] = useState(DEFAULTS);
  const [savedSettings, setSavedSettings] = useState(DEFAULTS);
  const [saveStatus, setSaveStatus] = useState(null);
  const [showDefaultConfirm, setShowDefaultConfirm] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/wall/clinic-settings")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((json) => {
        if (cancelled) return;
        const next = fromApi(json);
        setSettings(next);
        setSavedSettings(next);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const persist = async (next) => {
    const response = await fetch("/api/wall/clinic-settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(next),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return fromApi(await response.json());
  };

  const hasChanges = !deepEqual(settings, savedSettings);

  const updateSetting = useCallback((path, value) => {
    setSettings((prev) => {
      const next = JSON.parse(JSON.stringify(prev));
      path.split(".").reduce((o, k, i, arr) => {
        if (i === arr.length - 1) o[k] = value;
        return o[k];
      }, next);
      return next;
    });
    setSaveStatus(null);
  }, []);

  const handleLeadHoursChange = (delta) => {
    const i = LEAD_OPTIONS_HOURS.indexOf(settings.minimumBookingLeadHours);
    const next = Math.max(0, Math.min(LEAD_OPTIONS_HOURS.length - 1, i + delta));
    updateSetting("minimumBookingLeadHours", LEAD_OPTIONS_HOURS[next]);
  };

  const handleIdFieldsChange = (value) => {
    updateSetting("patientIdentificationFieldsRequired", Math.max(1, Math.min(4, value)));
  };

  const handleSave = async () => {
    try {
      const saved = await persist(settings);
      setSettings(saved);
      setSavedSettings(saved);
      setSaveStatus("saved");
    } catch {
      setSaveStatus(null);
    }
    setTimeout(() => setSaveStatus(null), 3000);
  };

  const handleSetDefault = async () => {
    try {
      const saved = await persist(DEFAULTS);
      setSettings(saved);
      setSavedSettings(saved);
      setSaveStatus("defaulted");
    } catch {
      setSettings(DEFAULTS);
      setSaveStatus("defaulted");
    }
    setTimeout(() => setSaveStatus(null), 3000);
  };

  useEffect(() => {
    const onLeave = (e) => {
      if (!hasChanges) return;
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onLeave);
    return () => window.removeEventListener("beforeunload", onLeave);
  }, [hasChanges]);

  return (
    <div className="settings-page">
      <SectionHeader
        eyebrow="Ajustes"
        title="Llamadas"
        subtitle="Reglas de la clínica. Quién atiende, cómo suena y qué puede hacer está en IA."
        action={
          <>
            <Button
              variant="secondary"
              onClick={() => setShowDefaultConfirm(true)}
              disabled={!hasChanges && deepEqual(settings, DEFAULTS)}
            >
              Por defecto
            </Button>
            <Button variant="primary" onClick={handleSave} disabled={!hasChanges}>
              {hasChanges ? "Guardar cambios" : "Sin cambios"}
            </Button>
          </>
        }
      />

      {saveStatus === "saved" && <div className="settings-toast saved">Guardado</div>}
      {saveStatus === "defaulted" && <div className="settings-toast defaulted">Valores por defecto restaurados</div>}

      <div className="settings-groups">
        <div className="settings-pair">
          <Card padding="lg" className="settings-group">
            <div className="settings-group-head">
              <h3>Reserva</h3>
              <p>Antelación y tope de la llamada.</p>
            </div>
            <div className="settings-rows">
              <div className="settings-row settings-row-stepper">
                <div>
                  <span className="settings-row-label">Antelación mínima</span>
                  <span className="settings-row-desc">Tiempo mínimo entre la llamada y la cita.</span>
                </div>
                <div className="settings-stepper">
                  <button
                    className="ui-stepper-btn"
                    onClick={() => handleLeadHoursChange(-1)}
                    disabled={settings.minimumBookingLeadHours <= LEAD_OPTIONS_HOURS[0]}
                    aria-label="Decrementar"
                  >
                    −
                  </button>
                  <input type="text" className="ui-stepper-input" value={leadLabel(settings.minimumBookingLeadHours)} readOnly />
                  <button
                    className="ui-stepper-btn"
                    onClick={() => handleLeadHoursChange(1)}
                    disabled={settings.minimumBookingLeadHours >= LEAD_OPTIONS_HOURS[LEAD_OPTIONS_HOURS.length - 1]}
                    aria-label="Incrementar"
                  >
                    +
                  </button>
                </div>
              </div>
              <div className="settings-row settings-row-cap">
                <div>
                  <span className="settings-row-label">Duración máx.</span>
                  <span className="settings-row-desc">Fijado por la plataforma.</span>
                </div>
                <div className="settings-cap-display">
                  <input type="text" value={`${settings.callTimeCapMinutes} min`} readOnly disabled className="ui-cap-input" />
                </div>
              </div>
            </div>
          </Card>

          <Card padding="lg" className="settings-group">
            <div className="settings-group-head">
              <h3>Identificación</h3>
              <p>Datos que debe confirmar un paciente existente (nombre, DNI, teléfono o fecha de nacimiento).</p>
            </div>
            <div className="settings-rows">
              <div className="settings-row settings-row-stepper">
                <div>
                  <span className="settings-row-label">Campos requeridos</span>
                </div>
                <div className="settings-stepper">
                  <button
                    className="ui-stepper-btn"
                    onClick={() => handleIdFieldsChange(settings.patientIdentificationFieldsRequired - 1)}
                    disabled={settings.patientIdentificationFieldsRequired <= 1}
                    aria-label="Decrementar"
                  >
                    −
                  </button>
                  <input type="number" className="ui-stepper-input" value={settings.patientIdentificationFieldsRequired} min={1} max={4} readOnly />
                  <button
                    className="ui-stepper-btn"
                    onClick={() => handleIdFieldsChange(settings.patientIdentificationFieldsRequired + 1)}
                    disabled={settings.patientIdentificationFieldsRequired >= 4}
                    aria-label="Incrementar"
                  >
                    +
                  </button>
                  <span className="settings-stepper-unit">datos</span>
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>

      {showDefaultConfirm && (
        <div className="ui-modal-overlay" onClick={() => setShowDefaultConfirm(false)}>
          <div className="ui-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ui-modal-head">
              <h3>Restablecer valores por defecto</h3>
              <button className="ui-modal-close" onClick={() => setShowDefaultConfirm(false)}>
                ✕
              </button>
            </div>
            <div className="ui-modal-body">
              <p>Esto restablecerá los ajustes de llamada:</p>
              <ul>
                <li>
                  Antelación mínima: <strong>1 día</strong>
                </li>
                <li>
                  Identificación: <strong>1 dato</strong>
                </li>
              </ul>
            </div>
            <div className="ui-modal-actions">
              <Button variant="ghost" onClick={() => setShowDefaultConfirm(false)}>
                Cancelar
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  handleSetDefault();
                  setShowDefaultConfirm(false);
                }}
              >
                Restablecer
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
