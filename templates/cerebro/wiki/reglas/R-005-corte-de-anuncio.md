---
tipo: regla
id: R-005
titulo: Corte de anuncio
fecha: 2026-11-19
fuente: "C1 20:05 («APAGAR: US$ 3 gastados y ningún pago iniciado. O CPC mayor a US$ 0,60»); C1 54:20 (AD2: «1 pago iniciado de 13. Muy debajo del 15 %» → OFF); L2 19:55; T3 14:12; diseño §4.13 (Anuncio: APAGAR / ESPERAR); corrección del 2026-11-19 («los vídeos son la ley»)"
umbrales: [corte.anuncio.gasto_usd, corte.anuncio.cpc_max_usd, corte.anuncio.pi_visitas_min]
estado: vigente
---

# R-005 · Corte de anuncio

## Regla

Con un gasto de al menos `corte.anuncio.gasto_usd` (3) US$ en un anuncio **y** (0 pagos iniciados **o** CPC mayor que `corte.anuncio.cpc_max_usd` (0,6) US$ **o** menos de `corte.anuncio.pi_visitas_min` (0,15) pagos iniciados por visita), se propone pausar su conjunto. Nunca solo por el CTR. Si el gasto es menor que `corte.anuncio.gasto_usd` (3) US$, el estado es ESPERAR, sin propuesta: «todavía no gastó lo suficiente para juzgarlo» (C1 20:05). Un anuncio que vendió es MANTENER: «vendió. Anda. No lo toques» (C1 20:05, C1 54:20).

## Por qué

Es lo que hacen los vídeos: «APAGAR: US$ 3 gastados y ningún pago iniciado. O CPC mayor a US$ 0,60» (C1 20:05); «AD3 zafa porque sí tiene pagos iniciados» (L2 19:55); en la tabla real de C1 54:20, el AD2 con 1 pago iniciado de 13 visitas («muy debajo del 15 %») sale OFF. El corte de US$ 3 gana sobre los US$ 2 de T3 14:12. La guarda de 1.000 impresiones del diseño no está en los vídeos y se quitó el 2026-11-19.

## Cómo se aplica

`/leer` revisa cada conjunto con su gasto acumulado desde la activación, también en la ronda intradía (el gasto es acumulado), y deposita una propuesta de pausa; solo el ejecutor pausa, tras tu Aceptar en Telegram. Se pausa el conjunto (en ABO con 1 anuncio por conjunto da lo mismo, C1 54:20). Mientras el píxel no haya confirmado InitiateCheckout, las ramas de pagos iniciados no se aplican solas y el anuncio se juzga por el CPC (desvío D1 del plan 23). Vale para todo anuncio, también dentro de una oferta con ventas; no sustituye el corte de oferta (R-006).

## Fuente

C1 20:05, C1 54:20, L2 19:55 y T3 14:12; diseño §4.13, filas «Anuncio: APAGAR» y «Anuncio: ESPERAR».
