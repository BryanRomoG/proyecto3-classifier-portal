import { z } from 'zod';

export const inferenceCropSchema = z.object({
  annotationId: z.number().int().positive(),
});

export const pythonInferenceResponseSchema = z
  .object({
    model: z.object({
      runId: z.string().min(1),
      runName: z.string().min(1),
      checkpointSha256: z.string().regex(/^[0-9a-f]{64}$/),
    }),
    predictedClass: z.string().min(1),
    confidence: z.number().min(0).max(1),
    probabilities: z.record(z.string().min(1), z.number().min(0).max(1)),
  })
  .superRefine((value, context) => {
    if (!(value.predictedClass in value.probabilities)) {
      context.addIssue({
        code: 'custom',
        message: 'La clase predicha no aparece en las probabilidades.',
        path: ['predictedClass'],
      });
    }
  });

export type PythonInferenceResponse = z.infer<typeof pythonInferenceResponseSchema>;
