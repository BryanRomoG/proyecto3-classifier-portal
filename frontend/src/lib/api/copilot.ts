import { type CopilotAnswer, copilotAnswerSchema } from "../contracts/schemas";
import { ApiError, extractMessageField, jsonBody } from "./client";

/**
 * El Copilot es un servicio Python aparte (`copilot`, docker-compose.yml),
 * no una ruta del backend Node -- por eso tiene su propia base URL en vez de
 * usar `apiRequest`/`API_BASE_URL` (que apuntan al backend). En Docker,
 * nginx reenvía `/copilot-api/` a ese servicio (ver
 * frontend/docker/nginx.conf); fuera de Docker (`npm run dev`),
 * vite.config.ts hace lo mismo.
 *
 * Corrección de revisión (validación en vivo, APP-10): NO puede ser
 * `/copilot` -- esa es también la ruta de esta misma pantalla en React
 * Router. Visitar la página directo (sin `/query`) hacía que nginx
 * interceptara la petición con su propio redirect de "falta la barra
 * final" antes de que le tocara a la SPA, y ese redirect de nginx pierde el
 * puerto (`localhost:8080` -> `localhost`), rompiendo la carga de la
 * página con un "Unable to connect" sin pista de la causa real. Ver el
 * comentario en nginx.conf.
 */
const configuredBaseUrl = import.meta.env.VITE_COPILOT_BASE_URL as string | undefined;

export const COPILOT_BASE_URL: string =
  configuredBaseUrl !== undefined && configuredBaseUrl.trim() !== ""
    ? configuredBaseUrl
    : "/copilot-api";

/**
 * Le hace una pregunta real al Dataset Copilot (POST /query) y valida la
 * respuesta contra `copilotAnswerSchema`. Nunca inventa el mensaje de error:
 * lo toma del cuerpo `{ "error": "..." }` que ya arma `http_app.py` (400
 * pregunta inválida, 502 falló el provider, 503 no configurado) — el mismo
 * patrón que `apiRequest`, replicado aquí porque este servicio vive en una
 * base URL distinta.
 */
export async function askCopilot(question: string): Promise<CopilotAnswer> {
  let res: Response;
  try {
    res = await fetch(`${COPILOT_BASE_URL}/query`, {
      method: "POST",
      ...jsonBody({ question }),
    });
  } catch {
    throw new ApiError(0, "No se pudo conectar con el Copilot.");
  }

  if (!res.ok) {
    let message = "El Copilot no pudo responder. Intenta de nuevo.";
    try {
      const body: unknown = await res.json();
      message = extractMessageField(body) ?? message;
    } catch {
      // el body no era JSON, se usa el mensaje por defecto
    }
    throw new ApiError(res.status, message);
  }

  const json: unknown = await res.json();
  const parsed = copilotAnswerSchema.safeParse(json);
  if (!parsed.success) {
    throw new Error(`Respuesta inválida del Copilot: ${parsed.error.message}`);
  }
  return parsed.data;
}
