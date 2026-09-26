import { useCallback, useEffect, useState } from "react";
import type { ZodSchema } from "zod";

type FetchState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: T };

/**
 * Fetches and validates one of the shared data contracts (quality.json,
 * splits.json, versions.json — see `contracts/README.md` at the repo
 * root). Unlike `useValidatedFetch`, this does NOT go through the `/api`
 * backend proxy: it reads static files served from `frontend/public/`
 * (mirrors of the contracts at the repo root), because the pipeline that
 * will eventually produce these has not been built yet (DQ-0x / OPS-0x).
 *
 * This is intentionally the ONLY place these screens read the mock
 * contracts from — editing the JSON file under `public/contracts/` and
 * reloading the page reflects the change with no application code touched
 * (see APP-01's Agent Test).
 */
export function useContractFetch<T>(path: string, schema: ZodSchema<T>) {
  const [state, setState] = useState<FetchState<T>>({ status: "loading" });

  const load = useCallback(() => {
    let cancelled = false;
    setState({ status: "loading" });

    fetch(path, { headers: { Accept: "application/json" } })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`El servidor respondió con estado ${res.status}.`);
        }
        const json: unknown = await res.json();
        const parsed = schema.safeParse(json);
        if (!parsed.success) {
          throw new Error(`El contrato en ${path} no tiene el formato esperado.`);
        }
        if (!cancelled) {
          setState({ status: "success", data: parsed.data });
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof Error ? err.message : "Error desconocido al cargar el contrato.";
        setState({ status: "error", message });
      });

    return () => {
      cancelled = true;
    };
  }, [path, schema]);

  useEffect(() => load(), [load]);

  return { ...state, reload: load };
}
