#!/usr/bin/env python3
"""
Análisis comparativo - Programación Semanal CAMMESA
========================================================
Lee processed/historico.json y genera processed/analisis.json con,
para CADA semana disponible: KPIs propios + comparación vs. semana
anterior y vs. promedio de hasta 4 semanas previas, ranking de cambios
por central, unidades sin generación (solo el dato real: lista y
conteo, sin inferir causa ni potencia), y sección especial Alto Valle.

Nota sobre "potencia": el .mdb de programación NO trae potencia nominal
(MW) instalada de cada unidad, solo energía programada (MWh/semana).
Por eso reportamos "potencia media equivalente" = MWh / 168h, que es la
potencia constante que, sostenida toda la semana, produciría esa energía.
No es la potencia instalada de la máquina.

USO:
    python3 scripts/analisis.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "processed"
HISTORICO_PATH = OUT_DIR / "historico.json"
ANALISIS_PATH = OUT_DIR / "analisis.json"

UMBRAL_CENTRAL_PCT = 10.0
UMBRAL_DEMANDA_PCT = 5.0
UMBRAL_COMBUSTIBLE_PCT = 15.0
UMBRAL_CMG_PCT = 10.0
HORAS_SEMANA = 168.0

TECNOLOGIAS = {
    "GEN_HID": "Hidráulica", "GEN_TER": "Térmica", "GEN_NUC": "Nuclear",
    "GEN_REN": "Renovable", "GEN_IMP": "Importación",
}

ALTO_VALLE_UNIDADES = ["AVALCC22", "AVALCC23", "AVALTG21", "AVALTG22", "AVALTG23"]

# Unidades de medida de CONSUMO_COMB, según el dataset público oficial de CAMMESA
# ("Consumo de combustibles por tipo de máquina y tipo de tecnología", datos.gob.ar):
# Gas Natural [Dam3] - Fuel Oil [Ton] - Gas Oil [M3] - Carbón Mineral [Ton].
# GasAcue/GasProp son las dos vías de gas natural (por gasoducto / propio-contratado).
UNIDADES_COMBUSTIBLE = {
    "Carbon": "Ton", "Dies_Oil": "m³", "Fuel_Oil": "Ton",
    "GasAcue": "Dam³", "GasProp": "Dam³",
}


def pct_change(actual, anterior):
    if actual is None or anterior in (None, 0):
        return None
    return round((actual - anterior) / abs(anterior) * 100, 1)


def mw_equiv(mwh_total):
    if mwh_total is None:
        return None
    return round(mwh_total / HORAS_SEMANA, 1)


def gen_tecnologia_resumen(semana):
    out = {}
    total = 0
    for var, info in semana.get("generacion_tecnologia", {}).items():
        label = TECNOLOGIAS.get(var, var)
        out[label] = info["total"]
        total += info["total"] or 0
    out["__total__"] = total
    for label in list(out.keys()):
        if label != "__total__" and out[label] and total:
            out[f"{label}_pct"] = round(out[label] / total * 100, 1)
    return out


def demanda_resumen(semana):
    rt = semana.get("resumen_totales", {})
    return {
        "demanda_neta": (rt.get("DEMNETA") or {}).get("total"),
        "demanda_bruta": (rt.get("DEMBRUTA") or {}).get("total"),
        "importacion": (rt.get("IMPORT") or {}).get("total"),
        "exportacion": (rt.get("EXPORT") or {}).get("total"),
    }


def centrales_dict(semana):
    return {f"{c['region']}|{c['empresa']}": c for c in semana.get("generacion_centrales", [])}


def comparar_centrales(actual_sem, anterior_sem):
    """Devuelve TODAS las centrales (con y sin cambio relevante) en una sola lista,
    cada una marcada con cambio_relevante=True/False, más un resumen agregado."""
    actual = centrales_dict(actual_sem)
    anterior = centrales_dict(anterior_sem) if anterior_sem else {}
    todas = []
    for key, c in actual.items():
        mwh_act = c["total"] or 0
        mwh_ant = (anterior.get(key) or {}).get("total", 0) or 0
        var = pct_change(mwh_act, mwh_ant)
        evento = None
        if mwh_ant == 0 and mwh_act > 0:
            evento = "ENTRA_EN_SERVICIO"
        elif mwh_ant > 0 and mwh_act == 0:
            evento = "SALE_DE_SERVICIO"
        cambio_relevante = bool(evento) or (var is not None and abs(var) >= UMBRAL_CENTRAL_PCT)
        todas.append({
            "central": c["empresa"], "region": c["region"], "tecnologia": c["tecnologia"],
            "mwh_actual": mwh_act, "mwh_anterior": mwh_ant, "variacion_pct": var, "evento": evento,
            "mw_equiv": mw_equiv(mwh_act), "cambio_relevante": cambio_relevante,
        })
    todas.sort(key=lambda x: (not x["cambio_relevante"],
                               -(abs(x["variacion_pct"]) if x["variacion_pct"] is not None else 1e9)))

    con = [c for c in todas if c["cambio_relevante"]]
    sin = [c for c in todas if not c["cambio_relevante"]]
    resumen = {
        "con_cambio": {
            "cantidad": len(con), "mwh_total": round(sum(c["mwh_actual"] for c in con), 1),
            "mw_equiv_total": round(sum(c["mwh_actual"] for c in con) / HORAS_SEMANA, 1),
        },
        "sin_cambio": {
            "cantidad": len(sin), "mwh_total": round(sum(c["mwh_actual"] for c in sin), 1),
            "mw_equiv_total": round(sum(c["mwh_actual"] for c in sin) / HORAS_SEMANA, 1),
        },
    }
    return todas, resumen


ORDEN_COMBUSTIBLES = ["GasAcue", "GasProp", "Fuel_Oil", "Dies_Oil", "Carbon"]
ORDEN_BLOQUES_CMG = ["PICO", "RESTO", "VALLE"]


def combustibles_todos(actual_sem, anterior_sem):
    """TODOS los combustibles, en orden fijo, con su variación (no solo los que superan
    el umbral) — para el cuadro lateral de la sección Combustibles."""
    actual = actual_sem.get("consumo_combustibles", {})
    anterior = (anterior_sem or {}).get("consumo_combustibles", {})
    out = []
    claves = ORDEN_COMBUSTIBLES + [c for c in actual if c not in ORDEN_COMBUSTIBLES]
    for comb in claves:
        if comb not in actual:
            continue
        val_act = actual[comb]["total"]
        val_ant = (anterior.get(comb) or {}).get("total")
        var = pct_change(val_act, val_ant)
        out.append({
            "combustible": comb, "actual": val_act, "anterior": val_ant, "variacion_pct": var,
            "unidad": UNIDADES_COMBUSTIBLE.get(comb),
            "relevante": var is not None and abs(var) >= UMBRAL_COMBUSTIBLE_PCT,
        })
    return out


def comparar_combustibles(actual_sem, anterior_sem):
    return [c for c in combustibles_todos(actual_sem, anterior_sem) if c["relevante"]]


def costo_marginal_todos(actual_sem, anterior_sem):
    """Los 3 bloques SIEMPRE, en orden fijo, con su variación (no solo los relevantes)."""
    actual = actual_sem.get("precios", {})
    anterior = (anterior_sem or {}).get("precios", {})
    out = []
    for bloque in ORDEN_BLOQUES_CMG:
        if bloque not in actual:
            continue
        val_act = actual[bloque]["promedio"]
        val_ant = (anterior.get(bloque) or {}).get("promedio")
        var = pct_change(val_act, val_ant)
        out.append({
            "bloque": bloque, "actual": val_act, "anterior": val_ant, "variacion_pct": var,
            "relevante": var is not None and abs(var) >= UMBRAL_CMG_PCT,
        })
    return out


def comparar_precios(actual_sem, anterior_sem):
    return [c for c in costo_marginal_todos(actual_sem, anterior_sem) if c["relevante"]]


def cotas_nuevas(actual_sem, anterior_sem):
    actual = set(actual_sem.get("cotas", {}).keys())
    anterior = set((anterior_sem or {}).get("cotas", {}).keys())
    return sorted(actual - anterior)



def unidades_sin_generacion(semana):
    """Solo el dato real: unidades con 0 MWh programados esta semana. Sin causa ni potencia inferida."""
    off = [u for u in semana.get("generacion_unidades", []) if (u["total"] or 0) == 0]
    out = [{"unidad": u["unidad"], "region": u["region"], "empresa": u["empresa"], "tipo_maq": u["tipo_maq"]}
           for u in off]
    out.sort(key=lambda x: (x["region"], x["empresa"], x["unidad"]))
    return out


def alto_valle_resumen(actual_sem, anterior_sem):
    """SIEMPRE devuelve las 5 unidades, en el mismo orden, aunque alguna no aparezca
    en el archivo de esa semana (se marca sin_datos=True en vez de omitirla — evita
    que la grilla de tarjetas se descuadre semana a semana)."""
    actual_units = {u["unidad"]: u for u in actual_sem.get("generacion_unidades", []) if u["unidad"] in ALTO_VALLE_UNIDADES}
    anterior_units = {u["unidad"]: u for u in (anterior_sem or {}).get("generacion_unidades", []) if u["unidad"] in ALTO_VALLE_UNIDADES}
    out = []
    for code in ALTO_VALLE_UNIDADES:
        u = actual_units.get(code)
        if not u:
            out.append({
                "unidad": code, "tipo_maq": None, "empresa": "ALTO VALLE", "region": "COM",
                "total": None, "dias": None, "mwh_anterior": None, "variacion_pct": None,
                "evento": None, "mw_equiv": None, "sin_datos": True,
            })
            continue
        ant = anterior_units.get(code)
        mwh_ant = ant["total"] if ant else 0
        var = pct_change(u["total"], mwh_ant)
        evento = None
        if (mwh_ant or 0) == 0 and (u["total"] or 0) > 0:
            evento = "ENTRA_EN_SERVICIO"
        elif (mwh_ant or 0) > 0 and (u["total"] or 0) == 0:
            evento = "SALE_DE_SERVICIO"
        out.append({**u, "mwh_anterior": mwh_ant, "variacion_pct": var, "evento": evento,
                     "mw_equiv": mw_equiv(u["total"]), "sin_datos": False})
    return out


def main():
    if not HISTORICO_PATH.exists():
        raise SystemExit(f"No existe {HISTORICO_PATH}. Correr antes scripts/etl_to_json.py")

    historico = json.loads(HISTORICO_PATH.read_text())
    semanas_ordenadas = sorted(historico.values(), key=lambda s: s["num_semana"])
    nums = [s["num_semana"] for s in semanas_ordenadas]

    por_semana = {}
    for i, sem in enumerate(semanas_ordenadas):
        anterior = semanas_ordenadas[i - 1] if i > 0 else None
        gt = gen_tecnologia_resumen(sem)
        dem = demanda_resumen(sem)
        gt_ant = gen_tecnologia_resumen(anterior) if anterior else {}
        dem_ant = demanda_resumen(anterior) if anterior else {}

        demanda_cmp = {}
        for k, v in dem.items():
            v_ant = dem_ant.get(k)
            demanda_cmp[k] = {"actual": v, "anterior": v_ant, "variacion_pct": pct_change(v, v_ant)}

        todas_centrales, resumen_centrales = comparar_centrales(sem, anterior)
        unidades_off = unidades_sin_generacion(sem)

        por_semana[str(sem["num_semana"])] = {
            "num_semana": sem["num_semana"],
            "finicio": sem["finicio"],
            "semana_anterior": anterior["num_semana"] if anterior else None,
            "temperatura_media": {"actual": sem.get("temperatura_media"),
                                   "anterior": anterior.get("temperatura_media") if anterior else None},
            "generacion_por_tecnologia": {"actual": gt, "anterior": gt_ant},
            "demanda": demanda_cmp,
            "centrales": todas_centrales,
            "resumen_centrales": resumen_centrales,
            "combustibles": combustibles_todos(sem, anterior),
            "cambios_combustibles": comparar_combustibles(sem, anterior),
            "costo_marginal": costo_marginal_todos(sem, anterior),
            "cambios_costo_marginal": comparar_precios(sem, anterior),
            "unidades_fuera_de_servicio": unidades_off,
            "cotas_nuevas": cotas_nuevas(sem, anterior),
            "valores_agua": sem.get("valores_agua", []),
            "alto_valle": alto_valle_resumen(sem, anterior),
        }

    serie_gen = {str(s["num_semana"]): gen_tecnologia_resumen(s) for s in semanas_ordenadas}
    serie_dem = {str(s["num_semana"]): demanda_resumen(s) for s in semanas_ordenadas}
    serie_comb = {str(s["num_semana"]): {k: v["total"] for k, v in s.get("consumo_combustibles", {}).items()}
                  for s in semanas_ordenadas}
    serie_precios = {str(s["num_semana"]): {k: v["promedio"] for k, v in s.get("precios", {}).items()}
                      for s in semanas_ordenadas}
    serie_alto_valle = {
        str(s["num_semana"]): {u["unidad"]: u["total"] for u in s.get("generacion_unidades", [])
                                if u["unidad"] in ALTO_VALLE_UNIDADES}
        for s in semanas_ordenadas
    }

    resultado = {
        "semanas_disponibles": nums,
        "ultima_semana": nums[-1] if nums else None,
        "unidades_combustible": UNIDADES_COMBUSTIBLE,
        "por_semana": por_semana,
        "series": {
            "generacion_por_tecnologia": serie_gen,
            "demanda": serie_dem,
            "consumo_combustibles": serie_comb,
            "costo_marginal": serie_precios,
            "alto_valle": serie_alto_valle,
        },
    }

    ANALISIS_PATH.write_text(json.dumps(resultado, indent=2, ensure_ascii=False, default=str))
    print(f"Análisis generado: {ANALISIS_PATH}")
    print(f"Semanas: {nums}")


if __name__ == "__main__":
    main()
