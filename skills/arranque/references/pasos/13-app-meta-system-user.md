# 13 · App de Meta y usuario del sistema

**Objetivo**
Crear la app de Meta y un usuario del sistema con permiso mínimo, y dejar su token solo en manos del ejecutor.

**Antes de empezar**
- Pasos 04, 05, 06 y 12 hechos. Terminal de Ubuntu (WSL) **aparte** para los comandos con `sudo`.
- Tu `business_id` sale de `trovefy arranque estado` (paso 04). Úsalo como `?business_id=<id>` en toda URL de Business; si Meta dice «tienes varios portfolios», elige el del paso 04.
- La cuenta publicitaria del paso 06 (`act_<act_id>`) también sale de `trovefy arranque estado`; aquí no se escribe su número real.
- El token es secreto: nunca lo pegues en el chat; Claude no lo ve.

**Pasos**
1. Entra a https://developers.facebook.com/apps/ y crea una app de tipo **Business**, asociada al portfolio del paso 04.
2. En Business Settings (con `?business_id=<id>`) ve a Usuarios → Usuarios del sistema y crea `trovefy-ejecutor` con rol **Employee (Empleado)**.
3. Asígnale la cuenta del paso 06 (`act_<act_id>`), la página del paso 05 y el dataset si ya existe (si no, se asigna en `/tracking`, fase 2).
4. Genera el token del usuario del sistema con los permisos `ads_management` y `business_management`. Si el panel de la app ofrece cuenta *sandbox*, anótalo: `trovefy arranque hecho 13 --dato sandbox=si` (o `sandbox=no`) (P-08).
5. Abre el archivo de secretos (terminal aparte): `sudo -u trovefy-exec nano /home/trovefy-exec/.config/trovefy-ejecutor/secretos.env`
6. Con el archivo abierto, busca la línea `META_TOKEN=` (ya existe, vacía) y pega el token justo después del `=`, sin comillas ni otra línea. Guarda con Ctrl+O, Enter y sal con Ctrl+X. Nunca lo pegues en el chat.
7. Comprueba la cuenta (terminal aparte): `sudo -u trovefy-exec /home/trovefy-exec/.local/bin/trovefy-ejecutor comprobar-meta`. Con COP confirma el *offset* 1.
8. Arranca el servicio, ya con los dos tokens: `sudo systemctl start trovefy-ejecutor`
9. Prueba el circuito con `trovefy aprobaciones probar` (propuesta noop) y acéptala en Telegram.
10. Pide la verificación: `trovefy arranque verificar 13`

**Errores típicos**
- Síntoma: Meta muestra «Verificación necesaria». Arreglo: la completa tú en el navegador; Claude no la hace.
- Síntoma: «el ejecutor aún no ha comprobado la cuenta de Meta (falta meta.json)». Arreglo: repite el paso 7.
- Síntoma: «offset sin confirmar (P-21)». Arreglo: repite el paso 7 con el token bien pegado.
- Síntoma: «el offset … no es el oficial de …». Arreglo: oficial de Meta: COP *offset* 1, USD *offset* 100 (P-21). Con COP y America/Bogota es decisión tuya (D-37); los límites van en COP.
- Síntoma: «la moneda de Meta … no coincide con la del paso 06». Arreglo: corrige el paso 06 o la cuenta asignada.
- Síntoma: «validate_only falló: permiso …». Arreglo: revisa que el usuario tenga `ads_management` y la cuenta asignada; genera el token otra vez.
- Síntoma: «no medido: meta.json es de otra cuenta». Arreglo: asigna al usuario la cuenta del paso 06 y repite el paso 7.
- Síntoma: «algo que parece un secreto; no se lee». Arreglo: el estado no debe llevar tokens; revisa `sudo -u trovefy-exec /home/trovefy-exec/.local/bin/trovefy-ejecutor comprobar-meta`.
- Síntoma: «No se pueden leer los secretos (ValueError)»: la clave quedó duplicada (escribiste otra línea `META_TOKEN=` en vez de usar la que ya existía) o el token va entre comillas. Arreglo: abre otra vez el archivo (paso 5), deja una sola línea `META_TOKEN=` con el token detrás, sin comillas, y borra la otra.
- Síntoma: «Falta META_TOKEN» o el servicio no arranca. Arreglo: repite los pasos 6 y 7 y luego el 8.
- Síntoma: renuevas el token más adelante (caducó o lo revocaste). Arreglo: pégalo en la misma línea `META_TOKEN=` y reinicia el servicio para que lo lea: `sudo systemctl restart trovefy-ejecutor`; el servicio en marcha no relee `secretos.env`.
- Síntoma: «no medido: el offset aún no está fijado en limites.yaml (repite comprobar-meta)». Arreglo: repite el paso 7; `comprobar-meta` fija el *offset* en los límites.
- Síntoma: pegaste el token en el chat. Arreglo: revócalo, genera otro y pégalo tú en `secretos.env`.

**Cómo se verifica**
`trovefy arranque verificar 13` (lo puede ejecutar Claude) lee `meta.json` del ejecutor, sin sudo ni secretos: contrasta cuenta, moneda, zona, *offset* oficial (también el fijado en los límites, que el servicio publica en `estado/limites.json`) y `validate_only`. Guarda los campos comprobados en `config/evidencia/`; la cuenta sale enmascarada.
