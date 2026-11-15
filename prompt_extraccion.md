# Prompt para extraer eventos con IA

Usen este prompt con **un archivo de `extractos/` por conversación** (una empresa a la vez). Si la IA permite subir PDFs, también pueden adjuntar el EEFF completo del año que vayan a verificar.

Lo que devuelve la IA se pega en la hoja `plantilla_eventos.csv`. **Nada entra al panel sin que una persona revise las dos citas y las páginas.** La IA se equivoca con montos, monedas y años, y a veces confunde un activo con otro.

---

## Prompt (copiar desde aquí)

Eres un asistente de investigación contable. Te paso páginas de los Estados Financieros auditados de una empresa peruana que reporta a la SMV. Cada página viene marcada con `===== ARCHIVO: ... | PAGINA: n =====`.

**Tarea:** encuentra todos los **eventos de realización** de inmuebles: ventas (incluye dación en pago y aporte de inmuebles) y expropiaciones (indemnización o justiprecio pagado por el Estado, Ley 30025, trato directo). Solo cuentan los terrenos, edificios y otros inmuebles clasificados como:
- **Propiedades de inversión (NIC 40)**, o
- **Propiedad, planta y equipo (NIC 16)**, o
- **Activos mantenidos para la venta (NIIF 5)** que antes estaban en alguna de las dos categorías anteriores.

No cuentan la venta de inventario inmobiliario (lotes o departamentos de un proyecto que la empresa vende como su negocio, NIC 2), ni la venta de maquinaria, vehículos o acciones.

**Para cada evento, devuelve una fila CSV con estas columnas, en este orden:**

| Columna | Qué poner |
|---|---|
| id_evento | vacío (lo llenamos nosotros) |
| empresa | nombre de la empresa |
| anio_evento | año en que se realizó la venta o expropiación |
| fecha_evento | fecha exacta si aparece (dd/mm/aaaa); si no, vacío |
| tipo_evento | `venta` o `expropiacion` |
| parte_relacionada | `si` si el comprador es una empresa del mismo grupo o una parte relacionada; si no, `no` |
| descripcion_activo | qué inmueble es y dónde está, tal como lo describe el documento |
| norma | `NIC40`, `NIC16` o `NIIF5` (si estaba en NIIF 5, indica en notas de dónde venía) |
| modelo_medicion | `costo`, `valor_razonable` (NIC 40), `revaluacion` (NIC 16) o `no_revelado` |
| tecnica_valor_razonable | `mercado`, `ingreso`, `costo_NIIF13` o `no_aplica` |
| fecha_ultima_tasacion | fecha de la última tasación antes del evento, si aparece; si no, vacío |
| reclasificado_niif5 | `si` o `no` |
| valor_libros | valor en libros del activo **justo antes** del evento. Si fue reclasificado a NIIF 5, usa el valor previo a la reclasificación y anota ambos en notas. Solo el número, sin separador de miles |
| fecha_valor_libros | fecha del estado financiero de donde sale el valor en libros |
| precio_realizado | precio de venta o monto de la indemnización. Solo el número |
| moneda | `PEN` o `USD`, y la unidad si el documento la indica (ej. `PEN miles`) |
| resultado_reportado | ganancia o pérdida que reporta la empresa por el evento, si aparece |
| fuente_valor_libros | `archivo, página` de donde sale el valor en libros |
| cita_valor_libros | frase textual del documento con ese monto (máximo 40 palabras) |
| fuente_precio | `archivo, página` de donde sale el precio |
| cita_precio | frase textual del documento con ese monto (máximo 40 palabras) |
| mismo_activo | `si` si está claro que los dos montos son del mismo activo; `dudoso` si no |
| confianza | `alta`, `media` o `baja` |
| notas | cualquier ambigüedad: montos agregados de varios inmuebles, cambio de moneda, parte relacionada, etc. |

**Reglas:**
1. **No inventes ni calcules montos.** Si el valor en libros o el precio no aparece explícitamente, deja la celda vacía y explica en notas qué falta. Una ganancia sola no basta para deducir el precio, salvo que el documento dé también el valor en libros; en ese caso escribe en notas "precio derivado = valor en libros + ganancia" y pon confianza `media`.
2. Si la venta incluye varios inmuebles y el documento da montos por separado, haz **una fila por inmueble**. Si solo da el total, haz una fila y anótalo en notas.
3. Si el mismo evento aparece en varios años (por ejemplo, el EEFF del año siguiente lo repite como comparativo), devuélvelo **una sola vez**.
4. Copia las citas exactamente como están en el texto.
5. Al final, aparte del CSV, lista los indicios de eventos que encontraste pero no pudiste completar, con su archivo y página, para revisarlos a mano.

Devuelve primero el bloque CSV (con encabezado) y después la lista de indicios.
