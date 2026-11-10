# 02 · Caza sin cuentas

**Objetivo**
Encontrar tu primera oferta ganadora mirando la Biblioteca de anuncios de Meta, sin necesitar ninguna cuenta tuya todavía.

**Antes de empezar**
- Pasos 00 y 01 verificados.
- La caza llega con el plan 07 (`/trovify:cazar --modo nicho`). Hasta entonces este paso no puede completarse; puedes avanzar con los pasos 03 a 08 mientras tanto.

**Pasos**
1. Cuando el plan 07 esté instalado, escribe `/trovify:cazar --modo nicho` y dile a Claude el nicho que te interesa.
2. Claude busca en la Biblioteca de anuncios y guarda fichas en `wiki/ofertas/`. Tú eliges con calma cuáles te interesan; Claude te propone opciones y una recomendada.
3. Cada ficha debe traer el enlace a la Biblioteca de anuncios por país, para que puedas ver tú mismo el anuncio.
4. Cuando haya al menos una ficha así, pide la verificación.

**Errores típicos**
- Síntoma: «ninguna ficha de wiki/ofertas/ tiene un enlace reproducible a la Biblioteca de anuncios». Arreglo: ejecuta `/trovify:cazar --modo nicho`; si esa orden todavía no existe, el paso espera al plan 07.
- Síntoma: hay fichas pero el paso sigue sin pasar. Arreglo: la ficha necesita un enlace que empiece por `https://www.facebook.com/ads/library/` en su campo `link_biblioteca`, dentro de `paises`.

**Cómo se verifica**
`trovify arranque verificar 02` busca en `wiki/ofertas/` una ficha cuyo `paises.<país>.link_biblioteca` sea un enlace a la Biblioteca de anuncios de Facebook. Con una basta; la ficha queda como evidencia.
