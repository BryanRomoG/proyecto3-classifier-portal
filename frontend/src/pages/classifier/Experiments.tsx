const experiments = [
  {
    id: "EXP-001",
    optimizer: "Adam",
    epochs: 20,
    accuracy: "91.4%",
    loss: "0.284",
    status: "Completed",
  },
  {
    id: "EXP-002",
    optimizer: "SGD",
    epochs: 25,
    accuracy: "88.7%",
    loss: "0.361",
    status: "Completed",
  },
  {
    id: "EXP-003",
    optimizer: "Adam",
    epochs: 30,
    accuracy: "93.1%",
    loss: "0.219",
    status: "Running",
  },
];

export function Experiments() {
  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Experiments</h2>
          <p>Historial de experimentos del clasificador.</p>
        </div>

        <span className="demo-badge">Datos de ejemplo</span>
      </div>

      <div className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Experiment</th>
              <th>Optimizer</th>
              <th>Epochs</th>
              <th>Accuracy</th>
              <th>Loss</th>
              <th>Status</th>
            </tr>
          </thead>

          <tbody>
            {experiments.map((experiment) => (
              <tr key={experiment.id}>
                <td>{experiment.id}</td>
                <td>{experiment.optimizer}</td>
                <td>{experiment.epochs}</td>
                <td>{experiment.accuracy}</td>
                <td>{experiment.loss}</td>
                <td>
                  <span className="status-badge">{experiment.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
