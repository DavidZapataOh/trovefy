# 05 · Página de Facebook

**Objetivo**
Crear la página «madre» de tu negocio, con la marca de tu primer producto, dentro de tu portfolio comercial.

**Antes de empezar**
- Paso 04 hecho (`verificado`, o `hecho` con «patrón sin confirmar»).
- El nombre de la marca del primer producto decidido (el de la página será ese, no tu nombre personal).
- Sin VPN mientras la creas.

**Pasos**
1. Abre el navegador de Trovify con el perfil de Meta:
   `trovify navegador abrir meta https://business.facebook.com/`
2. Crea la página desde tu portfolio (Cuentas → Páginas → Añadir → Crear una página nueva): nombre = la marca del primer producto, una categoría que encaje y una descripción breve y verdadera. Sin reseñas ni testimonios inventados.
3. Abre la página y copia su dirección (empieza por `https://www.facebook.com/`). Si Facebook la muestra con un ID numérico, vale igual.
4. Cierra la ventana del navegador y guarda la dirección en el paso:
   `trovify arranque hecho 05 --dato url=https://www.facebook.com/<tu-página>`

**Errores típicos**
- Síntoma: «no medido: falta la URL de la página». Arreglo: repite el paso 4 con tu dirección.
- Síntoma: «no medido: inicia sesión…». Arreglo: abre el navegador con el comando del paso 1 y entra con tu perfil.
- Síntoma: «la página no muestra un ID reconocible». Arreglo: comprueba que la dirección es la de tu página y que está publicada.

**Cómo se verifica**
Al verificar se abre una ventana del navegador de Trovify unos segundos; no la toques.
`trovify arranque verificar 05` abre la dirección guardada (solo de facebook.com) con el perfil de Meta, extrae el ID de la página y guarda la captura y el ID en `config/evidencia/05-…`. El ID queda en los datos del paso como `page_id`.
Mientras el patrón no esté confirmado con tu pantalla real, el resultado es «no medido: patrón sin confirmar con tu pantalla real» y la captura y los trozos de la página con el ID quedan en `config/evidencia/provisional/` (nunca la página entera); el paso no se verifica todavía.
Para confirmarlo, tras tu primera captura real: `trovify arranque confirmar 05` muestra lo que Trovify leyó de tu pantalla; si coincide con lo que ves y lo dices, Claude ejecuta `trovify arranque confirmar 05 --respuesta si` y vuelve a verificar. Si no coincide, hay que ajustar el patrón en el repo (no es tarea tuya).
