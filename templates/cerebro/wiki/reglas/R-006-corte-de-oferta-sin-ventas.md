---
tipo: regla
id: R-006
titulo: Corte de oferta sin ventas (PU-01)
fecha: 2026-11-09
fuente: "Usuario (PU-01, 2026-11-09); diseño §0 punto 6, §4.1 y §8.0; C1 1:24:15"
umbrales: [corte.oferta.sin_ventas_usd, corte.oferta.factor_cpa_be]
estado: vigente
---

# R-006 · Corte de oferta sin ventas (PU-01)

## Regla

El usuario lo dijo así: «matar el producto a los ~US$ 25 sin ventas». Una oferta con 0 ventas muere al llegar a min(`corte.oferta.sin_ventas_usd` (25) US$, `corte.oferta.factor_cpa_be` (2) × CPA_BE), **sin esperar ningún plazo** y haga el tiempo que haga desde la activación. Manda el gasto (`precedencia_corte: gasto`). Con ventas, al llegar al techo prorrogado, un ROAS neto acumulado inferior a `roas.apagar` (1,4) también corta.

## Por qué

Había un conflicto entre tres reglas: la guarda de 72 h, el corte sin ventas hacia los US$ 25 y un techo de US$ 50. El usuario lo resolvió a favor del gasto. Con US$ 500 en total, cada test sin ventas debe costar lo menos posible. El factor sustituye al 3× CPA_BE del HTML.

## Cómo se aplica

`/leer` compara el gasto acumulado de la oferta con el corte y, si no hay ventas, propone apagarla al buzón. Es el segundo corte por gasto acumulado que admite el día en curso. Las 72 h (R-011) no protegen a una oferta sin ventas. Esta regla no se reabre sin una nueva decisión explícita del usuario.

## Fuente

Usuario (PU-01, 2026-11-09), diseño §0 punto 6 y §8.0. Fila «Corte de oferta» de §4.1 y C1 1:24:15.
