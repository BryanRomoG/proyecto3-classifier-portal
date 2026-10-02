
export default function Training() {
  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Training</h2>
          <p>Configuración de entrenamiento del modelo.</p>
        </div>

        <span className="demo-badge">Datos de ejemplo</span>
      </div>

      <div className="card">
        <h3>Configuración</h3>

        <div className="form-grid">
          <label>
            Optimizer
            <select defaultValue="Adam">
              <option>Adam</option>
              <option>SGD</option>
              <option>RMSprop</option>
            </select>
          </label>

          <label>
            Batch size
            <input type="number" defaultValue={32} />
          </label>

          <label>
            Epochs
            <input type="number" defaultValue={20} />
          </label>

          <label>
            Learning rate
            <input type="number" defaultValue={0.001} step={0.0001} />
          </label>

          <label>
            Image size
            <select defaultValue="224">
              <option value="128">128 × 128</option>
              <option value="224">224 × 224</option>
              <option value="256">256 × 256</option>
            </select>
          </label>

          <label>
            Dropout
            <input type="number" defaultValue={0.2} step={0.1} min={0} max={1} />
          </label>
        </div>

        <button type="button" className="primary-button">
          Preparar entrenamiento
        </button>
      </div>

      <div className="card">
        <h3>Último entrenamiento</h3>

        <div className="stats-grid">
          <div>
            <span>Epochs</span>
            <strong>20</strong>
          </div>

          <div>
            <span>Accuracy</span>
            <strong>91.4%</strong>
          </div>

          <div>
            <span>Validation loss</span>
            <strong>0.284</strong>
          </div>

          <div>
            <span>Estado</span>
            <strong>Completado</strong>
          </div>
        </div>
      </div>
    </section>
  );
}

