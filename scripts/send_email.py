#!/usr/bin/env python3
"""
Reporte por email — CAMMESA Tracker
=====================================
Envía un resumen de los archivos nuevos descargados (programación semanal
y/o redespacho) con los indicadores clave extraídos de los JSONs procesados.

Variables de entorno requeridas (GitHub Secrets):
  GMAIL_APP_PASSWORD   → App Password de 16 dígitos de la cuenta Gmail
  NUEVOS_ARCHIVOS      → lista de archivos separada por comas (del paso download)

Variables opcionales:
  EMAIL_FROM           → remitente (default: jarvis.aconcagua@gmail.com)
  EMAIL_TO             → destinatario (default: igual que EMAIL_FROM)

USO:
    GMAIL_APP_PASSWORD=xxxx NUEVOS_ARCHIVOS=psem2726.MDB python3 scripts/send_email.py
"""
import json
import os
import smtplib
import sys
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT     = Path(__file__).resolve().parent.parent
TZ_ARG   = timezone(timedelta(hours=-3))

EMAIL_FROM = os.environ.get("EMAIL_FROM", "jarvis.aconcagua@gmail.com")
EMAIL_TO   = os.environ.get("EMAIL_TO",   "draggio@aconcaguaenergia.com", "jspinoso@aconcaguaenergia.com")
APP_PASS   = os.environ.get("GMAIL_APP_PASSWORD", "")
ARCHIVOS   = [f.strip() for f in os.environ.get("NUEVOS_ARCHIVOS", "").split(",") if f.strip()]


def fmt(n, dec=0):
    if n is None:
        return "s/d"
    try:
        return f"{float(n):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(n)


def cargar_json(path):
    p = ROOT / "processed" / path
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return None


def seccion_programacion(semana_num):
    """Genera el bloque HTML con los datos de una semana nueva."""
    analisis = cargar_json("analisis.json")
    if not analisis:
        return "<p>No se pudo leer analisis.json</p>"

    D = analisis.get("por_semana", {}).get(str(semana_num))
    if not D:
        return f"<p>No se encontraron datos para la semana {semana_num}</p>"

    finicio = D.get("finicio", "")
    sem_ant = D.get("semana_anterior")

    # Calcular rango de fechas
    rango = ""
    try:
        from datetime import datetime, timedelta
        m = __import__("re").match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", finicio)
        if m:
            f0 = datetime(2000 + int(m.group(3)) if len(m.group(3)) == 2 else int(m.group(3)),
                          int(m.group(1)), int(m.group(2)))
            f1 = f0 + timedelta(days=6)
            rango = f"{f0.strftime('%d/%m/%Y')} → {f1.strftime('%d/%m/%Y')}"
    except Exception:
        rango = finicio

    gt  = D.get("generacion_por_tecnologia", {}).get("actual", {})
    gt_ant = D.get("generacion_por_tecnologia", {}).get("anterior", {})
    dem = D.get("demanda", {})
    dn  = dem.get("demanda_neta", {})
    imp = dem.get("importacion", {})

    def delta_str(pct):
        if pct is None:
            return ""
        arrow = "▲" if pct > 0 else "▼"
        color = "#e74c3c" if pct > 5 else "#27ae60" if pct < -5 else "#7f8c8d"
        return f' <span style="color:{color};font-size:12px">{arrow} {fmt(abs(pct), 1)}%</span>'

    tecs = [
        ("Térmica",    "#f39c12"), ("Hidráulica", "#3498db"),
        ("Nuclear",    "#9b59b6"), ("Renovable",  "#27ae60"),
        ("Importación","#95a5a6"),
    ]
    filas_gen = ""
    for tec, color in tecs:
        mwh = gt.get(tec)
        pct = gt.get(f"{tec}_pct")
        mwh_ant = gt_ant.get(tec)
        var = None
        if mwh and mwh_ant:
            var = round((mwh - mwh_ant) / mwh_ant * 100, 1)
        filas_gen += f"""
        <tr>
          <td style="padding:6px 10px;border-bottom:1px solid #eee;">
            <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:{color};margin-right:6px"></span>
            {tec}
          </td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right">{fmt(mwh)} MWh</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right">{fmt(pct, 1)}%</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right">{fmt(var, 1) + '%' if var is not None else '—'}{delta_str(var)}</td>
        </tr>"""

    # Alertas relevantes
    alertas = []
    if dn.get("variacion_pct") and abs(dn["variacion_pct"]) >= 5:
        v = dn["variacion_pct"]
        alertas.append(f'{"▲" if v > 0 else "▼"} Demanda neta {fmt(abs(v), 1)}% vs semana anterior')
    for c in D.get("cambios_combustibles", []):
        alertas.append(f'{"▲" if c["variacion_pct"] > 0 else "▼"} {c["combustible"]} {fmt(abs(c["variacion_pct"]), 1)}% ({c.get("unidad", "")})')
    for c in D.get("cambios_costo_marginal", []):
        alertas.append(f'{"▲" if c["variacion_pct"] > 0 else "▼"} CMg {c["bloque"]} {fmt(abs(c["variacion_pct"]), 1)}%')
    salientes = [c["central"] for c in D.get("centrales", []) if c.get("evento") == "SALE_DE_SERVICIO"]
    entrantes = [c["central"] for c in D.get("centrales", []) if c.get("evento") == "ENTRA_EN_SERVICIO"]
    if salientes:
        alertas.append(f"Salen de servicio: {', '.join(salientes[:5])}")
    if entrantes:
        alertas.append(f"Entran en servicio: {', '.join(entrantes[:5])}")

    alertas_html = "".join(f'<li style="margin:4px 0;color:#555">{a}</li>' for a in alertas) if alertas else "<li style='color:#7f8c8d'>Sin alertas relevantes</li>"

    comp = f"comparado vs semana {sem_ant}" if sem_ant else "primera semana sin comparación previa"

    return f"""
    <h2 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:8px">
        Semana {semana_num} — {rango}
    </h2>
    <p style="color:#7f8c8d;margin-top:-8px;margin-bottom:16px">{comp}</p>

    <div style="display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap">
      <div style="flex:1;min-width:160px;background:#f8f9fa;border-radius:6px;padding:14px;border-left:4px solid #3498db">
        <div style="font-size:11px;color:#7f8c8d;text-transform:uppercase;letter-spacing:1px">Demanda Neta</div>
        <div style="font-size:22px;font-weight:700;margin:4px 0">{fmt(dn.get("actual"))} MWh</div>
        <div style="font-size:12px;color:#7f8c8d">{delta_str(dn.get("variacion_pct"))}</div>
      </div>
      <div style="flex:1;min-width:160px;background:#f8f9fa;border-radius:6px;padding:14px;border-left:4px solid #f39c12">
        <div style="font-size:11px;color:#7f8c8d;text-transform:uppercase;letter-spacing:1px">Generación Térmica</div>
        <div style="font-size:22px;font-weight:700;margin:4px 0">{fmt(gt.get("Térmica"))} MWh</div>
        <div style="font-size:12px;color:#7f8c8d">{fmt(gt.get("Térmica_pct"), 1)}% del total</div>
      </div>
      <div style="flex:1;min-width:160px;background:#f8f9fa;border-radius:6px;padding:14px;border-left:4px solid #27ae60">
        <div style="font-size:11px;color:#7f8c8d;text-transform:uppercase;letter-spacing:1px">Renovable</div>
        <div style="font-size:22px;font-weight:700;margin:4px 0">{fmt(gt.get("Renovable_pct"), 1)}%</div>
        <div style="font-size:12px;color:#7f8c8d">{fmt(gt.get("Renovable"))} MWh</div>
      </div>
      <div style="flex:1;min-width:160px;background:#f8f9fa;border-radius:6px;padding:14px;border-left:4px solid #95a5a6">
        <div style="font-size:11px;color:#7f8c8d;text-transform:uppercase;letter-spacing:1px">Importación</div>
        <div style="font-size:22px;font-weight:700;margin:4px 0">{fmt(imp.get("actual"))} MWh</div>
        <div style="font-size:12px;color:#7f8c8d">{delta_str(imp.get("variacion_pct"))}</div>
      </div>
    </div>

    <h3 style="color:#2c3e50">Generación por tecnología</h3>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>
        <tr style="background:#f8f9fa">
          <th style="padding:8px 10px;text-align:left;color:#7f8c8d;font-weight:500">Tecnología</th>
          <th style="padding:8px 10px;text-align:right;color:#7f8c8d;font-weight:500">MWh</th>
          <th style="padding:8px 10px;text-align:right;color:#7f8c8d;font-weight:500">% total</th>
          <th style="padding:8px 10px;text-align:right;color:#7f8c8d;font-weight:500">Var. vs sem. ant.</th>
        </tr>
      </thead>
      <tbody>{filas_gen}</tbody>
    </table>

    <h3 style="color:#2c3e50;margin-top:20px">Alertas</h3>
    <ul style="margin:0;padding-left:20px">{alertas_html}</ul>
    """


def seccion_redespacho(semana_num):
    """Genera el bloque HTML con el resumen del redespacho."""
    comp = cargar_json("comparacion_redespacho.json")
    if not comp:
        return "<p>No se pudo leer comparacion_redespacho.json</p>"

    rd = comp.get(str(semana_num))
    if not rd:
        return f"<p>No se encontraron datos de redespacho para la semana {semana_num}</p>"

    motivos = rd.get("motivos") or []
    motivos_html = "".join(
        f'<li style="margin:4px 0;color:#e67e22;font-weight:600">{m}</li>'
        for m in motivos
    ) if motivos else "<li style='color:#7f8c8d'>Sin motivos informados</li>"

    filas_bal = ""
    labels = {"termico": "Térmica", "hidraulico": "Hidráulica", "nuclear": "Nuclear",
               "renovable": "Renovable", "importacion": "Importación"}
    for k, label in labels.items():
        v = rd.get("balance", {}).get(k, {})
        if not v:
            continue
        prog = v.get("programado_gwh")
        redesp = v.get("redespachado_gwh")
        delta = v.get("delta_gwh")
        pct   = v.get("delta_pct")
        color = "#e74c3c" if (delta or 0) > 0 else "#27ae60" if (delta or 0) < 0 else "#7f8c8d"
        filas_bal += f"""
        <tr>
          <td style="padding:6px 10px;border-bottom:1px solid #eee">{label}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right">{fmt(prog, 1)}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right">{fmt(redesp, 1)}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:{color}">
            {('+' if (delta or 0) > 0 else '') + fmt(delta, 1) if delta is not None else '—'} GWh
            {f'({fmt(pct, 1)}%)' if pct is not None else ''}
          </td>
        </tr>"""

    fecha_em = rd.get("fecha_emision", "")
    try:
        fecha_em = datetime.fromisoformat(fecha_em).strftime("%d/%m/%Y %H:%M")
    except Exception:
        pass

    return f"""
    <h2 style="color:#2c3e50;border-bottom:2px solid #e67e22;padding-bottom:8px">
        ⚡ Redespacho — Semana {semana_num}
    </h2>
    <p style="color:#7f8c8d;margin-top:-8px;margin-bottom:16px">Emitido: {fecha_em}</p>

    <h3 style="color:#2c3e50">Motivos del redespacho</h3>
    <ul style="margin:0 0 16px;padding-left:20px">{motivos_html}</ul>

    <h3 style="color:#2c3e50">Balance — Programado vs. Redespachado (GWh)</h3>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>
        <tr style="background:#fef9f0">
          <th style="padding:8px 10px;text-align:left;color:#7f8c8d;font-weight:500">Tecnología</th>
          <th style="padding:8px 10px;text-align:right;color:#7f8c8d;font-weight:500">Programado</th>
          <th style="padding:8px 10px;text-align:right;color:#7f8c8d;font-weight:500">Redespachado</th>
          <th style="padding:8px 10px;text-align:right;color:#7f8c8d;font-weight:500">Variación</th>
        </tr>
      </thead>
      <tbody>{filas_bal}</tbody>
    </table>
    """


def seccion_combustibles(semana_num):
    """Tabla de consumo de combustibles con barras de progreso visuales."""
    analisis = cargar_json("analisis.json")
    if not analisis:
        return ""
    D = analisis.get("por_semana", {}).get(str(semana_num))
    if not D:
        return ""

    series = analisis.get("series", {}).get("consumo_combustibles", {})
    semanas = sorted(analisis.get("semanas_disponibles", []))

    # Datos actuales
    comb_actual = series.get(str(semana_num), {})
    if not comb_actual:
        return ""

    COLORES = {
        "GasAcue": "#3498db", "GasProp": "#2980b9",
        "Fuel_Oil": "#e74c3c", "Dies_Oil": "#e67e22", "Carbon": "#7f8c8d",
    }
    UNIDADES = {
        "GasAcue": "Dam³", "GasProp": "Dam³",
        "Fuel_Oil": "Ton", "Dies_Oil": "m³", "Carbon": "Ton",
    }
    NOMBRES = {
        "GasAcue": "Gas Acuerdo", "GasProp": "Gas Propio",
        "Fuel_Oil": "Fuel Oil", "Dies_Oil": "Gas Oil", "Carbon": "Carbón",
    }

    # Valor máximo para escalar las barras (máximo histórico de cada combustible)
    maximos = {}
    for s in semanas:
        for k, v in series.get(str(s), {}).items():
            if v and v > maximos.get(k, 0):
                maximos[k] = v

    filas = ""
    for k, v in comb_actual.items():
        if not v:
            continue
        nombre  = NOMBRES.get(k, k)
        unidad  = UNIDADES.get(k, "")
        color   = COLORES.get(k, "#95a5a6")
        maximo  = maximos.get(k, v) or v
        pct_bar = min(round(v / maximo * 100), 100)

        # Variación vs semana anterior
        sem_ant = semanas[-2] if len(semanas) >= 2 and semanas[-1] == semana_num else None
        v_ant   = series.get(str(sem_ant), {}).get(k) if sem_ant else None
        var_html = ""
        if v_ant and v_ant > 0:
            var = round((v - v_ant) / v_ant * 100, 1)
            flecha = "▲" if var > 0 else "▼"
            c_var = "#e74c3c" if var > 15 else "#27ae60" if var < -15 else "#7f8c8d"
            var_html = f'<span style="color:{c_var};font-size:11px;margin-left:6px">{flecha} {abs(var):.1f}%</span>'

        filas += f"""
        <tr>
          <td style="padding:8px 10px;width:110px;font-size:13px">{nombre}</td>
          <td style="padding:8px 10px">
            <div style="background:#f0f0f0;border-radius:3px;height:14px;overflow:hidden">
              <div style="background:{color};width:{pct_bar}%;height:14px;border-radius:3px"></div>
            </div>
          </td>
          <td style="padding:8px 10px;text-align:right;font-size:13px;white-space:nowrap">
            {fmt(v)} {unidad}{var_html}
          </td>
        </tr>"""

    return f"""
    <h3 style="color:#2c3e50;margin-top:20px">Consumo de combustibles</h3>
    <table style="width:100%;border-collapse:collapse">
      <tbody>{filas}</tbody>
    </table>
    """


def generar_html(nuevos):
    """Genera el cuerpo HTML del email."""
    ahora = datetime.now(TZ_ARG).strftime("%d/%m/%Y %H:%M")

    secciones = ""
    semanas_prog = []
    semanas_redesp = []

    for f in nuevos:
        f_lower = f.lower()
        if f_lower.endswith(".mdb"):
            import re
            m = re.search(r"psem(\d{2})\d{2}\.mdb", f_lower)
            if m:
                semanas_prog.append(int(m.group(1)))
        elif "redespacho" in f_lower and f_lower.endswith(".xls"):
            comp = cargar_json("comparacion_redespacho.json")
            if comp:
                semanas_redesp = list(comp.keys())

    for s in sorted(set(semanas_prog)):
        secciones += seccion_programacion(s)
        secciones += seccion_combustibles(s)

    for s in sorted(set(semanas_redesp)):
        secciones += seccion_redespacho(int(s))

    if not secciones:
        secciones = "<p>No se pudieron extraer datos de los archivos nuevos.</p>"

    # Título del header: usar la semana más relevante
    semana_label = ""
    if semanas_prog:
        semana_label = f"Semana {sorted(semanas_prog)[-1]}"
    elif semanas_redesp:
        semana_label = f"Semana {sorted(semanas_redesp)[-1]}"

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head><meta charset="UTF-8"></head>
    <body style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;color:#2c3e50">
      <div style="background:linear-gradient(135deg,#1a252f,#2c3e50);padding:24px;border-radius:8px 8px 0 0">
        <div style="color:#f39c12;font-size:11px;letter-spacing:2px;text-transform:uppercase">CAMMESA · Tracker</div>
        <h1 style="color:#fff;margin:8px 0 4px;font-size:22px">Actualización Programación Semanal CAMMESA{' — ' + semana_label if semana_label else ''}</h1>
        <div style="color:#95a5a6;font-size:13px">{ahora} · Archivos nuevos: {', '.join(nuevos)}</div>
      </div>
      <div style="padding:24px;background:#fff;border:1px solid #eee;border-top:none;border-radius:0 0 8px 8px">
        {secciones}
        <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
        <div style="text-align:center;padding:16px;background:#f8f9fa;border-radius:6px">
          <div style="font-size:13px;color:#7f8c8d;margin-bottom:10px">Ver tablero completo</div>
          <a href="http://10.203.16.33/ctavav/index.html"
             style="display:inline-block;background:#2c3e50;color:#fff;text-decoration:none;
                    padding:10px 24px;border-radius:4px;font-size:14px;font-weight:600">
            Abrir Dashboard →
          </a>
        </div>
        <p style="font-size:11px;color:#bdc3c7;text-align:center;margin-top:16px">
          Generado automáticamente por CAMMESA Tracker
        </p>
      </div>
    </body>
    </html>
    """


def main():
    if not APP_PASS:
        print("ERROR: GMAIL_APP_PASSWORD no está configurada", file=sys.stderr)
        sys.exit(1)

    if not ARCHIVOS:
        print("Sin archivos nuevos que reportar.")
        return

    print(f"Enviando reporte para: {ARCHIVOS}")

    # Extraer número de semana para el asunto
    import re
    semana_asunto = ""
    for f in ARCHIVOS:
        m = re.search(r"psem(\d{2})\d{2}\.mdb", f.lower())
        if m:
            semana_asunto = m.group(1)
            break
    asunto = f"Actualización Programación Semanal CAMMESA: Semana {semana_asunto}" if semana_asunto \
             else f"Actualización Programación Semanal CAMMESA: {', '.join(ARCHIVOS)}"

    html = generar_html(ARCHIVOS)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, APP_PASS)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"✓ Email enviado a {EMAIL_TO}")
    except Exception as e:
        print(f"ERROR al enviar email: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
