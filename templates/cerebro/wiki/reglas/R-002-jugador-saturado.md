---
tipo: regla
id: R-002
titulo: Jugador saturado
fecha: 2026-11-09
fuente: "Santino; auditoría de caza §4.5 punto 8; diseño §4.1"
umbrales: [caza.saturado.activos_jugador]
estado: vigente
---

# R-002 · Jugador saturado

## Regla

A partir de `caza.saturado.activos_jugador` (150) anuncios activos de un mismo jugador se avisa de saturación: la oferta puede tener un competidor dominante y poco hueco.

## Por qué

Más de 150–200 anuncios activos de un mismo jugador lo hacen «saturado»: sirve como fuente, no como rival de frente (diseño §4.3). Criterio del diseño (sin fuente en los vídeos): el aviso no prohíbe la oferta; obliga a decidirlo con los ojos abiertos.

## Cómo se aplica

`/cazar` cuenta los anuncios activos por página y, al llegar al umbral, marca la oferta como «jugador saturado» en su ficha y en el veredicto. `/auditar` lo pondera en el hueco.

## Fuente

Diseño §4.1, fila «Vara de caza» (aviso a partir de 150 activos). Santino (S1) y auditoría de caza §4.5 punto 8.
