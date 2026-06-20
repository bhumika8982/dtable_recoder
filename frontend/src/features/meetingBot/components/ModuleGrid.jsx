import { Link } from "react-router-dom";
import { MODULES } from "../modules.js";
import StatusBadge from "./StatusBadge.jsx";

// Main meeting detail view: each module as a clickable card in a responsive
// grid (2 columns desktop, 1 column mobile). Clicking a card opens that
// module's own page.
export default function ModuleGrid({ meeting }) {
  const id = meeting.meeting_id;
  return (
    <div className="mb-module-grid">
      {MODULES.map((m) => (
        <Link key={m.key} to={`/meetings/${id}/${m.key}`} className="card mb-module-card">
          <div className="mb-module-card-head">
            <h3>{m.title}</h3>
            <StatusBadge status={meeting[m.statusField]} />
          </div>
          <p className="muted">{m.info}</p>
          <span className="mb-module-open">Open →</span>
        </Link>
      ))}
    </div>
  );
}
