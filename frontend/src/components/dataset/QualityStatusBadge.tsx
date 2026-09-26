type Status = "pass" | "warn" | "fail";

const STATUS_CONFIG: Record<Status, { label: string; dot: string; bg: string; text: string }> = {
  pass: {
    label: "Pass",
    dot: "bg-status-done",
    bg: "bg-status-done-soft",
    text: "text-status-done",
  },
  warn: {
    label: "Warn",
    dot: "bg-status-pending",
    bg: "bg-status-pending-soft",
    text: "text-status-pending",
  },
  fail: { label: "Fail", dot: "bg-red-600", bg: "bg-red-50", text: "text-red-700" },
};

/**
 * Badge compartido por Overview, Analyzers, Splits y Settings para mostrar
 * el resultado de un check de calidad (pass/warn/fail) o el estado global
 * del gate — mismos tokens de color que `StatusBadge` del Portal de
 * Anotación, pero con su propio mapa porque el dominio de estados es
 * distinto (calidad de dataset, no estado de una foto).
 */
export function QualityStatusBadge({ status }: { status: Status }): JSX.Element {
  const config = STATUS_CONFIG[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${config.bg} ${config.text}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${config.dot}`} aria-hidden="true" />
      {config.label}
    </span>
  );
}
