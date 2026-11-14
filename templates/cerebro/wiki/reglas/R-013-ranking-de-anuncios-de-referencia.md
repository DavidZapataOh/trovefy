---
tipo: regla
id: R-013
titulo: Ranking de anuncios de referencia
fecha: 2026-11-13
fuente: "Diseño §4.4; cuongbigdigi rank.js:23-30; contrato 4"
umbrales: [referencia.ranking.min_dias, referencia.ranking.max_variantes, referencia.ranking.peso_variantes, referencia.en_test.min_variantes, referencia.top, referencia.medios.retencion_dias]
estado: vigente
---

# R-013 · Ranking de anuncios de referencia

## Regla

Un anuncio de referencia entra en el ranking tras `referencia.ranking.min_dias` (7) días activo; las variantes cuentan hasta `referencia.ranking.max_variantes` (30), con peso `referencia.ranking.peso_variantes` (2). Con al menos `referencia.en_test.min_variantes` (3) variantes se considera en test. El informe muestra los `referencia.top` (10) primeros y los vídeos y lotes del MCP se borran a los `referencia.medios.retencion_dias` (30) días.

## Por qué

Un anuncio que sigue activo tras una semana y que su dueño sigue variando es la señal más barata de que vende. El material ajeno no es nuestro: se analiza y caduca, no se archiva.

## Cómo se aplica

`/ver-anuncios` lee estos umbrales de `config/umbrales.yaml`, ordena, enseña el top y limpia ~/.cache/trovefy/referencia/ pasada la retención. Nada ajeno se guarda en el cerebro.

## Fuente

Diseño §4.4; cuongbigdigi rank.js:23-30; contrato 4.
