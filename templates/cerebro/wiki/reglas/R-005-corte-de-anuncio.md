---
tipo: regla
id: R-005
titulo: Corte de anuncio
fecha: 2026-11-09
fuente: "Diseño §4.1 (Corte de anuncio); L2 19:55; S1 10:00; T3 14:12"
umbrales: [corte.anuncio.gasto_usd, corte.anuncio.cpc_max_usd]
estado: vigente
---

# R-005 · Corte de anuncio

## Regla

Con un gasto de al menos `corte.anuncio.gasto_usd` (3) US$ en un anuncio **y** (0 pagos iniciados **o** CPC mayor que `corte.anuncio.cpc_max_usd` (0,6) US$), se propone apagar el anuncio o el conjunto. Nunca solo por el CTR.

## Por qué

Con US$ 3 ya hay datos para saber si un anuncio lleva a pagos iniciados, y esperar más solo quema capital. Gana sobre los 2 US$ de T3 por tener más señal. El CTR solo engaña: un clic barato que no llega al pago no vale nada.

## Cómo se aplica

`/leer` revisa cada anuncio con el gasto acumulado del día en curso (uno de los dos cortes que admite el día abierto) y lo propone al buzón; solo el ejecutor apaga, tras un Aceptar. No aplica a ofertas con ventas ni sustituye el corte de oferta (R-006).

## Fuente

Diseño §4.1, fila «Corte de anuncio». Gana L2 + S1.
