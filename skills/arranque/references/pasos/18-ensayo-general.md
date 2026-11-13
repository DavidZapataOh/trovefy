# 18 · Ensayo general

**Objetivo**
Probar de punta a punta el circuito (propuesta, Telegram, Meta en seco, compra y reembolso) antes de gastar dinero real en anuncios.

**Antes de empezar**
- Pasos 12, 13 y 14 verificados; el servicio late (`trovefy aprobaciones estado`).
- Una pasarela de pago lista y tu tarjeta para una compra de prueba de US$ 1–5.
- Claude deposita cada propuesta con un comando solo en la línea, sin cadenas ni variables.
- El montaje del ensayo lleva `solo_validar`: el ejecutor solo valida la campaña en Meta, no crea nada y no exige que la página ni el dataset estén en sus límites (aún no tienes dataset: llega en `/tracking`, fase 2). Los montajes reales sí los exigen.

**Pasos**
1. Claude deposita un `noop` con `trovefy aprobaciones probar`. Pulsa **Aceptar** en Telegram.
2. Claude prepara el montaje de prueba con `trovefy arranque ensayo montaje`: escribe en `propuestas/ensayo/` un `crear_estructura_pausada` mínimo con `"solo_validar": true` y una imagen de prueba generada (con su sha256), con la página del paso 05 y la cuenta del paso 06. Después lo deposita con la ruta que imprime: `trovefy buzon depositar <ruta>`. El ejecutor solo pasa la campaña por `validate_only`: nada queda creado ni subido en Meta. Acéptalo en Telegram.
3. Haz una compra real de prueba de US$ 1–5 en tu tienda y regístrala: `trovefy arranque ensayo compra --pedido <id> --importe 2.00 --moneda USD --pasarela <whop|hotmart|impultienda>`
4. Reembolsa esa compra en la pasarela y registra: `trovefy arranque ensayo reembolso --pedido <id>`
5. Pide la verificación: `trovefy arranque verificar 18`

Los medios reales de `/montar` (bajo `productos/`) son una decisión de la Fase 3; la imagen de `propuestas/ensayo/` solo sirve para este ensayo.

**Errores típicos**
- Síntoma: no llega nada a Telegram. Arreglo: revisa los dos STOP: el del cerebro (`.trovefy/STOP`, bloquea depósitos) y el del ejecutor (`/stop` en Telegram, bloquea escrituras en Meta).
- Síntoma: el depósito se rechaza. Arreglo: el comando va solo en la línea y con la ruta que imprimió `trovefy arranque ensayo montaje`.
- Síntoma: `trovefy arranque ensayo montaje` dice que falta el `page_id` o la cuenta. Arreglo: verifica el paso 05 o marca el 06 con `--dato act_id=…`.
- Síntoma: el montaje vuelve rechazado con `pagina_no_permitida` o `dataset_no_permitido`. Arreglo: el montaje no llevaba `solo_validar`; genera el de prueba con `trovefy arranque ensayo montaje`.
- Síntoma: «no hay copia de la auditoría en el vault». Arreglo: el ejecutor la copia al vault (plan 12); comprueba que el servicio late con `trovefy aprobaciones estado`.
- Síntoma: «falta un noop aceptado por Telegram y ejecutado». Arreglo: repite el paso 1 y acéptalo en Telegram.
- Síntoma: «falta el montaje en validate_only». Arreglo: repite el paso 2 y acéptalo en Telegram.
- Síntoma: «falta la compra de prueba». Arreglo: paso 3.
- Síntoma: «falta el reembolso de la compra de prueba …». Arreglo: si solo hiciste la compra, el paso falla hasta registrar el reembolso (paso 4).
- Síntoma: «la copia de la auditoría no cuadra». Arreglo: no la edites; avisa para revisarla con el ejecutor.
- Síntoma: «no medido: …». Arreglo: avisa para revisar el registro del ensayo.
- Síntoma: `trovefy aprobaciones estado` sin latido. Arreglo: `sudo systemctl start trovefy-ejecutor` en la terminal aparte (con los dos tokens ya pegados, paso 13).

**Cómo se verifica**
`trovefy arranque verificar 18` lee la copia de la auditoría en el vault y el registro del ensayo: comprueba la cadena de la auditoría tramo a tramo (un hueco no invalida los eventos de un tramo que cuadra), un `noop` aceptado y ejecutado, un montaje en `validate_only` y la compra de prueba con su reembolso. Deja la evidencia en `config/evidencia/`.
