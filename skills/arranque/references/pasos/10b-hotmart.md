# 10b · Respaldo de cobro: Hotmart

**Objetivo**
Cobrar con Hotmart y retirar a tu banco colombiano con HotPay Internacional, si Whop no te sirve (paso 10 bloqueado).

**Antes de empezar**
- Solo si el paso 10 está bloqueado o Whop no te funciona; si no, sáltalo.
- **Con Hotmart cambia cómo se vende:** el checkout, el order bump y el upsell son de Hotmart, no de Impultienda. La landing (la página de venta) va aparte, en Cloudflare Pages, y su botón lleva al checkout de Hotmart. Piensa en esto antes de montar el embudo.
- **Retiro mínimo: US$ 50** (o € 50) para cuentas internacionales, con una tarifa variable según el monto (https://help.hotmart.com/es/article/Como-sacar-a-minha-comiss%C3%A3o-/216440207, leída el 2026-11-10). Las cuentas Wise no se aceptan.
- Hotmart solo muestra el formulario de **cuenta bancaria después de tu primera venta**, y el banco debe estar en Colombia y a tu nombre (https://help.hotmart.com/es/article/23867226765709/). Por eso este paso puede quedar «hecho» pero no verificado hasta esa primera venta.
- Segundo respaldo, si tampoco sirve Hotmart: Lemon Squeezy. Solo se menciona aquí; no se prepara nada todavía.

**Pasos**
1. Crea tu cuenta en https://app.hotmart.com/ y completa tus datos y el documento (lo haces tú; Claude no ve contraseñas ni códigos).
2. Abre el navegador de Trovify con el perfil de Hotmart:
   `trovify navegador abrir hotmart https://app.hotmart.com/`
3. Crea un **producto de prueba** (menú Productos) para probar el flujo.
4. Cuando tengas una primera venta, registra tu cuenta bancaria colombiana: Mi cuenta > Datos financieros > Nueva cuenta (nombre del beneficiario igual al de tu cuenta Hotmart, tipo y número de cuenta, código BIC-SWIFT). Hotmart la revisa hasta 5 días hábiles. Para recibir en pesos (COP) el banco debe aparecer en la lista; si no, regístrala como «Banco Internacional» y recibe dólares.
5. Márcalo cuando esté:
   `trovify arranque hecho 10b`

**Errores típicos**
- Síntoma: «pendiente de primera venta». Arreglo: no es un fallo; el formulario del banco aparece tras la primera venta. Hazla (o espera) y vuelve a verificar.
- Síntoma: la cuenta se devuelve («Devuelto»). Arreglo: corrige los datos bancarios; el nombre y el tipo de cuenta deben coincidir con los de Hotmart.
- Síntoma: «no medido: patrón sin confirmar con tu pantalla real». Arreglo: es lo esperado hasta que se capture tu cuenta real por primera vez.
- Síntoma: «no medido: mapa desactualizado (…)». Arreglo: Hotmart cambió esa pantalla; avisa para actualizar el mapa.

**Cómo se verifica**
Al verificar se abre una ventana del navegador de Trovify unos segundos; no la toques.
`trovify arranque verificar 10b` lee solo (sin clics) tus productos y tus datos financieros con el perfil de Hotmart, según `templates/hotmart/mapa.yaml`. Sin cuenta bancaria todavía el resultado es «pendiente de primera venta» (no medido, no fallo). Es ✓ si hay al menos un producto y una cuenta bancaria colombiana aprobada para el retiro de HotPay Internacional.
Mientras el mapa no esté confirmado con tu pantalla real, el resultado es «no medido» y la captura queda en `config/evidencia/provisional/`.
