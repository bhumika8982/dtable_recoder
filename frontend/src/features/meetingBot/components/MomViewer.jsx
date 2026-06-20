// Renders the rich structured MoM.
function Bullets({ title, items }) {
  if (!items || items.length === 0) return null;
  return (
    <>
      <h4>{title}</h4>
      <ul>{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </>
  );
}

export default function MomViewer({ mom, emptyText = "MoM not generated yet." }) {
  if (!mom || (!mom.summary && !(mom.key_discussion_points || []).length))
    return <p className="muted">{emptyText}</p>;

  const actions = mom.action_items || [];
  const notes = mom.speaker_wise_notes || {};
  return (
    <div className="mb-mom">
      <h4>Summary</h4>
      <p>{mom.summary || "—"}</p>

      <Bullets title="Key Discussion Points" items={mom.key_discussion_points} />
      <Bullets title="Decisions Taken" items={mom.decisions_taken} />

      {actions.length > 0 && (
        <>
          <h4>Action Items</h4>
          <ul>
            {actions.map((a, i) => (
              <li key={i}>
                <strong>{a.task}</strong>
                {a.owner ? ` — ${a.owner}` : ""}
                {a.deadline ? ` (by ${a.deadline})` : ""}
                {a.priority ? ` [${a.priority}]` : ""}
              </li>
            ))}
          </ul>
        </>
      )}

      <Bullets title="Pending Tasks" items={mom.pending_tasks} />
      <Bullets title="Next Steps" items={mom.next_steps} />

      {Object.keys(notes).length > 0 && (
        <>
          <h4>Speaker-wise Notes</h4>
          {Object.entries(notes).map(([name, points]) => (
            <div key={name}>
              <strong>{name}</strong>
              <ul>{(points || []).map((p, i) => <li key={i}>{p}</li>)}</ul>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
