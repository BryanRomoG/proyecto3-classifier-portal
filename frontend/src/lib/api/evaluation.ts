import { z } from "zod";

const SelectionSchema = z.object({
  selected: z.boolean().optional(),
  run_id: z.string().optional(),
  model_version: z.string().optional(),
  dataset_version: z.string().optional(),
  test_opened: z.boolean().optional(),
});

export type Selection = z.infer<
  typeof SelectionSchema
>;

export async function getSelection(): Promise<Selection> {
  const response = await fetch(
    "/api/evaluation/selection",
  );

  if (!response.ok) {
    throw new Error(
      "No se pudo obtener la selección.",
    );
  }

  return SelectionSchema.parse(
    await response.json(),
  );
}

export async function getEvaluation(): Promise<
  Record<string, unknown>
> {
  const response = await fetch(
    "/api/evaluation",
  );

  if (!response.ok) {
    throw new Error(
      "No se pudo obtener la evaluación.",
    );
  }

  return z
    .record(z.string(), z.unknown())
    .parse(await response.json());
}
