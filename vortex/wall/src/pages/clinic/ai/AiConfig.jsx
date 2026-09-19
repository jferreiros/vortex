import PersonalitiesRail from "../home/PersonalitiesRail";
import AgentCard from "../settings/AgentCard";
import "../home/home.css";
import "../settings/settings.css";

export default function AiConfig() {
  return (
    <div className="home-page">
      <PersonalitiesRail />
      <AgentCard />
    </div>
  );
}
