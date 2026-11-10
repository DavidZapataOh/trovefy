---
tipo: regla
id: R-011
titulo: Paciencia de 72 h
fecha: 2026-11-09
fuente: "Diseño §4.1 (Paciencia); T3; Usuario (PU-01)"
umbrales: [paciencia.con_ventas_h]
estado: vigente
---

# R-011 · Paciencia de 72 h

## Regla

Antes de `paciencia.con_ventas_h` (72) horas no se proponen cortes por CPA ni por ROAS, y esto **solo** protege a las ofertas **con ventas** pero con CPA alto. Las ofertas sin ventas mueren por gasto (R-006); el filtro de US$ 3 vale para anuncios sueltos (R-005).

## Por qué

T3 pide paciencia y otra regla decidía a los US$ 2. El usuario resolvió que manda el gasto: la paciencia protege lo que ya vende, no lo que gasta sin vender.

## Cómo se aplica

`/leer` comprueba cuántas horas lleva activa la oferta y si tiene ventas antes de proponer un corte por CPA o ROAS. Sin ventas, aplica R-006 sin esperar.

## Fuente

Diseño §4.1, fila «Paciencia». Usuario (PU-01) y HTML.
