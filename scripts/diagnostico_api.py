#!/usr/bin/env python3
"""
Diagnóstico de la API CAMMESA
==============================
Corre este script desde GitHub Actions (workflow_dispatch) para ver
exactamente qué devuelve la API y entender por qué no descargó archivos.

Agrega un step temporal al workflow:
    - name: Diagnóstico API
      run: python3 scripts/diagnostico_api.py

O desde local si tenés acceso a la API:
    pip install requests
    python3 scripts/diagnostico_api.py
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE_URL = "https://api.cammesa.com/pub-svc/public"
NEMO = "PROGRAMACION_SEMANAL_UNIF"
TZ_ARG = timezone(timedelta(hours=-3))
ROOT = Path(__file__).resolve().parent.parent


def fmt_fecha_api(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000-03:00")


def get_raw(path, params=None):
    url = f"{BASE_URL}/{path.lstrip('/')}"
    print(f"\n{'─'*60}")
    print(f"GET {url}")
    if params:
        print(f"Params: {params}")
    try:
        r = requests.get(url, params=params, timeout=30)
        print(f"Status: {r.status_code}")
        print(f"Content-Type: {r.headers.get('content-type', '?')}")
        print(f"Respuesta ({len(r.content)} bytes):")
        try:
            parsed = r.json()
            print(json.dumps(parsed, indent=2, ensure_ascii=False, default=str)[:3000])
            return parsed
        except Exception:
            print(r.text[:1000])
            return None
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def main():
    print("=" * 60)
    print(f"DIAGNÓSTICO API CAMMESA — {datetime.now(TZ_ARG).isoformat()}")
    print("=" * 60)

    # 1. Fecha del último documento
    print("\n### 1. Fecha del último documento disponible ###")
    ultimo = get_raw("obtieneFechaUltimoDocumento", {"nemo": NEMO})

    # 2. Documentos de los últimos 30 días
    print("\n### 2. Documentos últimos 30 días ###")
    ahora = datetime.now(TZ_ARG)
    desde = ahora - timedelta(days=30)
    docs = get_raw("findDocumentosByNemoRango", {
        "nemo": NEMO,
        "fechadesde": fmt_fecha_api(desde),
        "fechahasta": fmt_fecha_api(ahora),
    })

    # 3. Si hay documentos, inspeccionar el primero en detalle
    if docs and isinstance(docs, list) and len(docs) > 0:
        print(f"\n### 3. Detalle del documento más reciente (de {len(docs)} total) ###")
        doc = docs[0]
        print(f"Claves del documento: {list(doc.keys())}")
        print(f"ID: {doc.get('id')}")
        print(f"Fecha: {doc.get('fecha') or doc.get('fechaPublicacion') or 'CAMPO NO ENCONTRADO'}")
        adjuntos = doc.get("adjuntos") or doc.get("attachments") or []
        print(f"Adjuntos (clave 'adjuntos'): {len(doc.get('adjuntos', []))} items")
        print(f"Adjuntos (clave 'attachments'): {len(doc.get('attachments', []))} items")
        if adjuntos:
            print("Primer adjunto:")
            print(json.dumps(adjuntos[0], indent=2, default=str))
        else:
            print("⚠ SIN ADJUNTOS — puede ser que la clave del campo sea diferente")
            print("Documento completo:")
            print(json.dumps(doc, indent=2, default=str)[:2000])

    # 4. Qué archivos hay actualmente en el repo
    print("\n### 4. Archivos actuales en data/ y redespaches/ ###")
    for carpeta in ["data", "redespaches"]:
        d = ROOT / carpeta
        if d.exists():
            archivos = sorted(d.iterdir())
            print(f"{carpeta}/: {[f.name for f in archivos]}")
        else:
            print(f"{carpeta}/: (no existe)")

    # 5. Último log de descarga
    print("\n### 5. Últimas corridas del downloader ###")
    log_path = ROOT / "processed" / "download_log.json"
    if log_path.exists():
        log = json.loads(log_path.read_text())
        for entry in log[-3:]:
            print(json.dumps(entry, indent=2, ensure_ascii=False, default=str))
    else:
        print("(no existe processed/download_log.json — el downloader nunca corrió con éxito)")

    print("\n" + "=" * 60)
    print("FIN DEL DIAGNÓSTICO")


if __name__ == "__main__":
    main()
