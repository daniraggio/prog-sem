#!/usr/bin/env python3
"""
ETL -> JSON histórico - Programación Semanal CAMMESA
=========================================================
Recorre TODOS los archivos .MDB en data/, extrae lo relevante de cada
semana y arma/actualiza processed/historico.json.

Diseñado para correr en GitHub Actions cada vez que se sube un .mdb
nuevo a data/, pero también funciona en local.

Es idempotente: si una semana (NumSemana) ya está en historico.json,
se recalcula y reemplaza (permite re-subir un .mdb corregido).

USO:
    python3 scripts/etl_to_json.py

Requiere mdbtools instalado (mdb-export). No usa librerías externas
de Python (solo stdlib) para minimizar dependencias en CI.
"""
import csv
import io
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "processed"
HISTORICO_PATH = OUT_DIR / "historico.json"

DIA_COLS = ["Dia1", "Dia2", "Dia3", "Dia4", "Dia5", "Dia6", "Dia7"]

# Unidades de Alto Valle a trackear en su sección especial
ALTO_VALLE_UNIDADES = ["AVALCC22", "AVALCC23", "AVALTG21", "AVALTG22", "AVALTG23"]

TECNOLOGIAS = {
    "GEN_HID": "Hidráulica",
    "GEN_TER": "Térmica",
    "GEN_NUC": "Nuclear",
    "GEN_REN": "Renovable",
    "GEN_IMP": "Importación",
}


def mdb_export(mdb_path: Path, tabla: str) -> list[dict]:
    res = subprocess.run(
        ["mdb-export", "-D", "%m/%d/%y %H:%M:%S", str(mdb_path), tabla],
        capture_output=True, text=True, check=True,
    )
    return list(csv.DictReader(io.StringIO(res.stdout)))


def to_float(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_finicio(finicio: str):
    for fmt in ("%m/%d/%y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(finicio, fmt)
        except ValueError:
            continue
    return None


def fechas_semana(finicio_str):
    f0 = parse_finicio(finicio_str)
    if not f0:
        return [None] * 7
    return [(f0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def procesar_mdb(mdb_path: Path) -> dict:
    """Extrae de un .mdb todo lo necesario para una semana, en forma compacta."""
    fecha_rows = mdb_export(mdb_path, "FECHA")
    if not fecha_rows:
        raise ValueError(f"{mdb_path}: tabla FECHA vacía")
    num_semana = int(fecha_rows[0]["NumSemana"])
    finicio = fecha_rows[0]["FInicio"]
    fechas = fechas_semana(finicio)

    semana = {
        "num_semana": num_semana,
        "finicio": finicio,
        "fechas": fechas,
        "archivo_origen": mdb_path.name,
    }

    # ---- RESUMEN (totales de mercado) ----
    resumen_rows = mdb_export(mdb_path, "RESUMEN")
    semana["resumen_totales"] = {
        r["Var"]: {"descrip": r["Descrip"], "total": to_float(r.get("Total")),
                    "dias": [to_float(r.get(d)) for d in DIA_COLS]}
        for r in resumen_rows
    }

    # ---- GENERACION ----
    gen_rows = mdb_export(mdb_path, "GENERACION")

    # Nivel 1: tecnología agregada nacional (Region vacía)
    gen_tecnologia = {}
    for r in gen_rows:
        if r.get("Region") == "" and (r.get("Empresa") or "") == "":
            var = r["Var"]
            gen_tecnologia[var] = {
                "label": TECNOLOGIAS.get(var, var),
                "total": to_float(r.get("Total")),
                "dias": [to_float(r.get(d)) for d in DIA_COLS],
            }
    semana["generacion_tecnologia"] = gen_tecnologia

    # Nivel 3: central (Empresa cargada, Generador vacío)
    gen_centrales = []
    for r in gen_rows:
        if (r.get("Generador") or "") == "" and (r.get("Empresa") or "") != "":
            gen_centrales.append({
                "var": r["Var"], "tecnologia": TECNOLOGIAS.get(r["Var"], r["Var"]),
                "region": r["Region"], "empresa": r["Empresa"],
                "total": to_float(r.get("Total")) or 0,
                "dias": [to_float(r.get(d)) for d in DIA_COLS],
            })
    semana["generacion_centrales"] = gen_centrales

    # Nivel 4: unidad (Generador cargado) -> guardamos TODAS para poder calcular
    # heurísticas de disponibilidad histórica y potencia equivalente en el análisis
    gen_unidades = []
    for r in gen_rows:
        if (r.get("Generador") or "") != "":
            total = to_float(r.get("Total")) or 0
            dias = [to_float(r.get(d)) for d in DIA_COLS]
            gen_unidades.append({
                "unidad": r["Generador"], "tipo_maq": r["TipoMaq"], "var": r["Var"],
                "empresa": r["Empresa"], "region": r["Region"],
                "total": total, "dias": dias,
            })
    semana["generacion_unidades"] = gen_unidades

    # ---- CONSUMO_COMB ----
    comb_rows = mdb_export(mdb_path, "CONSUMO_COMB")
    semana["consumo_combustibles"] = {
        r["Combustible"]: {"total": to_float(r.get("Total")),
                            "dias": [to_float(r.get(d)) for d in DIA_COLS]}
        for r in comb_rows
    }

    # ---- PRECIOS ----
    # La variable de costo marginal horario cambió de nombre entre archivos: la mayoría de las
    # semanas usan "CMgh", pero en algunas CAMMESA la llama "CMO" (misma magnitud, ~mismo orden
    # de valores). Hay además una variable "MER" (precio de referencia, escala totalmente distinta,
    # ~10-20 mil vs. ~200-300 mil) que NO es costo marginal y no debe mezclarse.
    # Elegimos explícitamente una sola variable por prioridad, nunca combinamos varias bajo el
    # mismo Bloque (eso pisaba datos silenciosamente).
    precios_rows = mdb_export(mdb_path, "PRECIOS")
    PRIORIDAD_VAR_CMG = ["CMgh", "CMO"]
    vars_presentes = {r["Var"] for r in precios_rows}
    var_elegida = next((v for v in PRIORIDAD_VAR_CMG if v in vars_presentes), None)

    precios = {}
    for r in precios_rows:
        if var_elegida is not None and r["Var"] != var_elegida:
            continue
        bloque = r["Bloque"]
        dias = [to_float(r.get(d)) for d in DIA_COLS]
        validos = [d for d in dias if d is not None]
        precios[bloque] = {
            "region": r["Region"], "var_origen": r["Var"],
            "promedio": round(sum(validos) / len(validos), 2) if validos else None,
            "dias": dias,
        }
    semana["precios"] = precios
    semana["precios_var_origen"] = var_elegida
    semana["precios_vars_disponibles"] = sorted(vars_presentes)

    # ---- COTAS (universo de embalses reportados, para detectar altas/bajas) ----
    cotas_rows = mdb_export(mdb_path, "COTAS")
    semana["cotas"] = {r["CentHidr"]: {"cota_ini": to_float(r.get("CotaIni")),
                                        "cota_fin": to_float(r.get("CotaFin"))}
                        for r in cotas_rows}

    # ---- VALORES_AGUA (comentarios de restricciones operativas) ----
    va_rows = mdb_export(mdb_path, "VALORES_AGUA")
    semana["valores_agua"] = [
        {"region": r["Region"], "cent_hidr": r["CentHidr"], "valor": to_float(r.get("Valor")),
         "comentario": r.get("Comentario")}
        for r in va_rows
    ]

    # ---- TEMPERATURAS ----
    temp_rows = mdb_export(mdb_path, "TEMPERATURAS")
    if temp_rows:
        dias_t = [to_float(temp_rows[0].get(d)) for d in DIA_COLS]
        validos = [d for d in dias_t if d is not None]
        semana["temperatura_media"] = round(sum(validos) / len(validos), 1) if validos else None
    else:
        semana["temperatura_media"] = None

    return semana


def main():
    if not DATA_DIR.exists():
        print(f"No existe {DATA_DIR}", file=sys.stderr)
        sys.exit(1)

    mdb_files = sorted(DATA_DIR.glob("*.MDB")) + sorted(DATA_DIR.glob("*.mdb"))
    mdb_files = sorted(set(mdb_files))
    if not mdb_files:
        print("No se encontraron archivos .mdb en data/. Nada que hacer.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    historico = {}
    if HISTORICO_PATH.exists():
        historico = json.loads(HISTORICO_PATH.read_text())

    for mdb_path in mdb_files:
        print(f"Procesando {mdb_path.name} ...")
        try:
            semana = procesar_mdb(mdb_path)
        except Exception as e:
            print(f"  ERROR procesando {mdb_path.name}: {e}", file=sys.stderr)
            continue
        historico[str(semana["num_semana"])] = semana
        print(f"  -> Semana {semana['num_semana']} ({semana['finicio']}) OK")

    HISTORICO_PATH.write_text(json.dumps(historico, indent=2, ensure_ascii=False))
    print(f"\nHistórico actualizado: {HISTORICO_PATH}")
    print(f"Semanas en la base: {sorted(int(k) for k in historico.keys())}")


if __name__ == "__main__":
    main()
