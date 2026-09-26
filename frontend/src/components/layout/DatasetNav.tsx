import { Bot, Gauge, GitBranch, LayoutGrid, Settings, SplitSquareVertical } from "lucide-react";
import type { ComponentType, SVGProps } from "react";
import { NavLink } from "react-router-dom";

interface NavItem {
  label: string;
  to: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
}

/**
 * Las seis pantallas de la app de Calidad y Versionado de Datasets
 * (distinta del Portal de Anotación — ver GlobalNav para ese nav). Orden
 * fijado por APP-02: Overview, Analyzers, Splits, Versions, Copilot,
 * Settings.
 */
const NAV_ITEMS: NavItem[] = [
  { label: "Overview", to: "/overview", icon: LayoutGrid },
  { label: "Analyzers", to: "/analyzers", icon: Gauge },
  { label: "Splits", to: "/splits", icon: SplitSquareVertical },
  { label: "Versions", to: "/versions", icon: GitBranch },
  { label: "Copilot", to: "/copilot", icon: Bot },
  { label: "Settings", to: "/settings", icon: Settings },
];

export function DatasetNav() {
  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-border bg-sidebar lg:h-screen lg:w-64 lg:overflow-y-auto lg:border-b-0 lg:border-r">
      <div className="flex items-center gap-2 px-5 py-5">
        <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-accent-mint" aria-hidden />
        <span className="truncate text-sm font-semibold text-ink">Dataset Quality</span>
      </div>

      <nav className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible lg:px-3 lg:pb-6">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-accent-lilac-soft text-accent-lilac"
                    : "text-ink-muted hover:bg-surface hover:text-ink"
                }`
              }
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden />
              <span className="whitespace-nowrap">{item.label}</span>
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}
