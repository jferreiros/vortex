import { useState } from "react";
import Hero from "./Hero";
import Explainer from "./Explainer";
import { useCrossfadeScroll } from "./useCrossfadeScroll";
import "./landing.css";

// The landing page is not part of the Clinic View's navigation — it's a
// one-time introduction, reached only at "/". See AppRouter.jsx.
export default function Landing() {
  const { veilOpacity, scrollToId } = useCrossfadeScroll();
  const [introReady, setIntroReady] = useState(false);

  return (
    <div className="landing-root">
      <Hero onScrollNext={() => scrollToId("explainer", () => setIntroReady(true))} />
      <Explainer play={introReady} />
      <div className="landing-scroll-veil" style={{ opacity: veilOpacity }} />
    </div>
  );
}
