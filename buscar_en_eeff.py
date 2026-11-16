# -*- coding: utf-8 -*-
"""
Busca palabras clave DENTRO de los PDF de EEFF descargados (zips del scraper)
y arma un "paquete" de paginas relevantes por empresa para pasarselo a la IA.
Asi la IA lee 20-40 paginas por empresa en vez de cientos.

USO (en tu PC, con los zips descargados en una carpeta, ej. SMV_Data/):

    pip install pypdf cryptography
    python buscar_en_eeff.py SMV_Data

SALIDA (carpeta extractos/):
    paginas_relevantes.csv     -> empresa, archivo, pagina, palabras, puntaje
    <empresa>.txt              -> texto de las paginas relevantes, con el
                                  archivo y numero de pagina de cada una
                                  (esto es lo que se sube a la IA)
"""

import csv
import io
import os
import re
import sys
import unicodedata
import zipfile

from pypdf import PdfReader

# palabra -> peso. Las de evento pesan mas que las de contexto.
PALABRAS = {
    # eventos
    "expropia": 5, "justiprecio": 5, "ley 30025": 5, "trato directo": 4,
    "indemnizacion": 3, "venta de inmueble": 4, "venta de terreno": 4,
    "venta de propiedad": 4, "enajenacion": 3, "compraventa": 3,
    "transferencia de inmueble": 4, "transferencia de terreno": 4,
    "ganancia en venta": 3, "perdida en venta": 3, "utilidad en venta": 3,
    "ingreso por venta de activo": 3, "baja de activo": 2, "dacion en pago": 3,
    "mantenidos para la venta": 3, "niif 5": 2,
    # contexto de medicion
    "propiedades de inversion": 2, "propiedad de inversion": 2, "nic 40": 2,
    "nic 16": 1, "valor razonable": 1, "revaluacion": 2, "excedente de revaluacion": 2,
    "tasacion": 2, "tasador": 2, "perito": 1, "modelo del costo": 2, "modelo de costo": 2,
    "costo atribuido": 1, "terrenos": 1, "inmuebles": 1,
}
UMBRAL = 5          # puntaje minimo para que una pagina entre al paquete
EXIGE_EVENTO = True  # la pagina debe tener al menos una palabra de evento
EVENTO = {k for k, v in PALABRAS.items() if v >= 3}


def normalizar(t):
    t = unicodedata.normalize("NFKD", t or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", t)


def puntuar(texto):
    t = normalizar(texto)
    hallados = {k: t.count(k) for k in PALABRAS if k in t}
    puntaje = sum(PALABRAS[k] * min(n, 3) for k, n in hallados.items())
    return puntaje, hallados


def pdfs_en(carpeta):
    """Devuelve (empresa, nombre_archivo, bytes) de PDFs sueltos y dentro de zips."""
    for raiz, _, archivos in os.walk(carpeta):
        for a in archivos:
            ruta = os.path.join(raiz, a)
            if a.lower().endswith(".zip"):
                # nombre del zip: EEFFDD-<Empresa>-Individual.zip
                empresa = re.sub(r"^(EEFFDD|EEFF-EMPRESAS)-|-(Individual|Consolidado)\.zip$", "", a)
                try:
                    with zipfile.ZipFile(ruta) as z:
                        for n in z.namelist():
                            if n.lower().endswith(".pdf"):
                                yield empresa, f"{a}/{n}", z.read(n)
                except zipfile.BadZipFile:
                    print(f"[!] zip danado: {ruta}")
            elif a.lower().endswith(".pdf"):
                yield os.path.basename(raiz), a, open(ruta, "rb").read()


def main():
    carpeta = sys.argv[1] if len(sys.argv) > 1 else "SMV_Data"
    os.makedirs("extractos", exist_ok=True)
    filas = []
    paquetes = {}
    vistos = set()
    no_abiertos = []
    for empresa, archivo, datos in pdfs_en(carpeta):
        # los reportes tabulares (EEFF-EMPRESAS) no tienen notas: se saltan
        if archivo.startswith("EEFF-EMPRESAS"):
            continue
        clave = (empresa, os.path.basename(archivo), len(datos))
        if clave in vistos:
            continue
        vistos.add(clave)
        try:
            lector = PdfReader(io.BytesIO(datos))
            paginas = list(lector.pages)
        except Exception as e:
            # PDF protegido, danado o raro: se anota y se sigue con el siguiente
            print(f"[!] no se pudo abrir {archivo}: {e}")
            no_abiertos.append(archivo)
            continue
        sin_texto = 0
        for i, pagina in enumerate(paginas, 1):
            try:
                texto = pagina.extract_text() or ""
            except Exception:
                texto = ""
            if len(texto.strip()) < 50:
                sin_texto += 1
                continue
            puntaje, hallados = puntuar(texto)
            if puntaje < UMBRAL or (EXIGE_EVENTO and not (set(hallados) & EVENTO)):
                continue
            filas.append({"empresa": empresa, "archivo": archivo, "pagina": i,
                          "puntaje": puntaje, "palabras": ", ".join(sorted(hallados))})
            paquetes.setdefault(empresa, []).append(
                f"\n===== ARCHIVO: {archivo} | PAGINA: {i} | puntaje {puntaje} =====\n{texto}\n")
        if sin_texto > 0.5 * max(1, len(paginas)):
            print(f"[aviso] {archivo}: {sin_texto} paginas sin texto (PDF escaneado; "
                  f"revisarlo a mano o con OCR)")

    with open("extractos/paginas_relevantes.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["empresa", "archivo", "pagina", "puntaje", "palabras"])
        w.writeheader()
        w.writerows(sorted(filas, key=lambda r: (r["empresa"], -r["puntaje"])))
    for empresa, partes in paquetes.items():
        nombre = re.sub(r'[<>:"/\\|?*]', "_", empresa)[:80]
        with open(f"extractos/{nombre}.txt", "w", encoding="utf-8") as f:
            f.write(f"EMPRESA: {empresa}\n")
            f.writelines(partes)
    with open("extractos/no_abiertos.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(no_abiertos))
    print(f"{len(no_abiertos)} PDF no se pudieron abrir (ver extractos/no_abiertos.txt)")
    print(f"{len(filas)} paginas relevantes en {len(paquetes)} empresas -> carpeta extractos/")


if __name__ == "__main__":
    main()
