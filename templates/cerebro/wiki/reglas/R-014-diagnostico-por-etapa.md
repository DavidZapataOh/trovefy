---
tipo: regla
id: R-014
titulo: Diagnóstico por etapa
fecha: 2026-11-19
fuente: "S1 10:00 (diagnóstico de Santino); C1 20:05 («¿fue el anuncio, la oferta o la landing? Claude te lo diagnostica»); C1 54:20; L2 19:15; añadido (no cambia el método)"
umbrales: [diagnostico.ctr_min, diagnostico.llegada_min, diagnostico.conversion_pagina_min, diagnostico.pi_a_compra_min, diagnostico.pi_min, diagnostico.clics_min]
estado: vigente
---

# R-014 · Diagnóstico por etapa

## Regla

`/leer` mira dónde se cae el embudo con lo acumulado desde la activación. **Anuncio:** CTR por debajo de `diagnostico.ctr_min` (0,015) → aviso a `/creativos`. **Página:** menos de `diagnostico.llegada_min` (0,8) de los clics llegan a la página, o menos del 15 % de las visitas empiezan a pagar (con los pagos iniciados medidos) → aviso a `/landing`. **Checkout:** con al menos `diagnostico.pi_min` (16) pagos iniciados, menos de `diagnostico.pi_a_compra_min` (0,125) terminan en compra, o la pasarela rechaza intentos → aviso a `/checkout`. Con menos de `diagnostico.clics_min` (300) clics, cada hallazgo es solo una línea del parte («dato aún flojo») y no genera aviso. La referencia de la página es que convierta más de `diagnostico.conversion_pagina_min` (0,02).

## Por qué

Santino diagnostica así: «CTR > 1,5 %; llegan a la página > 80 % de los clics; la página convierte > 2 %» y «¿falla el anuncio? → gancho y CTR. ¿Falla la página? → visitas que empiezan a pagar. ¿Falla el checkout? → empiezan a pagar y no terminan» (S1 10:00). «46 pagos iniciados contra 6 ventas: 1 de cada 8» (L2 19:15). El 15 % de pagos iniciados sobre visitas sale de C1 54:20 (R-005).

## Cómo se aplica

Si falla la página o el checkout, `/leer` **avisa** con una alerta a `/landing` o `/checkout` y **no toca la campaña** (regla 9 del CLAUDE.md del cerebro): los hallazgos nunca generan una propuesta de pausa ni de presupuesto. Es un añadido que no cambia el método.

## Fuente

S1 10:00, C1 20:05, C1 54:20 y L2 19:15.
