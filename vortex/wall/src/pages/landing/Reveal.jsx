import { useEffect, useRef, useState } from "react";
import { useSpring, animated } from "@react-spring/web";

// Fades/slides a block up once it enters the viewport. React Spring is the
// right tool here (unlike the hero's scroll-linked shrink above): this is
// a discrete state change — off-screen vs. arrived — not a value that
// should track the scrollbar 1:1, so an eased spring is what makes it feel
// like the content is settling into place.
export default function Reveal({ children, delay = 0, className = "" }) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          io.disconnect();
        }
      },
      { threshold: 0.2 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const style = useSpring({
    opacity: visible ? 1 : 0,
    transform: visible ? "translateY(0px)" : "translateY(28px)",
    delay,
    config: { tension: 200, friction: 26 },
  });

  return (
    <animated.div ref={ref} style={style} className={className}>
      {children}
    </animated.div>
  );
}
