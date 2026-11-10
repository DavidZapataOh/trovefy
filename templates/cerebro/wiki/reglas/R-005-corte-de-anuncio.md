---
tipo: regla
id: R-005
titulo: Corte de anuncio
fecha: 2026-11-09
fuente: "Diseño §4.1 (Corte de anuncio) y §4.13 (Anuncio: APAGAR / ESPERAR); L2 19:55; S1 10:00; T3 14:12"
umbrales: [corte.anuncio.gasto_usd, corte.anuncio.cpc_max_usd, corte.anuncio.impresiones_min]
estado: vigente
---

# R-005 · Corte de anuncio

## Regla

Con un gasto de al menos `corte.anuncio.gasto_usd` (3) US$ en un anuncio **y** (0 pagos iniciados **o** CPC mayor que `corte.anuncio.cpc_max_usd` (0,6) US$), se propone apagar el anuncio o el conjunto. Nunca solo por el CTR. Mientras el anuncio no llegue a ese gasto **ni** a `corte.anuncio.impresiones_min` (1000) impresiones, el estado es ESPERAR (diseño §4.13), sin propuesta.

## Por qué

El corte de US$ 3 gana sobre los 2–3 US$ de las demás fuentes y sobre el CPC > 0,6 combinado con CPM flojo, y gana L2 + S1 (diseño §4.1, fila «Corte de anuncio»). «Nunca solo por el CTR» es parte de la regla del diseño §4.1; el motivo no consta en los vídeos.

## Cómo se aplica

`/leer` revisa cada anuncio con el gasto acumulado del día en curso (uno de los dos cortes que admite el día abierto) y lo propone al buzón; solo el ejecutor apaga, tras un Aceptar. El corte vale para todo anuncio, también dentro de una oferta con ventas (diseño §4.1 y §4.13, «Anuncio: APAGAR»); no sustituye el corte de oferta (R-006).

## Fuente

Diseño §4.1, fila «Corte de anuncio»; §4.13, filas «Anuncio: APAGAR» y «Anuncio: ESPERAR» (gasto < US$ 3 o < 1.000 impresiones). Gana L2 + S1.
