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

T3 sube +30 %/h o ×2 y S sube +50 %/2 h; el diseño fija +30 % por paso, un paso cada 2 h como máximo, con tope de +50 % (diseño §4.1, fila «Ritmo del surf», gana HTML + fluxo). Un cambio de presupuesto de más del 20 % reinicia el aprendizaje de Meta (notas de investigación, auditoría de repos, field guide de YSY-99), por eso cada propuesta indica si reinicia el aprendizaje (diseño §3.4, regla 4). Sin pausar de noche y con vuelta a la base a las 23:00 locales (diseño §4.1, fila «Noche»); el motivo no consta en los vídeos.

## Cómo se aplica

`/escalar` propone cada paso al buzón con entidad, ID, de → a, motivo y si reinicia el aprendizaje. El día en curso sirve para el surf, pero nunca para escalar fuera de este ritmo.

## Fuente

Diseño §4.1, filas «Ritmo del surf» y «Noche». Gana HTML + fluxo.
