import { useState, useEffect, useCallback } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import Switch from "../../../components/ui/Switch";
import Button from "../../../components/ui/Button";
import "./settings.css";

const DEFAULTS = {
  permissions: {
    canBook: true,
    canReschedule: true,
    canCancel: true,
    canRegister: true,
    canInfo: true,
    canEscalate: true,
  },
  minimumBookingLeadHours: 24,
  patientIdentificationFieldsRequired: 1,
  callTimeCapMinutes: 3,
  personalization: {
    tone: 50,
    friendliness: 50,
    speechRate: 50,
    voice: "female",
  },
};

const PERMISSIONS_CONFIG = [
  { key: "canBook", label: "Reservar citas" },
  { key: "canReschedule", label: "Reprogramar citas" },
  { key: "canCancel", label: "Cancelar citas" },
  { key: "canRegister", label: "Registrar paciente nuevo" },
  { key: "canInfo", label: "Información de clínica" },
  { key: "canEscalate", label: "Escalar urgencias" },
];

const LEAD_OPTIONS_HOURS = [2, 3, 4, 5, 6, 7, 8, 12, 24, 48, 72, 96];

function leadLabel(hours) {
  return hours < 24 ? `${hours} h` : `${hours / 24} ${hours === 24 ? "día" : "días"}`;
}

const LEAD_HELP = "Tiempo mínimo entre la llamada y la cita.";

const ID_FIELDS_HELP =
  "Cuántos datos debe confirmar un paciente existente antes de confiar su identidad: nombre, DNI/NIE, teléfono o fecha de nacimiento.";

const CAP_HELP = "Fijado por la plataforma.";

const PERSONALIZATION_CONFIG = [
  { key: "tone", label: "Tono", leftLabel: "Formal", rightLabel: "Cercano" },
  { key: "friendliness", label: "Amabilidad", leftLabel: "Directo", rightLabel: "Muy amable" },
  { key: "speechRate", label: "Ritmo de habla", leftLabel: "Pausado", rightLabel: "Rápido" },
];

const VOICE_OPTIONS = [
  { value: "female", label: "Mujer" },
  { value: "male", label: "Hombre" },
];

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

export default function Settings() {
  const [settings, setSettings] = useState(DEFAULTS);
  const [savedSettings, setSavedSettings] = useState(DEFAULTS);
  const [isSaving, setIsSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState(null);
  const [showDefaultConfirm, setShowDefaultConfirm] = useState(false);

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

  const handlePermissionChange = (key, checked) => {
    updateSetting(`permissions.${key}`, checked);
  };

  const handleLeadHoursChange = (delta) => {
    const i = LEAD_OPTIONS_HOURS.indexOf(settings.minimumBookingLeadHours);
    const next = Math.max(0, Math.min(LEAD_OPTIONS_HOURS.length - 1, i + delta));
    updateSetting("minimumBookingLeadHours", LEAD_OPTIONS_HOURS[next]);
  };

  const handleIdFieldsChange = (value) => {
    const clamped = Math.max(1, Math.min(4, value));
    updateSetting("patientIdentificationFieldsRequired", clamped);
  };

  const handlePersonalizationChange = (key, value) => {
    updateSetting(`personalization.${key}`, value);
  };

  const handleSave = async () => {
    setIsSaving(true);
    setSaveStatus("saving");
    await new Promise((r) => setTimeout(r, 600));
    setSavedSettings(JSON.parse(JSON.stringify(settings)));
    setSaveStatus("saved");
    setIsSaving(false);
    setTimeout(() => setSaveStatus(null), 3000);
  };

  const handleSetDefault = () => {
    setSettings(DEFAULTS);
    setSaveStatus("defaulted");
    setTimeout(() => setSaveStatus(null), 3000);
  };

  const handleBeforeUnload = (e) => {
    if (hasChanges) {
      e.preventDefault();
      e.returnValue = "";
    }
  };

  useEffect(() => {
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasChanges]);

  // TODO: wire to GET /api/wall/settings/agent-rules
  // useEffect(() => { fetch(...).then(setSettings).then(setSavedSettings); }, []);

  // TODO: wire to PUT /api/wall/settings/agent-rules
  // const handleSave = async () => { await fetch(..., { method: 'PUT', body: JSON.stringify(settings) }); ... };

  // TODO: wire to POST /api/wall/settings/agent-rules/defaults
  // const handleSetDefault = async () => { await fetch(..., { method: 'POST' }); setSettings(DEFAULTS); setSavedSettings(DEFAULTS); };

  return (
    <div className="settings-page">
      <SectionHeader
        eyebrow="Configuración"
        title="Reglas del agente"
        subtitle="Qué puede hacer Vortex y cómo suena. Aplica a llamadas nuevas."
        action={
          <>
            <Button variant="secondary" onClick={() => setShowDefaultConfirm(true)} disabled={!hasChanges && deepEqual(settings, DEFAULTS)}>
              Por defecto
            </Button>
            <Button variant="primary" onClick={handleSave} disabled={!hasChanges || isSaving}>
              {isSaving ? "Guardando..." : hasChanges ? "Guardar cambios" : "Sin cambios"}
            </Button>
          </>
        }
      />

      {saveStatus === "saved" && <div className="settings-toast saved">Guardado — aplica a llamadas nuevas</div>}
      {saveStatus === "defaulted" && <div className="settings-toast defaulted">Valores por defecto restaurados</div>}

      <div className="settings-groups">
        {/* 1. Voz del agente */}
        <Card padding="lg" className="settings-group settings-group-top">
          <div className="settings-group-head">
            <h3>Voz del agente</h3>
            <p>Cómo suena el agente.</p>
          </div>
          <div className="settings-rows">
            {PERSONALIZATION_CONFIG.map((k) => (
              <div className="settings-row" key={k.key}>
                <div>
                  <span className="settings-row-label">{k.label}</span>
                </div>
                <div className="settings-slider">
                  <span className="settings-slider-end">{k.leftLabel}</span>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    step={1}
                    value={settings.personalization[k.key]}
                    onChange={(e) => handlePersonalizationChange(k.key, parseInt(e.target.value))}
                    aria-label={k.label}
                  />
                  <span className="settings-slider-end">{k.rightLabel}</span>
                </div>
              </div>
            ))}
            <div className="settings-row">
              <div>
                <span className="settings-row-label">Probar</span>
              </div>
              {/* TODO: wire to a short TTS sample with the current slider values */}
              <Button variant="secondary" onClick={() => {}}>
                ▶ Try
              </Button>
            </div>
            <div className="settings-row">
              <div>
                <span className="settings-row-label">Voz</span>
              </div>
              <select
                className="ui-select"
                value={settings.personalization.voice}
                onChange={(e) => handlePersonalizationChange("voice", e.target.value)}
              >
                {VOICE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
          </div>
        </Card>

        <div className="settings-pair">
        {/* 2. Reserva y duración de llamada */}
        <Card padding="lg" className="settings-group">
          <div className="settings-group-head">
            <h3>Reserva</h3>
            <p>Agenda y duración de la llamada.</p>
          </div>
          <div className="settings-rows">
            <div className="settings-row settings-row-stepper">
              <div>
                <span className="settings-row-label">Antelación mínima</span>
                <span className="settings-row-desc">{LEAD_HELP}</span>
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
                <input
                  type="text"
                  className="ui-stepper-input"
                  value={leadLabel(settings.minimumBookingLeadHours)}
                  readOnly
                />
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
                <span className="settings-row-label">Duración máx. de llamada</span>
                <span className="settings-row-desc">{CAP_HELP}</span>
              </div>
              <div className="settings-cap-display">
                <input
                  type="text"
                  value={`${settings.callTimeCapMinutes} min`}
                  readOnly
                  disabled={true}
                  className="ui-cap-input"
                  title={CAP_HELP}
                />
              </div>
            </div>
          </div>
        </Card>

        {/* 3. Identificación */}
        <Card padding="lg" className="settings-group">
          <div className="settings-group-head">
            <h3>Identificación</h3>
            <p>{ID_FIELDS_HELP}</p>
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
                <input
                  type="number"
                  className="ui-stepper-input"
                  value={settings.patientIdentificationFieldsRequired}
                  onChange={(e) => handleIdFieldsChange(parseInt(e.target.value) || 1)}
                  min={1}
                  max={4}
                  readOnly
                />
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

        {/* 4. Permisos del agente */}
        <Card padding="lg" className="settings-group">
          <div className="settings-group-head">
            <h3>Permisos</h3>
            <p>Lo que el agente puede hacer por sí solo.</p>
          </div>
          <div className="settings-perms">
            {PERMISSIONS_CONFIG.map((p) => (
              <div className="settings-perm" key={p.key}>
                <span className="settings-row-label">{p.label}</span>
                <Switch
                  checked={settings.permissions[p.key]}
                  onChange={(checked) => handlePermissionChange(p.key, checked)}
                  label={p.label}
                />
              </div>
            ))}
          </div>
        </Card>
      </div>

      {showDefaultConfirm && (
        <div className="ui-modal-overlay" onClick={() => setShowDefaultConfirm(false)}>
          <div className="ui-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ui-modal-head">
              <h3>Restablecer valores por defecto</h3>
              <button className="ui-modal-close" onClick={() => setShowDefaultConfirm(false)}>✕</button>
            </div>
            <div className="ui-modal-body">
              <p>Esto restablecerá todos los controles a los valores por defecto:</p>
              <ul>
                <li>Permisos: <strong>ON</strong></li>
                <li>Antelación mínima: <strong>1 día</strong></li>
                <li>Identificación: <strong>1 dato</strong></li>
                <li>Tono / Amabilidad / Ritmo: <strong>50</strong></li>
                <li>Voz: <strong>Mujer</strong></li>
              </ul>
            </div>
            <div className="ui-modal-actions">
              <Button variant="ghost" onClick={() => setShowDefaultConfirm(false)}>Cancelar</Button>
              <Button variant="primary" onClick={() => { handleSetDefault(); setShowDefaultConfirm(false); }}>Restablecer</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}