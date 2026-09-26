# DQ-04 — Línea base de objetos pequeños y desbalance

## Fuente analizada

- Archivo local: `C:\Users\santi\Downloads\coco-dataset.json`
- Tamaño: 346,069 bytes
- SHA-256: `935e9bb639bfe966fdc3b1bbe95becf07dcd09f7567079642f22a73646531936`

El JSON COCO no se incorpora al repositorio. La huella permite identificar exactamente la
fuente usada y coincide con la línea base M3.

## Configuración de DQ-04

| Analizador | Configuración |
| --- | --- |
| Objetos pequeños | `max_width=32 px`, `max_height=32 px`, `sample_limit=10` |
| Desbalance | `min_images_per_class=300` |

Una caja cuenta como pequeña si su ancho **y** alto son menores o iguales a los límites.
Para ambos analizadores se excluyen las cajas que exceden los límites de su imagen. La
cobertura de clase se mide por `image_id` distintos con al menos una caja válida, no por
el total de anotaciones.

## Resultados

### Objetos pequeños

| Métrica | Valor |
| --- | ---: |
| Anotaciones válidas | 1,038 |
| Objetos pequeños | 14 |
| Porcentaje | 1.3487475915% |
| Clase más afectada | `car` |

Las primeras muestras deterministas son las anotaciones `619`, `643`, `645`, `662`, `663`,
`665`, `666`, `667`, `670` y `671`. El analizador entrega para cada una `annotation_id`,
`image_id`, categoría y `bbox`; el límite de diez muestras evita que un reporte crezca sin
control.

### Desbalance de clases

| Clase | Imágenes distintas con caja válida | ¿Bajo 300? |
| --- | ---: | --- |
| `person` | 311 | No |
| `car` | 309 | No |
| `dog` | 0 | Sí |

- Mayoría activa: `person` (311).
- Minoría activa: `car` (309).
- Ratio mayoría/minoría activa: `1.0064724919`.
- Clase bajo el mínimo: `dog`.

`dog` aparece como cobertura cero y permanece en la lista de clases bajo el mínimo. No se
usa como divisor del ratio para evitar una métrica infinita; el ratio compara las clases
que sí tienen cobertura válida.

## Alcance

Estos valores son las salidas de los analizadores DQ-04, no un veredicto de liberación.
DQ-06 integrará estas métricas con `quality.yaml`, el Quality Gate y el contrato
`quality.json`. En particular, el límite geométrico de 32×32 px es independiente del
umbral de Gate de 40% para `small_objects`.
