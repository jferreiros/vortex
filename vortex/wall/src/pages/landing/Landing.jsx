import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Hero from "./Hero";
import "./landing.css";

// The landing page is not part of the Clinic View's navigation — it's a
// one-time introduction, reached only at "/". See AppRouter.jsx. There is
// nothing below the hero: "Get to know me" blurs the page out for a beat,
// then navigates into the Clinic View, so the change isn't abrupt.
const LEAVE_MS = 260;

export default function Landing() {
  const navigate = useNavigate();
  const [leaving, setLeaving] = useState(false);

  const enter = () => {
    if (leaving) return;
    setLeaving(true);
    window.setTimeout(() => navigate("/clinic/home"), LEAVE_MS);
  };

  return (
    <div className={`landing-root${leaving ? " landing-root-leaving" : ""}`}>
      <Hero onEnter={enter} />
    </div>
  );
}
