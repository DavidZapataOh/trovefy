---
tipo: regla
id: R-010
titulo: Ritmo del surf
fecha: 2026-11-19
fuente: "S1 10:00 y 10:27–11:30; S2 13:36, 14:10 y 14:40; T3 11:22 y 12:35; L2 21:25; C1 56:16; corrección del 2026-11-19 («los vídeos son la ley»)"
umbrales: [surf.cada_h, surf.roas_subir, surf.factor_subir, surf.roas_bajar, surf.factor_bajar, surf.base_hora, surf.base_usd]
estado: vigente
---

# R-010 · Ritmo del surf

## Regla

Durante el test, cada `surf.cada_h` (2) horas, de día y de noche, se mira cada conjunto con lo de **hoy**: con ROAS neto de al menos `surf.roas_subir` (2,0) **y** ventas nuevas desde la ronda anterior, su presupuesto se multiplica por `surf.factor_subir` (2); con ROAS al menos 2 pero sin ventas nuevas, no se toca; con ROAS neto de `surf.roas_bajar` (1,75) o menos, se multiplica por `surf.factor_bajar` (0,5), sin bajar nunca de la base. A las `surf.base_hora` (23) horas del país, todo conjunto vuelve a su base de `surf.base_usd` (5) US$.

## Por qué

Es lo que hacen los vídeos: «si tiene más de ROAS de dos, lo vas a duplicar… cada 2 horas» (S1 10:27); «SURFEAR: 50 % cada 2 hs. / +2 roas / 1.75 −50 % / 11pm poner todo [a la base]» (S2 14:10, S2 14:40); «solo con ventas nuevas: si mantiene el ROAS pero no vendió desde la última revisión, no se toca» (T3 12:35); en ABO, a nivel de cada conjunto (T3 11:22); «lo subís durante el día, lo bajás al final del día… a la hora de ese país» (C1 56:16). El techo de la campaña (R-007) sigue mandando: Meta para el gasto ahí.

## Cómo se aplica

`/leer --intradia` deposita cada cambio como propuesta de presupuesto (en la moneda de la cuenta, a la baja con la TRM) que aceptas por Telegram; el ejecutor relee después para confirmar que el conjunto sigue activo (T3 12:35). `/leer --base` deposita a las 23:00 del país la vuelta a la base de todos. Si un ×2 supera un límite del ejecutor, no se recorta en silencio: el parte lo dice y se propone subir el límite. Sin comisiones fijadas no hay ROAS neto, y sin ROAS neto no hay surf.

## Fuente

S1 10:00 y 10:27–11:30; S2 13:36, 14:10 y 14:40; T3 11:22 y 12:35; L2 21:25; C1 56:16.
