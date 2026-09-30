# Bitácora técnica — historial de decisiones

_Registro cronológico de cada prueba, tal como se hizo (29-09-2026). El resumen está en el [README](../README.md)._

## Cómo correrlo
- Doble clic en `ejecutar.bat`, o `python main.py`
- El reporte queda en `resultados\scan_AAAAMMDD_HHMM.xlsx` (hojas: Decisiones, Mercado, Config usada)
- Todos los parámetros se cambian en `config.yaml`

## Flujo
| Etapa | Archivo | Qué hace |
|---|---|---|
| Datos | `datos.py` | Descarga velas cerradas (API pública, sin clave) |
| Señales | `scanner.py` | EMA 20/50/200, RSI, ATR, volumen relativo → Ruptura, Pullback, Momentum, Continuación, Reversión |
| Plan | `planner.py` | Entrada, stop bajo el mínimo reciente (1–3 ATR), objetivo en la resistencia siguiente o 2R, R:B |
| Riesgo | `riesgo.py` | R:B mínimo, volatilidad, puntaje, tamaño (1% de riesgo), máx. posiciones, exposición, pérdida total, drawdown |

Veredicto: **APROBADO** (pasa todo) · **WATCHLIST** (casi, o sin cupo en la cartera) · **RECHAZADO**.

## Fase 2 — Backtest
- Doble clic en `ejecutar_backtest.bat`, o `python backtest.py` (~2,5 min; la primera vez descarga la historia a `datos_historicos\`, después solo lo nuevo)
- Usa **el mismo** `scanner.py` / `planner.py` / `riesgo.py`, vela por vela, viendo solo el pasado
- Entra en la apertura siguiente; si una vela toca stop y objetivo, asume stop. Comisión 0,1% por lado + 0,05% de deslizamiento. Salida por tiempo a las 42 velas
- Métricas separadas en **entrenamiento** (antes de `fecha_corte`) y **validación** (después)
- El freno por drawdown se desactiva en la simulación (congelaría el sistema para siempre); el drawdown sí se mide
- Reporte: `resultados\backtest_*.xlsx` (Resumen + gráfico, Por setup, Por par, Operaciones, Curva) y `curva_*.png`

### Resultado 1ª corrida (29-09-2026, 4H, 2023-09 → 2026-09)
418 operaciones · win rate 42,6% · expectativa +0,08R · profit factor 1,10 · +25,9% vs BTC +210% · drawdown −24%.
Validación (2025–2026) ≈ plana (+0,9%). Ruptura y Momentum positivos; Pullback y Continuación negativos.

### Ajustes aplicados (29-09-2026) y resultado
`setups_activos: [Ruptura, Momentum, Reversión]` + `tendencias_permitidas: [alcista]` en `config.yaml`.

| Versión | Expect. entren. | Expect. valid. | Retorno total | DD máx. |
|---|---|---|---|---|
| Original | +0,10R | +0,05R | +25,9% | −24% |
| Solo sin Pullback/Continuación | +0,22R | +0,04R | +37,7% | −21% |
| **+ filtro de tendencia (actual)** | +0,25R | +0,15R | +62,6% | −14% |

⚠️ El filtro de tendencia se eligió mirando los 3 años completos (en entrenamiento solo, lateral daba +0,08R),
así que la validación **no es limpia** para ese filtro.

### Prueba limpia: 2020-09 → 2023-09 (datos nunca vistos)
`python backtest.py --desde 2020-09-29 --hasta 2023-09-29`

| | Con filtro (actual) | Sin filtro |
|---|---|---|
| Operaciones | 250 | 292 |
| Expectativa | **+0,27R** | +0,16R |
| Profit factor | 1,48 | 1,26 |
| Retorno | **+85,9%** | +51,8% |
| Drawdown máx. | **−13,4%** | −18,2% |
| 2022 (bajista) | −0,13R | −0,23R |

BTC comprar y mantener en el mismo periodo: +152,8% con drawdown de −77%.
✅ El filtro de tendencia se confirma fuera de la muestra. Ruptura sostiene el sistema (+0,29R, 233 op.);
Momentum queda en +0,05R con 17 operaciones (muestra insuficiente).
⚠️ Sesgo de supervivencia: la lista de pares es la de hoy (no incluye monedas que colapsaron, como LUNA en 2022).

### Prueba A (stop dinámico) + fuerza relativa vs BTC — 29-09-2026
Criterio fijado ANTES de correr: se adopta solo si mejora en los dos periodos. Parámetros fijos, sin optimizar:
stop dinámico desde +1R a 3 ATR del cierre máximo; fuerza relativa = par le gana a BTC en 30 días.

| Versión | 2020-23 expect. / retorno / DD | 2023-26 expect. / retorno / DD |
|---|---|---|
| **Actual** | +0,27R / +86% / −13% | +0,20R / +63% / −14% |
| A: stop dinámico | +0,45R / +90% / −16% | +0,22R / **+45%** / **−21%** |
| Fuerza relativa | +0,33R / +106% / −12% | +0,19R / +56% / −17% |
| A + fuerza relativa | +0,38R / +67% / −16% | +0,22R / +40% / −22% |

❌ **Ninguna se adopta.** El stop dinámico gana más por operación (mejor operación: +22R) pero deja posiciones
abiertas mucho más tiempo, ocupa los 3 cupos y hace menos operaciones → menos retorno y más caída en 2023-26.
La fuerza relativa ayuda en 2020-23 y empeora en 2023-26. Ambas quedan como interruptores apagados en `config.yaml`
(`plan.salida`, `senales.fuerza_relativa_activa`). Gráfico: `resultados\comparacion_A_fuerza_relativa.jpg`.

## Paper trading (desde 29-09-2026)
- `paper.py` usa **el mismo motor** que el backtest (`cartera.py`), vela a vela, con capital ficticio
- Tarea programada de Windows **TRADER_IA_paper**: corre cada hora en segundo plano (si el PC estuvo apagado, se pone al día solo)
- Ver estado: doble clic en `ver_paper.bat` (actualiza y abre `paper\ESTADO.md`)
- Registro: `paper\log.txt` · historial: `paper\operaciones.csv` · curva: `paper\curva.csv`
- Partir de cero: `python paper.py --reset`
- Detener la tarea: `schtasks /Delete /TN TRADER_IA_paper /F`

