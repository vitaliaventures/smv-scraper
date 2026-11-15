# -*- coding: utf-8 -*-
"""
=============================================================================
 BUSCADOR DE HECHOS DE IMPORTANCIA (SMV) -- ventas de inmuebles y expropiaciones
=============================================================================

QUE HACE:
  1. Abre la pagina de Hechos de Importancia del SIMV y lee la lista completa
     de empresas (vigentes y, si INCLUIR_RETIRADAS=1, tambien las retiradas).
  2. Reparte las empresas en NUM_TANDAS tandas (la tanda a correr = BATCH).
  3. Para cada empresa consulta TODOS sus hechos de importancia, en ventanas de
     ANIOS_POR_VENTANA anios (la SMV se pone muy lenta con rangos largos).
  4. Guarda:
       SMV_HI/hechos_todos_tanda<B>.csv      -> todos los hechos encontrados
       SMV_HI/hechos_candidatos_tanda<B>.csv -> solo los que parecen venta o
                                               expropiacion de inmuebles
       SMV_HI/resumen_tanda<B>.csv           -> cuantos candidatos por empresa
       SMV_HI/docs/...                       -> PDFs de los candidatos (si
                                               DESCARGAR_DOCS=1)
  Si se corta, al volver a correr salta las empresas ya terminadas (lee el
  archivo de resumen).

COMO SE USA EN GITHUB ACTIONS: workflow "Buscar Hechos de Importancia".
EN TU PC (prueba):  set BATCH=1 & set NUM_TANDAS=1 & set LIMITE_EMPRESAS=2
                    python buscar_hechos.py
=============================================================================
"""

import csv
import os
import re
import time
import traceback
import unicodedata

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select

# ----------------------------------------------------------------------------
# CONFIGURACION
# ----------------------------------------------------------------------------
URL_HI = ("https://www.smv.gob.pe/SIMV/Frm_HechosDeImportancia"
          "?data=AEC85625CCC24CEF792DAE7794ED2132F7CFCB8B1C")
OUT_DIR = os.path.join(os.getcwd(), "SMV_HI")
BATCH = int(os.environ.get("BATCH", "1"))
NUM_TANDAS = int(os.environ.get("NUM_TANDAS", "1"))
ANIO_INICIO = int(os.environ.get("ANIO_INICIO", "2009"))
ANIO_FIN = int(os.environ.get("ANIO_FIN", time.strftime("%Y")))
ANIOS_POR_VENTANA = int(os.environ.get("ANIOS_POR_VENTANA", "3"))
INCLUIR_RETIRADAS = os.environ.get("INCLUIR_RETIRADAS", "1") == "1"
DESCARGAR_DOCS = os.environ.get("DESCARGAR_DOCS", "1") == "1"
LIMITE_EMPRESAS = int(os.environ.get("LIMITE_EMPRESAS", "0"))  # 0 = sin limite (para pruebas)
ESPERA_MAX = 240  # segundos maximos esperando el "Cargando..." de la SMV

# Palabras que marcan un hecho como candidato (se busca en tipo + descripcion,
# sin tildes y en minusculas).
PALABRAS_CLAVE = [
    "expropia", "inmueble", "terreno", "predio", "enajena", "venta de",
    "compraventa", "compra venta", "transferencia de terreno", "transferencia de propiedad",
    "propiedad de inversion", "propiedades de inversion", "edificio", "local comercial",
    "lote", "hectarea", "tierras", "indemniza", "justiprecio", "ley 30025",
    "ley n 30025", "tasacion", "dacion en pago", "aporte de inmueble", "revaluacion",
]
# Tipo "16. Adquisicion, enajenacion o reestructuracion de activos" siempre entra.
TIPOS_CLAVE = ["16. adquisicion, enajenacion"]

# Descarta falsos positivos frecuentes ("lote" de bonos, etc.) solo si NO hay
# otra palabra clave fuerte.
PALABRAS_FUERTES = {"expropia", "inmueble", "terreno", "predio", "justiprecio",
                    "ley 30025", "ley n 30025", "propiedad de inversion",
                    "propiedades de inversion", "edificio", "hectarea", "tierras"}

CAMPOS = ["empresa", "codigo_smv", "estado", "expediente", "fecha_presentacion",
          "fecha_acuerdo", "tipo", "descripcion", "documentos"]


# ----------------------------------------------------------------------------
def normalizar(texto):
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).lower().strip()


def es_candidato(tipo, descripcion):
    t = normalizar(tipo + " " + descripcion)
    if any(k in t for k in TIPOS_CLAVE):
        return ["tipo16"]
    hallados = [k for k in PALABRAS_CLAVE if k in t]
    if not hallados:
        return []
    if set(hallados) <= {"lote", "venta de", "tasacion", "revaluacion", "enajena",
                         "compraventa", "compra venta", "local comercial", "dacion en pago"}:
        # solo palabras debiles: exigimos que no sea claramente sobre valores
        if re.search(r"bono|papel(es)? comercial|accion(es)?|instrumento|serie|emision", t) \
                and not (set(hallados) & PALABRAS_FUERTES):
            return []
    return hallados


def limpiar_nombre(n):
    return re.sub(r'[<>:"/\\|?*]', "_", n).strip()[:80]


def setup_driver():
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1400,1000")
    d = webdriver.Chrome(options=opts)
    d.set_page_load_timeout(120)
    d.set_script_timeout(60)
    return d


def cargando(driver):
    """True mientras la SMV muestra el modal 'Cargando ...'."""
    try:
        return driver.execute_script(
            "var m=document.querySelector('.modal.in, .modal.show');"
            "return !!(m && /Cargando/.test(m.innerText||''));")
    except Exception:
        return True


def esperar_fin_carga(driver, maximo=ESPERA_MAX, minimo=2):
    time.sleep(minimo)
    fin = time.time() + maximo
    while time.time() < fin:
        if not cargando(driver):
            # el DOM puede seguir actualizandose un instante
            time.sleep(1)
            if not cargando(driver):
                return True
        time.sleep(2)
    return False


def cerrar_modales(driver):
    driver.execute_script(
        "document.querySelectorAll('.modal.in .close, .modal.show .close')"
        ".forEach(function(b){try{b.click()}catch(e){}});")


def abrir_pagina(driver):
    driver.get(URL_HI)
    WebDriverWait(driver, 60).until(
        lambda d: d.find_elements(By.ID, "MainContent_cboDenominacionSocial"))
    esperar_fin_carga(driver, 60, 1)


def fijar_retiradas(driver, valor):
    cb = driver.find_element(By.ID, "MainContent_cbxRetiradas")
    if cb.is_selected() != valor:
        driver.execute_script("arguments[0].click();", cb)  # dispara postback
        esperar_fin_carga(driver, 90, 3)
        WebDriverWait(driver, 60).until(
            lambda d: d.find_element(By.ID, "MainContent_cbxRetiradas").is_selected() == valor)


def leer_empresas(driver):
    sel = driver.find_element(By.ID, "MainContent_cboDenominacionSocial")
    out = []
    for o in sel.find_elements(By.TAG_NAME, "option"):
        v = o.get_attribute("value")
        t = (o.get_attribute("textContent") or "").strip()
        if v and v != "-1":
            out.append((v, t))
    return out


def listar_universo(driver):
    abrir_pagina(driver)
    fijar_retiradas(driver, False)
    vigentes = leer_empresas(driver)
    universo = [(v, t, "vigente") for v, t in vigentes]
    if INCLUIR_RETIRADAS:
        fijar_retiradas(driver, True)
        ya = {v for v, _ in vigentes}
        for v, t in leer_empresas(driver):
            if v not in ya:
                universo.append((v, t, "retirada"))
        fijar_retiradas(driver, False)
    universo.sort(key=lambda x: normalizar(x[1]))
    return universo


def seleccionar_empresa(driver, codigo, nombre, estado):
    fijar_retiradas(driver, estado == "retirada")
    sel = Select(driver.find_element(By.ID, "MainContent_cboDenominacionSocial"))
    sel.select_by_value(codigo)  # dispara onchange -> postback
    esperar_fin_carga(driver, 90, 3)
    WebDriverWait(driver, 60).until(
        lambda d: d.find_element(By.ID, "MainContent_cboDenominacionSocial")
        .get_attribute("value") == codigo)
    cerrar_modales(driver)


def buscar_rango(driver, desde, hasta):
    driver.execute_script(
        "document.getElementById('txtFechDesde').value=arguments[0];"
        "document.getElementById('txtFechHasta').value=arguments[1];"
        "var d=document.getElementById('txtBusquedaDesc'); if(d) d.value='';",
        desde, hasta)
    driver.execute_script("document.getElementById('MainContent_btnBuscar').click();")
    if not esperar_fin_carga(driver, ESPERA_MAX, 3):
        raise TimeoutError(f"La SMV no respondio a tiempo ({desde}-{hasta})")
    # comprobar que la busqueda tomo las fechas (si no, el resultado no sirve)
    v = driver.find_element(By.ID, "txtFechDesde").get_attribute("value")
    if v != desde:
        raise RuntimeError(f"La SMV no aplico el filtro de fechas (quedo '{v}')")


def leer_resultados(driver):
    """Lee las tarjetas de resultados con un solo script (rapido)."""
    return driver.execute_script(r"""
        var out=[];
        document.querySelectorAll('table[id^="MainContent_grdHechosImportancia2_grdDetalle"] tr')
          .forEach(function(tr){
            var card=tr.querySelector('.card-body'); if(!card) return;
            var cab=(card.querySelector('p.text-blue')||{}).innerText||'';
            var tipo=(card.querySelector('.card-title')||{}).innerText||'';
            var acuerdo=((card.querySelector('span.small')||{}).innerText||'').replace(/Fecha de acuerdo:\s*/,'');
            var desc=(card.querySelector('p.card-text')||{}).innerText||'';
            var docs=[].map.call(card.querySelectorAll('a[href*="documento.aspx"], a[href$=".pdf"]'),
                                 function(a){return a.href;});
            out.push({cab:cab.trim(), tipo:tipo.trim(), acuerdo:acuerdo.trim(),
                      desc:desc.trim(), docs:docs});
          });
        return out;""")


def ventanas():
    a = ANIO_INICIO
    while a <= ANIO_FIN:
        b = min(a + ANIOS_POR_VENTANA - 1, ANIO_FIN)
        yield f"01/01/{a}", f"31/12/{b}"
        a = b + 1


def descargar_doc(url, destino):
    try:
        r = requests.get(url, timeout=90, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200 or len(r.content) < 500:
            return False
        ext = ".pdf"
        ctype = r.headers.get("Content-Type", "")
        cd = r.headers.get("Content-Disposition", "")
        m = re.search(r'filename="?([^";]+)', cd)
        if m and "." in m.group(1):
            ext = os.path.splitext(m.group(1))[1][:6] or ext
        elif "html" in ctype:
            ext = ".html"
        with open(destino + ext, "wb") as f:
            f.write(r.content)
        return True
    except Exception as e:
        print(f"      [!] no se pudo descargar {url}: {e}")
        return False


def anexar_csv(ruta, filas, campos):
    nuevo = not os.path.exists(ruta)
    with open(ruta, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        if nuevo:
            w.writeheader()
        for fila in filas:
            w.writerow(fila)


def empresas_terminadas(ruta_resumen):
    if not os.path.exists(ruta_resumen):
        return set()
    with open(ruta_resumen, encoding="utf-8-sig") as f:
        return {r["codigo_smv"] for r in csv.DictReader(f)}


def procesar_empresa(driver, codigo, nombre, estado, rutas):
    seleccionar_empresa(driver, codigo, nombre, estado)
    vistos = set()
    todos, candidatos = [], []
    for desde, hasta in ventanas():
        for intento in (1, 2):
            try:
                buscar_rango(driver, desde, hasta)
                break
            except Exception as e:
                print(f"    [!] {desde}-{hasta}: {e} (intento {intento})")
                if intento == 2:
                    raise
                abrir_pagina(driver)
                seleccionar_empresa(driver, codigo, nombre, estado)
        for r in leer_resultados(driver):
            m = re.search(r"EXP\.\s*(\d+)\s*DEL\s*([\d/]+)", r["cab"])
            exp = m.group(1) if m else ""
            fecha = m.group(2) if m else ""
            clave = (exp, r["tipo"], r["desc"][:80])
            if clave in vistos:
                continue
            vistos.add(clave)
            fila = {"empresa": nombre, "codigo_smv": codigo, "estado": estado,
                    "expediente": exp, "fecha_presentacion": fecha,
                    "fecha_acuerdo": r["acuerdo"],
                    "tipo": re.sub(r"^\d+\s*-\s*", "", r["tipo"]),
                    "descripcion": r["desc"], "documentos": " ".join(r["docs"])}
            todos.append(fila)
            pal = es_candidato(fila["tipo"], fila["descripcion"])
            if pal:
                c = dict(fila)
                c["palabras_clave"] = ", ".join(pal)
                candidatos.append(c)
        print(f"    {desde}-{hasta}: acumulado {len(todos)} hechos, {len(candidatos)} candidatos")

    anexar_csv(rutas["todos"], todos, CAMPOS)
    anexar_csv(rutas["cand"], candidatos, CAMPOS + ["palabras_clave"])

    if DESCARGAR_DOCS:
        carpeta = os.path.join(OUT_DIR, "docs", limpiar_nombre(nombre))
        for c in candidatos:
            for i, url in enumerate(c["documentos"].split()):
                os.makedirs(carpeta, exist_ok=True)
                fecha = c["fecha_presentacion"].replace("/", "-")
                descargar_doc(url, os.path.join(carpeta, f"{fecha}_EXP{c['expediente']}_{i+1}"))

    anexar_csv(rutas["resumen"], [{"empresa": nombre, "codigo_smv": codigo, "estado": estado,
                                   "hechos": len(todos), "candidatos": len(candidatos)}],
               ["empresa", "codigo_smv", "estado", "hechos", "candidatos"])


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rutas = {k: os.path.join(OUT_DIR, f"{n}_tanda{BATCH}.csv") for k, n in
             [("todos", "hechos_todos"), ("cand", "hechos_candidatos"), ("resumen", "resumen")]}
    driver = setup_driver()
    try:
        universo = listar_universo(driver)
        print(f"[info] Universo: {len(universo)} empresas "
              f"({sum(1 for u in universo if u[2]=='retirada')} retiradas)")
        with open(os.path.join(OUT_DIR, "universo_empresas.csv"), "w", newline="",
                  encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["codigo_smv", "empresa", "estado"])
            for v, t, e in universo:
                w.writerow([v, t, e])

        mias = universo[BATCH - 1::NUM_TANDAS]
        if LIMITE_EMPRESAS:
            mias = mias[:LIMITE_EMPRESAS]
        hechas = empresas_terminadas(rutas["resumen"])
        print(f"[info] TANDA {BATCH}/{NUM_TANDAS}: {len(mias)} empresas ({len(hechas)} ya hechas)")

        for n, (codigo, nombre, estado) in enumerate(mias, 1):
            if codigo in hechas:
                continue
            print(f"\n[{n}/{len(mias)}] {nombre} ({estado})")
            for intento in (1, 2):
                try:
                    procesar_empresa(driver, codigo, nombre, estado, rutas)
                    break
                except Exception:
                    traceback.print_exc()
                    print(f"  [!] fallo la empresa (intento {intento}); reabriendo navegador")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = setup_driver()
                    abrir_pagina(driver)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
