import { useHeroScroll } from "./useHeroScroll";
import "./hero.css";

function scrollToExplainer() {
  document.getElementById("explainer")?.scrollIntoView({ behavior: "smooth" });
}

// Two-column hero, sized to fill almost the whole viewport: Vorty and the
// headline share one centered row (vertically centered on each other —
// the text column has nothing else in it pulling its center off the
// avatar's), and the CTA lives in its own footer strip pinned to the very
// bottom of the section, independent of how tall the headline gets.
export default function Hero() {
  const { ref, progress } = useHeroScroll();
  const fade = Math.max(0, 1 - progress * 2.2);
  const lift = progress * -50;

  return (
    <section className="landing-hero" ref={ref}>
      <div className="landing-hero-content" style={{ opacity: fade }}>
        <div className="landing-hero-row" style={{ transform: `translateY(${lift}px)` }}>
          <div className="landing-hero-avatar-col">
            <div className="landing-hero-avatar">
              {/* Self-contained animated SVG — see
                  vortex/observability/live.py:wall_avatar2d_animated. */}
              <img
                className="landing-hero-avatar-img"
                src="/wall/avatar2d-animated"
                alt="Vorty, el agente de voz de Vortex"
              />
            </div>
          </div>

          <div className="landing-hero-text-col">
            <h1>
              <span className="landing-hero-hi">Hi!</span> <span className="landing-hero-imvorty">I am Vorty</span>
            </h1>
            <p>
              A voice AI agent that answers the inbound scheduling calls for <strong>YOUR</strong> clinic.
            </p>
          </div>
        </div>

        <div className="landing-hero-cta-wrap">
          <button type="button" className="landing-hero-cta" onClick={scrollToExplainer}>
            <span>Get to know me</span>
            <svg viewBox="0 0 24 16" width="24" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M2 2l10 7 10-7" />
              <path d="M2 8l10 7 10-7" opacity="0.5" />
            </svg>
          </button>
        </div>
      </div>
    </section>
  );
}
