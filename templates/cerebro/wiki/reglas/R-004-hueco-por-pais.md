---
tipo: regla
id: R-004
titulo: Hueco por país y elección de país
fecha: 2026-11-09
fuente: "Diseño §4.1 (Mercado de arranque); R5 y R8; auditoría de caza §4.6; [D-13]"
umbrales: [hueco.sin_traducir_min_dias, hueco.competidor_c7_min, hueco.max_competencia_local, hueco.intentos_para_cero, auditar.peso.demanda, auditar.peso.hueco, auditar.peso.precio, auditar.peso.cpm, auditar.peso.cultural]
estado: vigente
---

# R-004 · Hueco por país y elección de país

## Regla

El país de arranque es un mercado con hueco de idioma, elegido por `/auditar`. Hay hueco cuando la pauta lleva sin traducir `hueco.sin_traducir_min_dias` (30) días o más, hay al menos `hueco.competidor_c7_min` (3) competidores con C7 y la competencia local en el idioma es de `hueco.max_competencia_local` (0); se busca con `hueco.intentos_para_cero` (2) intentos antes de dar un cero por bueno. La puntuación de `/auditar` pesa demanda (`auditar.peso.demanda` (35)), hueco (`auditar.peso.hueco` (30)), precio (`auditar.peso.precio` (15)), CPM (`auditar.peso.cpm` (10)) y cultural (`auditar.peso.cultural` (10)).

## Por qué

Europa (Tomi) y el país propio (Santino) se contradicen. Lo que une a ambos es el hueco: un país donde nadie vende la oferta en el idioma local. Colombia o la LatAm hispana solo entran si la oferta lo pide.

## Cómo se aplica

`/auditar` busca competencia local por país, repite la búsqueda antes de aceptar un cero y puntúa con los pesos de `umbrales.yaml`. La elección de país queda en `AUDITORIA.md`.

## Fuente

Diseño §4.1, fila «Mercado de arranque» (gana el HTML). R5, R8 y auditoría de caza §4.6; pesos de auditoría [D-13].
