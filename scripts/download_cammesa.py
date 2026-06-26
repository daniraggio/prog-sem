#!/usr/bin/env python3
"""
Descarga automática de documentos CAMMESA desde la API pública.
================================================================
Corre diariamente desde GitHub Actions (5am Argentina / 8am UTC) y descarga
los archivos nuevos que no estén ya en el repo:
  - Programación semanal (.mdb) → data/
  - Redespacho semanal (.xls)   → redespaches/    [requiere configurar NEMO_REDESPACHO]

API base: https://api.cammesa.com/pub-svc/public
No requiere autenticación.

Flujo por cada NEMO:
  1. GET /obtieneFechaUltimoDocumento?nemo=...
     → fecha del documento más reciente disponible
  2. GET /findDocumentosByNemoRango?nemo=...&fechadesde=...&fechahasta=...
     → lista de documentos con sus adjuntos (id, nombre)
  3. GET /findAllAttachmentZipByNemoId?nemo=...&docId=...
     → ZIP con todos los adjuntos del documento
     (o individual: /findAttachmentByNemoId?nemo=...&docId=...&attachmentId=...)

Salida (para el workflow de GitHub Actions):
  - Escribe en $GITHUB_OUTPUT: downloaded=true/false
  - Exit code 0 siempre (los errores se loguean pero no frenan el pipeline)
  - Escribe processed/download_log.json con el registro de cada corrida

USO:
    python3 scripts/download_cammesa.py

Para usar redespacho, setear la variable de entorno NEMO_REDESPACHO o
editar NEMO_REDESPACHO directamente abajo:
    NEMO_REDESPACHO=REDESPACHO_SEMANAL python3 scripts/download_cammesa.py
"""
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ── Configuración ──────────────────────────────────────────────────────────────

BASE_URL = "https://api.cammesa.com/pub-svc/public"
TZ_ARG = timezone(timedelta(hours=-3))  # UTC-3 (Argentina, sin DST)
TIMEOUT = 60  # segundos por request

# Único NEMO para programación semanal Y redespacho — la diferencia es la extensión
NEMO = "PROGRAMACION_SEMANAL_UNIF"

ROOT = Path(__file__).resolve().parent.parent

# Destino por extensión dentro del mismo NEMO
DESTINO_POR_EXT = {
    ".mdb": ROOT / "data",
    ".xls": ROOT / "redespaches",
    ".xlsx": ROOT / "redespaches",
}

DOWNLOAD_LOG = ROOT / "processed" / "download_log.json"

# Cuántos días hacia atrás buscar documentos
DIAS_BUSQUEDA = 21


# ── Helpers ────────────────────────────────────────────────────────────────────

def fmt_fecha_api(dt: datetime) -> str:
    """Formato ISO que acepta la API de CAMMESA: 2026-06-01T00:00:00.000-03:00"""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000-03:00")


def get(path: str, params: dict | None = None) -> dict | list | None:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"  ERROR GET {url}: {e}", file=sys.stderr)
        return None


def download_bytes(path: str, params: dict) -> bytes | None:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT * 2, stream=True)
        r.raise_for_status()
        return r.content
    except requests.exceptions.RequestException as e:
        print(f"  ERROR descarga {url}: {e}", file=sys.stderr)
        return None


# ── Lógica principal ────────────────────────────────────────────────────────────

def archivos_existentes_todos() -> set[str]:
    """Nombres de todos los archivos ya presentes en data/ y redespaches/ (en minúsculas)."""
    existentes = set()
    for destino in set(DESTINO_POR_EXT.values()):
        if destino.exists():
            existentes |= {f.name.lower() for f in destino.iterdir()
                           if f.suffix.lower() in DESTINO_POR_EXT}
    return existentes


def get(path: str, params: dict | None = None) -> dict | list | None:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"  ERROR GET {url}: {e}", file=sys.stderr)
        return None


def download_bytes(path: str, params: dict) -> bytes | None:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT * 2, stream=True)
        r.raise_for_status()
        return r.content
    except requests.exceptions.RequestException as e:
        print(f"  ERROR descarga {url}: {e}", file=sys.stderr)
        return None


def guardar_archivo(nombre: str, contenido: bytes) -> bool:
    """Guarda el archivo en el directorio correcto según su extensión."""
    ext = Path(nombre).suffix.lower()
    destino = DESTINO_POR_EXT.get(ext)
    if not destino:
        return False
    destino.mkdir(parents=True, exist_ok=True)
    (destino / nombre).write_bytes(contenido)
    return True


def procesar() -> list[str]:
    """
    Busca y descarga archivos nuevos del NEMO PROGRAMACION_SEMANAL_UNIF.
    Devuelve lista de nombres de archivos descargados.
    """
    ya_tenemos = archivos_existentes_todos()
    print(f"[{NEMO}] Archivos ya en repo: {len(ya_tenemos)}")

    # 1. Fecha del último documento disponible
    ultimo = get("obtieneFechaUltimoDocumento", {"nemo": NEMO})
    if not ultimo:
        print("  No se pudo obtener la fecha del último documento.")
        return []
    print(f"  Último documento disponible: {ultimo}")

    # 2. Buscar documentos en los últimos DIAS_BUSQUEDA días
    ahora = datetime.now(TZ_ARG)
    desde = ahora - timedelta(days=DIAS_BUSQUEDA)
    docs = get("findDocumentosByNemoRango", {
        "nemo": NEMO,
        "fechadesde": fmt_fecha_api(desde),
        "fechahasta": fmt_fecha_api(ahora),
    })
    if not docs:
        print(f"  No se encontraron documentos en los últimos {DIAS_BUSQUEDA} días.")
        return []
    print(f"  Documentos encontrados: {len(docs)}")

    descargados = []

    for doc in docs:
        doc_id = doc.get("id")
        adjuntos = doc.get("adjuntos") or []
        fecha_doc = doc.get("fecha") or doc.get("fechaPublicacion") or "?"

        # Solo los adjuntos con extensiones que nos interesan
        adjuntos_relevantes = [
            a for a in adjuntos
            if Path(a.get("nombre", "")).suffix.lower() in DESTINO_POR_EXT
        ]
        if not adjuntos_relevantes:
            continue

        nuevos = [a for a in adjuntos_relevantes if a["nombre"].lower() not in ya_tenemos]
        if not nuevos:
            print(f"  Doc {doc_id} ({fecha_doc}): ya tenemos {[a['nombre'] for a in adjuntos_relevantes]}")
            continue

        print(f"  Doc {doc_id} ({fecha_doc}): {len(nuevos)} archivo(s) nuevo(s)")

        # Intentar ZIP primero (más eficiente)
        zip_bytes = download_bytes(
            "findAllAttachmentZipByNemoId",
            {"nemo": NEMO, "docId": doc_id},
        )

        if zip_bytes:
            try:
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                    for entry in zf.infolist():
                        nombre = Path(entry.filename).name
                        ext = Path(nombre).suffix.lower()
                        if ext not in DESTINO_POR_EXT or nombre.lower() in ya_tenemos:
                            continue
                        contenido = zf.read(entry.filename)
                        if guardar_archivo(nombre, contenido):
                            destino = DESTINO_POR_EXT[ext]
                            print(f"    ✓ {nombre} → {destino.name}/ ({entry.file_size:,} bytes)")
                            descargados.append(nombre)
                            ya_tenemos.add(nombre.lower())
                continue
            except zipfile.BadZipFile:
                pass  # fallback a descarga individual abajo

        # Fallback: descargar adjunto por adjunto
        for adj in nuevos:
            adj_id = adj.get("id")
            nombre = adj["nombre"]
            contenido = download_bytes(
                "findAttachmentByNemoId",
                {"nemo": NEMO, "docId": doc_id, "attachmentId": adj_id},
            )
            if contenido and guardar_archivo(nombre, contenido):
                ext = Path(nombre).suffix.lower()
                destino = DESTINO_POR_EXT[ext]
                print(f"    ✓ {nombre} → {destino.name}/ ({len(contenido):,} bytes)")
                descargados.append(nombre)
                ya_tenemos.add(nombre.lower())

    return descargados


def set_github_output(key: str, value: str):
    """Escribe una variable de output para GitHub Actions."""
    gho = os.environ.get("GITHUB_OUTPUT")
    if gho:
        with open(gho, "a") as f:
            f.write(f"{key}={value}\n")
    else:
        print(f"  [output] {key}={value}")


def main():
    print(f"=== Descarga CAMMESA — {datetime.now(TZ_ARG).isoformat()} ===")

    total_descargados = []
    errores = []

    try:
        archivos = procesar()
        total_descargados.extend(archivos)
    except Exception as e:
        import traceback
        msg = f"Error inesperado: {e}\n{traceback.format_exc()}"
        print(msg, file=sys.stderr)
        errores.append({"error": str(e), "traceback": traceback.format_exc()})

    # Registrar en log
    (ROOT / "processed").mkdir(parents=True, exist_ok=True)
    log = []
    if DOWNLOAD_LOG.exists():
        try:
            log = json.loads(DOWNLOAD_LOG.read_text())
        except Exception:
            log = []
    log.append({
        "timestamp": datetime.now(TZ_ARG).isoformat(),
        "descargados": total_descargados,
        "errores": errores,
    })
    DOWNLOAD_LOG.write_text(json.dumps(log[-30:], indent=2, ensure_ascii=False))

    # Comunicar al workflow
    hay_nuevos = len(total_descargados) > 0
    set_github_output("downloaded", "true" if hay_nuevos else "false")
    set_github_output("count", str(len(total_descargados)))
    set_github_output("files", ",".join(total_descargados))

    if hay_nuevos:
        print(f"\n✓ {len(total_descargados)} archivo(s) nuevo(s): {total_descargados}")
    else:
        print("\n— Sin archivos nuevos esta corrida.")


if __name__ == "__main__":
    main()
