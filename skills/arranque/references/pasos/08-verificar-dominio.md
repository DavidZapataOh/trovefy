# 08 · Verificar el dominio en Meta

**Objetivo**
Que Meta confirme que el dominio es tuyo, requisito para usarlo en anuncios y eventos.

**Antes de empezar**
- Pasos 04 y 07 verificados.
- Sin VPN.

**Pasos**
1. Abre el navegador de Trovify con el perfil de Meta (comando de Trovify, no de sistema):
   `trovify navegador abrir meta https://business.facebook.com/settings/owned-domains`
2. Inicia sesión tú si hace falta. Pulsa «Añadir» y escribe tu dominio (el del paso 07). Elige verificar con un **registro TXT de DNS**.
3. Meta te muestra un valor que empieza por `facebook-domain-verification=`. Cópialo.
4. En otra pestaña, entra en https://dash.cloudflare.com/ → tu dominio → «DNS» → «Registros» → «Agregar registro». Tipo `TXT`, nombre `@`, contenido el valor que copiaste. Guarda.
5. Espera unos minutos: el DNS tarda en propagarse (a veces horas). Puedes comprobar el TXT con `trovify arranque verificar 08`.
6. Cuando el TXT aparezca, vuelve a Meta y pulsa «Verificar». Si Meta dice que no lo encuentra, espera y vuelve a pulsarlo.
7. Cuando el dominio figure como verificado, cierra el navegador y avisa a Claude.

**Errores típicos**
- Síntoma: «no hay un TXT de Meta en el dominio». Arreglo: revisa que el registro sea TXT, con nombre `@` y el contenido completo; si lo acabas de crear, espera y repite.
- Síntoma: «TXT de Meta encontrado; falta confirmar el estado en Business Settings». Arreglo: el TXT está, pero falta pulsar «Verificar» en Meta o confirmar con tu pantalla real; el paso aún no se da por verificado.
- Síntoma: «Meta no muestra el dominio como verificado». Arreglo: pulsa «Verificar» en Business Settings → Dominios y repite más tarde.
- Síntoma: «no medido: inicia sesión en el navegador de Trovify». Arreglo: repite el paso 1 y entra con tu perfil.
- Síntoma: «no medido: falta el dominio». Arreglo: guarda el dominio con `trovify arranque hecho 07 --dato dominio=<tu-dominio>`.

**Cómo se verifica**
`trovify arranque verificar 08` primero busca por DNS sobre HTTPS un TXT que empiece por `facebook-domain-verification=`; si falta, falla sin abrir el navegador. Si está, abre una ventana del navegador de Trovify unos segundos (no la toques) en `business.facebook.com/settings/owned-domains` y busca tu dominio con estado verificado; guarda captura y datos en `config/evidencia/`.
Mientras ese patrón no esté confirmado con tu pantalla real, el resultado es «no medido» aunque el TXT esté, porque el TXT solo no es la verificación de Meta; la captura queda en `config/evidencia/provisional/`.
