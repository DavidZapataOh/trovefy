# 08 · Verificar el dominio en Meta

**Objetivo**
Que Meta confirme que el dominio es tuyo, requisito para usarlo en anuncios y eventos.

**Antes de empezar**
- Paso 07 verificado y paso 04 hecho (`verificado`, o `hecho` con «patrón sin confirmar»).
- Si tienes varios portfolios, el `business_id` del tuyo guardado en el 04 (`trovefy arranque hecho 04 --dato business_id=<id>`): el 08 lo reutiliza.
- Sin VPN.

**Pasos**
1. Abre el navegador de Trovefy con el perfil de Meta (comando de Trovefy, no de sistema):
   `trovefy navegador abrir meta https://business.facebook.com/latest/settings/domains?business_id=<id>`
   (con el `business_id` de tu portfolio; si solo tienes uno, vale `https://business.facebook.com/settings/owned-domains`).
2. Inicia sesión tú si hace falta. Pulsa «Añadir» y escribe tu dominio (el del paso 07). Elige verificar con un **registro TXT de DNS**.
3. Meta te muestra un valor que empieza por `facebook-domain-verification=`. Cópialo.
4. En otra pestaña, entra en https://dash.cloudflare.com/ → tu dominio → «DNS» → «Registros» → «Agregar registro». Tipo `TXT`, nombre `@`, contenido el valor que copiaste. Guarda.
5. Espera unos minutos: el DNS tarda en propagarse (a veces horas). Puedes comprobar el TXT con `trovefy arranque verificar 08`.
6. Cuando el TXT aparezca, vuelve a Meta y pulsa «Verificar». Si Meta dice que no lo encuentra, espera y vuelve a pulsarlo.
7. Cuando el dominio figure como verificado, cierra el navegador y avisa a Claude.

**Errores típicos**
- Síntoma: «no hay un TXT de Meta en el dominio». Arreglo: revisa que el registro sea TXT, con nombre `@` y el contenido completo; si lo acabas de crear, espera y repite.
- Síntoma: «TXT de Meta encontrado; falta confirmar el estado en Business Settings». Arreglo: el TXT está, pero falta pulsar «Verificar» en Meta o confirmar con tu pantalla real; el paso aún no se da por verificado.
- Síntoma: «confirma cuando Meta muestre el dominio verificado» al confirmar. Arreglo: el patrón del 08 solo se confirma con tu dominio ya verificado en Meta; termina los pasos 5 y 6, vuelve a verificar y confirma entonces.
- Síntoma: «Meta no muestra el dominio como verificado». Arreglo: pulsa «Verificar» en Business Settings → Dominios y repite más tarde.
- Síntoma: «no medido: inicia sesión en el navegador de Trovefy». Arreglo: repite el paso 1 y entra con tu perfil.
- Síntoma: «no medido: tienes varios portfolios: guarda cuál usas con `trovefy arranque hecho 04 --dato business_id=<id>`». Arreglo: Meta abrió «Seleccionar negocio»; guarda el ID de tu portfolio (guía 04, paso 6) y vuelve a verificar.
- Síntoma: «no medido: Meta pide una verificación de seguridad en el navegador de Trovefy; hazla tú y vuelve a verificar» (Meta enseña «Verificación necesaria»). Arreglo: abre el navegador con el comando del paso 1, completa tú la verificación y vuelve a verificar.
- Síntoma: «no medido: falta el dominio». Arreglo: guarda el dominio con `trovefy arranque hecho 07 --dato dominio=<tu-dominio>`.

**Cómo se verifica**
`trovefy arranque verificar 08` primero busca por DNS sobre HTTPS un TXT que empiece por `facebook-domain-verification=`; si falta, falla sin abrir el navegador. Si está, abre una ventana del navegador de Trovefy unos segundos (no la toques) en `business.facebook.com/latest/settings/domains?business_id=<id>` (el ID del paso 04; sin él, `business.facebook.com/settings/owned-domains`) y busca tu dominio con estado verificado; guarda captura y datos en `config/evidencia/`.
Mientras ese patrón no esté confirmado con tu pantalla real, el resultado es «no medido» aunque el TXT esté, porque el TXT solo no es la verificación de Meta; la captura y el texto leído quedan en `config/evidencia/provisional/`.
Para confirmarlo, tras tu primera captura real: `trovefy arranque confirmar 08` muestra lo que Trovefy leyó de tu pantalla; si coincide con lo que ves y lo dices, Claude ejecuta `trovefy arranque confirmar 08 --respuesta si` y vuelve a verificar. Si no coincide, hay que ajustar el patrón en el repo (no es tarea tuya).
