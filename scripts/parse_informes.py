#!/usr/bin/env python3
"""
Parser de Informes "Previsión Despacho Energético" (CAMMESA, PDF quincenal)
=============================================================================
Lee todos los .pdf en informes/, extrae texto y tablas con pdfplumber, y arma
processed/informes.json (acumulativo e idempotente, igual filosofía que
etl_to_json.py para los .mdb).

DISEÑO Y SUPUESTOS:
- Este informe es un PowerPoint exportado a PDF con una estructura de slides
  bastante fija (título, escenario previsto, parque generador, balance
  semanal, transporte y distribución, habilitaciones, nuevo equipamiento).
  El parser identifica cada sección por el TÍTULO de la slide (texto), no por
  número de página fijo, así tolera que se agreguen/saquen páginas.
- Las tablas (parque generador, balance semanal, mantenimientos) se extraen
  con pdfplumber posicionalmente. Si la estructura interna de alguna tabla
  cambia de forma inesperada, el campo estructurado correspondiente puede
  quedar vacío o parcial — por eso SIEMPRE se guarda también el texto crudo
  de cada página completa (paginas_texto), para no perder información aunque
  el parseo estructurado falle parcialmente.
- No se inventa ningún dato: lo que no se puede extraer con confianza queda
  en None/vacío, nunca se completa con un valor supuesto.

USO:
    python3 scripts/parse_informes.py
"""
import json
import re
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("Falta pdfplumber. Instalar con: pip install pdfplumber", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parent.parent
INFORMES_DIR = ROOT / "informes"
OUT_DIR = ROOT / "processed"
INFORMES_JSON = OUT_DIR / "informes.json"

BALANCE_LABELS = ["Demanda", "Exportación", "Térmico", "Hidráulico", "Nuclear", "Renovable", "Importación"]


def to_float(s):
    if s in (None, ""):
        return None
    s = str(s).replace(".", "", s.count(".") - 1 if str(s).count(".") > 1 else 0) if False else str(s)
    try:
        return float(str(s).replace(",", "."))
    except ValueError:
        return None


def find_page(pdf, *titulos):
    """Devuelve el índice (0-based) de la primera página cuyo texto contiene alguno de los títulos dados."""
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if any(t.lower() in text.lower() for t in titulos):
            return i
    return None


def parse_portada(pdf):
    text = (pdf.pages[0].extract_text() or "").strip()
    out = {"titulo_raw": text, "semana_a": None, "semana_b": None, "anio": None, "fecha_informe": None}
    m = re.search(r"Semanas?\s+(\d+)\s*/\s*(\d+)\s+y\s+(\d+)\s*/\s*(\d+)", text)
    if m:
        out["semana_a"] = int(m.group(1))
        out["semana_b"] = int(m.group(3))
        out["anio"] = 2000 + int(m.group(4))  # "26" -> 2026
    m2 = re.search(r",\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*$", text)
    if m2:
        out["fecha_informe"] = m2.group(1)
    return out


def parse_escenario_previsto(pdf):
    idx = find_page(pdf, "Escenario previsto")
    if idx is None:
        return None
    text = pdf.pages[idx].extract_text() or ""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    lines = lines[1:]  # saca el título de la slide
    bullets = []
    label_re = re.compile(r"^([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\.\- ]{2,45}?)\s*:\s*(.*)$")
    for line in lines:
        m = label_re.match(line)
        if m and len(m.group(1).split()) <= 6:
            bullets.append({"titulo": m.group(1).strip(), "texto": m.group(2).strip()})
        elif bullets:
            bullets[-1]["texto"] = (bullets[-1]["texto"] + " " + line).strip()
        else:
            bullets.append({"titulo": None, "texto": line})

    # Post-proceso: si un bullet quedó con título pero sin texto (la fuente a veces
    # pone "Título :" en su propia línea y el contenido recién en la siguiente,
    # que el regex interpreta como un bullet nuevo), se fusiona con el siguiente.
    fusionados = []
    i = 0
    while i < len(bullets):
        b = bullets[i]
        if not b["texto"] and i + 1 < len(bullets):
            nxt = bullets[i + 1]
            texto = (f"{nxt['titulo']}: " if nxt["titulo"] else "") + nxt["texto"]
            fusionados.append({"titulo": b["titulo"], "texto": texto.strip()})
            i += 2
        else:
            fusionados.append(b)
            i += 1
    return fusionados


def parse_parque_generador(pdf):
    idx = find_page(pdf, "Situación parque generador")
    if idx is None:
        return None
    tables = pdf.pages[idx].extract_tables()
    resultado = {"termicas": [], "hidraulicas": []}
    destino = None
    for t in tables:
        for row in t:
            primera = (row[0] or "").strip() if row[0] else ""
            if "TÉRMICAS" in primera.upper():
                destino = "termicas"
                continue
            if "HIDRÁULICAS" in primera.upper():
                destino = "hidraulicas"
                continue
            if primera.upper() == "CENTRAL":
                continue  # fila de encabezado de columnas
            if destino is None:
                continue
            central, maquina, estado, fecha, motivo = (list(row) + [None] * 5)[:5]
            if central:
                ultimo_central = central
            else:
                central = ultimo_central if resultado[destino] or True else None
            if not any([central, maquina, estado, fecha, motivo]):
                continue
            resultado[destino].append({
                "central": (central or "").strip(),
                "maquina": (maquina or "").strip(),
                "estado": (estado or "").strip(),
                "fecha": (fecha or "").strip() or None,
                "motivo": (motivo or "").strip().replace("\n", " ") or None,
            })
    return resultado


def parse_balance_semanal(pdf):
    idx = find_page(pdf, "Perspectivas para la próxima semana", "Balance Semanal")
    if idx is None:
        return None
    tables = pdf.pages[idx].extract_tables()
    if len(tables) < 2:
        return None

    def limpiar(t):
        return [[(c.replace("\n", " ").strip() if c else c) for c in row] for row in t]

    t = [limpiar(x) for x in tables]
    out = {"semana_a": {}, "semana_b": {}}

    # --- tabla 0 y 1: balance semanal + consumo de combustibles ---
    if len(t) >= 2 and len(t[0]) >= 14 and len(t[1]) >= 14:
        t0, t1 = t[0], t[1]
        balance_a, balance_b = {}, {}
        for i, label in enumerate(BALANCE_LABELS):
            row0 = t0[3 + i]
            row1 = t1[3 + i]
            balance_a[label] = {"gwh": to_float(row0[3]), "mw_med": to_float(row0[4])}
            vals1 = [c for c in row1 if c not in (None, "")]
            balance_b[label] = {"gwh": to_float(vals1[0]) if len(vals1) > 0 else None,
                                 "mw_med": to_float(vals1[1]) if len(vals1) > 1 else None}
        comb_a, comb_b = [], []
        for i in range(10, 14):
            row0 = t0[i]
            row1 = t1[i]
            nombre = row0[1]
            unidad = row0[2]
            if not nombre:
                continue
            comb_a.append({"combustible": nombre, "unidad": unidad, "valor": to_float(row0[3])})
            vals1 = [c for c in row1 if c not in (None, "")]
            comb_b.append({"combustible": nombre, "unidad": unidad, "valor": to_float(vals1[0]) if vals1 else None})
        out["semana_a"]["balance"] = balance_a
        out["semana_b"]["balance"] = balance_b
        out["semana_a"]["consumo_combustibles"] = comb_a
        out["semana_b"]["consumo_combustibles"] = comb_b

    # --- tabla 2 y 3: despacho MW medio por central + niveles de embalses ---
    if len(t) >= 4:
        t2, t3 = t[2], t[3]
        despacho_a, despacho_b, niveles = [], [], []
        # filas 0..6 (hasta encontrar la fila de encabezado "Niveles"): despacho por central
        i = 0
        while i < len(t2) and not (t2[i][0] and "Niveles" in str(t2[i][0])) and not (t2[i][2] in ("Hoy",)):
            row2 = t2[i]
            central = row2[1]
            if not central:
                i += 1
                continue
            mw_a = to_float(row2[2])
            mw_b = to_float(t3[i][0]) if i < len(t3) and t3[i] else None
            despacho_a.append({"central": central, "mw_med": mw_a})
            despacho_b.append({"central": central, "mw_med": mw_b})
            i += 1
        header_idx = i  # fila del encabezado Hoy/Domingo/Domingo
        for j in range(header_idx + 1, len(t2)):
            row2 = t2[j]
            central = row2[1]
            if not central:
                continue
            hoy = to_float(row2[2]) if len(row2) > 2 else None
            domingo_a = to_float(row2[3]) if len(row2) > 3 else None
            domingo_b = to_float(t3[j][0]) if j < len(t3) and t3[j] else None
            niveles.append({"central": central, "hoy": hoy,
                             "domingo_fin_semana_a": domingo_a, "domingo_fin_semana_b": domingo_b})
        out["despacho_centrales"] = {"semana_a": despacho_a, "semana_b": despacho_b}
        out["niveles_embalses"] = niveles

    return out


def parse_transporte_distribucion(pdf):
    idx_stat = find_page(pdf, "Condiciones previstas de Operación en el STAT")
    bullets = []
    if idx_stat is not None:
        text = pdf.pages[idx_stat].extract_text() or ""
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("▪"):
                bullets.append(line.lstrip("▪").strip())
            elif bullets and line and not line[0].isupper():
                bullets[-1] = (bullets[-1] + " " + line).strip()

    idx_mant = find_page(pdf, "TRABAJOS DE MANTENIMIENTOS RELEVANTES")
    mantenimientos = []
    dias_cols = []
    if idx_mant is not None:
        tables = pdf.pages[idx_mant].extract_tables()
        for t in tables:
            if not t or not t[0]:
                continue
            header = [(c or "").replace("\n", "") for c in t[0]]
            if "N°" in header and "EQUIPO" in header:
                dias_cols = header[4:]
                for row in t[1:]:
                    if not row or not row[0]:
                        continue
                    dias = {dias_cols[k]: (row[4 + k] == "X") for k in range(len(dias_cols)) if 4 + k < len(row)}
                    mantenimientos.append({
                        "numero": row[0],
                        "equipo": (row[1] or "").replace("\n", " "),
                        "propietario": row[2],
                        "trabajo": (row[3] or "").replace("\n", " "),
                        "dias": dias,
                    })
    return {"condiciones_stat": bullets, "mantenimientos_relevantes": mantenimientos, "dias_columnas": dias_cols}


def parse_bullets_fecha(pdf, *titulos):
    """Para las slides 'Nuevas habilitaciones...' y 'Nuevo Equipamiento de Generación':
    párrafos que empiezan con 'El DD/MM/AAAA se habilitó...'."""
    idx = find_page(pdf, *titulos)
    if idx is None:
        return None
    text = pdf.pages[idx].extract_text() or ""
    lines = text.split("\n")
    body = "\n".join(lines[1:])  # saca título
    partes = re.split(r"(?=El \d{1,2}/\d{1,2}/\d{2,4}\s)", body)
    bullets = []
    for p in partes:
        p = " ".join(p.split())
        if not p:
            continue
        item = {"texto": p}
        m_fecha = re.match(r"El (\d{1,2}/\d{1,2}/\d{2,4})", p)
        if m_fecha:
            item["fecha"] = m_fecha.group(1)
        m_pot = re.search(r"(\d+(?:[.,]\d+)?)\s*MW", p)
        if m_pot:
            item["potencia_mw"] = to_float(m_pot.group(1))
        m_nombre = re.search(r"[“\"]([^”\"]+)[”\"]", p)
        if m_nombre:
            item["nombre"] = m_nombre.group(1)
        m_empresa = re.search(r"\(([^()]+(?:S\.A\.|SA|S\.R\.L\.))\)", p)
        if m_empresa:
            item["empresa"] = m_empresa.group(1)
        m_prov = re.search(r"provincia de ([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ ]+?)\.?\s*$", p)
        if m_prov:
            item["provincia"] = m_prov.group(1).strip()
        bullets.append(item)
    bullets = [b for b in bullets if "fecha" in b]
    return bullets


def parsear_pdf(pdf_path: Path) -> dict:
    with pdfplumber.open(str(pdf_path)) as pdf:
        portada = parse_portada(pdf)
        informe = {
            "archivo_origen": pdf_path.name,
            **portada,
            "escenario_previsto": parse_escenario_previsto(pdf),
            "parque_generador": parse_parque_generador(pdf),
            "balance_semanal": parse_balance_semanal(pdf),
            "transporte_distribucion": parse_transporte_distribucion(pdf),
            "nuevas_habilitaciones_transporte": parse_bullets_fecha(pdf, "Nuevas habilitaciones de Transporte"),
            "nuevo_equipamiento_generacion": parse_bullets_fecha(pdf, "Nuevo Equipamiento de Generación"),
            "paginas_texto": [(p.extract_text() or "") for p in pdf.pages],
        }
    return informe


def clave_informe(informe: dict) -> str:
    if informe.get("anio") and informe.get("semana_b"):
        return f"{informe['anio']}_{informe['semana_b']}"
    return informe["archivo_origen"]


def main():
    if not INFORMES_DIR.exists():
        print(f"No existe {INFORMES_DIR}. Nada que hacer.")
        return

    pdfs = sorted(INFORMES_DIR.glob("*.pdf")) + sorted(INFORMES_DIR.glob("*.PDF"))
    pdfs = sorted(set(pdfs))
    if not pdfs:
        print("No se encontraron .pdf en informes/. Nada que hacer.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    informes = {}
    if INFORMES_JSON.exists():
        informes = json.loads(INFORMES_JSON.read_text())

    errores = []
    for pdf_path in pdfs:
        print(f"Procesando {pdf_path.name} ...")
        try:
            informe = parsear_pdf(pdf_path)
        except Exception as e:
            import traceback
            print(f"  ERROR: {e}", file=sys.stderr)
            errores.append({"archivo": pdf_path.name, "error": str(e), "traceback": traceback.format_exc()})
            continue
        key = clave_informe(informe)
        informes[key] = informe
        print(f"  -> {key} OK (semana {informe.get('semana_a')} y {informe.get('semana_b')}, año {informe.get('anio')})")

    INFORMES_JSON.write_text(json.dumps(informes, indent=2, ensure_ascii=False))
    print(f"\nInformes en la base: {sorted(informes.keys())}")

    if errores:
        (OUT_DIR / "informes_errors.json").write_text(json.dumps(errores, indent=2, ensure_ascii=False))
        print(f"\n¡ATENCIÓN! {len(errores)} informe(s) no se pudieron procesar. Detalle en processed/informes_errors.json")
        sys.exit(2)
    else:
        errores_path = OUT_DIR / "informes_errors.json"
        if errores_path.exists():
            errores_path.unlink()


if __name__ == "__main__":
    main()
