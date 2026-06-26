#!/usr/bin/env python3
"""
Descarga automática de documentos CAMMESA desde la API pública.
================================================================
NEMOs confirmados por diagnóstico:
  - PROGRAMACION_SEMANAL_UNIF  → adjunto es un .zip que contiene el .mdb
  - PROGRAMACION_SEMANAL_REDESP → adjunto es redespacho.xls (mismo nombre siempre)

Problemas resueltos vs. versión anterior:
  1. Filtramos por .zip (no .mdb) y extraemos el .mdb del interior.
  2. Los redespaches se renombran con la fecha del documento para no pisarse
     (redespacho_20260526.xls, redespacho_20260529.xls, etc.).
  3. El tracking de "ya descargado" usa el ID del documento, no el nombre del
     archivo, guardado en processed/downloaded_ids.json.
  4. El rango de búsqueda incluye hoy completo (hasta las 23:59).

USO:
    python3 scripts/download_cammesa.py
"""
import io
import json
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ── Configuración ────────────────────────────────────────────────────────────

BASE_URL = "https://api.cammesa.com/pub-svc/public"
TZ_ARG   = timezone(timedelta(hours=-3))
TIMEOUT  = 60

NEMO_PROG   = "PROGRAMACION_SEMANAL_UNIF"
NEMO_REDESP = "PROGRAMACION_SEMANAL_REDESP"

ROOT            = Path(__file__).resolve().parent.parent
DIR_PROG        = ROOT / "data"
DIR_REDESP      = ROOT / "redespaches"
DOWNLOADED_IDS  = ROOT / "processed" / "downloaded_ids.json"
DOWNLOAD_LOG    = ROOT / "processed" / "download_log.json"

DIAS_BUSQUEDA = 30   # amplio para no perder nada

# ── Helpers ──────────────────────────────────────────────────────────────────

def fmt_api(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000-03:00")

def get_json(path: str, params: dict) -> dict | list | None:
    url = f"{BASE_URL}/{path}"
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  ERROR GET {url}: {e}", file=sys.stderr)
        return None

def download_bytes(path: str, params: dict) -> bytes | None:
    url = f"{BASE_URL}/{path}"
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT * 2)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"  ERROR descarga {url}: {e}", file=sys.stderr)
        return None

def cargar_ids() -> dict:
    """Carga el registro de doc IDs ya procesados: {doc_id: nombre_guardado}.
    Valida que cada archivo realmente exista — si no, lo elimina del registro
    para que se vuelva a descargar."""
    if not DOWNLOADED_IDS.exists():
        return {}
    try:
        ids = json.loads(DOWNLOADED_IDS.read_text())
    except Exception:
        return {}

    # Validar que los archivos sigan existiendo
    todos_los_archivos = set()
    for d in [DIR_PROG, DIR_REDESP]:
        if d.exists():
            todos_los_archivos |= {f.name for f in d.iterdir()}

    ids_validos = {}
    for doc_id, nombre in ids.items():
        if nombre in todos_los_archivos:
            ids_validos[doc_id] = nombre
        else:
            print(f"  [IDs] '{nombre}' ya no existe en el repo — removiendo de downloaded_ids")
    return ids_validos

def guardar_ids(ids: dict):
    DOWNLOADED_IDS.parent.mkdir(parents=True, exist_ok=True)
    DOWNLOADED_IDS.write_text(json.dumps(ids, indent=2, ensure_ascii=False))

def fecha_doc_a_str(fecha_str: str) -> str:
    """Convierte '26/05/2026' → '20260526' para usarlo en nombres de archivo."""
    try:
        return datetime.strptime(fecha_str, "%d/%m/%Y").strftime("%Y%m%d")
    except Exception:
        return fecha_str.replace("/", "")

def set_github_output(key: str, value: str):
    import os
    gho = os.environ.get("GITHUB_OUTPUT")
    if gho:
        with open(gho, "a") as f:
            f.write(f"{key}={value}\n")
    else:
        print(f"  [output] {key}={value}")

# ── Descarga programación semanal ────────────────────────────────────────────

def descargar_programacion(docs: list, ids_vistos: dict) -> list[str]:
    """
    Los adjuntos son .zip que contienen el .mdb.
    Descargamos el ZIP y extraemos el .mdb a data/.
    """
    DIR_PROG.mkdir(parents=True, exist_ok=True)
    mdb_existentes = {f.name.lower() for f in DIR_PROG.iterdir() if f.suffix.lower() == ".mdb"}
    descargados = []

    for doc in docs:
        if doc.get("nemo") != NEMO_PROG:
            continue
        doc_id = doc["id"]
        if doc_id in ids_vistos:
            continue

        adjuntos = doc.get("adjuntos") or []
        zip_adj = next((a for a in adjuntos if a["nombre"].lower().endswith(".zip")), None)
        if not zip_adj:
            continue

        zip_nombre = zip_adj["nombre"]           # ej. "psem2626.zip"
        mdb_nombre = zip_nombre.replace(".zip", ".MDB")  # ej. "psem2626.MDB"

        if mdb_nombre.lower() in mdb_existentes:
            print(f"  [PROG] {mdb_nombre} ya existe, marcando ID como visto")
            ids_vistos[doc_id] = mdb_nombre
            continue

        print(f"  [PROG] Descargando {zip_nombre} (doc {doc_id[:8]}…)")
        contenido = download_bytes("findAttachmentByNemoId", {
            "nemo": NEMO_PROG,
            "docId": doc_id,
            "attachmentId": zip_adj["id"],
        })
        if not contenido:
            continue

        # Extraer el .mdb del ZIP
        try:
            with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
                mdb_entry = next(
                    (e for e in zf.infolist() if e.filename.upper().endswith(".MDB")),
                    None
                )
                if not mdb_entry:
                    print(f"    ⚠ No hay .mdb dentro de {zip_nombre}", file=sys.stderr)
                    continue
                data = zf.read(mdb_entry.filename)
                dest = DIR_PROG / mdb_nombre
                dest.write_bytes(data)
                print(f"    ✓ Extraído: {mdb_nombre} ({len(data):,} bytes) → data/")
                descargados.append(mdb_nombre)
                ids_vistos[doc_id] = mdb_nombre
                mdb_existentes.add(mdb_nombre.lower())
        except zipfile.BadZipFile:
            # Algunos adjuntos ya son el .mdb directamente aunque digan .zip
            dest = DIR_PROG / mdb_nombre
            dest.write_bytes(contenido)
            print(f"    ✓ Guardado directo: {mdb_nombre} ({len(contenido):,} bytes) → data/")
            descargados.append(mdb_nombre)
            ids_vistos[doc_id] = mdb_nombre
            mdb_existentes.add(mdb_nombre.lower())

    return descargados

# ── Descarga redespacho ──────────────────────────────────────────────────────

def descargar_redespaches(docs: list, ids_vistos: dict) -> list[str]:
    """
    Los redespaches siempre se llaman 'redespacho.xls' en la API.
    Los renombramos con la fecha del documento para no pisarlos:
    redespacho_20260526.xls, redespacho_20260529.xls, etc.
    """
    DIR_REDESP.mkdir(parents=True, exist_ok=True)
    descargados = []

    for doc in docs:
        if doc.get("nemo") != NEMO_REDESP:
            continue
        doc_id = doc["id"]
        if doc_id in ids_vistos:
            continue

        adjuntos = doc.get("adjuntos") or []
        xls_adj = next((a for a in adjuntos if a["nombre"].lower().endswith(".xls")), None)
        if not xls_adj:
            continue

        fecha_str = fecha_doc_a_str(doc.get("fecha", ""))
        nombre_destino = f"redespacho_{fecha_str}.xls"
        dest = DIR_REDESP / nombre_destino

        if dest.exists():
            print(f"  [REDESP] {nombre_destino} ya existe, marcando ID como visto")
            ids_vistos[doc_id] = nombre_destino
            continue

        print(f"  [REDESP] Descargando redespacho del {doc.get('fecha')} (doc {doc_id[:8]}…)")
        contenido = download_bytes("findAttachmentByNemoId", {
            "nemo": NEMO_REDESP,
            "docId": doc_id,
            "attachmentId": xls_adj["id"],
        })
        if not contenido:
            continue

        dest.write_bytes(contenido)
        print(f"    ✓ Guardado: {nombre_destino} ({len(contenido):,} bytes) → redespaches/")
        descargados.append(nombre_destino)
        ids_vistos[doc_id] = nombre_destino

    return descargados

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"=== Descarga CAMMESA — {datetime.now(TZ_ARG).isoformat()} ===")

    ids_vistos = cargar_ids()
    ahora = datetime.now(TZ_ARG)
    desde = ahora - timedelta(days=DIAS_BUSQUEDA)
    # El rango incluye hoy hasta las 23:59 para no perder publicaciones del día
    hasta = ahora.replace(hour=23, minute=59, second=59)

    print(f"Buscando documentos desde {fmt_api(desde)} hasta {fmt_api(hasta)}")

    # Un solo llamado devuelve AMBOS NEMOs mezclados (confirmado por diagnóstico)
    docs = get_json("findDocumentosByNemoRango", {
        "nemo": NEMO_PROG,
        "fechadesde": fmt_api(desde),
        "fechahasta": fmt_api(hasta),
    })
    if not docs:
        print("Sin respuesta de la API.")
        set_github_output("downloaded", "false")
        set_github_output("count", "0")
        set_github_output("files", "")
        return

    print(f"Documentos encontrados: {len(docs)}"
          f" (prog: {sum(1 for d in docs if d.get('nemo')==NEMO_PROG)},"
          f" redesp: {sum(1 for d in docs if d.get('nemo')==NEMO_REDESP)})")

    total = []
    errores = []

    try:
        total += descargar_programacion(docs, ids_vistos)
    except Exception as e:
        import traceback
        errores.append({"paso": "programacion", "error": str(e), "traceback": traceback.format_exc()})
        print(f"  ERROR en programación: {e}", file=sys.stderr)

    try:
        total += descargar_redespaches(docs, ids_vistos)
    except Exception as e:
        import traceback
        errores.append({"paso": "redespacho", "error": str(e), "traceback": traceback.format_exc()})
        print(f"  ERROR en redespacho: {e}", file=sys.stderr)

    guardar_ids(ids_vistos)

    # Log
    log = []
    if DOWNLOAD_LOG.exists():
        try:
            log = json.loads(DOWNLOAD_LOG.read_text())
        except Exception:
            pass
    log.append({
        "timestamp": ahora.isoformat(),
        "descargados": total,
        "errores": errores,
    })
    DOWNLOAD_LOG.write_text(json.dumps(log[-30:], indent=2, ensure_ascii=False))

    set_github_output("downloaded", "true" if total else "false")
    set_github_output("count", str(len(total)))
    set_github_output("files", ",".join(total))

    if total:
        print(f"\n✓ {len(total)} archivo(s) nuevo(s): {total}")
    else:
        print("\n— Sin archivos nuevos esta corrida.")

if __name__ == "__main__":
    main()
