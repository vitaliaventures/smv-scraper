# -*- coding: utf-8 -*-
"""
=============================================================================
 SCRAPER SMV PERU -- Descarga masiva de Estados Financieros y Dictamen
=============================================================================

QUE HACE:
  Para cada empresa en la lista EMPRESAS, este script:
    1. Busca la empresa en el portal smv.gob.pe
    2. Entra a "Informacion Financiera"
    3. Para Individual primero, luego Consolidada (recorrido completo por
       separado, uno despues del otro), recorre los anios en ANIOS de mas
       reciente a mas antiguo:
        - Intenta Anual, buscando fila(s) de "Dictamen"
        - Si NO hay ninguna fila de "Dictamen" en Anual, revisa SIEMPRE los
          4 trimestres completos (I a IV, sin detenerse en el primer exito)
          buscando "Dictamen"
        - Si tampoco hay "Dictamen" en ningun trimestre, revisa los 4
          trimestres de nuevo buscando "Notas"
        - En cada parada (Anual o cada trimestre) descarga tambien el reporte
          tabular "Estados Financieros" (icono de lupa), que abre una pagina
          con varias pestanias (Situacion Financiera, Resultados, Patrimonio,
          Flujo de Efectivo, Resultados Integrales, Firmantes) y descarga cada
          una en PDF (o Excel si el PDF falla)
        - El anio en curso (ej. 2026) se trata igual: Anual simplemente no
          encuentra nada (el ejercicio no ha cerrado) y cae naturalmente a
          revisar los 4 trimestres
        - Si un anio completo (Anual + 4 trimestres) no encuentra NADA, se
          cuenta como "anio vacio". Al acumular 3 anios vacios SEGUIDOS, se
          asume que no hay mas historia hacia atras para ese tipo y se
          detiene la busqueda de anios (pasando al siguiente tipo o empresa)
    4. Organiza todo en 4 carpetas por empresa (EEFFDD Individual/Consolidado,
       EEFF-EMPRESAS Individual/Consolidado) y las comprime en .zip al final,
       igual que las que subes manualmente.

REQUISITOS (correr estos comandos UNA VEZ en PowerShell antes de usar el script):

    python --version
    (si no tienes Python, descargalo de https://www.python.org/downloads/
     y en el instalador marca la casilla "Add Python to PATH")

    pip install selenium webdriver-manager

CORRE:
    python scrape_smv.py
=============================================================================
"""

import os
import time
import shutil
import re
import traceback

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

# ============================================================================
# CONFIGURACION -- AJUSTA AQUI
# ============================================================================

OUTPUT_DIR = os.path.join(os.getcwd(), "SMV_Data")   # Carpeta raiz (funciona igual en Windows o Linux)
STAGING_DIR = os.path.join(OUTPUT_DIR, "_descargas_temp")  # Chrome SIEMPRE descarga aqui primero
HEADLESS = True    # En GitHub Actions no hay pantalla -> siempre headless
TIMEOUT = 20
PAUSA_ENTRE_ACCIONES = 1.5

# ----------------------------------------------------------------------------
# Las 17 empresas se dividen en 3 tandas para que cada corrida quede comoda-
# mente por debajo del limite de 6 horas por job de GitHub Actions. La tanda
# a correr se elige con la variable de entorno BATCH (1, 2 o 3), que el
# workflow de GitHub Actions asigna automaticamente (corren las 3 en paralelo).
# ----------------------------------------------------------------------------
# TEMPORAL: solo las 4 empresas que fallaron antes por el bug del buscador.
# Las otras 13 ya se descargaron con exito en la corrida anterior -- no hace
# falta repetirlas. (Las listas completas originales quedan comentadas abajo
# para restaurarlas facilmente mas adelante si hace falta.)
EMPRESAS_TANDA_1 = []
EMPRESAS_TANDA_2 = [
    "Interproperties Peru S.A.",
    "Pacifico Vida",
]
EMPRESAS_TANDA_3 = [
    "Cencosud Shopping S.A.",
    "Mapfre Peru Compañia de Seguros y Reaseguros",
]

# --- Listas completas originales (comentadas, para restaurar despues) ---
# EMPRESAS_TANDA_1 = [
#     "Los Portales S.A.",
#     "Inversiones Centenario S.A.A.",
#     "Andino Investment Holding S.A.A.",
#     "Rimac Seguros y Reaseguros",
#     "Pacifico Compañia de Seguros y Reaseguros",
#     "InRetail Peru Corp",
# ]
# EMPRESAS_TANDA_2 = [
#     "Interseguro Compañia de Seguros",
#     "La Positiva Seguros y Reaseguros S.A.",
#     "La Positiva Vida Seguros y Reaseguros S.A.",
#     "Interproperties Peru S.A.",
#     "Pacifico Vida",
#     "Administradora Jockey Plaza Shopping Center S.A.",
# ]
# EMPRESAS_TANDA_3 = [
#     "Cencosud Shopping S.A.",
#     "Mapfre Peru Compañia de Seguros y Reaseguros",
#     "Activo Inmobiliario Peruano S.A.A.",
#     "Inmobiliaria IDE S.A.",
#     "Futura Consorcio Inmobiliario S.A.",
# ]

_TANDAS = {"1": EMPRESAS_TANDA_1, "2": EMPRESAS_TANDA_2, "3": EMPRESAS_TANDA_3}
BATCH = os.environ.get("BATCH", "1")
EMPRESAS = _TANDAS.get(BATCH, EMPRESAS_TANDA_1)
print(f"[info] Corriendo TANDA {BATCH}: {EMPRESAS}")

# Rango completo real (ya activado, confirmado funcionando de punta a punta)
ANIOS = list(range(2026, 1998, -1))   # de 2026 hacia 1999, descendente

TIPOS = ["Individual", "Consolidada"]

# ============================================================================
# NO HACE FALTA TOCAR NADA DE AQUI PARA ABAJO
# ============================================================================


def limpiar_nombre(nombre):
    return re.sub(r'[<>:"/\\|?*]', '_', nombre).strip()


def _reintentar(funcion, intentos=3, etiqueta="accion", espera_base=5):
    """Ejecuta 'funcion' (sin argumentos, usa closures) reintentando ante fallos
    de red u otros errores transitorios. Espera un poco más entre cada intento."""
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            return funcion()
        except Exception as e:
            ultimo_error = e
            espera = espera_base * intento
            print(f"    [!] {etiqueta}: intento {intento}/{intentos} fallo ({type(e).__name__}: {e}). "
                  f"Esperando {espera}s antes de reintentar...")
            time.sleep(espera)
    raise ultimo_error


def click_seguro(driver, elemento):
    """Hace clic en 'elemento'. Si un elemento superpuesto (ej. un menu que se
    expande) intercepta el clic normal, usa clic por JavaScript como respaldo,
    que no se puede bloquear por superposicion visual."""
    try:
        elemento.click()
    except Exception:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elemento)
        time.sleep(0.3)
        try:
            elemento.click()
        except Exception:
            driver.execute_script("arguments[0].click();", elemento)


CHROME_PROFILE_DIR = os.path.join(OUTPUT_DIR, "_chrome_profile")  # perfil/cache de Chrome
os.environ["TMP"] = os.path.join(OUTPUT_DIR, "_temp")
os.environ["TEMP"] = os.path.join(OUTPUT_DIR, "_temp")
os.environ["WDM_LOCAL"] = "1"
os.environ["WDM_CACHE_DIR"] = os.path.join(OUTPUT_DIR, "_wdm_cache")
os.makedirs(os.path.join(OUTPUT_DIR, "_temp"), exist_ok=True)  # crearla YA, antes de que algo la necesite


def setup_driver():
    """Crea el navegador Chrome. TODO (descargas, perfil/cache del navegador,
    y archivos temporales) queda organizado dentro de OUTPUT_DIR."""
    os.makedirs(STAGING_DIR, exist_ok=True)
    os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, "_temp"), exist_ok=True)

    options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": STAGING_DIR,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
        "profile.default_content_settings.popups": 0,
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument("--disk-cache-dir=" + os.path.join(OUTPUT_DIR, "_chrome_cache"))
    if HEADLESS:
        options.add_argument("--headless=new")
        # Necesario para correr Chrome dentro de un contenedor Linux (GitHub Actions):
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1400,1000")
    options.add_argument("--disable-notifications")

    # Selenium Manager (incluido desde Selenium 4.6+) detecta automaticamente la
    # version de Chrome instalada y descarga el chromedriver EXACTO que coincide --
    # mas confiable en CI que webdriver-manager, que a veces desincroniza versiones.
    driver = webdriver.Chrome(options=options)
    try:
        # IMPORTANTE: usamos "Browser.setDownloadBehavior" (no "Page.setDownloadBehavior").
        # El comando "Page." solo aplica a la pestana actual; el comando "Browser." aplica
        # a TODAS las pestanas/ventanas del navegador, incluidas las que se abran despues
        # (como la pestana de la lupa de "Estados Financieros"). Esto es lo que causaba
        # que algunas descargas no se detectaran nunca.
        driver.execute_cdp_cmd("Browser.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": STAGING_DIR,
            "eventsEnabled": True,
        })
        print(f"[debug] Descargas forzadas por CDP (Browser-wide) hacia: {STAGING_DIR}")
        print(f"[debug] Perfil/cache de Chrome en: {CHROME_PROFILE_DIR}")
    except Exception as e:
        print(f"[!] No se pudo forzar la carpeta de descarga por CDP: {e}")
    return driver


def esperar_descarga_completa(timeout=25):
    """Espera un archivo nuevo en STAGING_DIR (ya sin .crdownload) y lo devuelve.
    Devuelve la lista de nombres nuevos (usualmente 0 o 1)."""
    archivos_antes = set(os.listdir(STAGING_DIR))
    return archivos_antes


def reforzar_comportamiento_descarga(driver):
    """Reaplica Browser.setDownloadBehavior; es redundante casi siempre (el comando
    ya es global), pero es una salvaguarda barata por si el navegador necesita que
    se lo repitamos tras cambiar de ventana/pestana."""
    try:
        driver.execute_cdp_cmd("Browser.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": STAGING_DIR,
            "eventsEnabled": True,
        })
    except Exception:
        pass


def esperar_y_mover(archivos_antes, carpeta_final, etiqueta, timeout=25):
    """Espera que aparezca un archivo nuevo en STAGING_DIR y lo mueve a carpeta_final
    con el prefijo 'etiqueta'. Devuelve True si se movio algo."""
    fin = time.time() + timeout
    nuevos = []
    while time.time() < fin:
        archivos_ahora = set(os.listdir(STAGING_DIR))
        candidatos = archivos_ahora - archivos_antes
        nuevos = [f for f in candidatos if not f.endswith(".crdownload") and not f.endswith(".tmp")]
        if nuevos:
            time.sleep(1)  # margen de seguridad para que termine de escribirse
            break
        time.sleep(0.5)

    if not nuevos:
        print(f"    [!] {etiqueta}: no se detecto ninguna descarga nueva tras {timeout}s")
        return False

    os.makedirs(carpeta_final, exist_ok=True)
    for f in nuevos:
        origen = os.path.join(STAGING_DIR, f)
        destino = os.path.join(carpeta_final, f"{etiqueta}_{f}")
        try:
            if os.path.exists(destino):
                os.remove(destino)
            shutil.move(origen, destino)
        except Exception as e:
            print(f"    [!] No se pudo mover {f}: {e}")
    print(f"    [OK] {etiqueta}: descargado -> {nuevos}")
    return True


def buscar_empresa(driver, nombre_empresa):
    driver.get("https://www.smv.gob.pe/simv/")
    time.sleep(2)
    print(f"    [debug] URL actual: {driver.current_url}")

    wait = WebDriverWait(driver, TIMEOUT)
    caja = wait.until(EC.presence_of_element_located((By.ID, "txtSearch")))
    print("    [debug] Campo de busqueda encontrado.")

    palabras = nombre_empresa.split()
    # Intentos quitando palabras desde el INICIO (util cuando la palabra distintiva
    # esta al final, ej. "La Positiva Seguros..." -> "Positiva Seguros...")
    intentos_desde_inicio = [" ".join(palabras[i:]) for i in range(len(palabras) - 1)]
    # Intentos quitando palabras desde el FINAL (util cuando la palabra distintiva
    # esta al principio, ej. "Cencosud Shopping S.A." -> "Cencosud Shopping" -> "Cencosud")
    intentos_desde_final = [" ".join(palabras[:i]) for i in range(len(palabras) - 1, 0, -1)]

    # Intercalamos ambas listas, priorizando el nombre completo primero
    intentos = [nombre_empresa]
    for a, b in zip(intentos_desde_inicio, intentos_desde_final):
        if a not in intentos:
            intentos.append(a)
        if b not in intentos:
            intentos.append(b)
    if not intentos:
        intentos = [nombre_empresa]

    for texto_intento in intentos:
        caja.clear()
        caja.send_keys(texto_intento)
        time.sleep(PAUSA_ENTRE_ACCIONES + 1.5)
        primera_palabra = texto_intento.split()[0].upper()
        try:
            opcion = WebDriverWait(driver, 4).until(EC.element_to_be_clickable(
                (By.XPATH,
                 f"//*[contains(translate(normalize-space(text()),"
                 f"'abcdefghijklmnopqrstuvwxyzáéíóú','ABCDEFGHIJKLMNOPQRSTUVWXYZAEIOU'),"
                 f"'{primera_palabra}')]"
                 f"[not(self::script) and not(self::style) and not(@id='txtSearch')]")
            ))
            opcion.click()
            time.sleep(PAUSA_ENTRE_ACCIONES)
            return
        except Exception:
            print(f"    [.] Sin sugerencias con '{texto_intento}', probando con menos palabras...")
            continue

    print(f"    [!] Sin sugerencias para '{nombre_empresa}'. Probando con ENTER...")
    caja.clear()
    caja.send_keys(nombre_empresa)
    caja.send_keys(Keys.RETURN)
    time.sleep(PAUSA_ENTRE_ACCIONES)


def ir_a_informacion_financiera(driver):
    wait = WebDriverWait(driver, TIMEOUT)
    xpaths_candidatos = [
        "//div[@class='small' and contains(translate(text(),'Í','I'),'nformaci') ]",
        "//div[contains(@class,'small')][contains(text(),'financiera')]/parent::*",
        "//div[contains(@class,'small')][contains(text(),'financiera')]/ancestor::a[1]",
    ]
    ultimo_error = None
    for xp in xpaths_candidatos:
        try:
            boton = wait.until(EC.element_to_be_clickable((By.XPATH, xp)))
            click_seguro(driver, boton)
            time.sleep(PAUSA_ENTRE_ACCIONES + 1)
            print(f"    [debug] En Informacion Financiera. URL: {driver.current_url}")
            return
        except Exception as e:
            ultimo_error = e
            continue
    raise ultimo_error


def marcar_periodo(driver, anual=True):
    id_periodo = "MainContent_cboPeriodo_1" if anual else "MainContent_cboPeriodo_0"
    try:
        label = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, f"label[for='{id_periodo}']"))
        )
        radio = driver.find_element(By.ID, id_periodo)
        if not radio.is_selected():
            click_seguro(driver, label)
        return driver.find_element(By.ID, id_periodo).is_selected()
    except Exception as e:
        print(f"    [!] No se pudo marcar Periodo: {e}")
        return False


def marcar_tipo(driver, tipo):
    id_tipo = "MainContent_cboTipo_0" if tipo == "Individual" else "MainContent_cboTipo_1"
    try:
        label = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, f"label[for='{id_tipo}']"))
        )
        radio = driver.find_element(By.ID, id_tipo)
        if not radio.is_selected():
            click_seguro(driver, label)
        return driver.find_element(By.ID, id_tipo).is_selected()
    except Exception as e:
        print(f"    [!] No se pudo marcar Tipo='{tipo}': {e}")
        return False


def seleccionar_anio(driver, anio):
    try:
        sel = WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.ID, "MainContent_cboAnio"))
        )
        opciones = [o.get_attribute("value") for o in sel.find_elements(By.TAG_NAME, "option")]
        if str(anio) not in opciones:
            return False
        Select(sel).select_by_value(str(anio))
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"    [!] Error seleccionando anio {anio}: {e}")
        return False


def seleccionar_trimestre(driver, trimestre_num):
    try:
        sel = WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.ID, "MainContent_cboTrimestre"))
        )
        Select(sel).select_by_value(str(trimestre_num))
        time.sleep(1)
        return True
    except Exception as e:
        print(f"    [!] Error seleccionando trimestre {trimestre_num}: {e}")
        return False


def reconfirmar_trimestre(driver, trimestre_num):
    """Vuelve a fijar el trimestre justo antes de Filtrar, por si un postback
    anterior (ej. al reconfirmar Periodo) lo reseteo a otro valor."""
    try:
        sel = WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.ID, "MainContent_cboTrimestre"))
        )
        valor_actual = Select(sel).first_selected_option.get_attribute("value")
        if valor_actual != str(trimestre_num):
            Select(sel).select_by_value(str(trimestre_num))
            time.sleep(1)
        return True
    except Exception as e:
        print(f"    [!] No se pudo reconfirmar Trimestre={trimestre_num}: {e}")
        return False


def hacer_clic_filtrar(driver, tipo, anual, trimestre=None):
    wait = WebDriverWait(driver, TIMEOUT)
    marcar_periodo(driver, anual=anual)
    marcar_tipo(driver, tipo)
    if not anual and trimestre:
        reconfirmar_trimestre(driver, trimestre)
    boton = wait.until(EC.element_to_be_clickable((By.ID, "MainContent_lnkBuscar")))
    click_seguro(driver, boton)
    time.sleep(PAUSA_ENTRE_ACCIONES + 1.5)


def buscar_filas_por_palabras(driver, palabras_clave):
    filas_encontradas = []
    try:
        filas = driver.find_elements(By.XPATH, "//table[@id='MainContent_grdInfoFinanciera']//tr")
    except Exception:
        return filas_encontradas
    for fila in filas:
        texto = fila.text
        if any(palabra.lower() in texto.lower() for palabra in palabras_clave):
            filas_encontradas.append(fila)
    return filas_encontradas


def descargar_fila(driver, fila, carpeta_destino, etiqueta):
    try:
        link = fila.find_element(By.XPATH, ".//a | .//img")
    except Exception:
        print(f"    [!] {etiqueta}: fila sin icono de descarga")
        return False

    archivos_antes = esperar_descarga_completa()
    ventanas_antes = driver.window_handles
    try:
        link.click()
    except Exception as e:
        print(f"    [!] {etiqueta}: no se pudo hacer clic ({e})")
        return False

    time.sleep(2)
    ventanas_despues = driver.window_handles
    if len(ventanas_despues) > len(ventanas_antes):
        driver.switch_to.window(ventanas_despues[-1])
        reforzar_comportamiento_descarga(driver)
        time.sleep(2)

    resultado = esperar_y_mover(archivos_antes, carpeta_destino, etiqueta)

    if len(driver.window_handles) > len(ventanas_antes):
        try:
            driver.close()
        except Exception:
            pass
        driver.switch_to.window(ventanas_antes[0])

    return resultado


def descargar_todas_las_filas(driver, carpeta_destino, palabras_clave, etiqueta_base):
    """Descarga TODAS las filas que coincidan. Devuelve (filas_encontradas, descargas_exitosas)."""
    filas = buscar_filas_por_palabras(driver, palabras_clave)
    if not filas:
        return 0, 0
    print(f"    [debug] {etiqueta_base}: {len(filas)} fila(s) coinciden con {palabras_clave}")
    exitos = 0
    total = len(filas)
    for i in range(total):
        filas_actuales = buscar_filas_por_palabras(driver, palabras_clave)
        if i >= len(filas_actuales):
            break
        etiqueta = f"{etiqueta_base}_{i+1}" if total > 1 else etiqueta_base
        if descargar_fila(driver, filas_actuales[i], carpeta_destino, etiqueta):
            exitos += 1
        time.sleep(1)
    return total, exitos


def descargar_reporte_eeff_tabular(driver, carpeta_destino, etiqueta):
    """Maneja la fila 'Estados Financieros' (lupa). Abre una pagina con varias PESTANIAS
    (Bootstrap pills: Situacion Financiera, Resultados, Patrimonio, Flujo de Efectivo,
    Resultados Integrales, Firmantes -- la cantidad varia segun el anio/empresa).
    Para cada pestania: la activa, y descarga su PDF (o Excel si el PDF falla)."""
    filas = buscar_filas_por_palabras(driver, ["Estados Financieros"])
    filas_exactas = [f for f in filas if "Dictamen" not in f.text and "Notas" not in f.text]

    if not filas_exactas:
        return 0

    exitos = 0
    for i in range(len(filas_exactas)):
        filas_actuales = buscar_filas_por_palabras(driver, ["Estados Financieros"])
        filas_actuales = [f for f in filas_actuales if "Dictamen" not in f.text and "Notas" not in f.text]
        if i >= len(filas_actuales):
            break
        fila = filas_actuales[i]
        try:
            lupa = fila.find_element(By.XPATH, ".//a | .//img")
        except Exception:
            continue

        ventanas_antes = driver.window_handles
        try:
            lupa.click()
        except Exception:
            continue
        time.sleep(2.5)
        ventanas_despues = driver.window_handles

        if len(ventanas_despues) <= len(ventanas_antes):
            print(f"    [!] {etiqueta}: la lupa no abrio pestana nueva")
            continue

        driver.switch_to.window(ventanas_despues[-1])
        reforzar_comportamiento_descarga(driver)
        time.sleep(1.5)

        # Buscar las pestanias (Bootstrap pills). IDs conocidos: lnkBalance, lnkEstadoGP,
        # lnkEstadoPatrimonio, lnkEstadoFlujo, lnkResultadosIntegrales, lnktbnFirmates.
        # Usamos un selector generico por si la cantidad/IDs varian en anios antiguos.
        pestanias = driver.find_elements(By.CSS_SELECTOR, "a[data-toggle='pill']")
        if not pestanias:
            # Reporte sin pestanias (formato antiguo) -> tratamos la pagina entera como una sola
            pestanias = [None]

        print(f"    [debug] {etiqueta}: {len(pestanias)} pestania(s) encontradas en el reporte tabular")

        for j in range(len(pestanias)):
            pestanias_actuales = driver.find_elements(By.CSS_SELECTOR, "a[data-toggle='pill']")
            nombre_pestania = f"tab{j+1}"
            if pestanias_actuales and j < len(pestanias_actuales):
                try:
                    nombre_pestania = pestanias_actuales[j].text.strip().replace(" ", "")[:20] or f"tab{j+1}"
                    pestanias_actuales[j].click()
                    time.sleep(2)  # dar tiempo a que la pestania renderice su contenido
                except Exception:
                    pass

            archivos_antes = esperar_descarga_completa()
            descargado = False
            etiqueta_completa = f"{etiqueta}_EEFF_{nombre_pestania}"

            # Selectores CONFIRMADOS: <img id="Ipdf"> y <img id="Iexcel">, a veces
            # envueltos en un <a> (ej. id="cbExcel"). Preferimos clickear el <a>
            # padre si existe. Esperamos ACTIVAMENTE (hasta 10s) a que este
            # realmente clickeable, en vez de asumir que ya esta listo tras un
            # tiempo fijo -- esto es lo que causaba fallos intermitentes.
            try:
                img_pdf = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "Ipdf"))
                )
                clic_pdf = img_pdf
                try:
                    clic_pdf = img_pdf.find_element(By.XPATH, "./ancestor::a[1]")
                except Exception:
                    pass
                WebDriverWait(driver, 10).until(EC.element_to_be_clickable(clic_pdf))
                clic_pdf.click()
                time.sleep(1)
                descargado = esperar_y_mover(archivos_antes, carpeta_destino, etiqueta_completa, timeout=15)
            except Exception as e:
                print(f"    [debug] {etiqueta_completa}: PDF no disponible/clickeable ({type(e).__name__})")

            if not descargado:
                try:
                    img_excel = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.ID, "Iexcel"))
                    )
                    clic_excel = img_excel
                    try:
                        clic_excel = img_excel.find_element(By.XPATH, "./ancestor::a[1]")
                    except Exception:
                        pass
                    WebDriverWait(driver, 10).until(EC.element_to_be_clickable(clic_excel))
                    clic_excel.click()
                    time.sleep(1)
                    descargado = esperar_y_mover(archivos_antes, carpeta_destino, etiqueta_completa, timeout=15)
                except Exception as e:
                    print(f"    [debug] {etiqueta_completa}: Excel tampoco disponible/clickeable ({type(e).__name__})")

            if descargado:
                exitos += 1
            else:
                print(f"    [!] {etiqueta} pestania '{nombre_pestania}': no se pudo descargar "
                      f"(revisar selector de iconos PDF/Excel)")

        if len(driver.window_handles) > len(ventanas_antes):
            try:
                driver.close()
            except Exception:
                pass
            driver.switch_to.window(ventanas_antes[0])
        time.sleep(1)

    return exitos


def procesar_anio_tipo(driver, carpeta_dictamen, carpeta_tabular, anio, tipo):
    """Procesa un (anio, tipo): intenta Anual buscando 'Dictamen'; si no hay,
    revisa los 4 trimestres COMPLETOS (una sola pasada, sin detenerse en el
    primer exito), buscando 'Dictamen' O 'Notas' juntos en cada visita (evita
    visitar/descargar el mismo trimestre dos veces). En cada parada (Anual o
    cada trimestre) descarga tambien el reporte tabular 'Estados Financieros'
    (lupas) UNA sola vez por visita. Aplica igual para el anio en curso (Anual
    simplemente no encontrara nada, y cae naturalmente a revisar los trimestres).
    Devuelve True si se encontro CUALQUIER cosa (Dictamen, Notas, o EEFF tabular)."""

    def _filtrar(anual, trimestre=None):
        marcar_tipo(driver, tipo)
        marcar_periodo(driver, anual=anual)
        if not seleccionar_anio(driver, anio):
            return False
        if not anual and trimestre:
            seleccionar_trimestre(driver, trimestre)
        hacer_clic_filtrar(driver, tipo=tipo, anual=anual, trimestre=trimestre)
        return True

    encontro_algo = False

    # ---------- Intento 1: Anual ----------
    if _filtrar(anual=True):
        etiqueta = f"{anio}_{tipo}_Anual"
        filas_anual, _ = descargar_todas_las_filas(driver, carpeta_dictamen, ["Dictamen"], etiqueta)
        exitos_tab = descargar_reporte_eeff_tabular(driver, carpeta_tabular, etiqueta)
        if filas_anual > 0 or exitos_tab > 0:
            encontro_algo = True

        if filas_anual > 0:
            # Se encontro la fila de Dictamen en Anual -> no hace falta revisar trimestres.
            return True
    else:
        print(f"    [info] {anio} ({tipo}): Anual no disponible en el selector para este anio.")

    # ---------- Intento 2: Intermedio, los 4 trimestres, UNA sola pasada buscando 'Dictamen' o 'Notas' juntos ----------
    print(f"    [info] {anio} ({tipo}): sin 'Dictamen' en Anual. Probando Intermedio (4 trimestres, una sola pasada)...")
    for trimestre in [1, 2, 3, 4]:
        if not _filtrar(anual=False, trimestre=trimestre):
            continue
        etiqueta = f"{anio}_{tipo}_TrimestreI{trimestre}"
        filas, _ = descargar_todas_las_filas(driver, carpeta_dictamen, ["Dictamen", "Notas"], etiqueta)
        exitos_tab = descargar_reporte_eeff_tabular(driver, carpeta_tabular, etiqueta)
        if filas > 0 or exitos_tab > 0:
            encontro_algo = True

    if not encontro_algo:
        print(f"    [info] {anio} ({tipo}): SIN informacion disponible (ni Anual ni ningun trimestre).")

    return encontro_algo


def nombre_carpeta_zip(prefijo, nombre_empresa, tipo):
    tipo_legible = "Individual" if tipo == "Individual" else "Consolidado"
    return limpiar_nombre(f"{prefijo}-{nombre_empresa}-{tipo_legible}")


def procesar_empresa(driver, nombre_empresa):
    carpeta_empresa = os.path.join(OUTPUT_DIR, limpiar_nombre(nombre_empresa))
    os.makedirs(carpeta_empresa, exist_ok=True)
    print(f"\n{'='*70}\nEMPRESA: {nombre_empresa}\n{'='*70}")

    try:
        _reintentar(lambda: buscar_empresa(driver, nombre_empresa), intentos=3, etiqueta="buscar_empresa")
    except Exception:
        print(f"  [ERROR] No se pudo buscar la empresa (tras varios intentos):")
        traceback.print_exc()
        return

    try:
        _reintentar(lambda: ir_a_informacion_financiera(driver), intentos=3, etiqueta="ir_a_informacion_financiera")
    except Exception:
        print(f"  [ERROR] No se pudo entrar a Informacion Financiera (tras varios intentos):")
        traceback.print_exc()
        return

    carpetas_generadas = []

    for tipo in TIPOS:
        nombre_dictamen = nombre_carpeta_zip("EEFFDD", nombre_empresa, tipo)
        nombre_tabular = nombre_carpeta_zip("EEFF-EMPRESAS", nombre_empresa, tipo)
        carpeta_dictamen = os.path.join(carpeta_empresa, nombre_dictamen)
        carpeta_tabular = os.path.join(carpeta_empresa, nombre_tabular)
        os.makedirs(carpeta_dictamen, exist_ok=True)
        os.makedirs(carpeta_tabular, exist_ok=True)

        anios_vacios_seguidos = 0
        for anio in ANIOS:
            print(f"\n  --- {nombre_empresa} | {tipo} | {anio} ---")

            # --- BLINDAJE: si la ventana/sesion del navegador se cerro o se corrompio,
            # la recreamos en vez de dejar que TODO el resto del proceso falle en cascada ---
            try:
                _ = driver.current_url
            except Exception:
                print("    [!] La ventana del navegador se cerro inesperadamente. Reabriendo...")
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = setup_driver()
                try:
                    buscar_empresa(driver, nombre_empresa)
                    ir_a_informacion_financiera(driver)
                except Exception:
                    print("    [ERROR] No se pudo recuperar la sesion. Se salta este (tipo, anio).")
                    continue

            try:
                encontro_algo = procesar_anio_tipo(driver, carpeta_dictamen, carpeta_tabular, anio, tipo)
            except Exception:
                print(f"    [ERROR] {tipo} {anio}:")
                traceback.print_exc()
                encontro_algo = False

            if encontro_algo:
                anios_vacios_seguidos = 0
            else:
                anios_vacios_seguidos += 1
                if anios_vacios_seguidos >= 3:
                    print(f"    [info] {tipo}: 3 anios seguidos sin ninguna informacion "
                          f"(Anual, ni ningun trimestre). Se asume que no hay mas historia "
                          f"hacia atras para este tipo y se detiene la busqueda de anios.")
                    break

        if os.listdir(carpeta_dictamen):
            carpetas_generadas.append((carpeta_dictamen, nombre_dictamen))
        if os.listdir(carpeta_tabular):
            carpetas_generadas.append((carpeta_tabular, nombre_tabular))

    for carpeta, nombre_zip in carpetas_generadas:
        try:
            ruta_zip_sin_ext = os.path.join(carpeta_empresa, nombre_zip)
            shutil.make_archive(ruta_zip_sin_ext, "zip", carpeta)
            print(f"  [ZIP] Creado: {ruta_zip_sin_ext}.zip")
        except Exception as e:
            print(f"  [!] No se pudo comprimir {carpeta}: {e}")

    return driver  # puede haber cambiado si se recreo la sesion


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    driver = setup_driver()
    try:
        for empresa in EMPRESAS:
            nuevo_driver = procesar_empresa(driver, empresa)
            if nuevo_driver is not None:
                driver = nuevo_driver
    finally:
        print("\nTerminado. Cerrando navegador en 5 segundos...")
        time.sleep(5)
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
