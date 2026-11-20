---
tipo: regla
id: R-007
titulo: Estructura y techo del test
fecha: 2026-11-19
fuente: "C1 0:18:10 («5 conjuntos · 1 anuncio c/u · $5 por anuncio · Techo $100 · Plazo 1 semana»); Diseño §4.1; [D-08]; corrección del 2026-11-19 («los vídeos son la ley»)"
umbrales: [test.presupuesto_conjunto_usd, test.conjuntos, test.spend_cap_usd, cuenta.limite_gasto_inicial_usd]
estado: vigente
---

# R-007 · Estructura y techo del test

## Regla

El test es ABO: `test.conjuntos` (5) conjuntos × 1 anuncio × `test.presupuesto_conjunto_usd` (5) US$/día, es decir, US$ 25/día por producto-país, con 5 anuncios de reserva para las renovaciones cada 48 h. El techo es `test.spend_cap_usd` (100) US$ por producto-país, aplicado como `spend_cap` de la campaña (en la moneda de la cuenta, a la baja con la TRM del día), y el plazo es de 1 semana. No hay prórroga. La cuenta publicitaria arranca con un límite de gasto de `cuenta.limite_gasto_inicial_usd` (250) US$.

## Por qué

Es lo que hacen los vídeos: «5 conjuntos · 1 anuncio c/u · $5 por anuncio · Techo $100 · Plazo 1 semana» (C1 0:18:10). El techo de US$ 30 con prórroga a US$ 55 no estaba en los vídeos y se quitó el 2026-11-19. El corte de la oferta sin ventas (R-006) sigue cortando antes, a unos US$ 25.

## Cómo se aplica

`/montar` crea la campaña con esa estructura y el `spend_cap` (si Meta exigiera un mínimo mayor, el mismo techo va como límite de la cuenta: desvío D1 del plan 22). Los límites del ejecutor no recortan el techo en silencio: se suben con una propuesta `limite_ejecutor`. `/caja` cuenta los huecos de test con el techo de US$ 100.

## Fuente

C1 0:18:10. Diseño §4.1 y [D-08] para la estructura; diseño §4.2 paso 06 y §4.17 para el límite de la cuenta.
