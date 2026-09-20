import { useState, useEffect, useCallback } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import PermissionsCard from "./PermissionsCard";
import "./settings.css";

const DEFAULTS = {
  minimumBookingLeadHours: 24,
  patientIdentificationFieldsRequired: 1,
  callTimeCapMinutes: 3,
};

const LEAD_OPTIONS_HOURS = [2, 3, 4, 5, 6, 7, 8, 12, 24, 48, 72, 96];

function leadLabel(hours) {
  return hours < 24 ? `${hours} h` : `${hours / 24} ${hours === 24 ? "day" : "days"}`;
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
    const submitted = settings;
    try {
      const saved = await persist(submitted);
      setSettings((current) => (deepEqual(current, submitted) ? saved : current));
      setSavedSettings(saved);
      setSaveStatus("saved");
    } catch {
      setSaveStatus("error");
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
      setSaveStatus("error");
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
        title="Call settings"
        subtitle="Clinic rules. Who answers and how they sound is under Customize agent."
        action={
          <>
            <Button
              variant="secondary"
              onClick={() => setShowDefaultConfirm(true)}
              disabled={!hasChanges && deepEqual(settings, DEFAULTS)}
            >
              Default
            </Button>
            <Button variant="primary" onClick={handleSave} disabled={!hasChanges}>
              {hasChanges ? "Save changes" : "No changes"}
            </Button>
          </>
        }
      />

      {saveStatus === "saved" && <div className="settings-toast saved">Saved</div>}
      {saveStatus === "defaulted" && <div className="settings-toast defaulted">Default values restored</div>}
      {saveStatus === "error" && <div className="settings-toast error">Could not save</div>}

      <div className="settings-groups">
        <div className="settings-pair">
          <Card padding="lg" className="settings-group">
            <div className="settings-group-head">
              <h3>Booking</h3>
              <p>Lead time and call cap.</p>
            </div>
            <div className="settings-rows">
              <div className="settings-row settings-row-stepper">
                <div>
                  <span className="settings-row-label">Minimum lead time</span>
                  <span className="settings-row-desc">Minimum time between the call and the appointment.</span>
                </div>
                <div className="settings-stepper">
                  <button
                    className="ui-stepper-btn"
                    onClick={() => handleLeadHoursChange(-1)}
                    disabled={settings.minimumBookingLeadHours <= LEAD_OPTIONS_HOURS[0]}
                    aria-label="Decrease"
                  >
                    −
                  </button>
                  <input type="text" className="ui-stepper-input" value={leadLabel(settings.minimumBookingLeadHours)} readOnly />
                  <button
                    className="ui-stepper-btn"
                    onClick={() => handleLeadHoursChange(1)}
                    disabled={settings.minimumBookingLeadHours >= LEAD_OPTIONS_HOURS[LEAD_OPTIONS_HOURS.length - 1]}
                    aria-label="Increase"
                  >
                    +
                  </button>
                </div>
              </div>
              <div className="settings-row settings-row-cap">
                <div>
                  <span className="settings-row-label">Max duration</span>
                  <span className="settings-row-desc">Set by the platform.</span>
                </div>
                <div className="settings-cap-display">
                  <input type="text" value={`${settings.callTimeCapMinutes} min`} readOnly disabled className="ui-cap-input" />
                </div>
              </div>
            </div>
          </Card>

          <Card padding="lg" className="settings-group">
            <div className="settings-group-head">
              <h3>Identification</h3>
              <p>Details an existing patient must confirm (name, ID number, phone, or date of birth).</p>
            </div>
            <div className="settings-rows">
              <div className="settings-row settings-row-stepper">
                <div>
                  <span className="settings-row-label">Required fields</span>
                </div>
                <div className="settings-stepper">
                  <button
                    className="ui-stepper-btn"
                    onClick={() => handleIdFieldsChange(settings.patientIdentificationFieldsRequired - 1)}
                    disabled={settings.patientIdentificationFieldsRequired <= 1}
                    aria-label="Decrease"
                  >
                    −
                  </button>
                  <input type="number" className="ui-stepper-input" value={settings.patientIdentificationFieldsRequired} min={1} max={4} readOnly />
                  <button
                    className="ui-stepper-btn"
                    onClick={() => handleIdFieldsChange(settings.patientIdentificationFieldsRequired + 1)}
                    disabled={settings.patientIdentificationFieldsRequired >= 4}
                    aria-label="Increase"
                  >
                    +
                  </button>
                  <span className="settings-stepper-unit">fields</span>
                </div>
              </div>
            </div>
          </Card>
        </div>

        <PermissionsCard />
      </div>

      {showDefaultConfirm && (
        <div className="ui-modal-overlay" onClick={() => setShowDefaultConfirm(false)}>
          <div className="ui-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ui-modal-head">
              <h3>Reset to default values</h3>
              <button className="ui-modal-close" onClick={() => setShowDefaultConfirm(false)}>
                ✕
              </button>
            </div>
            <div className="ui-modal-body">
              <p>This will reset the call settings:</p>
              <ul>
                <li>
                  Minimum lead time: <strong>1 day</strong>
                </li>
                <li>
                  Identification: <strong>1 field</strong>
                </li>
              </ul>
            </div>
            <div className="ui-modal-actions">
              <Button variant="ghost" onClick={() => setShowDefaultConfirm(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  handleSetDefault();
                  setShowDefaultConfirm(false);
                }}
              >
                Reset
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
