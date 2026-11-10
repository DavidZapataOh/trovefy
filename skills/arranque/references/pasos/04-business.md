# 04 · Portfolio comercial (Business Manager)

**Objetivo**
Crear tu portfolio comercial de Meta, el contenedor de tus páginas y cuentas publicitarias, y dejar su ID guardado.

**Antes de empezar**
- Paso 03 verificado.
- Ese día, **sin VPN** y desde tu conexión habitual.
- Un correo tuyo, real y que sepas leer (Meta te manda un mensaje de confirmación).

**Pasos**
1. Abre el navegador de Trovify con el perfil de Meta (comando de Trovify, no de sistema):
   `trovify navegador abrir meta https://business.facebook.com/`
2. Inicia sesión tú con tu perfil del paso 03. Contraseña y 2FA los escribes tú; Claude espera.
3. Crea el portfolio comercial: nombre real (tu nombre o el de tu negocio, tal como figura en tus documentos), tu nombre y apellidos reales y tu correo propio. Confirma el correo cuando llegue.
4. Cuando veas los ajustes del portfolio, cierra la ventana del navegador y avisa a Claude.
5. Marca el paso: `trovify arranque hecho 04`.

**Errores típicos**
- Síntoma: «no medido: inicia sesión en el navegador de Trovify». Arreglo: repite el paso 1 y entra con tu perfil; la sesión se guarda en el perfil de Trovify.
- Síntoma: «ya hay un navegador de Trovify abierto». Arreglo: cierra la ventana de Trovify que sigue abierta.
- Síntoma: «la página de ajustes de Business no muestra un portfolio con ID». Arreglo: aún no creaste el portfolio, o tu sesión entró en otro; ábrelo con el comando del paso 1 y créalo.
- Síntoma: Meta te pide verificar identidad. Arreglo: hazlo tú con tus documentos reales; Claude no los ve.

**Cómo se verifica**
Al verificar se abre una ventana del navegador de Trovify unos segundos; no la toques.
`trovify arranque verificar 04` abre `https://business.facebook.com/settings/` con el perfil de Meta, lee el `business_id=` de la URL final y guarda una captura (`config/evidencia/04-captura-<fecha>.png`) y el ID. Si la sesión ha caducado dice «no medido» en vez de fallar.
Mientras el patrón no esté confirmado con tu pantalla real, el resultado es «no medido: patrón sin confirmar con tu pantalla real» y la captura queda en `config/evidencia/provisional/`; el paso no se verifica todavía.
