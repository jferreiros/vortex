import { Navigate } from "react-router-dom";

// Old hash `#/clinic/personalities` now lives under IA.
export default function Personalities() {
  return <Navigate to="/clinic/ai" replace />;
}
