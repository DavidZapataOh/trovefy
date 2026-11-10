---
tipo: regla
id: R-010
titulo: Ritmo del surf
fecha: 2026-11-09
fuente: "Diseño §4.1 (Ritmo del surf y Noche); T3; playbook HTML; fluxo (idea)"
umbrales: [surf.paso_pct, surf.paso_max_pct, surf.cadencia_min_h]
estado: vigente
---

# R-010 · Ritmo del surf

## Regla

El surf sube el presupuesto un `surf.paso_pct` (0,3) por paso (fracción), un paso cada `surf.cadencia_min_h` (2) horas como mínimo, solo con ventas nuevas y ROAS acumulado de al menos `roas.escalar` (2,0). Tope duro por paso: `surf.paso_max_pct` (0,5). Sin pausar de noche: a las 23:00 locales lo surfeado vuelve a la base.

## Por qué

T3 sube +30 %/h o ×2 y S sube +50 %/2 h. Un paso de 30 % cada 2 h limita el sobregasto de Meta y respeta el reinicio del aprendizaje. Pausar de noche rompe el aprendizaje; devolver a la base a las 23:00 limita el gasto sin pausar.

## Cómo se aplica

`/escalar` propone cada paso al buzón con entidad, ID, de → a, motivo y si reinicia el aprendizaje. El día en curso sirve para el surf, pero nunca para escalar fuera de este ritmo.

## Fuente

Diseño §4.1, filas «Ritmo del surf» y «Noche». Gana HTML + fluxo.
