import { Bot, User } from "lucide-react";
import { type FormEvent, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { askCopilot } from "@/lib/api/copilot";
import type { CopilotAnswer } from "@/lib/contracts/schemas";

type Message =
  | { id: string; role: "user"; question: string }
  | { id: string; role: "assistant"; answer: CopilotAnswer }
  | { id: string; role: "assistant-error"; message: string };

/**
 * Copilot: chat real contra el agente de solo lectura (APP-06,
 * pipeline/src/dataset_quality/copilot/). Cablea esta pantalla contra el
 * servicio HTTP `copilot` (nuevo en APP-10, http_app.py) — cada pregunta
 * viaja por POST /copilot-api/query (ver lib/api/copilot.ts sobre por qué
 * no /copilot, que es la ruta de esta misma pantalla) y la respuesta viene del mismo
 * `answer_question` que usa el servidor MCP real (agent.py: "no separate
 * code path"), así que nunca inventa números: cada respuesta trae las
 * tool calls que la fundamentan (`tools_used`) y la versión del dataset
 * consultada (`dataset_version`), y un fallo del provider llega aquí como
 * un mensaje de error corto y fijo, nunca un traceback (ver
 * CopilotProviderError en agent.py y el mapeo de errores en http_app.py).
 *
 * Antes de APP-10 esta pantalla era un placeholder (ver contracts/README.md,
 * "Pendiente" en la versión de APP-07): el agente y el servidor MCP ya
 * existían del lado de Python, pero nada los invocaba en producción.
 */
export function CopilotPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [isSending, setIsSending] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || isSending) return;

    const userMessage: Message = { id: crypto.randomUUID(), role: "user", question: trimmed };
    setMessages((prev) => [...prev, userMessage]);
    setQuestion("");
    setIsSending(true);

    try {
      const answer = await askCopilot(trimmed);
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "assistant", answer }]);
    } catch (err) {
      const message =
        err instanceof ApiError || err instanceof Error
          ? err.message
          : "El Copilot no pudo responder. Intenta de nuevo.";
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "assistant-error", message },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  return (
    <main className="flex-1 px-6 py-6 lg:px-10 lg:py-8">
      <div className="mx-auto flex max-w-3xl flex-col gap-6">
        <header>
          <h1 className="text-xl font-semibold text-ink">Copilot</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Dataset Copilot — agente de solo lectura sobre el estado del dataset. Solo responde con
            datos reales de las herramientas MCP; nunca inventa cifras.
          </p>
        </header>

        <div
          className="flex min-h-[24rem] flex-col gap-4 rounded-2xl border border-border bg-surface p-5 shadow-card"
          aria-live="polite"
        >
          {messages.length === 0 && (
            <p className="my-auto text-center text-sm text-ink-muted">
              Pregúntale algo al Copilot, por ejemplo: "¿el release está bloqueado?" o "¿cuál es la
              versión actual del dataset?"
            </p>
          )}

          {messages.map((message) => (
            <ChatBubble key={message.id} message={message} />
          ))}

          {isSending && (
            <div className="flex items-start gap-2">
              <BotIcon />
              <div className="rounded-2xl rounded-tl-sm bg-canvas-subtle px-4 py-2.5 text-sm text-ink-muted">
                Consultando…
              </div>
            </div>
          )}
        </div>

        <form onSubmit={handleSubmit} className="flex items-end gap-2">
          <label htmlFor="copilot-question" className="sr-only">
            Pregunta para el Copilot
          </label>
          <textarea
            id="copilot-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                handleSubmit(event);
              }
            }}
            placeholder="Escribe tu pregunta…"
            rows={2}
            disabled={isSending}
            className="flex-1 resize-none rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={isSending || question.trim() === ""}
            className="rounded-lg bg-accent-lilac px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-lilac/90 disabled:cursor-not-allowed disabled:bg-border disabled:text-ink-faint disabled:shadow-none"
          >
            Enviar
          </button>
        </form>
      </div>
    </main>
  );
}

function BotIcon() {
  return (
    <div className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-accent-lilac-soft text-accent-lilac">
      <Bot className="h-4 w-4" aria-hidden />
    </div>
  );
}

function ChatBubble({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="flex items-start justify-end gap-2">
        <div className="rounded-2xl rounded-tr-sm bg-accent-lilac px-4 py-2.5 text-sm text-white">
          {message.question}
        </div>
        <div className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-canvas-subtle text-ink-muted">
          <User className="h-4 w-4" aria-hidden />
        </div>
      </div>
    );
  }

  if (message.role === "assistant-error") {
    return (
      <div className="flex items-start gap-2">
        <BotIcon />
        <div className="rounded-2xl rounded-tl-sm border border-status-pending-soft bg-status-pending-soft px-4 py-2.5 text-sm text-status-pending">
          {message.message}
        </div>
      </div>
    );
  }

  const { answer } = message;
  return (
    <div className="flex items-start gap-2">
      <BotIcon />
      <div className="flex flex-col gap-1.5 rounded-2xl rounded-tl-sm bg-canvas-subtle px-4 py-2.5 text-sm text-ink">
        <p>{answer.answer}</p>
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
          {answer.dataset_version && (
            <span className="rounded-full bg-surface px-2 py-0.5">
              dataset {answer.dataset_version}
            </span>
          )}
          {answer.tools_used.map((tool) => (
            <span key={tool} className="rounded-full bg-surface px-2 py-0.5 font-mono">
              {tool}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
