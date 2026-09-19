import Hero from "./Hero";
import Explainer from "./Explainer";
import "./landing.css";

// The landing page is not part of the Clinic View's navigation — it's a
// one-time introduction, reached only at "/". See AppRouter.jsx.
export default function Landing() {
  return (
    <div className="landing-root">
      <Hero />
      <Explainer />
    </div>
  );
}
