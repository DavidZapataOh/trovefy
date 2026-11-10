---
tipo: regla
id: R-012
titulo: Caza de pocos en pocos
fecha: 2026-11-09
fuente: "Diseño §4.3; R14; T1 49:58; auditoría de caza §4.2, §4.8 y §4.9"
umbrales: [caza.max_nuevas_por_ejecucion, caza.max_busquedas_sesion, caza.pausa_min_s, caza.pausa_max_s, caza.max_destinos_por_ejecucion, caza.palabra.min_resultados, caza.poda.strikes]
estado: vigente
---

# R-012 · Caza de pocos en pocos

## Regla

Cada ejecución de `/cazar` añade como máximo `caza.max_nuevas_por_ejecucion` (3) ofertas nuevas, hasta `caza.max_destinos_por_ejecucion` (10) destinos y `caza.max_busquedas_sesion` (30) búsquedas por sesión, con una pausa de `caza.pausa_min_s` (2) a `caza.pausa_max_s` (5) segundos entre ellas. Una palabra clave necesita al menos `caza.palabra.min_resultados` (20) resultados y se poda tras `caza.poda.strikes` (3) fallos.

## Por qué

T1 caza «de a tres», no «370 de golpe». La Biblioteca devuelve 429 hacia las 35 búsquedas, y la cuota de Claude y la atención del usuario también son finitas. Pocos candidatos bien auditados valen más que un volcado.

## Cómo se aplica

`/cazar` respeta los topes y las pausas de `umbrales.yaml`, anota lo que no entró en `wiki/caza/exclusiones.md` y deja el resto para la siguiente ejecución.

## Fuente

Diseño §4.3, R14 y T1 49:58; auditoría de caza §4.2, §4.8 y §4.9.
