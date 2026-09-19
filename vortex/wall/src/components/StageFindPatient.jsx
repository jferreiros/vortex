// The find_patient detail view: what was searched, and every record the
// directory matched — never just the winner, so the jury sees the query
// worked, not just that an id popped out.
export default function StageFindPatient({ tool }) {
  const args = tool.args || {};
  const result = tool.result || {};
  const records = Array.isArray(result.candidates)
    ? result.candidates
    : result.patient
      ? [result.patient]
      : [];
  const inputs = Object.entries(args).filter(([, v]) => v !== null && v !== undefined && v !== "");

  return (
    <div className="stage-details">
      <div className="stage-section">
        <h4>Entrada usada para buscar</h4>
        <div className="stage-chips">
          {inputs.length === 0 && <span className="stage-empty-inline">Sin datos de búsqueda.</span>}
          {inputs.map(([key, value]) => (
            <span className="chip" key={key}>
              <b>{key}</b>: {String(value)}
            </span>
          ))}
        </div>
      </div>
      <div className="stage-section stage-section-grow">
        <h4>Coincidencias en la base de datos ({records.length})</h4>
        <div className="stage-records">
          {records.length === 0 && <span className="stage-empty-inline">Sin coincidencias.</span>}
          {records.map((record, index) => {
            const name = record.full_name || record.name || record.patient_id || `Registro ${index + 1}`;
            const bits = [record.national_id, record.phone, record.date_of_birth].filter(Boolean);
            return (
              <div className="stage-record" key={record.patient_id || name || index}>
                <span className="stage-record-name">{name}</span>
                {bits.length > 0 && <span className="stage-record-meta">{bits.join(" · ")}</span>}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
