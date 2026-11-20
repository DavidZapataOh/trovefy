---
tipo: regla
id: R-009
titulo: Pre-escala
fecha: 2026-11-09
fuente: "Diseño §4.1 (Cuándo escalar); [D-09]"
umbrales: [preescala.min_ventas]
estado: vigente
---

# R-009 · Pre-escala

## Regla

La pre-escala se propone con al menos `preescala.min_ventas` (5) ventas y un ROAS neto acumulado de al menos `roas.escalar` (2,0), dentro del techo del test de `test.spend_cap_usd` (100) US$ (C1 0:18:10; sin prórroga).

## Por qué

Santino exige 10 ventas, pero con un test corto y un AOV de US$ 15–20 salen unos 5–7 pedidos: con 10 no se llegaría nunca. Criterio del diseño (sin fuente en los vídeos): con 5 ventas hay señal suficiente y el techo sigue protegiendo el capital.

## Cómo se aplica

`/escalar` comprueba ventas y ROAS neto acumulado con días cerrados antes de proponer el paso a la escalera ABO → CBO → Cost Cap → Bid Cap. El order bump se añade con 10 ventas acumuladas, no antes (diseño §4.1, fila «Order bump en el test 1»; todavía no tiene clave en `umbrales.yaml`).

## Fuente

Diseño §4.1, fila «Cuándo escalar» (HTML adaptado, [D-09]).
