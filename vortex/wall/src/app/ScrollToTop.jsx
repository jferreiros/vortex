import { useEffect } from "react";
import { useLocation } from "react-router-dom";

// React Router doesn't reset scroll on navigation — without this, opening
// Settings after scrolling halfway down Home lands you halfway down
// Settings too. One rule for every route: a new page opens at its top.
export default function ScrollToTop() {
  const { pathname } = useLocation();

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return null;
}
