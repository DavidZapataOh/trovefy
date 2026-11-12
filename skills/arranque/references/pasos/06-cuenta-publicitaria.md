# 06 · Cuenta publicitaria

**Objetivo**
Crear tu cuenta publicitaria de Meta con la moneda y la zona horaria correctas y un límite de gasto, para que nada se gaste sin que tú lo decidas.

**Antes de empezar**
- Pasos 04 y 05 hechos (`verificado`, o `hecho` con «patrón sin confirmar»).
- **Antes de crear nada: la moneda (USD) y la zona horaria no se pueden cambiar sin crear otra cuenta.** La zona horaria tiene que ser la del primer mercado que elijas con `/trovefy:auditar`; si todavía no lo has elegido, para aquí y hazlo primero.
- Meta deja cambiar moneda y zona horaria una vez cada 60 días (Ajustes de pago → Información del negocio → Editar), pero al hacerlo cierra la cuenta y crea una cuenta nueva; ese cambio puede quedar bloqueado por el límite de cuentas nuevas por persona que pone Meta (https://www.facebook.com/business/help/291404291014138).
- Una tarjeta colombiana con compras internacionales activadas (llama a tu banco si no estás seguro).
- Elige **pago automático con tarjeta**, no fondos prepagados ni saldo manual: Meta no permite límite de gasto de la cuenta en una cuenta prepagada (https://www.facebook.com/business/help/141820733085330).
- Sin VPN mientras la creas.

**Pasos**
1. Mira en tu archivo de decisión de `/trovefy:auditar` cuál es el primer mercado y su zona horaria (por ejemplo `Europe/Bucharest` para Rumanía).
2. Abre el navegador de Trovefy con el perfil de Meta:
   `trovefy navegador abrir meta https://business.facebook.com/`
3. Crea la cuenta publicitaria dentro de tu portfolio (Cuentas → Cuentas publicitarias → Añadir → Crear una cuenta publicitaria nueva). Elige moneda **USD** y la zona horaria del primer mercado.
4. Al configurar la facturación, revisa la Divisa y la Zona horaria en la pantalla de Información fiscal de la facturación antes de añadir la tarjeta: Meta puede cambiarlas por las de tu país. Si ves otra moneda o zona, corrígelas ahí antes de seguir.
5. Añade tu tarjeta como método de pago con **pago automático** (no prepago ni saldo manual: con ellos no podrás poner el límite).
6. En Ajustes de pago, pon un límite de gasto de la cuenta de unos US$ 250 (el umbral `cuenta.limite_gasto_inicial_usd`: el dinero de las pruebas más una reserva aprobada). Si tu cuenta está en otra moneda, pon el equivalente en esa moneda con el cambio del día de tu banco.
7. Copia el número de la cuenta (sale como `act=…` en la dirección de Ads Manager) y guárdalo:
   `trovefy arranque hecho 06 --dato act_id=<número>`
8. Solo si decides quedarte con una cuenta en otra moneda o zona (por ejemplo, Meta la dejó en pesos colombianos y no se puede cambiar), guarda tu decisión con tus valores:
   `trovefy arranque hecho 06 --dato moneda=COP --dato zona=America/Bogota`
   El verificador la compara con lo que ve y lo dice: «decisión del usuario: moneda COP (la guía pide USD)».

**Errores típicos**
- Síntoma: «no medido: elige primero el mercado con /auditar». Arreglo: ejecuta `/trovefy:auditar`, elige el mercado y vuelve a verificar.
- Síntoma: la moneda no es USD o la zona no coincide. Arreglo: cambiarlas crea una cuenta nueva (una vez cada 60 días, y puede bloquearlo el límite de cuentas nuevas); o crea otra cuenta con los valores correctos, o, si decides quedarte con esta, guarda tu decisión (paso 8).
- Síntoma: Meta puso la moneda y la zona de tu país en la Información fiscal. Arreglo: es lo que avisa el paso 4; si ya no se puede cambiar, decide tú y guárdalo (paso 8).
- Síntoma: «límite en COP; equivalencia en USD no medida». Arreglo: no es un fallo; Trovefy no inventa el tipo de cambio. Comprueba tú que el límite equivale a unos US$ 250 con el cambio del día.
- Síntoma: «no medido: no se ve la zona horaria en las pantallas de Meta». Arreglo: revísala tú en Facturación y pagos → Información del negocio → Editar y avisa para ajustar el patrón (cambio en el repo).
- Síntoma: «no medido: Meta pide una verificación de seguridad en el navegador de Trovefy; hazla tú y vuelve a verificar» (Meta enseña «Verificación necesaria» / «Verificar cuenta»). Arreglo: abre el navegador con el comando del paso 2, completa tú la verificación y vuelve a verificar.
- Síntoma: «la cuenta no tiene límite de gasto» o supera el máximo. Arreglo: ponlo en Ajustes de pago, hasta US$ 250 (o su equivalente en la moneda de tu cuenta). Si tu cuenta usa fondos prepagados, no admite límite: cambia a pago automático con tarjeta.
- Síntoma: «pon primero el límite de gasto (paso 6 de la guía) y vuelve a capturar» al confirmar. Arreglo: pon el límite (paso 6), vuelve a verificar para capturar la pantalla y confirma después.
- Síntoma: el pago se rechaza. Arreglo: pide a tu banco que active las compras internacionales.

**Cómo se verifica**
Al verificar se abre una ventana del navegador de Trovefy unos segundos; no la toques.
`trovefy arranque verificar 06` abre con el perfil de Meta la facturación de la cuenta (Divisa y límite de gasto) y sus ajustes (zona horaria), y los compara con tu decisión guardada (paso 8) o, si no la hay, con USD, el mercado elegido y el máximo del umbral. Un límite en otra moneda que USD se acepta y se dice «límite en COP; equivalencia en USD no medida». Guarda la captura en `config/evidencia/06-…` y el número de la cuenta como `act_id`.
Mientras el patrón no esté confirmado con tu pantalla real, el resultado es «no medido: patrón sin confirmar con tu pantalla real» y la captura y el texto leído quedan en `config/evidencia/provisional/`; el paso no se verifica todavía.
Para confirmarlo, tras tu primera captura real: `trovefy arranque confirmar 06` muestra lo que Trovefy leyó de tu pantalla; si coincide con lo que ves y lo dices, Claude ejecuta `trovefy arranque confirmar 06 --respuesta si` y vuelve a verificar. Si no coincide, hay que ajustar el patrón en el repo (no es tarea tuya).
La verificación completa por API (`currency`, `timezone_name`, `spend_cap`, `account_status`, `min_daily_budget`) llega en la Fase 1.
