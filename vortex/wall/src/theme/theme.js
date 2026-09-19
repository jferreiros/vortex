// JS-side mirror of tokens.css, for the handful of places a value needs to
// be a real JS value rather than a CSS var — react-spring configs, chart
// colour arrays (later), canvas/SVG code. Keep this in sync with
// tokens.css by hand; it's small on purpose so that's not a burden.

export const color = {
  bg: "#f6faf8",
  panel: "#ffffff",
  ink: "#1b2420",
  mute: "#6d7a74",
  faint: "#9aa6a0",
  border: "#e3e9e5",
  primary: "#2f7d5c",
  primaryDeep: "#1f5c43",
  primarySoft: "#e4f2ea",
  warn: "#b6543f",
  info: "#3a6ea5",
};

// react-spring config presets, named by feel rather than by number so a
// call site reads as intent ("springs.reveal") not tuning ("tension: 220").
export const springs = {
  gentle: { tension: 170, friction: 26 },
  reveal: { tension: 220, friction: 28 },
  snappy: { tension: 300, friction: 24 },
  slow: { tension: 120, friction: 30 },
};

export const breakpoint = {
  tablet: 1024,
  mobile: 640,
};
