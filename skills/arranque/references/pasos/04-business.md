# 04 · Portfolio comercial (Business Manager)

**Objetivo**
Crear tu portfolio comercial de Meta, el contenedor de tus páginas y cuentas publicitarias, y dejar su ID guardado.

**Antes de empezar**
- Paso 03 verificado.
- Ese día, **sin VPN** y desde tu conexión habitual.
- Un correo tuyo, real y que sepas leer (Meta te manda un mensaje de confirmación).

**Pasos**
1. Abre el navegador de Trovefy con el perfil de Meta (comando de Trovefy, no de sistema):
   `trovefy navegador abrir meta https://business.facebook.com/`
2. Inicia sesión tú con tu perfil del paso 03. Contraseña y 2FA los escribes tú; Claude espera.
3. Crea el portfolio comercial: nombre real (tu nombre o el de tu negocio, tal como figura en tus documentos), tu nombre y apellidos reales y tu correo propio. Confirma el correo cuando llegue.
4. Cuando veas los ajustes del portfolio, cierra la ventana del navegador y avisa a Claude.
5. Marca el paso: `trovefy arranque hecho 04`.
6. Si tienes **varios portfolios** (Meta te enseña «Seleccionar negocio»), elige el que vas a usar, copia el número que sale tras `business_id=` en la dirección y guárdalo:
   `trovefy arranque hecho 04 --dato business_id=<id>`
   Los pasos 04 y 08 abren ese portfolio directamente.

**Errores típicos**
- Síntoma: «no medido: inicia sesión en el navegador de Trovefy». Arreglo: repite el paso 1 y entra con tu perfil; la sesión se guarda en el perfil de Trovefy.
- Síntoma: «ya hay un navegador de Trovefy abierto». Arreglo: cierra la ventana de Trovefy que sigue abierta.
- Síntoma: «la página de ajustes de Business no muestra un portfolio con ID». Arreglo: aún no creaste el portfolio, o tu sesión entró en otro; ábrelo con el comando del paso 1 y créalo.
- Síntoma: «no medido: tienes varios portfolios: guarda cuál usas con `trovefy arranque hecho 04 --dato business_id=<id>`». Arreglo: haz el paso 6 de esta guía; no es un fallo.
- Síntoma: «Meta abrió «Seleccionar negocio» en vez del portfolio …» o «Meta abrió el portfolio X, no el guardado». Arreglo: el ID guardado no es el de tu portfolio o tu perfil no tiene acceso; abre el portfolio, copia su `business_id=` y vuelve a guardarlo.
- Síntoma: «no medido: Meta pide una verificación de seguridad en el navegador de Trovefy; hazla tú y vuelve a verificar» (Meta enseña «Verificación necesaria» / «Verificar cuenta»). Arreglo: abre el navegador con el comando del paso 1, completa tú la verificación y vuelve a verificar.
- Síntoma: Meta te pide verificar identidad. Arreglo: hazlo tú con tus documentos reales; Claude no los ve.

**Cómo se verifica**
Al verificar se abre una ventana del navegador de Trovefy unos segundos; no la toques.
`trovefy arranque verificar 04` abre con el perfil de Meta `https://business.facebook.com/latest/settings/business_info?business_id=<id>` si guardaste el ID (paso 6) o, si no, `https://business.facebook.com/settings/`; lee el `business_id=` de la URL final y guarda una captura (`config/evidencia/04-captura-<fecha>.png`) y el ID. Si la sesión ha caducado dice «no medido» en vez de fallar.
Mientras el patrón no esté confirmado con tu pantalla real, el resultado es «no medido: patrón sin confirmar con tu pantalla real» y la captura y el texto leído quedan en `config/evidencia/provisional/`; el paso no se verifica todavía.
Para confirmarlo, tras tu primera captura real: `trovefy arranque confirmar 04` muestra lo que Trovefy leyó de tu pantalla; si coincide con lo que ves y lo dices, Claude ejecuta `trovefy arranque confirmar 04 --respuesta si` y vuelve a verificar. Si no coincide, hay que ajustar el patrón en el repo (no es tarea tuya).
