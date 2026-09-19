import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useCallTimeline } from "../../../lib/useCallTimeline";
import { derivePhase } from "../../../lib/derive";
import { resolveRawId } from "../../../lib/callRoute";
import { DESIGNS, LIVE_CALL_DEFAULT_VARIANT } from "../../../designs/registry";
import DesignSwitcher from "../../../designs/DesignSwitcher";
import "./live-call-detail.css";

// Full-bleed by design: every Live Call concept already takes the whole
// viewport (position: fixed; inset: 0) to give the call itself maximum
// room. Wrapping it in the Clinic sidebar would fight that, so this route
// renders outside ClinicShell's layout and floats a small "back" pill
// instead — see AppRouter.
export default function LiveCallDetail() {
  const { callId: rawParam } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const { callId, isDemo, designVariant } = resolveRawId(rawParam);
  const qDesign = searchParams.get("design");
  const isPreview = isDemo || Boolean(qDesign);
  const initialVariant = qDesign || designVariant || LIVE_CALL_DEFAULT_VARIANT;
  const [variant, setVariant] = useState(DESIGNS[initialVariant] ? initialVariant : LIVE_CALL_DEFAULT_VARIANT);

  const { items, intent, call } = useCallTimeline(callId);
  const phase = derivePhase(items, call);
  const turnItems = items.filter((it) => it.type === "turn");

  function selectVariant(key) {
    setVariant(key);
    const next = new URLSearchParams(searchParams);
    if (key === LIVE_CALL_DEFAULT_VARIANT) {
      next.delete("design");
    } else {
      next.set("design", key);
    }
    setSearchParams(next, { replace: true });
  }

  const { Component } = DESIGNS[variant];

  return (
    <div className="live-call-detail-root">
      <button type="button" className="live-call-back" onClick={() => navigate("/clinic/live-calls")}>
        ← Volver a llamadas
      </button>
      <Component items={items} turnItems={turnItems} intent={intent} call={call} phase={phase} />
      {isPreview && <DesignSwitcher active={variant} onSelect={selectVariant} designs={DESIGNS} />}
    </div>
  );
}
