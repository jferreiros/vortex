import { useNavigate, useParams } from "react-router-dom";
import { useCallTimeline } from "../../../lib/useCallTimeline";
import { resolveRawId } from "../../../lib/callRoute";
import Design11 from "../../../designs/design11/Design11";
import "./live-call-detail.css";

// Full-bleed by design: Live Call already takes the whole viewport
// (position: fixed; inset: 0) to give the call itself maximum room.
// Wrapping it in the Clinic sidebar would fight that, so this route
// renders outside ClinicShell's layout — see AppRouter. The "back" button
// is part of Design11's own top bar (see its onBack prop), not floated
// over it, so it can share the row with the call duration bar.
export default function LiveCallDetail() {
  const { callId: rawParam } = useParams();
  const navigate = useNavigate();

  const { callId } = resolveRawId(rawParam);

  const { items, intent, call } = useCallTimeline(callId);
  const turnItems = items.filter((it) => it.type === "turn");

  return (
    <div className="live-call-detail-root">
      <Design11
        items={items}
        turnItems={turnItems}
        intent={intent}
        call={call}
        onBack={() => navigate("/clinic/live-calls")}
      />
    </div>
  );
}
