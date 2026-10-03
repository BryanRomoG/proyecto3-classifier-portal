
import io
import os

from PIL import Image

import torch
from torchvision import transforms


# ============================================================
# CONFIGURACIÓN
# ============================================================

MLFLOW_TRACKING_URI = os.getenv(
    "MLFLOW_TRACKING_URI",
    "http://localhost:5000",
)

SELECTED_RUN_ID = os.getenv(
    "SELECTED_RUN_ID",
    "",
)

MODEL_PATH = os.getenv(
    "MODEL_PATH",
    "./model.pt",
)

DEVICE = torch.device(
    "cuda"
    if torch.cuda.is_available()
    else "cpu"
)


# ============================================================
# CLASES
# ============================================================

CLASS_NAMES = [
    "cat",
    "dog",
]


# ============================================================
# PREPROCESAMIENTO
# ============================================================

def build_preprocess():
    """
    IMPORTANTE:

    Esta transformación debe ser EXACTAMENTE la misma
    utilizada por Evaluation/test_evaluation.

    Si Evaluation utiliza otro tamaño, mean/std o
    augmentation, copia esa configuración aquí.
    """

    return transforms.Compose(
        [
            transforms.Resize(
                (224, 224),
            ),

            transforms.ToTensor(),

            transforms.Normalize(
                mean=[
                    0.485,
                    0.456,
                    0.406,
                ],
                std=[
                    0.229,
                    0.224,
                    0.225,
                ],
            ),
        ]
    )


PREPROCESS = build_preprocess()


# ============================================================
# MODELO
# ============================================================

_model = None


def load_model():
    global _model

    if _model is not None:
        return _model

    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(
            f"No existe el modelo: {MODEL_PATH}"
        )

    checkpoint = torch.load(
        MODEL_PATH,
        map_location=DEVICE,
    )



    if isinstance(
        checkpoint,
        torch.nn.Module,
    ):
        model = checkpoint

    elif isinstance(
        checkpoint,
        dict,
    ) and "model" in checkpoint:
        model = checkpoint["model"]

    else:
        raise RuntimeError(
            "model.pt no contiene un modelo PyTorch "
            "directamente utilizable. Usa aquí la misma "
            "función de carga que Evaluation."
        )

    model = model.to(DEVICE)

    model.eval()

    _model = model

    return _model


# ============================================================
# PREDICCIÓN
# ============================================================

def predict(
    image_bytes: bytes,
    content_type: str,
):
    image = Image.open(
        io.BytesIO(image_bytes)
    ).convert("RGB")

    tensor = PREPROCESS(
        image
    )

    tensor = tensor.unsqueeze(
        0
    ).to(DEVICE)

    model = load_model()

    with torch.no_grad():
        logits = model(tensor)

        probabilities = torch.softmax(
            logits,
            dim=1,
        )[0]

    confidence, class_index = torch.max(
        probabilities,
        dim=0,
    )

    predicted_index = int(
        class_index.item()
    )

    predicted_class = CLASS_NAMES[
        predicted_index
    ]

    predictions = []

    for index, probability in enumerate(
        probabilities
    ):
        predictions.append(
            {
                "className":
                    CLASS_NAMES[index],

                "probability":
                    float(
                        probability.item()
                    ),
            }
        )

    predictions.sort(
        key=lambda item:
            item["probability"],
        reverse=True,
    )

    return {
        "predictions": predictions,

        "predicted_class":
            predicted_class,

        "confidence":
            float(
                confidence.item()
            ),
    }

