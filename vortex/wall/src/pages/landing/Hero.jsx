import "./hero.css";

// Two-column hero, sized to fill almost the whole viewport: Vorty and the
// text column share one centered row, vertically centered on each other. The
// text column holds the three stacked pieces — headline, copy and the CTA that
// enters the Clinic View — all left-aligned under one another.
export default function Hero({ onEnter }) {
  return (
    <section className="landing-hero">
      <div className="landing-hero-content">
        <div className="landing-hero-row">
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
              <span className="landing-hero-hi">Hi,</span> <span className="landing-hero-imvorty">I'm Vorty.</span>
            </h1>
            <p>
              I answer your clinic's calls — book, reschedule, cancel. Real slots, straight
              from the schedule. No guessing.
            </p>
            <button type="button" className="landing-hero-cta" onClick={onEnter}>
              <span>Get to know me</span>
              <svg viewBox="0 0 20 32" width="20" height="32" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 4l12 12-12 12" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
