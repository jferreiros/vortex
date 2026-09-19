import { useEffect, useRef, useState } from "react";

// Tracks how far the user has scrolled through the hero section as a
// 0..1 progress value, read directly off scroll position (rAF-throttled)
// rather than through a spring. For a value that's meant to track the
// scroll bar 1:1 — the avatar shrinking exactly as fast as you scroll — a
// direct mapping reads as more "attached" and fluid than a springed one,
// which would lag behind the finger/wheel. React Spring is used instead,
// deliberately, for the explainer section's own reveal-on-enter animations
// below (see useRevealSpring) where a discrete, eased transition is
// exactly what "arriving" should feel like.
export function useHeroScroll() {
  const ref = useRef(null);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    let raf = null;

    function measure() {
      raf = null;
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const h = rect.height || window.innerHeight;
      const p = Math.min(1, Math.max(0, -rect.top / h));
      setProgress(p);
    }

    function onScroll() {
      if (raf == null) raf = requestAnimationFrame(measure);
    }

    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf != null) cancelAnimationFrame(raf);
    };
  }, []);

  return { ref, progress };
}
