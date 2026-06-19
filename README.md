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
scripts/
  etl_to_json.py                ← .mdb → processed/historico.json (acumulativo)
  analisis.py                   ← historico.json → processed/analisis.json (KPIs + comparaciones)
processed/
  historico.json                ← datos crudos extraídos de cada semana (generado, no tocar a mano)
  analisis.json                 ← KPIs, variaciones semana a semana y serie histórica (lo que lee el dashboard)
index.html                      ← el dashboard (fetch de processed/analisis.json)
.github/workflows/build.yml     ← el Action que corre el pipeline al subir un .mdb
```

## Cómo navegar el dashboard

- El selector de semana arriba a la derecha (y los botones ◀ ▶) permiten ver **cualquier semana
  cargada**, no solo la última — cada una muestra su propia comparación contra la semana anterior
  y contra el promedio de las 4 semanas previas.
- La sección **★ Alto Valle** queda fija arriba de todo, con una tarjeta por máquina (estado activo/
  apagada, MWh de la semana, variación vs. semana anterior, y mini-gráfico de tendencia) más un
  gráfico de evolución histórica de las 5 unidades.
- Las alertas automáticas (franja de chips debajo de los KPIs) incluyen tanto las del sistema
  general como eventos de Alto Valle (entra/sale de servicio) marcados con un chip morado.

## Corriendo el pipeline en local (opcional, para probar antes de subir a GitHub)

```bash
sudo apt-get install mdbtools   # una sola vez
python3 scripts/etl_to_json.py
python3 scripts/analisis.py
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
