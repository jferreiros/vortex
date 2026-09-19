import { useNavigate } from "react-router-dom";
import Reveal from "./Reveal";
import Button from "../../components/ui/Button";
import Placeholder from "../../components/ui/Placeholder";
import "./explainer.css";

const STEPS = [
  {
    title: "Llamada entrante",
    text: "El paciente marca el número de la clínica. Vortex descuelga al instante.",
  },
  {
    title: "Identifica al paciente",
    text: "Confirma quién llama contra el directorio de la clínica, sin adivinar.",
  },
  {
    title: "Consulta agenda y reglas",
    text: "Disponibilidad real, horarios del centro, seguro y tipo de cita.",
  },
  {
    title: "Toma una acción",
    text: "Reserva, registra, cambia, cancela — o escala a una persona si no puede decidir.",
  },
];

export default function Explainer() {
  const navigate = useNavigate();

  return (
    <section className="landing-explainer" id="explainer">
      <div className="landing-explainer-inner">
        <Reveal className="landing-explainer-head">
          <span className="landing-explainer-eyebrow">Cómo funciona</span>
          <h2>Una decisión por llamada, nunca una conjetura.</h2>
          <p>
            Vortex no improvisa. Cada acción que toma viene de datos reales de la clínica —
            nunca de lo que el paciente dice que es cierto.
          </p>
        </Reveal>

        {/* PLACEHOLDER: explanatory diagram — the four steps below are real
            product copy; the connecting visual (illustration, motion path,
            or a more elaborate rendered diagram) is not final. */}
        <Reveal delay={80} className="landing-diagram">
          {STEPS.map((step, i) => (
            <div className="landing-diagram-step" key={step.title}>
              <div className="landing-diagram-node">
                <Placeholder kind="icon" className="landing-diagram-glyph" />
              </div>
              <span className="landing-diagram-index">{String(i + 1).padStart(2, "0")}</span>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
              {i < STEPS.length - 1 && <span className="landing-diagram-connector" />}
            </div>
          ))}
        </Reveal>

        <Reveal delay={160} className="landing-explainer-cta">
          <Button variant="primary" onClick={() => navigate("/clinic/home")}>
            Ir a la Clinic View →
          </Button>
          <span className="landing-explainer-cta-note">Sin registro. Es una demo del panel de la clínica.</span>
        </Reveal>
      </div>
    </section>
  );
}
