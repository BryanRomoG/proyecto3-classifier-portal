# Línea base M3 — DQ-03

## Fuente auditada

| Campo | Valor |
| --- | --- |
| Archivo | `coco-dataset.json` |
| SHA-256 | `935e9bb639bfe966fdc3b1bbe95becf07dcd09f7567079642f22a73646531936` |
| Imágenes totales | 313 |
| Anotaciones totales | 1,038 |
| Clases objetivo confirmadas | `person`, `car` |

El archivo COCO oficial no se versiona en este repositorio. Su nombre y hash permiten
identificar la misma exportación sin copiar imágenes ni anotaciones al control de versiones.

## Conteo M3 inicial

| Clase | ID de categoría | Imágenes distintas con al menos una caja válida | Mínimo requerido | Estado |
| --- | ---: | ---: | ---: | --- |
| `person` | 1 | 311 | 300 | Cumple |
| `car` | 2 | 309 | 300 | Cumple |

Ambas clases superan el mínimo de 300 imágenes distintas y válidas requerido para M3.

## Reglas aplicadas

- Se cuentan IDs de imagen distintos, no el número de cajas.
- Una imagen cuenta para una clase solo si tiene al menos una caja de esa clase con
  coordenadas no negativas, ancho y alto positivos y límites dentro de la imagen.
- Se excluyeron 0 cajas inválidas de las clases objetivo.
- Se excluyeron 2 imágenes que no contenían una caja válida de `person` o `car`.
- Se observaron 1,038 anotaciones válidas de las clases objetivo.

## Reproducción

El módulo `dataset_quality.analyzers.m3` valida primero la estructura COCO con los
modelos Pydantic de DQ-01 y después calcula el reporte. Con Docker Desktop activo, montar
la exportación de solo lectura en el contenedor y ejecutar:

```text
python -m dataset_quality.analyzers.m3 /input/coco-dataset.json --category person --category car
```

La salida debe conservar el hash mostrado arriba y los conteos 311 para `person` y 309
para `car`.

## Estado de validación

Validado en Docker con Python 3.12.14 el 2026-09-17:

- Pytest: 45 pruebas aprobadas.
- Ruff: `All checks passed!`.
- CLI M3: reprodujo el SHA-256 y todos los valores de esta tabla desde la exportación
  montada como solo lectura.

La evidencia ejecutable confirma que el reporte corresponde a la exportación oficial.
