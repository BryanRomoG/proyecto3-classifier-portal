
backend/src/ui/routes/inference.ts
````

````ts
import type { Request, Response } from "express";

import {
  predictImage,
} from "../../logic/inference.service.js";

export async function postInference(
  req: Request,
  res: Response,
) {
  try {
    if (!req.file) {
      res.status(400).json({
        error:
          "Debes enviar una imagen.",
      });

      return;
    }

    const result =
      await predictImage(
        req.file.buffer,
        req.file.mimetype,
      );

    res.status(200).json(result);
  } catch (error) {
    const message =
      error instanceof Error
        ? error.message
        : "No se pudo ejecutar la inferencia.";

    res.status(500).json({
      error: message,
    });
  }
}

