import { useHeroScroll } from "./useHeroScroll";
import "./hero.css";

// The landing page is deliberately not another light, calm app screen —
// it's the introduction, so it gets a bolder, darker treatment that hands
// off into the app's real palette as the user scrolls into the explainer.
export default function Hero() {
  const { ref, progress } = useHeroScroll();

  const scale = 1 - progress * 0.55;
  const translateY = progress * -70;
  const copyOpacity = Math.max(0, 1 - progress * 2.4);
  const avatarOpacity = Math.max(0.12, 1 - progress * 0.7);

  return (
    <section className="landing-hero" ref={ref}>
      <div className="landing-hero-inner">
        <div
          className="landing-hero-avatar-wrap"
          style={{ transform: `translateY(${translateY}px) scale(${scale})`, opacity: avatarOpacity }}
        >
          <div className="landing-hero-avatar">
            <span className="landing-hero-avatar-ring r1" />
            <span className="landing-hero-avatar-ring r2" />
            <span className="landing-hero-avatar-glow" />
            {/* Served straight off disk by the backend — see
                vortex/observability/live.py:wall_avatar2d — not bundled,
                so swapping the file needs no rebuild. */}
            <img className="landing-hero-avatar-img" src="/wall/avatar2d" alt="Vorty, el agente de voz de Vortex" />
          </div>
        </div>

        <div className="landing-hero-copy" style={{ opacity: copyOpacity }}>
          <span className="landing-hero-kicker">Vortex</span>
          <h1>
            Contesta el teléfono
            <br />
            antes de que suene dos veces.
          </h1>
          <p>
            Un agente de voz que identifica al paciente, consulta la agenda de la clínica
            y decide: reservar, registrar, cambiar, cancelar o escalar.
          </p>
        </div>

        <div className="landing-scroll-cue" style={{ opacity: copyOpacity }}>
          <span>Desliza para descubrir cómo funciona</span>
          <span className="landing-scroll-cue-arrow">↓</span>
        </div>
      </div>
    </section>
  );
}
