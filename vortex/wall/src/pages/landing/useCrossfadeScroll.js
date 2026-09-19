import { useCallback, useRef, useState } from "react";

// Eases the hand-off between hero and explainer: rather than the browser's
// native scrollIntoView (near-instant, no visual cue that a section change
// is happening), this fades a full-viewport veil in over the hero, scrolls
// underneath it on its own easing curve, then fades the veil back out once
// the explainer is in place. The veil's colour matches the explainer's
// background, so the cut reads as "the page breathes into the next section"
// rather than a hard jump.
const EASE_IN_OUT_CUBIC = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

const FADE_IN_MS = 420;
const SCROLL_MS = 900;
const HOLD_MS = 140;

export function useCrossfadeScroll() {
  const [veilOpacity, setVeilOpacity] = useState(0);
  const runningRef = useRef(false);

  const scrollToId = useCallback((targetId) => {
    if (runningRef.current) return;
    const target = document.getElementById(targetId);
    if (!target) return;
    runningRef.current = true;

    const startY = window.scrollY;
    const endY = target.getBoundingClientRect().top + window.scrollY;

    setVeilOpacity(1);

    window.setTimeout(() => {
      const start = performance.now();
      function step(now) {
        const t = Math.min(1, (now - start) / SCROLL_MS);
        window.scrollTo(0, startY + (endY - startY) * EASE_IN_OUT_CUBIC(t));
        if (t < 1) {
          requestAnimationFrame(step);
        } else {
          window.setTimeout(() => {
            setVeilOpacity(0);
            runningRef.current = false;
          }, HOLD_MS);
        }
      }
      requestAnimationFrame(step);
    }, FADE_IN_MS);
  }, []);

  return { veilOpacity, scrollToId };
}
