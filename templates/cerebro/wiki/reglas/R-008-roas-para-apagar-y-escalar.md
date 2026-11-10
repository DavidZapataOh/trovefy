---
tipo: regla
id: R-008
titulo: ROAS para apagar y escalar
fecha: 2026-11-09
fuente: "Diseño §4.1 (ROAS para apagar y escalar); C1 34:25; T3 10:05 y 14:30"
umbrales: [roas.apagar, roas.escalar]
estado: vigente
---

# R-008 · ROAS para apagar y escalar

## Regla

Hay dos umbrales distintos, ambos sobre ROAS **neto**: se propone apagar si el ROAS está por debajo de `roas.apagar` (1,4), se mantiene entre `roas.apagar` (1,4) y `roas.escalar` (2,0) y se propone escalar si es de al menos `roas.escalar` (2,0). Ninguna lectura vale con menos datos de los que exige la regla.

## Por qué

T3 apaga por debajo de 2 y el CLAUDE.md del vídeo por debajo de 1,4. Dos umbrales dejan una franja de espera en la que ni se mata una oferta recuperable ni se escala una que aún no rinde.

## Cómo se aplica

`/leer` calcula el ROAS neto con el ledger (comisiones, impuestos y reembolsos descontados) y días cerrados, y propone al buzón. Un CPA aislado no pausa (regla dura 9). El día en curso nunca sirve para escalar.

## Fuente

Diseño §4.1, fila «ROAS para apagar y escalar». Gana HTML + C1.
