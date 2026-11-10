# 06 · Cuenta publicitaria

**Objetivo**
Crear tu cuenta publicitaria de Meta con la moneda y la zona horaria correctas y un límite de gasto, para que nada se gaste sin que tú lo decidas.

**Antes de empezar**
- Pasos 04 y 05 verificados.
- **Antes de crear nada: la moneda (USD) y la zona horaria no se pueden cambiar después.** La zona horaria tiene que ser la del primer mercado que elijas con `/trovify:auditar`; si todavía no lo has elegido, para aquí y hazlo primero. Si te equivocas, Meta cierra la cuenta y hay que crear otra.
- Una tarjeta colombiana con compras internacionales activadas (llama a tu banco si no estás seguro).
- Elige **pago automático con tarjeta**, no fondos prepagados ni saldo manual: Meta no permite límite de gasto de la cuenta en una cuenta prepagada (https://www.facebook.com/business/help/141820733085330).
- Sin VPN mientras la creas.

**Pasos**
1. Mira en tu archivo de decisión de `/trovify:auditar` cuál es el primer mercado y su zona horaria (por ejemplo `Europe/Bucharest` para Rumanía).
2. Abre el navegador de Trovify con el perfil de Meta:
   `trovify navegador abrir meta https://business.facebook.com/`
3. Crea la cuenta publicitaria dentro de tu portfolio (Cuentas → Cuentas publicitarias → Añadir → Crear una cuenta publicitaria nueva). Elige moneda **USD** y la zona horaria del primer mercado.
4. Añade tu tarjeta como método de pago con **pago automático** (no prepago ni saldo manual: con ellos no podrás poner el límite).
5. En Ajustes de pago, pon un límite de gasto de la cuenta de unos US$ 250 (el umbral `cuenta.limite_gasto_inicial_usd`: el dinero de las pruebas más una reserva aprobada).
6. Copia el número de la cuenta (sale como `act=…` en la dirección de Ads Manager) y guárdalo:
   `trovify arranque hecho 06 --dato act_id=<número>`

**Errores típicos**
- Síntoma: «no medido: elige primero el mercado con /auditar». Arreglo: ejecuta `/trovify:auditar`, elige el mercado y vuelve a verificar.
- Síntoma: la moneda no es USD o la zona no coincide. Arreglo: no se pueden cambiar; crea otra cuenta publicitaria con los valores correctos.
- Síntoma: «la cuenta no tiene límite de gasto» o supera el máximo. Arreglo: ponlo en Ajustes de pago, hasta US$ 250. Si tu cuenta usa fondos prepagados, no admite límite: cambia a pago automático con tarjeta.
- Síntoma: el pago se rechaza. Arreglo: pide a tu banco que active las compras internacionales.

**Cómo se verifica**
Al verificar se abre una ventana del navegador de Trovify unos segundos; no la toques.
`trovify arranque verificar 06` abre los Ajustes de pago de la cuenta con el perfil de Meta, lee la moneda, la zona horaria y el límite de gasto, y los compara con el mercado elegido y con el máximo del umbral. Guarda la captura en `config/evidencia/06-…` y el número de la cuenta como `act_id`.
Mientras el patrón no esté confirmado con tu pantalla real, el resultado es «no medido: patrón sin confirmar con tu pantalla real» y la captura queda en `config/evidencia/provisional/`; el paso no se verifica todavía.
La verificación completa por API (`currency`, `timezone_name`, `spend_cap`, `account_status`, `min_daily_budget`) llega en la Fase 1.
