import { useState, useEffect, useCallback, useRef } from "react";
import Card from "../../../components/ui/Card";
import Pills from "../../../components/ui/Pills";
import "./settings.css";

const VOICE_DEFAULTS = { tone: 50, friendliness: 50, speechRate: 50, voice: "female" };

const RATES = [
  { value: 0, label: "Slow", sample: "Of course, take your time telling me the name and the date you prefer, and I'll note it down." },
  { value: 50, label: "Medium", sample: "Perfect, what day works for you for the appointment?" },
  { value: 100, label: "Fast", sample: "Tomorrow at ten, or Thursday at noon?" },
];

const VOICE_SAMPLE = {
  female: "Good morning, Clínica Arenal, this is Lucía speaking. How can I help you?",
  male: "Good morning, Clínica Arenal, this is Mateo speaking. How can I help you?",
};

function nearestRate(n) {
  return RATES.reduce((best, opt) => (Math.abs(opt.value - n) < Math.abs(best - n) ? opt.value : best), RATES[0].value);
}

// Both Try it buttons speak in the voice of the persona the rail has on the
// phone: the server resolves it, so the card never has to know which id that
// is. Activate another receptionist and the next press sounds like her.
export default function AgentCard() {
  const [cfg, setCfg] = useState(VOICE_DEFAULTS);
  const [saved, setSaved] = useState(VOICE_DEFAULTS);
  const [isTrying, setIsTrying] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [toast, setToast] = useState(null);
  const audioRef = useRef(null);
  const saveTimer = useRef(null);

  const setField = useCallback((key, value) => {
    setCfg((prev) => ({ ...prev, [key]: value }));
    setToast(null);
  }, []);

  useEffect(() => {
    fetch("/api/wall/voice-config")
      .then((r) => (r.ok ? r.json() : null))
      .then((next) => {
        if (!next) return;
        const merged = { ...VOICE_DEFAULTS, ...next };
        setCfg(merged);
        setSaved(merged);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (JSON.stringify(cfg) === JSON.stringify(saved)) return;
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      try {
        const r = await fetch("/api/wall/voice-config", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cfg),
        });
        if (!r.ok) throw new Error(`save failed: ${r.status}`);
        const next = { ...VOICE_DEFAULTS, ...(await r.json()) };
        setCfg(next);
        setSaved(next);
      } catch {
        setToast("error");
        setTimeout(() => setToast(null), 3000);
      }
    }, 400);
    return () => clearTimeout(saveTimer.current);
  }, [cfg, saved]);

  const speak = useCallback(
    async (extra) => {
      const r = await fetch("/api/wall/voice-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...cfg, ...extra }),
      });
      if (!r.ok) throw new Error(`preview failed: ${r.status}`);
      const url = URL.createObjectURL(await r.blob());
      audioRef.current?.pause();
      audioRef.current = new Audio(url);
      await audioRef.current.play();
    },
    [cfg],
  );

  const play = async (extra, setBusy) => {
    setBusy(true);
    try {
      await speak(extra);
    } catch {
      setToast("preview");
      setTimeout(() => setToast(null), 3000);
    }
    setBusy(false);
  };

  const preview = () => (isTrying ? null : play(undefined, setIsTrying));
  const test = () => (isTesting ? null : play({ sample: "test" }, setIsTesting));

  const rate = nearestRate(cfg.speechRate);
  const rateSample = RATES.find((opt) => opt.value === rate)?.sample;

  return (
    <Card padding="lg" className="agent-panel">
      {toast === "error" && <div className="settings-toast error">Could not save the voice settings</div>}
      {toast === "preview" && <div className="settings-toast error">Preview unavailable</div>}

      <section className="agent-block">
        <div className="agent-block-head">
          <h3>Voice</h3>
          <button type="button" className="agent-try" onClick={preview} disabled={isTrying}>
            {isTrying ? "…" : "Try it"}
          </button>
        </div>
        <Pills
          name="Voice"
          value={cfg.voice}
          options={[
            { value: "female", label: "Woman" },
            { value: "male", label: "Man" },
          ]}
          onChange={(value) => setField("voice", value)}
        />
        <p className="agent-sample">{VOICE_SAMPLE[cfg.voice]}</p>
      </section>

      <section className="agent-block">
        <div className="agent-block-head">
          <h3>Rate</h3>
          {/* Same preview, and the speed rides in the same payload: this
              button is how you hear what the slider did. */}
          <button type="button" className="agent-try" onClick={test} disabled={isTesting}>
            {isTesting ? "…" : "Try it"}
          </button>
        </div>
        <Pills
          name="Rate"
          value={rate}
          options={RATES}
          onChange={(value) => setField("speechRate", value)}
        />
        <p className="agent-sample">{rateSample}</p>
      </section>
    </Card>
  );
}
