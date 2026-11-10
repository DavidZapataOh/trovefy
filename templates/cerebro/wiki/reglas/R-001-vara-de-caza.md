---
tipo: regla
id: R-001
titulo: Vara de caza
fecha: 2026-11-09
fuente: "Diseño §4.1 (Vara de caza); C1 10:55; T3 25:25; auditoría de caza §4.2"
umbrales: [caza.perfil.tomi.c8_min, caza.perfil.santino.c7_min, caza.perfil.europa_caro.c8_min]
estado: vigente
---

# R-001 · Vara de caza

## Regla

Una oferta pasa la vara si su cohorte C8 es de al menos `caza.perfil.tomi.c8_min` (15) anuncios de la **misma oferta** en el país del enlace. Los perfiles `santino` (`caza.perfil.santino.c7_min` (30) en C7) y `europa-caro` (`caza.perfil.europa_caro.c8_min` (20) en C8) son opciones explícitas. Una excepción (R11) se registra por escrito en `decisiones/`.

## Por qué

Los vídeos dan varas distintas: 15+ en 8 días (Tomi), 30–50+ en 7 días (Santino), 50+ en 3 días (skill) y 9 en 14 como excepción. Con US$ 500 manda la de Tomi, respaldada por la auditoría de caza: es la que mejor separa una oferta que sostiene el gasto de un pico aislado.

## Cómo se aplica

`/cazar` calcula la cohorte C8 por oferta y país del enlace y compara con el perfil activo. Con menos, la oferta no pasa a `/auditar`. Las tres señales se exigen siempre; con menos, la excepción queda en `decisiones/`.

## Fuente

Diseño §4.1, fila «Vara de caza» y fila «Tres señales». Ganan Tomi y la auditoría de caza §4.2.
