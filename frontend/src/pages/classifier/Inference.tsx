
import { useState } from "react";

export default function Inference() {
  const [fileName, setFileName] = useState("");

  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Inference</h2>
          <p>Prueba de inferencia del clasificador.</p>
        </div>

        <span className="demo-badge">Datos de ejemplo</span>
      </div>

      <div className="card">
        <h3>Seleccionar imagen</h3>

        <input
          type="file"
          accept="image/*"
          onChange={(event) => {
            const file = event.target.files?.[0];

            if (file) {
              setFileName(file.name);
            }
          }}
        />

        {fileName && (
          <p>
            Archivo seleccionado: <strong>{fileName}</strong>
          </p>
        )}

        <button type="button" className="primary-button">
          Ejecutar inferencia
        </button>
      </div>

      <div className="card">
        <h3>Resultado</h3>

        <div className="inference-result">
          <span>Predicción</span>
          <strong>Dog</strong>

          <span>Confidence</span>
          <strong>96.8%</strong>

          <span>Modelo</span>
          <strong>cat-dog-classifier v1.1.0</strong>
        </div>
      </div>
    </section>
  );
}

