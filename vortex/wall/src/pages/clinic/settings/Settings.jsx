import { useState, useEffect, useCallback } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import Switch from "../../../components/ui/Switch";
import Button from "../../../components/ui/Button";
import Knob from "../../../components/ui/Knob";
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
  minimumBookingLeadDays: 1,
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
  { key: "canBook", label: "Reservar citas", desc: "Crear citas nuevas." },
  { key: "canReschedule", label: "Reprogramar citas", desc: "Mover citas a otro horario." },
  { key: "canCancel", label: "Cancelar citas", desc: "Anular citas por teléfono." },
  { key: "canRegister", label: "Registrar pacientes", desc: "Dar de alta pacientes nuevos." },
  { key: "canInfo", label: "Información de clínica", desc: "Horarios, sedes y requisitos." },
  { key: "canEscalate", label: "Escalar urgencias", desc: "Derivar a un humano." },
];

const LEAD_DAYS_HELP = "Días mínimos entre la llamada y la cita. 1 = la primera cita es mañana.";

const ID_FIELDS_HELP = "Datos que debe confirmar un paciente existente. Con 1, se pide un segundo solo si hay ambigüedad.";

const CAP_HELP = "Fijado por la plataforma.";

const PERSONALIZATION_CONFIG = [
  {
    key: "tone",
    label: "Tono",
    leftLabel: "Formal",
    rightLabel: "Cercano",
    getPreview: (v) =>
      v <= 33
        ? "«Buenos días, le atiendo desde la clínica. ¿En qué puedo ayudarle?»"
        : v <= 66
        ? "«¡Hola! ¿Qué tal? ¿En qué le echamos una mano hoy?»"
        : "«¡Buenas! Cuénteme, ¿qué necesita?»",
  },
  {
    key: "friendliness",
    label: "Amabilidad",
    leftLabel: "Directo",
    rightLabel: "Muy amable",
    getPreview: (v) =>
      v <= 33
        ? "«Le informo de su cita. ¿Confirma?»"
        : v <= 66
        ? "«Tenemos una cita para usted. ¿Le viene bien confirmarla?»"
        : "«¡Tenemos una cita genial para usted! ¿Le encaja?»",
  },
  {
    key: "speechRate",
    label: "Ritmo de habla",
    leftLabel: "Pausado",
    rightLabel: "Rápido",
    getPreview: (v) =>
      v <= 33
        ? "«Le... voy... a... dar... la... información... despacio.»"
        : v <= 66
        ? "«Le voy a dar la información a ritmo normal.»"
        : "«Le voy a dar la información rapidito para no hacerle esperar.»",
  },
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

  const handleLeadDaysChange = (value) => {
    const clamped = Math.max(0, Math.min(30, value));
    updateSetting("minimumBookingLeadDays", clamped);
  };

  const handleIdFieldsChange = (value) => {
    updateSetting("patientIdentificationFieldsRequired", value);
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
        {/* 1. Permisos del agente */}
        <Card padding="lg" className="settings-group">
          <div className="settings-group-head">
            <h3>Permisos</h3>
            <p>Lo que el agente puede hacer por sí solo.</p>
          </div>
          <div className="settings-rows">
            {PERMISSIONS_CONFIG.map((p) => (
              <div className="settings-row" key={p.key}>
                <div>
                  <span className="settings-row-label">{p.label}</span>
                  <span className="settings-row-desc">{p.desc}</span>
                </div>
                <Switch
                  checked={settings.permissions[p.key]}
                  onChange={(checked) => handlePermissionChange(p.key, checked)}
                  label={p.label}
                />
              </div>
            ))}
          </div>
        </Card>

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
                <span className="settings-row-desc">{LEAD_DAYS_HELP}</span>
              </div>
              <div className="settings-stepper">
                <button
                  className="ui-stepper-btn"
                  onClick={() => handleLeadDaysChange(settings.minimumBookingLeadDays - 1)}
                  disabled={settings.minimumBookingLeadDays <= 0}
                  aria-label="Decrementar"
                >
                  −
                </button>
                <input
                  type="number"
                  className="ui-stepper-input"
                  value={settings.minimumBookingLeadDays}
                  onChange={(e) => handleLeadDaysChange(parseInt(e.target.value) || 0)}
                  min={0}
                  max={30}
                  readOnly
                />
                <button
                  className="ui-stepper-btn"
                  onClick={() => handleLeadDaysChange(settings.minimumBookingLeadDays + 1)}
                  disabled={settings.minimumBookingLeadDays >= 30}
                  aria-label="Incrementar"
                >
                  +
                </button>
                <span className="settings-stepper-unit">días</span>
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
            <div className="settings-row settings-row-segmented">
              <div>
                <span className="settings-row-label">Campos requeridos</span>
              </div>
              <div className="ui-segmented" role="radiogroup" aria-label="Campos de identificación requeridos">
                <label className={`ui-segmented-btn ${settings.patientIdentificationFieldsRequired === 1 ? "active" : ""}`}>
                  <input
                    type="radio"
                    name="idFields"
                    value={1}
                    checked={settings.patientIdentificationFieldsRequired === 1}
                    onChange={() => handleIdFieldsChange(1)}
                  />
                  1 dato
                </label>
                <label className={`ui-segmented-btn ${settings.patientIdentificationFieldsRequired === 2 ? "active" : ""}`}>
                  <input
                    type="radio"
                    name="idFields"
                    value={2}
                    checked={settings.patientIdentificationFieldsRequired === 2}
                    onChange={() => handleIdFieldsChange(2)}
                  />
                  2 datos
                </label>
              </div>
            </div>
          </div>
        </Card>

        {/* 4. Voz del agente (roscas) */}
        <Card padding="lg" className="settings-group settings-group-wide">
          <div className="settings-group-head">
            <h3>Voz del agente</h3>
            <p>Cómo suena el agente.</p>
          </div>
          <div className="settings-knobs">
            {PERSONALIZATION_CONFIG.map((k) => (
              <Knob
                key={k.key}
                label={k.label}
                value={settings.personalization[k.key]}
                min={0}
                max={100}
                step={1}
                leftLabel={k.leftLabel}
                rightLabel={k.rightLabel}
                previewText={k.getPreview(settings.personalization[k.key])}
                onChange={(v) => handlePersonalizationChange(k.key, v)}
              />
            ))}
            <div className="ui-knob settings-voice-knob">
              <div className="ui-knob-label">Voz del agente</div>
              <select
                className="ui-select ui-voice-select"
                value={settings.personalization.voice}
                onChange={(e) => handlePersonalizationChange("voice", e.target.value)}
              >
                {VOICE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              <div className="ui-knob-preview">
                {settings.personalization.voice === "female" ? "Voz femenina seleccionada" : "Voz masculina seleccionada"}
              </div>
            </div>
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