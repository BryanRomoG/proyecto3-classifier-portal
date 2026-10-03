const classMetrics = [
  {
    className: "Car",
    precision: "93.2%",
    recall: "91.8%",
    f1: "92.5%",
  },
  {
    className: "Person",
    precision: "92.7%",
    recall: "94.1%",
    f1: "93.4%",
  },
];

export function Evaluation() {
  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Evaluation</h2>
          <p>Métricas de evaluación del modelo.</p>
        </div>

        <span className="demo-badge">Datos de ejemplo</span>
      </div>

      <div className="stats-grid">
        <div className="card stat-card">
          <span>Accuracy</span>
          <strong>93.1%</strong>
        </div>

        <div className="card stat-card">
          <span>Macro F1</span>
          <strong>92.9%</strong>
        </div>

        <div className="card stat-card">
          <span>Precision</span>
          <strong>92.9%</strong>
        </div>

        <div className="card stat-card">
          <span>Recall</span>
          <strong>93.0%</strong>
        </div>
      </div>

      <div className="card">
        <h3>Métricas por clase</h3>

        <table className="data-table">
          <thead>
            <tr>
              <th>Clase</th>
              <th>Precision</th>
              <th>Recall</th>
              <th>F1 Score</th>
            </tr>
          </thead>

          <tbody>
            {classMetrics.map((metric) => (
              <tr key={metric.className}>
                <td>{metric.className}</td>
                <td>{metric.precision}</td>
                <td>{metric.recall}</td>
                <td>{metric.f1}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Confusion Matrix</h3>

        <table className="confusion-matrix">
          <tbody>
            <tr>
              <th></th>
              <th>Pred. Car</th>
              <th>Pred. Person</th>
            </tr>
            <tr>
              <th>Real Car</th>
              <td>184</td>
              <td>16</td>
            </tr>
            <tr>
              <th>Real Person</th>
              <td>12</td>
              <td>188</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
