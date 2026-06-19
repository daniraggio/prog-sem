# Diccionario de Datos — Programación Semanal CAMMESA (.MDB)

_Basado en el relevamiento real de los 4 archivos provistos: `psem2326.MDB` (semana 23),
`psem2426.MDB` (semana 24), `psem2526.MDB` (semana 25), `psem2626.MDB` (semana 26 — todas de 2026).
Las 4 bases comparten exactamente el mismo esquema (13 tablas)._

## Modelo general

Cada archivo `.MDB` representa **una semana de programación estacional** (lunes a domingo, 7 días).
La mayoría de las tablas usan el patrón **"ancho"**: una columna por día (`Dia1`...`Dia7`, o `D0`...`D7`
en el caso de cotas hidráulicas), más una columna `Total`/`Med` con el acumulado o promedio semanal.

No existen claves primarias/foráneas declaradas formalmente en el motor Jet/Access (es una base
"plana" tipo hoja de cálculo), pero hay relaciones **lógicas** claras por nombre de campo:

```
FECHA (1 fila, ancla de la semana)
   └── NumSemana  ──┐  (clave temporal implícita en TODAS las tablas vía la semana del archivo)
                     │
GENERACION ──Generador/Empresa/Region──► jerarquía de despacho
   Var (tecnología) → Region → Empresa → Generador (central) → TipoMaq (unidad)

COTAS / QENTRANTE / VALORES_AGUA / HIDRO / GRUPOS_HID ──CentHidr──► identifican la misma central
                                                                      hidráulica entre sí

PRECIOS ──Region/Bloque──► nodo y franja horaria del costo marginal

CONSUMO_COMB ──Combustible──► tipo de combustible consumido por el parque térmico

TVP / CVP_COMB ──Generador──► costos variables de producción por combustible y central
```

La relación entre tablas es por **coincidencia de texto** en los campos `Generador`, `CentHidr`,
`Region`, `Empresa` — no hay un ID numérico autoincremental. Para el sistema de seguimiento, la
clave temporal `NumSemana` (tomada de la tabla `FECHA`) es la que permite "coser" todas las
tablas entre sí y entre archivos sucesivos.

---

## Tabla `FECHA`
**Función:** Ancla temporal del archivo. Una sola fila, identifica a qué semana corresponde toda la programación.

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| FInicio | DateTime | Fecha del lunes (Día 1) de la semana programada |
| DiaIni | Integer | Día de la semana de inicio (1 = lunes) |
| NumSemana | Integer | **Número de semana del año** — clave para vincular con todas las demás tablas y versionar el histórico |

---

## Tabla `RESUMEN`
**Función:** Tablero de indicadores agregados del sistema completo (la tabla más "ejecutiva" del archivo). 18 filas, cada una es una variable de mercado distinta.

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| Orden | Integer | Orden de presentación en el reporte original de CAMMESA |
| Var | Text(8) | Código corto de la variable (ver catálogo abajo) |
| Descrip | Text(30) | Descripción legible |
| Dia1...Dia7 | Double | Valor diario (MW de potencia pico o MWh de energía, según la variable) |
| Total | Double | Acumulado semanal (vacío para variables de potencia, no de energía) |

**Catálogo de `Var` observado:**

| Var | Descripción | Unidad |
|---|---|---|
| POTPICO | Potencia pico prevista | MW |
| POTEXPP | Potencia exportada en el pico | MW |
| POTTPICO | Potencia pico total | MW |
| DEMNETA | Demanda neta del sistema | MWh/día |
| PERDIDAS | Pérdidas de transporte | MWh/día |
| DEMBRUTA | Demanda bruta (neta + pérdidas) | MWh/día |
| EXPORT | Exportación total | MWh/día |
| BOMBEO | Consumo de centrales de bombeo | MWh/día |
| DEMABAST | Demanda a abastecer (bruta + export + bombeo) | MWh/día |
| FALLAS | Energía no suministrada (falla de abastecimiento) | MWh/día |
| IMPORT | Importación total | MWh/día |
| GEN_TV | Generación turbo-vapor | MWh/día |
| GEN_TG | Generación turbo-gas | MWh/día |
| GEN_CC | Generación ciclo combinado | MWh/día |
| GEN_DI | Generación motores diésel | MWh/día |
| GEN_NU | Generación nuclear | MWh/día |
| GEN_HI | Generación hidráulica | MWh/día |
| GEN_RE | Generación renovable | MWh/día |

---

## Tabla `GENERACION`
**Función:** Tabla más granular y de mayor volumen (975 filas). Programación de generación con **jerarquía de 4 niveles** dentro del mismo registro tabular (se distingue por qué campos vienen vacíos):

| Nivel | Patrón de campos llenos | Ejemplo |
|---|---|---|
| 1. País / tecnología | Var lleno; Region, Empresa, Generador vacíos | `GEN_HID` total nacional |
| 2. Región / tecnología | Var + Region; Empresa y Generador vacíos | `GEN_HID` + `CHO` (Comahue) |
| 3. Central | Var + Region + Empresa; Generador vacío | `GEN_HID/CHO/ALICURA` |
| 4. Unidad de generación | Var + Region + Empresa + Generador + TipoMaq | `GEN_HID/CHO/ALICURA/ALICHI/HI` |

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| Var | Text(8) | Tecnología agregada: GEN_HID, GEN_TER, GEN_NUC, GEN_REN, GEN_IMP |
| Region | Text(3) | Región eléctrica CAMMESA (ver catálogo abajo) |
| Empresa | Text(20) | Nombre comercial de la central (ej. "COSTANERA", "ALICURA") |
| Generador | Text(8) | Código de la unidad generadora específica (ej. "ALICHI") |
| TipoMaq | Text(2) | Tipo de máquina de la unidad (ver catálogo) |
| Dia1...Dia7 | Double | Energía programada por día (MWh) |
| Total | Double | Energía programada semanal (MWh) |

**Catálogo `TipoMaq`:** CC=Ciclo Combinado, TV=Turbo Vapor, TG=Turbo Gas, DI=Diésel/Motor,
HI=Hidráulica, NU=Nuclear, EO=Eólica, FV=Fotovoltaica (solar), IM=Importación.

**Catálogo `Region`** (24 valores observados): ABA, BBL, BOM, CHO (Comahue), COM, CUY (Cuyo),
EPE, EPN, ESE, EZE (Buenos Aires/Edesur), FUT, GAR, LIT (Litoral), MIS, NEA, NOA, NON, NOR,
ROD, S33, SUR, URU, UTE.

---

## Tabla `CONSUMO_COMB`
**Función:** Consumo semanal de combustibles del parque térmico, en unidades físicas (no energéticas).

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| Combustible | Text(8) | Carbon, Dies_Oil (gasoil), Fuel_Oil, GasAcue (gas por gasoducto), GasProp (gas propio/contratado) |
| Dia1...Dia7 | Double | Consumo diario (unidad física del combustible, ej. m³/día, ton/día según tipo) |
| Total | Double | Consumo semanal total |

---

## Tabla `PRECIOS`
**Función:** Costo marginal horario esperado, desagregado por bloque horario.

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| Var | Text(8) | `CMgh` = Costo Marginal horario |
| Region | Text(30) | Nodo de referencia (en los 4 archivos: "EZE") |
| Bloque | Text(8) | Franja horaria: PICO, RESTO, VALLE |
| Dia1...Dia7 | Double | Costo marginal esperado del día/bloque ($/MWh, pesos nominales) |

---

## Tabla `COTAS`
**Función:** Nivel de embalse (cota) de centrales hidráulicas al inicio y fin de la semana — clave para evaluar disponibilidad de generación hidráulica futura.

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| CentHidr | Text(8) | Código de la central hidráulica (ALICHI, CHOCHI, FUTAHI, etc.) |
| CotaIni | Double | Cota (m s.n.m.) al inicio de la semana |
| CotaFin | Double | Cota (m s.n.m.) prevista al fin de la semana |

## Tabla `HIDRO`
**Función:** Evolución diaria de la cota de cada central hidráulica (versión "ancha" diaria de COTAS).

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| Var | Integer | Código interno de agrupación |
| Descripcion | Text(30) | Código de la central hidráulica |
| D0...D7 | Double | Cota diaria (m s.n.m.) |
| DTotal | Double | (vacío en la práctica — no aplica promedio a una cota) |

## Tabla `QENTRANTE`
**Función:** Caudal entrante (aporte hídrico natural) programado por central, en m³/s.

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| CentHidr | Text(8) | Central hidráulica |
| Dia1...Dia7 | Double | Caudal entrante diario (m³/s) |
| Med | Double | Caudal medio semanal (m³/s) |

## Tabla `VALORES_AGUA`
**Función:** Valor económico del agua embalsada (señal de oportunidad de uso vs. ahorro) y comentarios de restricciones operativas.

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| Region | Text(3) | Región eléctrica |
| CentHidr | Text(8) | Central hidráulica |
| Valor | Double | Valor del agua ($/MWh aprox., escala relativa) |
| Comentario | Text(255) | Restricción operativa textual (ej. "RESTRINGIDO OPERACIÓN MEDIANO PLAZO") — **fuente de alertas cualitativas** |

## Tabla `GRUPOS_HID`
**Función:** Agrupa centrales hidráulicas en cuencas/sistemas para análisis conjunto.

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| GRUPO | Text(20) | Nombre del sistema hidráulico (ej. "COMAHUE", "CUYO") |
| CentHidr | Text(8) | Central perteneciente al grupo |
| Orden | Integer | Orden dentro del grupo (aguas arriba → abajo, probablemente) |

---

## Tabla `TEMPERATURAS`
**Función:** Temperatura de referencia usada en la previsión de demanda (proxy climático). Una sola fila.

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| Dia1...Dia7 | Double | Temperatura media prevista por día (°C) |

---

## Tabla `AUX_FLUJOS`
**Función:** Definición de corredores de transporte/interconexión entre regiones — metadata de topología de red, no datos de la semana en sí.

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| Corredor | Text(6) | Código del corredor de transporte (ej. "NOACEN") |
| Nodo1 / Nodo2 | Text(3) | Regiones que conecta el corredor |
| Orden | Integer | Orden del corredor |
| Signo | Integer | Convención de signo del flujo (+1/-1) según sentido |

---

## Tabla `TVP`
**Función:** Precios de combustibles ($/unidad) por central, usados para el cálculo de costos variables de producción. **En los 4 archivos provistos esta tabla está prácticamente vacía** (una fila sin datos) — posible limitación de la fuente o campo no utilizado en este ciclo de programación.

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| Area | Text(30) | Área de referencia de precios |
| Generador | Text(8) | Central |
| pGN / pFO / pGO / pCM | Double | Precio de gas natural / fuel oil / gasoil / carbón mineral |

## Tabla `CVP_COMB`
**Función:** Costo variable de producción por combustible y central. **Vacía en los 4 archivos provistos** (0 filas) — a monitorear si se completa en futuras semanas.

| Campo | Tipo | Interpretación de negocio |
|---|---|---|
| Generador | Text(8) | Central |
| CVP_GN / CVP_FO / CVP_GO / CVP_CM | Double | Costo variable de producción por tipo de combustible |

---

## Mapeo a los objetivos de análisis solicitados

| Objetivo | Tabla(s) fuente |
|---|---|
| Generación térmica | GENERACION (Var=GEN_TER), RESUMEN (GEN_TV/GEN_TG/GEN_CC/GEN_DI) |
| Generación hidráulica | GENERACION (Var=GEN_HID), COTAS, HIDRO, QENTRANTE, VALORES_AGUA, GRUPOS_HID |
| Generación renovable | GENERACION (Var=GEN_REN, TipoMaq=EO/FV) |
| Intercambios internacionales | RESUMEN (IMPORT/EXPORT), GENERACION (Var=GEN_IMP) |
| Combustibles | CONSUMO_COMB, TVP, CVP_COMB |
| Costos marginales | PRECIOS |
| Precios estacionales | PRECIOS (es la fuente más cercana disponible; no hay tabla de "precio estacional" explícita) |
| Restricciones de transporte | AUX_FLUJOS (topología); no se observan límites de capacidad de corredores en estos archivos |
| Disponibilidad de unidades | GENERACION a nivel unidad (TipoMaq lleno) — se infiere indisponibilidad cuando MWh=0 toda la semana |
| Mantenimientos | No hay tabla explícita de mantenimientos en este archivo. Se infiere indirectamente por unidades con generación 0 sostenida o por VALORES_AGUA.Comentario |
| Potencia y energía programada | RESUMEN (POTPICO/POTTPICO), GENERACION (energía por nivel) |

### Supuestos documentados
1. **No hay tabla de mantenimientos explícita** en el MDB de programación semanal (a diferencia de otras bases de CAMMESA como la de indisponibilidades). Las "salidas de servicio" que reporta el sistema son **inferidas**: unidades con `MWh = 0` durante toda la semana. Esto puede confundir indisponibilidad real con unidades simplemente no despachadas por mérito económico — se recomienda contrastar con la base de indisponibilidades de CAMMESA si está disponible.
2. El "nivel central" se identifica por filas con `Empresa` cargada y `Generador` vacío; el "nivel unidad" por filas con `Generador` cargado (que siempre traen `TipoMaq`).
3. `TVP` y `CVP_COMB` llegaron vacías en las 4 semanas — el sistema está preparado para poblarlas automáticamente si en el futuro CAMMESA las completa.
4. Los precios (`PRECIOS`) solo traen el nodo EZE en estos 4 archivos; si en alguna semana aparecen más nodos, el sistema los incorpora automáticamente (no hay nada hardcodeado).
