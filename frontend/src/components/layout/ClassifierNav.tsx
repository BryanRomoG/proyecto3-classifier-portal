import { NavLink } from "react-router-dom";

const links = [
  { label: "Training", path: "/training" },
  { label: "Experiments", path: "/experiments" },
  { label: "Evaluation", path: "/evaluation" },
  { label: "Models", path: "/models" },
  { label: "Inference", path: "/inference" },
];

export function ClassifierNav() {
  return (
    <nav className="classifier-nav">
      {links.map((link) => (
        <NavLink
          key={link.path}
          to={link.path}
          className={({ isActive }) =>
            isActive ? "classifier-nav-link active" : "classifier-nav-link"
          }
        >
          {link.label}
        </NavLink>
      ))}
    </nav>
  );
}
