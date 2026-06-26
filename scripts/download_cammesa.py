#!/usr/bin/env python3
"""
Descarga automática de documentos CAMMESA desde la API pública.
================================================================
API base: https://api.cammesa.com/pub-svc/public
NEMO de consulta: PROGRAMACION_SEMANAL_UNIF

La respuesta mezcla dos tipos de documentos distinguibles por su campo "nemo":
  - "PROGRAMACION_SEMANAL"        → adjunto es un .zip con el .mdb adentro → va a data/
  - "PROGRAMACION_SEMANAL_REDESP" → adjunto es redespacho.xls → va a redespaches/
     (todos se llaman redespacho.xls; los renombramos con la fecha del doc)

Tracking: processed/downloaded_ids.json guarda {doc_id → nombre_guardado} para
no re-descargar. Se valida que el archivo siga existiendo en cada corrida.
"""
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE_URL = "https://api.cammesa.com/pub-svc/public"
TZ_ARG   = timezone(timedelta(hours=-3))
TIMEOUT  = 90

ROOT       = Path(__file__).resolve().parent.parent
DIR_PROG   = ROOT / "data"
DIR_REDESP = ROOT / "redespaches"
IDS_FILE   = ROOT / "processed" / "downloaded_ids.json"
LOG_FILE   = ROOT / "processed" / "download_log.json"


def fmt_api(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000-03:00")

def gh_output(key, value):
    gho = os.environ.get("GITHUB_OUTPUT")
    if gho:
        with open(gho, "a") as f:
            f.write(f"{key}={value}\n")
    print(f"[output] {key}={value}")

def get_json(path, params):
    url = f"{BASE_URL}/{path}"
    print(f"  GET {url} params={params}")
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        print(f"  → {r.status_code}, {len(r.content)} bytes")
        return data
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return None

def get_bytes(path, params):
    url = f"{BASE_URL}/{path}"
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT * 2)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"  ERROR descarga: {e}", file=sys.stderr)
        return None

def cargar_ids():
    if not IDS_FILE.exists():
        return {}
    try:
        ids = json.loads(IDS_FILE.read_text())
    except Exception:
        return {}
    # Validar que los archivos referenciados aún existan
    existentes = set()
    for d in [DIR_PROG, DIR_REDESP]:
        if d.exists():
            existentes |= {f.name for f in d.iterdir()}
    validos = {k: v for k, v in ids.items() if v in existentes}
    if len(validos) != len(ids):
        print(f"  [IDs] {len(ids)-len(validos)} entradas removidas (archivos ya no existen)")
    return validos

def guardar_ids(ids):
    IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    IDS_FILE.write_text(json.dumps(ids, indent=2, ensure_ascii=False))

def fecha_a_str(fecha_str):
    """'26/05/2026' → '20260526'"""
    try:
        return datetime.strptime(fecha_str, "%d/%m/%Y").strftime("%Y%m%d")
    except Exception:
        return fecha_str.replace("/", "")


def main():
    print(f"\n{'='*60}")
    print(f"Descarga CAMMESA — {datetime.now(TZ_ARG).isoformat()}")
    print(f"{'='*60}")

    ids = cargar_ids()
    print(f"IDs ya procesados: {len(ids)}")

    ahora = datetime.now(TZ_ARG)
    desde = ahora - timedelta(days=30)
    hasta = ahora.replace(hour=23, minute=59, second=59)

    # ── Consulta a la API ──────────────────────────────────────────────────────
    print(f"\nConsultando documentos {fmt_api(desde)} → {fmt_api(hasta)}")
    docs = get_json("findDocumentosByNemoRango", {
        "nemo": "PROGRAMACION_SEMANAL_UNIF",
        "fechadesde": fmt_api(desde),
        "fechahasta": fmt_api(hasta),
    })

    if not docs:
        print("Sin respuesta de la API o sin documentos.")
        gh_output("downloaded", "false")
        gh_output("count", "0")
        gh_output("files", "")
        return

    print(f"\nDocumentos recibidos: {len(docs)}")
    for d in docs:
        adj_nombres = [a.get("nombre","?") for a in (d.get("adjuntos") or [])]
        print(f"  [{d.get('nemo')}] {d.get('fecha')} {d.get('hora','')} "
              f"id={d.get('id','')[:12]}… adj={adj_nombres}")

    # ── Separar por tipo ───────────────────────────────────────────────────────
    progs   = [d for d in docs if d.get("nemo") == "PROGRAMACION_SEMANAL"]
    redesps = [d for d in docs if d.get("nemo") == "PROGRAMACION_SEMANAL_REDESP"]
    otros   = [d for d in docs if d.get("nemo") not in ("PROGRAMACION_SEMANAL",
                                                          "PROGRAMACION_SEMANAL_REDESP")]
    print(f"\nProgramaciones: {len(progs)} | Redespaches: {len(redesps)} | Otros: {len(otros)}")
    if otros:
        print(f"  NEMOs desconocidos: {set(d.get('nemo') for d in otros)}")

    descargados = []

    # ── Descargar programaciones (.zip → .mdb) ─────────────────────────────────
    print(f"\n--- Programaciones ({len(progs)}) ---")
    DIR_PROG.mkdir(parents=True, exist_ok=True)
    mdb_existentes = {f.name.lower() for f in DIR_PROG.iterdir()
                      if f.suffix.lower() == ".mdb"}

    for doc in sorted(progs, key=lambda d: d.get("fecha", "")):
        doc_id  = doc["id"]
        fecha   = doc.get("fecha", "?")
        adjuntos = doc.get("adjuntos") or []

        zip_adj = next((a for a in adjuntos
                        if a.get("nombre", "").lower().endswith(".zip")), None)
        if not zip_adj:
            print(f"  {fecha}: sin adjunto .zip — {[a.get('nombre') for a in adjuntos]}")
            continue

        zip_nombre = zip_adj["nombre"]
        mdb_nombre = zip_nombre.replace(".zip", ".MDB").replace(".ZIP", ".MDB")

        if mdb_nombre.lower() in mdb_existentes:
            if doc_id not in ids:
                ids[doc_id] = mdb_nombre   # sincronizar IDs con archivos existentes
            print(f"  {fecha}: {mdb_nombre} ya existe")
            continue

        if doc_id in ids:
            print(f"  {fecha}: {doc_id[:12]}… ya procesado como {ids[doc_id]}")
            continue

        print(f"  {fecha}: descargando {zip_nombre}…")
        data = get_bytes("findAttachmentByNemoId", {
            "nemo": "PROGRAMACION_SEMANAL_UNIF",
            "docId": doc_id,
            "attachmentId": zip_adj["id"],
        })
        if not data:
            continue

        # Extraer .mdb del ZIP
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                mdb_entry = next(
                    (e for e in zf.infolist() if e.filename.upper().endswith(".MDB")),
                    None
                )
                if not mdb_entry:
                    print(f"    ⚠ No hay .mdb en el ZIP. Contenido: {[e.filename for e in zf.infolist()]}")
                    continue
                contenido = zf.read(mdb_entry.filename)
                dest = DIR_PROG / mdb_nombre
                dest.write_bytes(contenido)
                print(f"    ✓ {mdb_nombre} ({len(contenido):,} bytes) → data/")
                descargados.append(mdb_nombre)
                ids[doc_id] = mdb_nombre
                mdb_existentes.add(mdb_nombre.lower())
        except zipfile.BadZipFile:
            # A veces el "zip" es el .mdb directo
            dest = DIR_PROG / mdb_nombre
            dest.write_bytes(data)
            print(f"    ✓ {mdb_nombre} (sin ZIP, {len(data):,} bytes) → data/")
            descargados.append(mdb_nombre)
            ids[doc_id] = mdb_nombre
            mdb_existentes.add(mdb_nombre.lower())

    # ── Descargar redespaches (.xls) ───────────────────────────────────────────
    print(f"\n--- Redespaches ({len(redesps)}) ---")
    DIR_REDESP.mkdir(parents=True, exist_ok=True)

    for doc in sorted(redesps, key=lambda d: d.get("fecha", "")):
        doc_id  = doc["id"]
        fecha   = doc.get("fecha", "?")
        adjuntos = doc.get("adjuntos") or []

        xls_adj = next((a for a in adjuntos
                        if a.get("nombre", "").lower().endswith(".xls")), None)
        if not xls_adj:
            print(f"  {fecha}: sin adjunto .xls — {[a.get('nombre') for a in adjuntos]}")
            continue

        # Nombre con fecha para distinguir entre semanas
        fecha_str = fecha_a_str(fecha)
        nombre_dest = f"redespacho_{fecha_str}.xls"
        dest = DIR_REDESP / nombre_dest

        if dest.exists():
            if doc_id not in ids:
                ids[doc_id] = nombre_dest
            print(f"  {fecha}: {nombre_dest} ya existe")
            continue

        if doc_id in ids:
            print(f"  {fecha}: {doc_id[:12]}… ya procesado como {ids[doc_id]}")
            continue

        print(f"  {fecha}: descargando redespacho → {nombre_dest}…")
        data = get_bytes("findAttachmentByNemoId", {
            "nemo": "PROGRAMACION_SEMANAL_UNIF",
            "docId": doc_id,
            "attachmentId": xls_adj["id"],
        })
        if not data:
            continue

        dest.write_bytes(data)
        print(f"    ✓ {nombre_dest} ({len(data):,} bytes) → redespaches/")
        descargados.append(nombre_dest)
        ids[doc_id] = nombre_dest

    # ── Guardar estado y reportar ──────────────────────────────────────────────
    guardar_ids(ids)

    log = []
    if LOG_FILE.exists():
        try:
            log = json.loads(LOG_FILE.read_text())
        except Exception:
            pass
    log.append({
        "timestamp": ahora.isoformat(),
        "docs_totales": len(docs),
        "progs_encontradas": len(progs),
        "redesps_encontrados": len(redesps),
        "descargados": descargados,
    })
    LOG_FILE.write_text(json.dumps(log[-30:], indent=2, ensure_ascii=False))

    gh_output("downloaded", "true" if descargados else "false")
    gh_output("count", str(len(descargados)))
    gh_output("files", ",".join(descargados))

    print(f"\n{'='*60}")
    if descargados:
        print(f"✓ {len(descargados)} archivo(s) nuevo(s): {descargados}")
    else:
        print("— Sin archivos nuevos.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
