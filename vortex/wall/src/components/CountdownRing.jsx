import { useSpring, animated } from "@react-spring/web";

// A small circular progress ring for the submit-window countdown. Pure SVG,
// styled entirely by the caller via className/size so each design concept
// can reskin it without forking the animation logic.
export default function CountdownRing({ ratio, size = 44, stroke = 4, className = "", children }) {
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const spring = useSpring({
    offset: circumference * (1 - Math.max(0, Math.min(1, ratio))),
    config: { tension: 170, friction: 26 },
  });

  return (
    <div className={`countdown-ring ${className}`} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          className="countdown-ring-track"
        />
        <animated.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={spring.offset}
          className="countdown-ring-fill"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      {children && <div className="countdown-ring-content">{children}</div>}
    </div>
  );
}
