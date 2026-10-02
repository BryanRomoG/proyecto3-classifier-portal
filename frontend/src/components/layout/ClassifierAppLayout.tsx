
import { Outlet } from "react-router-dom";
import ClassifierNav from "./ClassifierNav";

export default function ClassifierAppLayout() {
  return (
    <div className="classifier-app">
      <header className="classifier-header">
        <div>
          <h1>Classifier Portal</h1>
          <p>Proyecto 3 - Clasificador de imágenes</p>
        </div>
      </header>

      <ClassifierNav />

      <main className="classifier-content">
        <Outlet />
      </main>
    </div>
  );
}

