# DQ-08 - Evidencia de pruebas adversariales

## Alcance

La suite `pipeline/tests/test_dq08_adversarial.py` verifica que el pipeline rechace o
controle datos y configuraciones adversariales antes de permitir etapas posteriores.

| Escenario | Comportamiento comprobado |
| --- | --- |
| Cajas corruptas | Detecta ancho negativo y cajas fuera de los limites de la imagen; el modelo COCO estricto rechaza la carga corrupta. |
| Imagen recomprimida | pHash identifica una imagen JPEG recomprimida como duplicada y no confunde una imagen de control distinta. |
| Gate FAIL | El CLI devuelve codigo 1, escribe `quality.json` con estado `fail` y bloquea split, export y promotion. |
| Gate WARN | El CLI devuelve codigo 0, conserva estado `warn` y permite las etapas posteriores. |
| Cambio de YAML | Cambiar un umbral de 301 a 300 cambia el resultado de FAIL a PASS sin cambiar Python. |

## Prueba de mutacion

Se creo un worktree temporal separado de la rama de trabajo y se invirtio solo la
comparacion de `evaluate_policy`:

```python
# mutacion temporal, nunca incorporada
observed < check.threshold if check.comparison == "min" else observed > check.threshold
```

Al ejecutar `tests/test_quality_policy.py`, la prueba
`test_changing_yaml_threshold_changes_evaluation_without_python_changes` fallo porque
una observacion de 300 frente al umbral minimo 301 paso indebidamente. Resultado:
**1 failed, 10 passed**. Esto prueba que la suite detecta la inversion de la politica.
La copia temporal se elimina despues de capturar esta evidencia y la implementacion real
mantiene `min: >=` y `max: <=`.

## Validacion de la implementacion real

Antes de la mutacion, se ejecutaron `test_dq08_adversarial.py`,
`test_quality_policy.py` y Ruff sobre la rama real: **16 passed** y **All checks passed**.
La validacion final se repite despues de retirar el worktree temporal.
