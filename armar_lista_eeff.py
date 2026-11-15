# -*- coding: utf-8 -*-
"""
Arma empresas_eeff.txt (la lista que usa scrape_smv_v3.py) a partir de los
resultados del buscador de Hechos de Importancia.

USO (en tu PC, despues de descargar y descomprimir los artifacts
"hechos-importancia-tanda-N" dentro de una carpeta, ej. resultados_hi/):

    python armar_lista_eeff.py resultados_hi

Orden de la lista:
  1. Empresas con candidatos en hechos de importancia (mas candidatos primero)
  2. El resto del universo de empresas (por si tienen eventos pequenos que solo
     aparecen en las notas de los EEFF), sin bancos, AFP, fondos, SAB ni
     sociedades titulizadoras, que casi nunca tienen inmuebles propios
     relevantes para el trabajo.
Se excluyen las empresas de empresas_hechas.txt (ya descargadas).
Ademas junta todos los candidatos en un solo archivo: candidatos_todos.csv
"""

import csv
import difflib
import glob
import os
import re
import sys
import unicodedata

EXCLUIR_SECTOR = re.compile(
    r"\bBANCO\b|\bBANK\b|\bAFP\b|FONDO|\bSAB\b|SOCIEDAD AGENTE DE BOLSA|TITULIZ|"
    r"SOCIEDAD ADMINISTRADORA|CAJA MUNICIPAL|FINANCIERA|LEASING|FIDUCIARIA|"
    r"PATRIMONIO EN FIDEICOMISO|\bS\.?A\.?F\.?\b|SOCIEDAD TITULIZADORA")


def normalizar(t):
    t = unicodedata.normalize("NFKD", t or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).upper()
    t = re.sub(r"\(.*?\)", " ", t)                      # quita "(ANTES ...)"
    t = re.sub(r"\bS\.?\s?A\.?\s?A\.?\b|\bS\.?\s?A\.?\b|\bS\.?A\.?C\.?\b", " ", t)
    t = re.sub(r"[^A-Z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parecida(a, lista):
    na = normalizar(a)
    for b in lista:
        nb = normalizar(b)
        if na == nb or na in nb or nb in na:
            return True
        if difflib.SequenceMatcher(None, na, nb).ratio() >= 0.85:
            return True
    return False


def leer_lista(ruta):
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8-sig") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def main():
    carpeta = sys.argv[1] if len(sys.argv) > 1 else "resultados_hi"
    hechas = leer_lista("empresas_hechas.txt")

    universo = {}
    for ruta in glob.glob(os.path.join(carpeta, "**", "universo_empresas.csv"), recursive=True):
        with open(ruta, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                universo[r["codigo_smv"]] = r
    conteo, filas_cand = {}, []
    campos = None
    for ruta in glob.glob(os.path.join(carpeta, "**", "hechos_candidatos_tanda*.csv"), recursive=True):
        with open(ruta, encoding="utf-8-sig") as f:
            lector = csv.DictReader(f)
            campos = campos or lector.fieldnames
            for r in lector:
                filas_cand.append(r)
                conteo[r["empresa"]] = conteo.get(r["empresa"], 0) + 1

    if filas_cand:
        with open("candidatos_todos.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=campos)
            w.writeheader()
            w.writerows(filas_cand)

    con_eventos = sorted(conteo, key=lambda e: -conteo[e])
    resto = sorted(r["empresa"] for r in universo.values()
                   if r["empresa"] not in conteo and not EXCLUIR_SECTOR.search(r["empresa"].upper()))

    salida, saltadas = [], []
    for e in con_eventos + resto:
        (saltadas if parecida(e, hechas) else salida).append(e)

    with open("empresas_eeff.txt", "w", encoding="utf-8") as f:
        f.write("# Generado por armar_lista_eeff.py\n")
        f.write(f"# {len(con_eventos)} empresas con candidatos en hechos de importancia van primero\n")
        for e in salida:
            f.write(e + "\n")

    print(f"Universo: {len(universo)} empresas")
    print(f"Con candidatos en hechos de importancia: {len(con_eventos)} "
          f"({len(filas_cand)} hechos candidatos en total)")
    print(f"Saltadas por estar en empresas_hechas.txt: {len(saltadas)}")
    print(f"empresas_eeff.txt: {len(salida)} empresas")


if __name__ == "__main__":
    main()
