# Cómo ampliar la muestra a ≥250 eventos

## Archivos nuevos

| Archivo | Para qué |
|---|---|
| `buscar_hechos.py` + `.github/workflows/buscar-hechos.yml` | Revisa los Hechos de Importancia de **todas** las empresas de la SMV (vigentes y retiradas, 2009 en adelante) y marca los que parecen venta de inmuebles o expropiación. |
| `armar_lista_eeff.py` | Con esos resultados arma `empresas_eeff.txt`: primero las empresas con indicios, después el resto (sin bancos, AFP, fondos, etc.). |
| `scrape_smv_v3.py` + `.github/workflows/scraper-smv-v3.yml` | El scraper de EEFF de siempre, ahora con la lista desde `empresas_eeff.txt`. Salta las de `empresas_hechas.txt`, elige la empresa más parecida en el buscador (antes hacía clic en la primera sugerencia) y baja desde 2007 en vez de 1999. |
| `empresas_hechas.txt` | Las 26 empresas ya descargadas. Cencosud Shopping no está porque su descarga falló y conviene reintentarla. |
| `buscar_en_eeff.py` | Busca palabras clave dentro de los PDF descargados y arma un archivo por empresa solo con las páginas relevantes, para dárselo a la IA. |
| `prompt_extraccion.md` + `plantilla_eventos.csv` | Prompt para la IA y la plantilla de columnas del panel. |
| `requirements.txt` | Agrega `requests` y `pypdf`. |

Los archivos anteriores (`scrape_smv.py`, `scrape_smv_v2.py` y sus workflows) no se tocan.

## Paso 1: subir los archivos al repo
1. En github.com/vitaliaventures/smv-scraper: **Add file → Upload files**.
2. Arrastra **todo el contenido** de la carpeta descomprimida, incluida la carpeta `.github`. En Windows la carpeta `.github` puede estar oculta: actívala con *Vista → Elementos ocultos*.
3. Commit.

## Paso 2: probar el buscador de hechos (≈10 min)
1. **Actions → Buscar Hechos de Importancia → Run workflow**, con `prueba` = `si`.
2. Revisa 2 empresas y sube el artifact `hechos-importancia-tanda-1`. Descárgalo y abre:
   - `universo_empresas.csv`: debe tener unas 200 a 400 empresas.
   - `hechos_todos_tanda1.csv`: los hechos de las 2 empresas.
3. Si sale bien, pásame el log o el CSV y lo reviso. Si falla, pásame el log del paso "Buscar hechos".

## Paso 3: corrida completa del buscador (≈3 a 5 h)
**Run workflow** con `prueba` = `no`. Corren 8 tandas en paralelo. Los resultados se guardan **90 días**.

## Paso 4: armar la lista de empresas para EEFF
1. Descarga los 8 artifacts y descomprímelos dentro de una carpeta `resultados_hi`.
2. En PowerShell, en la carpeta del repo: `python armar_lista_eeff.py resultados_hi`
3. Sube al repo el `empresas_eeff.txt` que se genera. También queda `candidatos_todos.csv`, con todos los indicios juntos.

## Paso 5: descargar EEFF
**Actions → Scraper SMV Peru v3 → Run workflow** (8 tandas). Si alguna tanda no termina en 6 horas, vuelve a correrla: retoma con las empresas que falten de esa tanda.
- Revisa `empresas_no_encontradas.txt` en los artifacts: ahí quedan las empresas que el buscador de la SMV no pudo identificar con seguridad.

## Paso 6: encontrar los eventos
1. Descarga los zips en una carpeta `SMV_Data`, incluidos los de las 26 empresas anteriores.
2. `pip install pypdf`, luego `python buscar_en_eeff.py SMV_Data`.
3. Por cada archivo de `extractos/`, abre una conversación con la IA, pega el prompt de `prompt_extraccion.md` y sube el archivo.
4. Copia las filas a `plantilla_eventos.csv`. **Revisa a mano cada cita y página antes de aceptar un evento.**
5. Los indicios de `candidatos_todos.csv` (hechos de importancia) sirven para confirmar fechas y precios, y para no perder eventos grandes.

## Cuidado con
- **PDF escaneados:** `buscar_en_eeff.py` avisa cuando un PDF no tiene texto. Esos hay que revisarlos a mano o pasarlos por OCR.
- **Inventario inmobiliario (NIC 2):** las ventas de lotes o departamentos que son el negocio de la empresa no cuentan. El prompt ya lo indica, pero verifíquenlo.
- **Moneda y unidades** (miles o millones, soles o dólares): es el error más común de la IA.
