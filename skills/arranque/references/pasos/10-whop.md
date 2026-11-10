# 10 · Cobro con Whop

**Objetivo**
Poder cobrar en dólares en Impultienda con Whop y retirar el dinero a tu banco en Colombia.

**Antes de empezar**
- Paso 09 hecho (`verificado`, o `hecho` con «patrón sin confirmar»).
- **Antes de hacer el KYC, comprueba que Whop paga a Colombia.** La verificación de identidad se hace una vez y con tus documentos reales: no la empieces si el pago a tu país no está confirmado. `trovify arranque verificar 10` lo comprueba por ti en la página pública de Whop (https://docs.whop.com/manage-your-business/manage-payouts/set-up-payouts).
- Si la documentación de Whop no lista a Colombia, el verificador te lo dice y recomienda el paso 10b (Hotmart). Es una lectura de documentación: confírmalo conmigo y, si estás de acuerdo, marca el paso 10 como **bloqueado** (`trovify arranque bloqueado 10 --motivo "Whop no paga a Colombia"`); entonces el siguiente paso es el 10b.
- Tu cédula y la cuenta bancaria colombiana a tu nombre.
- Los comandos de sistema los escribes en una terminal de Ubuntu (WSL) aparte, sin `!`.

**Pasos**
1. Verifica primero el pago a Colombia, sin tocar nada de tu cuenta:
   `trovify arranque verificar 10`
   Si dice que Whop no paga a Colombia, para aquí, confírmalo y ve al paso 10b.
2. Crea tu cuenta en https://whop.com/ (contraseña y 2FA los haces tú).
3. Abre el navegador de Trovify con el perfil de Whop:
   `trovify navegador abrir whop https://whop.com/dashboard/balance/`
4. En Dashboard > Balances elige **Set up Whop Payments**, selecciona **Colombia** como país de la cuenta bancaria y completa el KYC (tus datos, tu banco y la foto de tu documento). Eso lo haces tú; Claude no ve tus documentos ni códigos.
5. En Impultienda conecta Whop como pasarela (Configuraciones > Pasarelas de pago).
6. Cuando el KYC esté aprobado y Whop conectado:
   `trovify arranque hecho 10`

**Errores típicos**
- Síntoma: «Whop no paga a Colombia según su documentación pública». Arreglo: confírmalo, marca el paso 10 como bloqueado y sigue con el paso 10b (Hotmart).
- Síntoma: «no medido: patrón sin confirmar con tu pantalla real». Arreglo: es lo esperado hasta que se capture tu panel real por primera vez; el paso no se verifica todavía.
- Síntoma: KYC pendiente. Arreglo: espera; Whop puede tardar y a veces revisa los retiros a mano. Vuelve a verificar después.
- Síntoma: «Whop no está conectado en Impultienda». Arreglo: conéctalo en Impultienda (paso 5).
- Síntoma: no ves tu banco como método de pago. Arreglo: Whop muestra los métodos disponibles para tu país al retirar; revisa Balances > Payout methods.

**Cómo se verifica**
Al verificar se abre una ventana del navegador de Trovify unos segundos; no la toques.
`trovify arranque verificar 10` primero lee (sin navegador) la lista pública de países de pago de Whop. Si Colombia no está en una lista que se reconoce, recomienda el 10b (no bloquea nada por su cuenta). Si está, lee en el panel de Whop el estado del KYC y en la pantalla de pasarelas de Impultienda que Whop esté conectado. Es ✓ solo con las tres cosas: Colombia en la lista, KYC aprobado y Whop conectado.
Mientras los mapas no estén confirmados con tus pantallas reales, el resultado es «no medido» y la captura y el texto leído quedan en `config/evidencia/provisional/`.
Para confirmarlo, tras tu primera captura real: `trovify arranque confirmar 10` muestra lo que Trovify leyó de tu pantalla; si coincide con lo que ves y lo dices, Claude ejecuta `trovify arranque confirmar 10 --respuesta si` y vuelve a verificar. Si no coincide, hay que ajustar el patrón en el repo (no es tarea tuya).
