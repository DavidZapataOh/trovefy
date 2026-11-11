---
tipo: regla
id: R-003
titulo: Nota y decisión de caza
fecha: 2026-11-09
fuente: "Auditoría de caza §4.4–§4.6; diseño §4.3; verificación de la Biblioteca 2026-11-09"
umbrales: [caza.nota.a_min, caza.nota.b_min, caza.supervivencia.min, caza.vida_mediana.min_dias, caza.crecimiento.acelerando, caza.crecimiento.cayendo, caza.filtro.fisico_min_senales, caza.filtro.tienda_min_senales, caza.peso.c8, caza.peso.longevidad, caza.peso.crecimiento, caza.peso.expansion, caza.peso.duplicacion, caza.peso.alcance_ue, caza.peso.supervivencia, caza.tope.c8, caza.tope.edad_dias, caza.tope.semanas, caza.tope.expansion, caza.tope.duplicacion, caza.tope.supervivencia, caza.mult.supervivencia_baja, caza.mult.cayendo, caza.mult.vida_corta]
estado: vigente
---

# R-003 · Nota y decisión de caza

## Regla

Cada oferta cazada recibe una nota de 0 a 100 con pesos y topes de `umbrales.yaml` (`caza.peso.c8` (25) para C8, `caza.peso.longevidad` (20) longevidad, `caza.peso.crecimiento` (15) crecimiento, `caza.peso.expansion` (15) expansión, `caza.peso.duplicacion` (10) duplicación, `caza.peso.alcance_ue` (10) alcance UE, `caza.peso.supervivencia` (5) supervivencia), con topes (`caza.tope.c8` (50), `caza.tope.edad_dias` (90), `caza.tope.semanas` (6), `caza.tope.expansion` (8), `caza.tope.duplicacion` (20), `caza.tope.supervivencia` (1)) y multiplicadores (`caza.mult.supervivencia_baja` (0,7), `caza.mult.cayendo` (0,5), `caza.mult.vida_corta` (0,7)). La decisión es A con nota de al menos `caza.nota.a_min` (70), B con al menos `caza.nota.b_min` (50) y descarte por debajo. Crecimiento: acelerando por encima de `caza.crecimiento.acelerando` (0,3) y cayendo por debajo de `caza.crecimiento.cayendo` (-0,3). Supervivencia mínima `caza.supervivencia.min` (0,3) y vida mediana mínima `caza.vida_mediana.min_dias` (14) días. El filtro de tipo exige `caza.filtro.fisico_min_senales` (2) señales para físico y `caza.filtro.tienda_min_senales` (3) para tienda.

## Por qué

Una nota con pesos fijos y fechados permite comparar cazas entre días y ver qué cambió. La verificación del 9-nov mostró que los originales duran meses y las copias unos días (mediana de 6 días), de ahí la vida mediana mínima y el multiplicador de vida corta.

## Cómo se aplica

`/cazar` calcula la nota con los pesos de `umbrales.yaml`, nunca con números en el código, y escribe la decisión (A, B o descarte) en el veredicto. Un dato ausente se anota «no medido: motivo», no se rellena con 0.

## Fuente

Auditoría de caza §4.4–§4.6 y diseño §4.3. Verificación de la Biblioteca 2026-11-09.
