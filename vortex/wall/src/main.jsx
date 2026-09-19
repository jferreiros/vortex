import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { bootstrapEntryHash } from "./lib/callRoute";
// Legacy theme: the palette the eleven Live Call concepts (src/designs/*)
// and the old app.css shell were built against. Left in place untouched.
import "./theme.css";
// New app-shell theme: everything under src/pages, src/components/ui and
// the Clinic View reads its colour/type/spacing/radius/shadow from here.
import "./theme/tokens.css";
import "./theme/base.css";

bootstrapEntryHash();

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
