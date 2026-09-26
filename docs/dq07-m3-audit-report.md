# DQ-07 - Auditoria final M3 y analizadores

## Fuente auditada

| Campo | Valor |
| --- | --- |
| COCO | `coco-dataset.json` proporcionado localmente |
| SHA-256 | `45f2217c2d83fa953a6845ed8bcc7009e2bd297757c4d12fb7bdf847282136a7` |
| Imagenes COCO | 311 |
| Archivos de imagen | 310 en `D:\person_car_dataset` |
| Anotaciones | 1,038 |
| Categorias | 3 (`person`, `car`, `dog`) |
| Clases M3 | `person`, `car` |
| Politica pHash | hash de 8 x 8 y distancia Hamming maxima de 8 |

Hay 310 archivos para 311 registros COCO porque dos registros referencian el mismo
archivo; el analisis pHash lo confirma como el unico par duplicado exacto.

## Resultado M3 despues de eliminar duplicados

M3 requiere al menos dos clases con 300 imagenes distintas y validas.

| Clase | Cajas validas | Imagenes antes | Imagenes despues | Umbral | Resultado |
| --- | ---: | ---: | ---: | ---: | --- |
| `person` | 472 | 311 | 310 | 300 | Cumple |
| `car` | 566 | 309 | 308 | 300 | Cumple |

El par pHash es `image_id` 3 y 4, con distancia 0 y similitud 1.0. Al colapsar su
componente conexo se elimina una imagen redundante sin perder evidencia de ninguna clase.

## Controles independientes

| Metrica | Resultado |
| --- | --- |
| Cajas invalidas | 0 |
| Objetos pequenos (<= 32 x 32 px) | 14 (1.3487%) |
| Ratio de desbalance | 1.0065 (`person` / `car`) |
| Pares duplicados pHash | 1 |
| Grupos de duplicados | 1 |
| Discrepancias frente a DQ-04 y DQ-05 | 0 |

## Conclusion

**DQ-07 queda completado.** La auditoria independiente concuerda con los analizadores
de produccion y M3 sigue cumpliendo tras el colapso de duplicados reales.

El detalle estructurado reproducible esta en
[`dq07-m3-audit.json`](dq07-m3-audit.json). Para reproducirlo se necesita el mismo JSON
y la carpeta de imagenes; en Docker sin acceso compartido a `D:` se debe copiar la
carpeta a un contenedor temporal antes de ejecutar:

```bash
python -m dataset_quality.analyzers.dq07_audit coco-dataset.json \
  --target-classes person car --min-images 300 \
  --image-root /ruta/a/person_car_dataset --phash-max-distance 8 \
  --output docs/dq07-m3-audit.json
```
