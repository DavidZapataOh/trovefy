# 09 · Impultienda

**Objetivo**
Tener tu cuenta de Impultienda en el plan **Free** con una tienda en el idioma del primer mercado, para vender con su checkout, bump y upsell.

**Antes de empezar**
- Paso 07 verificado y paso 08 hecho (`verificado`, o `hecho` con «patrón sin confirmar» / «falta confirmar el estado en Business Settings») (dominio listo).
- El plan **Free** es gratis y sin tarjeta: 1 tienda, 1 bono y 1 upsell, comisión de Impultienda del 5 % (https://impultienda.ar/, leída el 2026-11-10). Con eso basta para empezar.
- La prueba de 45 días de Starter, Pro o Max (pide tarjeta; no cobra hasta que termina) **solo se usa si hace falta una segunda tienda** u otro límite que el Free no cubra. No la actives por costumbre.
- Qué idioma tendrá la tienda: el del primer mercado que elegiste con `/trovefy:auditar`.

**Pasos**
1. Entra en https://impultienda.ar/register?plan=free y crea tu cuenta con tu correo (contraseña y verificación los haces tú; Claude no las ve).
2. Crea **una** tienda para el idioma del primer mercado.
3. Abre el navegador de Trovefy con el perfil de Impultienda e inicia sesión tú mismo:
   `trovefy navegador abrir impultienda https://app.impultienda.ar/`
4. Anota lo que averigües y no esté en esta guía (dominio propio en la tienda, HTML propio en la landing, precio por país, campo del Pixel/CAPI, UTMify, exportación de pedidos): en la página pública no está documentado.
5. Cuando la tienda exista, márcalo:
   `trovefy arranque hecho 09`

**Errores típicos**
- Síntoma: «no medido: patrón sin confirmar con tu pantalla real». Arreglo: es lo esperado hasta que se capture tu pantalla real por primera vez; el paso no se verifica todavía.
- Síntoma: «no medido: mapa desactualizado (…)». Arreglo: Impultienda cambió esa pantalla; avisa para actualizar el mapa. No hace falta que hagas nada en tu cuenta.
- Síntoma: «inicia sesión en el navegador de Trovefy». Arreglo: ejecuta el comando del paso 3 y entra con tu cuenta.
- Síntoma: «Impultienda no tiene ninguna tienda». Arreglo: crea la tienda del paso 2.

**Cómo se verifica**
Al verificar se abre una ventana del navegador de Trovefy unos segundos; no la toques.
`trovefy arranque verificar 09` lee solo (sin hacer clics) las pantallas de plan, tiendas y pasarelas con el perfil de Impultienda, según el mapa `templates/impultienda/mapa.yaml`. Es ✓ si el plan está activo y hay al menos una tienda, y guarda el plan, el número de tiendas y las pasarelas conectadas (el paso 10 las usa).
Mientras el mapa no esté confirmado con tu pantalla real (`capturado: null`), el resultado es «no medido» y las capturas y el texto de las tres pantallas quedan en `config/evidencia/provisional/`.
Para confirmarlo, tras tu primera captura real: `trovefy arranque confirmar 09` muestra lo que Trovefy leyó de tu pantalla; si coincide con lo que ves y lo dices, Claude ejecuta `trovefy arranque confirmar 09 --respuesta si` y vuelve a verificar. Si no coincide, hay que ajustar el patrón en el repo (no es tarea tuya).
