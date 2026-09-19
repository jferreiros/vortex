import { useEffect, useRef } from "react";
import { triggerPageWipe } from "../../app/pageWipe";
import "./explainer.css";

// Empty grey canvas save for the intro video. `play` flips once the
// crossfade scroll has fully settled (see useCrossfadeScroll.js) — the
// video only starts once the section is shown entire, never mid-slide.
// When it ends, a page wipe (PageWipeOverlay.jsx) carries us to the
// Clinic View — this replaces the old "Ir a la Clinic View" button.
export default function Explainer({ play }) {
  const videoRef = useRef(null);

  useEffect(() => {
    if (play) videoRef.current?.play();
  }, [play]);

  return (
    <section className="landing-explainer" id="explainer">
      <video
        ref={videoRef}
        className="landing-explainer-video"
        src={`${import.meta.env.BASE_URL}intro_v3.mp4`}
        playsInline
        onEnded={() => triggerPageWipe("/clinic/home")}
      />
    </section>
  );
}
