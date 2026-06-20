#!/usr/bin/env python3
"""
Imprime en Markdown el detalle de los archivos .mdb que fallaron en la última
corrida de etl_to_json.py, leyendo processed/etl_errors.json. Pensado para
volcarse al GITHUB_STEP_SUMMARY del workflow, pero también sirve corrido a mano.

USO:
    python3 scripts/print_etl_summary.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ERRORS_PATH = ROOT / "processed" / "etl_errors.json"


def main():
    if not ERRORS_PATH.exists():
        print("No hay errores registrados (processed/etl_errors.json no existe).")
        return

    data = json.loads(ERRORS_PATH.read_text())
    print(f"Corrida: {data.get('fecha_corrida', 's/d')}\n")
    for e in data.get("archivos_con_error", []):
        print(f"### {e['archivo']}")
        print("```")
        print(e["traceback"])
        print("```")


if __name__ == "__main__":
    main()
