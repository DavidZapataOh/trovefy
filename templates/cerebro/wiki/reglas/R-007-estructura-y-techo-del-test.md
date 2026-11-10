---
tipo: regla
id: R-007
titulo: Estructura y techo del test
fecha: 2026-11-09
fuente: "Diseño §4.1 (Estructura y Techo del test); Usuario (PU-01); [D-08] y [D-09]; C1 18:10"
umbrales: [test.presupuesto_conjunto_usd, test.conjuntos, test.spend_cap_usd, test.spend_cap_prorroga_usd, cuenta.limite_gasto_inicial_usd]
estado: vigente
---

# R-007 · Estructura y techo del test

## Regla

El test es ABO: `test.conjuntos` (5) conjuntos × 1 anuncio × `test.presupuesto_conjunto_usd` (5) US$/día, es decir, US$ 25/día por producto-país, con 5 anuncios de reserva para renovaciones. El techo es `test.spend_cap_usd` (30) US$ por producto-país aplicados como `spend_cap` de la campaña, con una única prórroga hasta `test.spend_cap_prorroga_usd` (55) US$ solo si hay ventas. La cuenta publicitaria arranca con un límite de gasto de `cuenta.limite_gasto_inicial_usd` (250) US$.

## Por qué

Los vídeos dan ABO 5×6, CBO 1-1-10×30, ABO 4–5×5 y ABO 5.5; con US$ 500 gana ABO 4–5×5 de Candy y Franco, por capital (diseño §4.1, fila «Estructura del test»). La CBO 1-1-10 no se usa en el mes 1 por el capital [D-08]. El `spend_cap` de 30 son los 25 del corte sin ventas más un margen para el sobregasto de Meta (diseño §4.14).

## Cómo se aplica

`/montar` propone la campaña con esa estructura y el `spend_cap`; `/caja` reserva el sobre de tests y calcula los huecos de test (unos 9–10 con US$ 280). La prórroga se pide una sola vez y solo con ventas.

## Fuente

Diseño §4.1, filas «Estructura del test» y «Techo del test». Usuario (PU-01), [D-08], [D-09] y diseño §4.2 paso 06 y §4.17 para el límite de la cuenta.
