const models = [
  {
    name: "car-person-classifier",
    version: "v1.0.0",
    accuracy: "91.4%",
    status: "Archived",
    date: "2026-09-24",
  },
  {
    name: "car-person-classifier",
    version: "v1.1.0",
    accuracy: "93.1%",
    status: "Production",
    date: "2026-09-28",
  },
];

export function Models() {
  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Models</h2>
          <p>Modelos registrados del clasificador.</p>
        </div>

        <span className="demo-badge">Datos de ejemplo</span>
      </div>

      <div className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Model</th>
              <th>Version</th>
              <th>Accuracy</th>
              <th>Status</th>
              <th>Date</th>
            </tr>
          </thead>

          <tbody>
            {models.map((model) => (
              <tr key={`${model.name}-${model.version}`}>
                <td>{model.name}</td>
                <td>{model.version}</td>
                <td>{model.accuracy}</td>
                <td>
                  <span className="status-badge">{model.status}</span>
                </td>
                <td>{model.date}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
