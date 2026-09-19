import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { onPageWipe } from "./pageWipe";
import "./pageWipe.css";

// A grey gradient panel that slides in from the left to cover the screen,
// swaps the route underneath while fully covered, then keeps sliding out
// to the right to reveal it. Mounted once at the router root (see
// AppRouter.jsx) so it survives the navigation it triggers.
const COVER_MS = 480;
const HOLD_MS = 120;
const REVEAL_MS = 480;

export default function PageWipeOverlay() {
  const [phase, setPhase] = useState("idle"); // idle | cover | reveal
  const navigate = useNavigate();
  const timers = useRef([]);

  useEffect(() => {
    return onPageWipe((toPath) => {
      timers.current.forEach(clearTimeout);
      timers.current = [];

      setPhase("cover");
      timers.current.push(
        window.setTimeout(() => {
          navigate(toPath);
          setPhase("reveal");
          timers.current.push(window.setTimeout(() => setPhase("idle"), REVEAL_MS));
        }, COVER_MS + HOLD_MS),
      );
    });
  }, [navigate]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  if (phase === "idle") return null;

  return <div className={`page-wipe page-wipe-${phase}`} />;
}
