import DesignOriginal from "./DesignOriginal";
import Design1 from "./design1/Design1";
import Design2 from "./design2/Design2";
import Design3 from "./design3/Design3";
import Design4 from "./design4/Design4";
import Design5 from "./design5/Design5";
import Design6 from "./design6/Design6";
import Design7 from "./design7/Design7";
import Design8 from "./design8/Design8";
import Design9 from "./design9/Design9";
import Design10 from "./design10/Design10";
import Design11 from "./design11/Design11";

// Every Live Call visual concept explored, keyed the same way the URL and
// the design-lab switcher use. The app shell's Live Call page picks one of
// these as the product's current skin — see LIVE_CALL_DEFAULT_VARIANT.
export const DESIGNS = {
  original: { label: "Original", Component: DesignOriginal },
  1: { label: "1 · Refinada", Component: Design1 },
  2: { label: "2 · Ilustrada", Component: Design2 },
  3: { label: "3 · Call-first", Component: Design3 },
  4: { label: "4 · Espacial", Component: Design4 },
  5: { label: "5 · Editorial", Component: Design5 },
  6: { label: "6 · Neobrutalista", Component: Design6 },
  7: { label: "7 · Suizo", Component: Design7 },
  8: { label: "8 · Lujo oscuro", Component: Design8 },
  9: { label: "9 · Pastel", Component: Design9 },
  10: { label: "10 · Terminal", Component: Design10 },
  11: { label: "11 · Clínico", Component: Design11 },
};

// The one line to touch to change the whole product's Live Call visual
// direction later — "let's change it from #11 to #2" is this constant.
export const LIVE_CALL_DEFAULT_VARIANT = "11";
