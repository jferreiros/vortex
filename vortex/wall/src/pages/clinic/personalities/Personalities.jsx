import PersonalitiesRail from "../home/PersonalitiesRail";
import "../home/home.css";

// Own route (`/clinic/personalities`) so the picker is in the sidebar;
// the same rail also sits on Home, which is the surface the team asked for.
export default function Personalities() {
  return (
    <div className="home-page">
      <PersonalitiesRail />
    </div>
  );
}
