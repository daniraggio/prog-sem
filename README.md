# prog-sem — Seguimiento de Programación Semanal CAMMESA

Dashboard estático que se actualiza solo: subís un `.mdb` nuevo a `data/`, GitHub Actions lo
procesa y el dashboard (`index.html`, servido por GitHub Pages) lo muestra automáticamente —
incluida una sección especial con las máquinas de **Alto Valle** (AVALCC22, AVALCC23, AVALTG21,
AVALTG22, AVALTG23).

## Cómo queda andando (setup, una sola vez)

1. **Activar permisos de escritura para Actions** (necesario para que el workflow pueda commitear
   los JSON generados):
   `Settings → Actions → General → Workflow permissions → "Read and write permissions"` → Save.

2. **Activar GitHub Pages**:
   `Settings → Pages → Build and deployment → Source: "Deploy from a branch"` → Branch: `main` /
   carpeta `/ (root)` → Save.

   GitHub te va a dar una URL del tipo `https://daniraggio.github.io/prog-sem/`.

3. Listo. La primera vez, corré el workflow manualmente para generar los JSON iniciales:
   `Actions → "Procesar Programación Semanal CAMMESA" → Run workflow`.

## Uso semanal (lo único que tenés que hacer de acá en adelante)

1. Subí el `.mdb` nuevo a la carpeta `data/` del repo (vía web de GitHub, `git push`, o arrastrando
   el archivo en la interfaz de GitHub — "Add file → Upload files").
2. Eso dispara automáticamente el GitHub Action, que:
   - Convierte el `.mdb` con `mdbtools` y lo integra a `processed/historico.json` (sin pisar las
     semanas anteriores — es acumulativo e idempotente: si subís de nuevo la misma semana
     corregida, la reemplaza, no la duplica).
   - Recalcula `processed/analisis.json` con las comparaciones de **todas** las semanas: cada
     semana vs. la anterior y vs. el promedio de las últimas 4.
   - Commitea esos dos JSON al repo.
3. GitHub Pages redeploya solo (no hace falta tocar nada más). En 1-2 minutos el dashboard ya
   muestra la semana nueva.

No hace falta instalar nada en tu máquina ni correr scripts a mano — todo el procesamiento corre
en GitHub Actions.

## Estructura del repo

```
data/                          ← subís acá cada .mdb semanal (psemXXYY.MDB)
informes/                      ← subís acá cada informe PDF quincenal "Previsión Despacho Energético"
scripts/
  etl_to_json.py                ← .mdb → processed/historico.json (acumulativo)
  analisis.py                   ← historico.json → processed/analisis.json (KPIs + comparaciones)
  parse_informes.py             ← informes/*.pdf → processed/informes.json
  print_etl_summary.py          ← auxiliar, imprime errores de carga para el resumen de CI
processed/
  historico.json                ← datos crudos extraídos de cada semana (generado, no tocar a mano)
  analisis.json                 ← KPIs, variaciones semana a semana y serie histórica (lo que lee el dashboard)
  informes.json                 ← informes PDF parseados (lo que lee la sección "Informe CAMMESA")
index.html                      ← el dashboard (fetch de processed/analisis.json y processed/informes.json)
requirements.txt                ← dependencias Python (pdfplumber)
.github/workflows/build.yml     ← el Action que corre el pipeline al subir un .mdb o un .pdf
```

## Informe PDF quincenal "Previsión Despacho Energético"

Además de la programación semanal (`.mdb`), el sistema procesa el informe PDF que CAMMESA publica
cada dos semanas.

**Dónde subirlo:** carpeta `informes/` (separada de `data/`, porque es otro tipo de archivo con otra
cadencia). Subir el `.pdf` ahí dispara el mismo workflow automáticamente.

**Qué extrae** (`scripts/parse_informes.py`, usando `pdfplumber`):
- Escenario previsto (importación/exportación, gas, hidrología por cuenca — texto)
- Situación del parque generador: tablas de centrales térmicas e hidráulicas indisponibles
  (central, máquina, fecha, motivo)
- Balance semanal de las 2 semanas que cubre el informe: demanda, generación por tecnología,
  consumo de combustibles, despacho medio y niveles de embalses por central hidráulica
- Transporte y distribución: condiciones del STAT y tabla de mantenimientos relevantes por día
- Nuevas habilitaciones de transporte y nuevo equipamiento de generación (con fecha, potencia,
  empresa y provincia cuando el texto lo permite extraer con confianza)

**Cómo identifica cada sección:** por el TÍTULO de la slide (no por número de página fijo), así
tolera que se agreguen o saquen páginas en futuros informes. Las tablas se extraen
posicionalmente; si la estructura interna de alguna cambia de forma inesperada en un informe
futuro, el campo estructurado correspondiente puede quedar vacío — por eso el dashboard **siempre**
muestra también el texto crudo completo de cada página al final de la sección (colapsado, click
para expandir), para que nunca se pierda información aunque el parseo estructurado falle.

**Nada se inventa:** lo que el parser no puede extraer con confianza queda vacío/`null`, nunca se
completa con un valor supuesto.

**Identificador de cada informe:** `{año}_{semana_b}` (la segunda de las dos semanas que cubre,
que suele ser la semana "actual"/próxima del informe). Si subís un informe corregido de la misma
quincena, se reemplaza — no se duplica.

## Cómo navegar el dashboard

- **Título común** "Programación Semanal CAMMESA" arriba de todo, visible en las tres secciones.
- **Menú lateral izquierdo**, en este orden: **📄 Informe CAMMESA** (el PDF quincenal), **▦ Mercado
  (MEM)** (la que se abre por defecto al entrar), y **★ Alto Valle**.
- El selector de semana (y los botones ◀ ▶), abajo en el menú lateral, aplica a ambas secciones —
  permiten ver **cualquier semana cargada**, no solo la última, cada una comparada contra su propia
  semana anterior y su propio promedio de 4 semanas.
- **Alertas en slots fijos**: la franja de chips debajo de los KPIs siempre muestra el mismo
  conjunto de indicadores, en el mismo orden (demanda, los 5 combustibles, los 3 bloques de costo
  marginal, centrales que salen/entran, embalses nuevos) — si una semana no tiene novedad en algún
  punto, el chip dice "sin cambios" en vez de desaparecer. Así la franja no cambia de forma ni de
  orden semana a semana. Pasando el cursor sobre los chips de "salen/entran de servicio" aparece un
  globito con el detalle de qué centrales son.
- **Centrales**: una sola tabla con **todas** las centrales del archivo, ordenable por cualquier
  columna y filtrable (Todas / Con cambios / Sin cambios), con encabezado fijo (sticky) al scrollear
  y ~15 filas visibles antes de necesitar scroll interno. Arriba, un cuadro resumen muestra, para
  cada grupo: cantidad, energía total (MWh) y potencia media equivalente (MW).
- **Unidades sin generación**: mismo criterio — encabezado fijo, ~15 filas visibles, scroll interno
  para el resto. Solo el dato real (unidad/región/empresa/tipo), sin inferir causa.
- **Combustibles**: el cuadro lateral ahora lista **todos** los combustibles de la semana (no solo
  los que superan el umbral de variación), con su unidad. El gráfico usa barras agrupadas (no
  apiladas) porque las unidades difieren entre combustibles.
- **★ Alto Valle**: siempre muestra las 5 tarjetas (AVALCC22/23, AVALTG21/22/23) en el mismo orden y
  en la misma posición. Si alguna semana una unidad no aparece en el archivo de CAMMESA (en vez de
  aparecer con 0 MWh, directamente no está en la fuente), la tarjeta se muestra igual con la
  etiqueta "sin datos" en lugar de desaparecer y descuadrar la grilla.

### Nota importante sobre "potencia" (MW)

El `.mdb` de programación semanal de CAMMESA **no incluye la potencia nominal instalada** de cada
unidad — solo trae energía programada (MWh) por día/semana. Por eso todo lo que el dashboard
muestra en MW es **potencia media equivalente** = MWh ÷ 168 horas (la potencia constante que,
sostenida toda la semana, produciría esa energía). No es la placa/potencia instalada de la máquina,
es un indicador derivado para poder comparar magnitudes en términos de potencia.

### Fuente de las unidades de combustibles

`CONSUMO_COMB` no trae un campo de unidad en el `.mdb`. Las unidades que se muestran (Gas Natural
[Dam³], Gas Oil [m³], Fuel Oil [Ton], Carbón Mineral [Ton]) se tomaron del dataset público oficial
de CAMMESA "Consumo de combustibles por tipo de máquina y tipo de tecnología"
(`datos.gob.ar/dataset/energia-datos-compania-administradora-mercado-mayorista-electrico-sa-cammesa`),
no son una suposición. `GasAcue` y `GasProp` son ambas vías de gas natural (por gasoducto / propio
o contratado), por eso comparten unidad (Dam³).

### Fix: costo marginal en 0 en algunas semanas

Se detectó que la tabla `PRECIOS` no usa siempre el mismo nombre de variable para el costo marginal
horario: la mayoría de los archivos traen `CMgh`, pero algunos (por ejemplo la semana 20) lo llaman
`CMO`, y además incluyen una variable extra `MER` con una escala totalmente distinta (~15.000 vs.
~300.000) que no es costo marginal. El ETL anterior mezclaba todo por `Bloque` sin distinguir la
variable, lo que en esas semanas terminaba pisando el dato real con el de `MER` (o quedando vacío).
Ahora `etl_to_json.py` elige explícitamente una sola variable por semana, con prioridad
`CMgh` → `CMO`, y nunca mezcla variables distintas bajo el mismo bloque horario.



## Corriendo el pipeline en local (opcional, para probar antes de subir a GitHub)

```bash
sudo apt-get install mdbtools   # una sola vez
pip install -r requirements.txt # una sola vez (pdfplumber, para los informes PDF)
python3 scripts/etl_to_json.py
python3 scripts/analisis.py
python3 scripts/parse_informes.py
python3 -m http.server 8000     # y abrir http://localhost:8000
```

## Umbrales de alerta (editables en `scripts/analisis.py`)

| Indicador | Umbral |
|---|---|
| Variación de generación por central | >10% |
| Variación de demanda neta | >5% |
| Variación de consumo de combustibles | >15% |
| Variación de costo marginal | >10% |
| Entrada/salida de servicio de cualquier unidad | siempre se reporta |

## Diccionario de datos y supuestos

Ver `DICCIONARIO_DATOS.md` para el detalle de las 13 tablas del `.mdb`, su estructura jerárquica
(país → región → central → unidad), catálogos de códigos y supuestos documentados (por ejemplo,
que no existe una tabla explícita de mantenimientos y las indisponibilidades se infieren por
generación = 0 MWh).

## Próximas mejoras sugeridas

- Sumar la base de indisponibilidades real de CAMMESA (si está disponible) para distinguir
  mantenimiento programado de no-despacho por mérito económico.
- Exportar automáticamente un PDF de una página con el resumen ejecutivo de cada semana.
- Si CAMMESA llega a completar `TVP`/`CVP_COMB` (precios y costos variables por combustible y
  central), el pipeline ya está preparado para incorporarlos sin cambios de código.
