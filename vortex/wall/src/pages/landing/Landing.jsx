import Hero from "./Hero";
import Explainer from "./Explainer";
import { useCrossfadeScroll } from "./useCrossfadeScroll";
import "./landing.css";

// The landing page is not part of the Clinic View's navigation — it's a
// one-time introduction, reached only at "/". See AppRouter.jsx.
export default function Landing() {
  const { veilOpacity, scrollToId } = useCrossfadeScroll();

  return (
    <div className="landing-root">
      <Hero onScrollNext={() => scrollToId("explainer")} />
      <Explainer />
      <div className="landing-scroll-veil" style={{ opacity: veilOpacity }} />
    </div>
  );
}
