#!/usr/bin/env python3
"""
Parser de Redespacho Semanal CAMMESA (.xls)
=============================================
Lee todos los .xls en redespaches/, extrae los datos del redespacho y
los guarda en processed/redespaches.json. Luego genera processed/
comparacion_redespacho.json cruzando con processed/historico.json
(la programación original del .mdb) para mostrar las diferencias.

Un redespacho es un ajuste que CAMMESA emite DURANTE la semana para
corregir la programación original. No ocurre necesariamente todas las
semanas. Contiene:
  - Motivos del redespacho (texto libre)
  - Balance diario por tecnología (GWh)
  - Despacho hidráulico diario por central (MWh)
  - Consumo de combustibles diario
  - Cotas previstas de embalses al fin de la semana
  - Costos marginales previstos para el resto de la semana

La clave de identificación es el número de semana (campo "SEMANA" del
propio archivo). Es idempotente: subir de nuevo el mismo redespacho
reemplaza el existente.

USO:
    python3 scripts/parse_redespacho.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("Falta pandas/xlrd. Instalar con: pip install pandas xlrd", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parent.parent
REDESPACHES_DIR = ROOT / "redespaches"
OUT_DIR = ROOT / "processed"
REDESPACHO_JSON = OUT_DIR / "redespaches.json"
HISTORICO_JSON = OUT_DIR / "historico.json"
COMPARACION_JSON = OUT_DIR / "comparacion_redespacho.json"

DIAS = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]

UNIDADES_COMBUSTIBLE = {
    "Gas (Dam3)": "Dam³", "GO": "m³", "FO": "Ton", "CM": "Ton",
    "GasAcue": "Dam³", "GasProp": "Dam³",
}

# Mapa para normalizar nombres de combustibles del redespacho al historico
MAP_COMBUSTIBLE = {
    "Gas (Dam3)": ["GasAcue", "GasProp"],  # el redespacho usa Gas total
    "GO": ["Dies_Oil"],
    "FO": ["Fuel_Oil"],
    "CM": ["Carbon"],
}

# Mapa tecnología redespacho → var del historico
MAP_TECNOLOGIA = {
    "TÉRMICO": "GEN_TER", "TÉRMICO ": "GEN_TER",
    "HIDRÁULICO": "GEN_HID", "HIDRÁULICO ": "GEN_HID",
    "NUCLEAR": "GEN_NUC",
    "RENOVABLE": "GEN_REN",
    "IMPORTACIÓN": "GEN_IMP", "IMPORTACIÓN ": "GEN_IMP",
}


def to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def find_row(df, *textos):
    """Devuelve el índice de la primera fila que contiene alguno de los textos dados."""
    for i, row in df.iterrows():
        for v in row.values:
            if isinstance(v, str) and any(t.upper() in v.upper() for t in textos):
                return i
    return None


def leer_dias(df, row_idx):
    """Lee 7 valores de las columnas 3 a 9 de una fila dada."""
    row = df.iloc[row_idx]
    return [to_float(row.iloc[j]) for j in range(3, 10)]


def parsear_xls(xls_path: Path) -> dict:
    df = pd.read_excel(str(xls_path), engine="xlrd", header=None)

    # --- Cabecera: número de semana y fecha de emisión ---
    # El número de semana está fijo en fila 3, columna 4 (0-indexed) del XLS
    num_semana, fecha_emision = None, None
    try:
        val_sem = df.iloc[3, 4]
        if pd.notna(val_sem) and 1 <= float(val_sem) <= 53:
            num_semana = int(float(val_sem))
    except (IndexError, ValueError, TypeError):
        pass
    # Fecha de emisión: buscar el datetime en la cabecera (fila 3, cols 3-9)
    for j in range(3, 10):
        v = df.iloc[3, j]
        if isinstance(v, datetime) or (hasattr(pd, "Timestamp") and isinstance(v, pd.Timestamp)):
            fecha_emision = pd.Timestamp(v).isoformat(timespec="seconds")
            break
    if num_semana is None:
        raise ValueError(f"No se encontró número de semana en {xls_path.name}")

    # --- Motivos del redespacho ---
    motivos = []
    i = 0
    while i < len(df):
        row = df.iloc[i]
        for v in row.values:
            if isinstance(v, str) and v.strip() and v.strip() not in ("nan", "NaT"):
                txt = v.strip()
                if any(kw in txt.upper() for kw in ("SEMANA", "REDESPACHO", "GERENCIA", "ENERGÍAS",
                                                       "HID OPTIM", "COMBUSTIBLE", "COTAS", "COSTO", "MERCADO",
                                                       "BALANCE", "LUNES", "MAYOR DISP", "MENOR DEM")):
                    if txt.upper().startswith("MAYOR ") or txt.upper().startswith("MENOR "):
                        motivos.append(txt)
        i += 1
        if len(motivos) >= 6:
            break

    # Más preciso: las filas 5 y 7 (0-indexed) suelen contener los motivos
    motivos = []
    for idx in range(5, 15):
        if idx >= len(df):
            break
        row = df.iloc[idx]
        for v in row.values:
            if isinstance(v, str) and len(v.strip()) > 3 and v.strip() not in ("nan",):
                txt = v.strip()
                if not any(kw in txt.upper() for kw in ("SEMANA", "GERENCIA", "REDESPACHO", "ENERGÍA")):
                    motivos.append(txt)

    # --- Fechas de los días ---
    row_fechas = find_row(df, "ENERGÍAS HIDRÁULICAS")
    fechas_dias = []
    if row_fechas is not None:
        fecha_row = df.iloc[row_fechas + 1]
        for j in range(3, 10):
            v = fecha_row.iloc[j]
            try:
                if pd.notna(v):
                    fechas_dias.append(pd.Timestamp(v).strftime("%Y-%m-%d"))
                else:
                    fechas_dias.append(None)
            except Exception:
                fechas_dias.append(None)

    # --- Balance por tecnología (GWh/día) ---
    balance = {}
    tecs_buscadas = ["DEMANDA+BOMBEO", "TÉRMICO", "NUCLEAR", "HIDRÁULICO", "RENOVABLE",
                     "IMPORTACIÓN", "EXPORTACIÓN TOTAL"]
    for tec in tecs_buscadas:
        idx = find_row(df, tec)
        if idx is not None:
            lbl = tec.strip()
            balance[lbl] = leer_dias(df, idx)

    # --- Hidráulico optimizable por central (MWh/día) ---
    idx_hid = find_row(df, "HID OPTIMIZABLE")
    hidro_centrales = {}
    if idx_hid is not None:
        for j in range(idx_hid + 1, min(idx_hid + 20, len(df))):
            row = df.iloc[j]
            nombre = None
            for v in row.values:
                if isinstance(v, str) and v.strip() and v.strip() not in ("nan",):
                    nombre = v.strip()
                    break
            if not nombre:
                break
            if any(kw in nombre.upper() for kw in ("COMBUSTIBLE", "GAS", "COTA", "COSTO", "BALANCE")):
                break
            vals = leer_dias(df, j)
            if any(v is not None for v in vals):
                hidro_centrales[nombre] = vals

    # --- Combustibles (por día) ---
    idx_comb = find_row(df, "COMBUSTIBLES")
    combustibles = {}
    if idx_comb is not None:
        for j in range(idx_comb + 1, min(idx_comb + 10, len(df))):
            row = df.iloc[j]
            nombre = None
            for v in row.values:
                if isinstance(v, str) and v.strip() and v.strip() not in ("nan",):
                    nombre = v.strip()
                    break
            if not nombre:
                break
            if any(kw in nombre.upper() for kw in ("COTA", "COSTO", "BALANCE")):
                break
            vals = leer_dias(df, j)
            if any(v is not None for v in vals):
                combustibles[nombre] = {
                    "dias": vals,
                    "total": sum(v for v in vals if v is not None),
                    "unidad": UNIDADES_COMBUSTIBLE.get(nombre),
                }

    # --- Cotas previstas ---
    idx_cotas = find_row(df, "COTAS PREVISTAS")
    cotas = {}
    if idx_cotas is not None:
        for j in range(idx_cotas + 1, min(idx_cotas + 15, len(df))):
            row = df.iloc[j]
            vals = [v for v in row.values if str(v) not in ("nan", "NaT")]
            if not vals:
                break
            nombre = str(vals[0]).strip() if vals else None
            if not nombre or any(kw in nombre.upper() for kw in ("COSTO", "MERCADO", "BALANCE")):
                break
            cota_val = to_float(vals[1]) if len(vals) > 1 else None
            comentario = str(vals[2]).strip() if len(vals) > 2 else None
            cotas[nombre] = {"cota": cota_val, "comentario": comentario}

    # --- Costos marginales ---
    idx_cmg = find_row(df, "COSTOS MARGINALES")
    costos_marginales = {}
    if idx_cmg is not None:
        for bloque in ["VALLE", "RESTO", "PICO"]:
            idx_b = find_row(df, bloque)
            if idx_b is not None and idx_b > idx_cmg:
                vals = leer_dias(df, idx_b)
                costos_marginales[bloque] = {
                    "dias": vals,
                    "promedio": round(sum(v for v in vals if v) / len([v for v in vals if v]), 2) if vals else None,
                }

    # --- Balance energético semanal ---
    idx_bal = find_row(df, "BALANCE ENERGÉTICO")
    balance_semanal = {}
    if idx_bal is not None:
        etiquetas = {
            "DEMANDA BRUTA": "demanda_bruta", "TÉRMICO": "termico", "TÉRMICO ": "termico",
            "HIDRÁULICO": "hidraulico", "HIDRÁULICO ": "hidraulico",
            "NUCLEAR": "nuclear", "RENOVABLE": "renovable",
            "IMPORTACIÓN": "importacion", "BOMBEO": "bombeo", "EXPORTACIÓN": "exportacion",
        }
        for j in range(idx_bal + 1, min(idx_bal + 15, len(df))):
            row = df.iloc[j]
            vals = [v for v in row.values if str(v) not in ("nan", "NaT")]
            if not vals:
                continue
            for k, clave in etiquetas.items():
                if any(isinstance(v, str) and k.upper() in v.upper() for v in vals):
                    num = next((to_float(v) for v in reversed(vals) if to_float(v) is not None), None)
                    if num:
                        balance_semanal[clave] = num

    return {
        "archivo_origen": xls_path.name,
        "num_semana": num_semana,
        "fecha_emision": fecha_emision,
        "motivos": motivos,
        "fechas_dias": fechas_dias,
        "balance_diario_gwh": balance,
        "hidro_centrales_mwh": hidro_centrales,
        "combustibles": combustibles,
        "cotas_previstas": cotas,
        "costos_marginales": costos_marginales,
        "balance_semanal_gwh": balance_semanal,
    }


def generar_comparacion(redespaches: dict, historico: dict) -> dict:
    """Cruza cada redespacho contra la programación original del .mdb."""
    comparaciones = {}
    for key, rd in redespaches.items():
        ns = str(rd["num_semana"])
        if ns not in historico:
            continue
        prog = historico[ns]

        # Balance energético: redespachado vs. programado
        bal_rd = rd["balance_semanal_gwh"]
        gen_prog = prog.get("generacion_tecnologia", {})
        HORAS = 168.0

        comparacion_balance = {}
        mapa = {"termico": "GEN_TER", "hidraulico": "GEN_HID", "nuclear": "GEN_NUC",
                "renovable": "GEN_REN", "importacion": "GEN_IMP"}
        for lbl, var in mapa.items():
            val_rd = bal_rd.get(lbl)  # GWh
            prog_info = gen_prog.get(var, {})
            val_prog_gwh = (prog_info.get("total") or 0) / 1000  # MWh -> GWh
            if val_rd is None and val_prog_gwh == 0:
                continue
            delta = round(val_rd - val_prog_gwh, 2) if val_rd and val_prog_gwh else None
            pct = round(delta / val_prog_gwh * 100, 1) if delta and val_prog_gwh else None
            comparacion_balance[lbl] = {
                "programado_gwh": round(val_prog_gwh, 2),
                "redespachado_gwh": val_rd,
                "delta_gwh": delta,
                "delta_pct": pct,
            }

        # Combustibles: redespacho vs. programado
        comb_prog = prog.get("consumo_combustibles", {})
        comparacion_combustibles = {}
        for nombre, info_rd in rd["combustibles"].items():
            claves_prog = MAP_COMBUSTIBLE.get(nombre, [nombre])
            val_prog = sum((comb_prog.get(k) or {}).get("total", 0) for k in claves_prog)
            val_rd = info_rd["total"]
            delta = round(val_rd - val_prog, 2) if val_prog else None
            pct = round(delta / val_prog * 100, 1) if delta and val_prog else None
            comparacion_combustibles[nombre] = {
                "programado": round(val_prog, 1) if val_prog else None,
                "redespachado": round(val_rd, 1),
                "delta": delta,
                "delta_pct": pct,
                "unidad": info_rd["unidad"],
            }

        # Costo marginal: redespacho vs. programado
        precios_prog = prog.get("precios", {})
        comparacion_cmg = {}
        for bloque, info_rd in rd["costos_marginales"].items():
            val_prog = (precios_prog.get(bloque) or {}).get("promedio")
            val_rd = info_rd["promedio"]
            delta = round(val_rd - val_prog, 0) if val_rd and val_prog else None
            pct = round(delta / val_prog * 100, 1) if delta and val_prog else None
            comparacion_cmg[bloque] = {
                "programado": val_prog,
                "redespachado": val_rd,
                "delta": delta,
                "delta_pct": pct,
            }

        comparaciones[key] = {
            "num_semana": rd["num_semana"],
            "fecha_emision": rd["fecha_emision"],
            "motivos": rd["motivos"],
            "balance": comparacion_balance,
            "combustibles": comparacion_combustibles,
            "costo_marginal": comparacion_cmg,
            "hidro_centrales_mwh": rd["hidro_centrales_mwh"],
            "cotas_previstas": rd["cotas_previstas"],
            "fechas_dias": rd["fechas_dias"],
        }
    return comparaciones


def main():
    if not REDESPACHES_DIR.exists():
        print(f"No existe {REDESPACHES_DIR}. Nada que hacer.")
        return

    xls_files = sorted(REDESPACHES_DIR.glob("redespacho*.xls"))
    xls_files += sorted(REDESPACHES_DIR.glob("redespacho*.xlsx"))
    xls_files += sorted(REDESPACHES_DIR.glob("redespacho*.XLS"))
    xls_files = sorted(set(xls_files))
    if not xls_files:
        print("No se encontraron archivos .xls/.xlsx en redespaches/. Nada que hacer.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    redespaches = {}
    if REDESPACHO_JSON.exists():
        redespaches = json.loads(REDESPACHO_JSON.read_text())

    errores = []
    for xls_path in xls_files:
        print(f"Procesando {xls_path.name} ...")
        try:
            rd = parsear_xls(xls_path)
        except Exception as e:
            import traceback
            print(f"  ERROR: {e}", file=sys.stderr)
            errores.append({"archivo": xls_path.name, "error": str(e), "traceback": traceback.format_exc()})
            continue
        key = f"{rd['num_semana']}"
        # Si ya existe un redespacho para esta semana, quedarse con el más reciente
        if key in redespaches:
            existente = redespaches[key].get("fecha_emision") or ""
            nuevo     = rd.get("fecha_emision") or ""
            if nuevo > existente:
                redespaches[key] = rd
                print(f"  -> Semana {rd['num_semana']} ({rd['fecha_emision']}) OK — reemplaza versión anterior")
            else:
                print(f"  -> Semana {rd['num_semana']} ({rd['fecha_emision']}) — ya tenemos uno más reciente, salteando")
        else:
            redespaches[key] = rd
            print(f"  -> Semana {rd['num_semana']} ({rd['fecha_emision']}) OK — motivos: {rd['motivos']}")

    REDESPACHO_JSON.write_text(json.dumps(redespaches, indent=2, ensure_ascii=False, default=str))
    print(f"\nRedespaches guardados: {sorted(redespaches.keys())}")

    # Comparación contra programación original
    if HISTORICO_JSON.exists():
        historico = json.loads(HISTORICO_JSON.read_text())
        comparacion = generar_comparacion(redespaches, historico)
        COMPARACION_JSON.write_text(json.dumps(comparacion, indent=2, ensure_ascii=False, default=str))
        print(f"Comparación generada: {COMPARACION_JSON}")
    else:
        print("No existe historico.json — omitiendo comparación.", file=sys.stderr)

    if errores:
        (OUT_DIR / "redespacho_errors.json").write_text(json.dumps(errores, indent=2, ensure_ascii=False))
        print(f"\n¡ATENCIÓN! {len(errores)} redespacho(s) con error.")
        sys.exit(2)
    else:
        ep = OUT_DIR / "redespacho_errors.json"
        if ep.exists():
            ep.unlink()


if __name__ == "__main__":
    main()
