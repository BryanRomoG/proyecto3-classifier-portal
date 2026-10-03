import type { z } from "zod";

/**
 * Todo el tráfico de red pasa por acá y por acá únicamente. El frontend
 * nunca importa Drizzle, MariaDB ni el SDK de MinIO — solo habla HTTP
 * contra el backend de la Fase 2/3.
 *
 * Base URL configurable por variable de entorno de Vite; por defecto usa
 * el proxy /api definido en vite.config.ts (ver ese archivo para el target
 * real del backend).
 */
/**
 * Si la variable no está definida o viene vacía, se usa el proxy `/api`
 * declarado en vite.config.ts. Una cadena vacía no activa `??`, por eso se
 * comprueba explícitamente.
 */
const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined;
const BASE_URL =
  configuredBaseUrl !== undefined && configuredBaseUrl.trim() !== "" ? configuredBaseUrl : "/api";

/**
 * Construye una URL utilizando la configuración central del API.
 */
export function buildApiUrl(path: string): string {
  return `${BASE_URL}${path}`;
}

export interface ApiFieldError {
  field: string;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  /** Errores por campo (`{field, message}`) cuando el backend los devuelve. */
  readonly fieldErrors: ApiFieldError[];

  constructor(message: string, status: number, fieldErrors: ApiFieldError[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

export class ApiParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiParseError";
  }
}

interface GetJsonOptions {
  signal?: AbortSignal;
}

/**
 * Hace GET a `path`, parsea el JSON crudo y lo valida con `schema`.
 * Si la respuesta HTTP no es OK, o si el parseo de Zod falla, lanza un
 * error tipado que los hooks convierten en un estado de UI legible
 * (nunca un crash silencioso ni un `as` sin validar).
 */
export async function getJson<S extends z.ZodType>(
  path: string,
  schema: S,
  options?: GetJsonOptions
): Promise<z.infer<S>> {
  let response: Response;
  try {
    response = await fetch(buildApiUrl(path), {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: options?.signal,
    });
  } catch {
    throw new ApiError("No se pudo conectar con el servidor.", 0);
  }

  if (!response.ok) {
    throw new ApiError(`El servidor respondió con un error (${response.status}).`, response.status);
  }

  let raw: unknown;
  try {
    raw = await response.json();
  } catch {
    throw new ApiParseError("La respuesta del servidor no es JSON válido.");
  }

  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    throw new ApiParseError("La respuesta del servidor no coincide con el formato esperado.");
  }

  return parsed.data;
}

interface JsonRequestOptions {
  signal?: AbortSignal;
}

export async function postJson<S extends z.ZodType>(
  path: string,
  body: unknown,
  schema: S,
  options?: JsonRequestOptions
): Promise<z.infer<S>> {
  let response: Response;

  try {
    response = await fetch(buildApiUrl(path), {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      signal: options?.signal,
    });
  } catch {
    throw new ApiError("No se pudo conectar con el servidor.", 0);
  }

  if (!response.ok) {
    let message = `El servidor respondió con un error (${response.status}).`;
    let fieldErrors: ApiFieldError[] = [];

    try {
      const raw = (await response.json()) as {
        error?: string;
        errors?: ApiFieldError[];
      };

      if (raw.error) {
        message = raw.error;
      }
      if (Array.isArray(raw.errors)) {
        fieldErrors = raw.errors;
      }
    } catch {
      // Se conserva el mensaje genérico.
    }

    throw new ApiError(message, response.status, fieldErrors);
  }

  let raw: unknown;

  try {
    raw = await response.json();
  } catch {
    throw new ApiParseError("La respuesta del servidor no es JSON válido.");
  }

  const parsed = schema.safeParse(raw);

  if (!parsed.success) {
    throw new ApiParseError("La respuesta del servidor no coincide con el formato esperado.");
  }

  return parsed.data;
}
