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
    agentName: "Vortex",
  },
};

const SAFETY_RULES = [
  {
    key: "privacy",
    label: "Privacidad de datos",
    desc: "Nunca leer en voz alta DNI/NIE, teléfono, fecha de nacimiento ni datos sensibles.",
  },
  {
    key: "noMedicalAdvice",
    label: "Sin consejo médico",
    desc: "El agente no diagnostica ni recomienda tratamientos; deriva a triaje/escalado.",
  },
  {
    key: "noFabrication",
    label: "No inventar datos",
    desc: "Nunca inventar pacientes, médicos, slots, precios ni disponibilidad.",
  },
  {
    key: "antiInjection",
    label: "Protección anti-inyección",
    desc: "Validación estricta de entradas y sanitización de prompts del usuario.",
  },
  {
    key: "consent",
    label: "Consentimiento antes de confirmar",
    desc: "Confirmación explícita del paciente antes de cualquier acción con efectos reales.",
  },
  {
    key: "emergencyEscalation",
    label: "Escalado de emergencias reales",
    desc: "Síntomas de riesgo vital derivan inmediatamente a humano/servicios de urgencia.",
  },
];

const PERMISSIONS_CONFIG = [
  {
    key: "canBook",
    label: "Reservar citas",
    desc: "Permite crear citas nuevas sin intervención humana adicional.",
  },
  {
    key: "canReschedule",
    label: "Reprogramar citas",
    desc: "Permite mover citas existentes a otro horario/día.",
  },
  {
    key: "canCancel",
    label: "Cancelar citas",
    desc: "Permite anular citas existentes por teléfono.",
  },
  {
    key: "canRegister",
    label: "Registrar pacientes nuevos",
    desc: "Permite crear fichas de pacientes que no existen en el directorio.",
  },
  {
    key: "canInfo",
    label: "Dar información de clínica",
    desc: "Horarios, sedes, especialidades, requisitos, etc.",
  },
  {
    key: "canEscalate",
    label: "Escalar emergencias médicas",
    desc: "Derivar a humano/servicios de urgencia ante síntomas de riesgo vital.",
  },
];

const LEAD_DAYS_HELP =
  "1 = la primera cita disponible es mañana. 0 solo si el reto permite same-day (hoy no).";

const ID_FIELDS_HELP =
  "Para pacientes existentes: 1 dato (nombre) busca y, si hay ambigüedad, pide un segundo. " +
  "Con 2 datos, exige dos campos independientes (nombre, DNI/NIE, teléfono, fecha de nacimiento) " +
  "antes de confiar la identidad. El alta de paciente nuevo siempre pide: nombre completo con dos apellidos, " +
  "DNI/NIE, fecha de nacimiento, email, aseguradora; teléfono de la línea si está disponible.";

const CAP_HELP =
  "Límite impuesto por la plataforma; no se puede cambiar desde Vortex.";

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
        : "«¡Tenemos una cita genial para usted! ¿Le encaja? 😊»",
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
        subtitle="Estos controles definen qué puede decidir Vortex por sí solo, cómo se identifica a los pacientes y cómo suena el agente. Los cambios aplican a llamadas nuevas."
        action={
          <>
            <Button variant="secondary" onClick={() => setShowDefaultConfirm(true)} disabled={!hasChanges && deepEqual(settings, DEFAULTS)}>
              Set as default
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
        {/* 1. Permisos del agente + Safety rules */}
        <Card padding="lg" className="settings-group">
          <div className="settings-group-head">
            <h3>Permisos del agente</h3>
            <p>Activa o desactiva qué capacidades tiene el agente. Si una está desactivada, no se expone la tool correspondiente y el agente responde con NO_ACTION y motivo válido.</p>
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
          <div className="settings-divider" />
          <div className="settings-group-head">
            <h3>Safety rules <span className="settings-badge">No editables</span></h3>
            <p>Reglas de seguridad duras que no pueden desactivarse. Se muestran para transparencia.</p>
          </div>
          <div className="settings-rows settings-safety">
            {SAFETY_RULES.map((r) => (
              <div className="settings-row" key={r.key}>
                <div>
                  <span className="settings-row-label">{r.label} <span className="settings-lock" title="No editable">🔒</span></span>
                  <span className="settings-row-desc">{r.desc}</span>
                </div>
                <Switch
                  checked={true}
                  onChange={() => {}}
                  disabled={true}
                  label={r.label}
                />
              </div>
            ))}
          </div>
        </Card>

        {/* 2. Antelación mínima */}
        <Card padding="lg" className="settings-group">
          <div className="settings-group-head">
            <h3>Antelación mínima para reservar</h3>
            <p>{LEAD_DAYS_HELP}</p>
          </div>
          <div className="settings-rows">
            <div className="settings-row settings-row-stepper">
              <div>
                <span className="settings-row-label">Mínimo días de antelación</span>
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
          </div>
        </Card>

        {/* 3. Cantidad de identificación */}
        <Card padding="lg" className="settings-group">
          <div className="settings-group-head">
            <h3>Cantidad de identificación</h3>
            <p>{ID_FIELDS_HELP}</p>
          </div>
          <div className="settings-rows">
            <div className="settings-row settings-row-segmented">
              <div>
                <span className="settings-row-label">Campos requeridos para pacientes existentes</span>
                <span className="settings-row-desc">{ID_FIELDS_HELP}</span>
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

        {/* 4. Límite de duración de llamada */}
        <Card padding="lg" className="settings-group">
          <div className="settings-group-head">
            <h3>Límite de duración de llamada</h3>
            <p>{CAP_HELP}</p>
          </div>
          <div className="settings-rows">
            <div className="settings-row settings-row-cap">
              <div>
                <span className="settings-row-label">Call time cap</span>
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

        {/* 5. Personalización del agente (roscas) */}
        <Card padding="lg" className="settings-group settings-group-wide">
          <div className="settings-group-head">
            <h3>Personalización del agente</h3>
            <p>Ajusta cómo suena y se presenta el agente. Los valores son una guía; el comportamiento final depende del modelo.</p>
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
            <div className="ui-knob settings-name-knob">
              <div className="ui-knob-label">Nombre del agente</div>
              <input
                type="text"
                className="ui-select ui-name-input"
                value={settings.personalization.agentName}
                onChange={(e) => handlePersonalizationChange("agentName", e.target.value)}
                placeholder="Nombre del agente"
              />
              <div className="ui-knob-preview">
                «Hola, soy {settings.personalization.agentName}. ¿En qué le ayudo?»
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
              <p>Esto restablecerá <strong>todos</strong> los controles a los valores por defecto del sistema:</p>
              <ul>
                <li>Todos los permisos: <strong>ON</strong></li>
                <li>Antelación mínima: <strong>1 día</strong></li>
                <li>Identificación: <strong>1 dato</strong> (segundo solo si ambigüedad)</li>
                <li>Tono / Amabilidad / Ritmo: <strong>punto medio (50)</strong></li>
                <li>Voz: <strong>Mujer</strong></li>
                <li>Nombre del agente: <strong>Vortex</strong></li>
              </ul>
              <p className="ui-modal-warning">Las Safety rules no se modifican.</p>
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