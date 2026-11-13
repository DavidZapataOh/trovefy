# 12 · Bot de Telegram y ejecutor

**Objetivo**
Instalar el ejecutor y dejar tu bot de Telegram emparejado contigo: ahí aprobarás cada propuesta con un botón.

**Antes de empezar**
- Una **terminal de Ubuntu (WSL) aparte**, fuera de Claude Code. Todos los comandos con `sudo` los escribes ahí, sin `!`.
- Tu cuenta de Telegram en el móvil.
- El token del bot es secreto: **lo pegas tú en un archivo; Claude no lo ve** ni debe pedírtelo por el chat.

**Pasos**
1. Instala el ejecutor (terminal aparte): `sudo bash ~/trovefy/trovefy/scripts/instalar-ejecutor.sh`
2. Cierra y abre la terminal para que tu usuario entre en el grupo `trovefy`.
3. En Telegram, abre @BotFather y escribe `/newbot`. Elige nombre y usuario del bot; BotFather te da el token.
4. Abre el archivo de secretos (terminal aparte): `sudo -u trovefy-exec nano /home/trovefy-exec/.config/trovefy-ejecutor/secretos.env`
5. El instalador ya dejó las claves: busca la línea `TELEGRAM_BOT_TOKEN=` (ya existe, vacía) y pega el token justo después del `=`, sin comillas ni otra línea (en Windows Terminal, clic derecho o Ctrl+Shift+V). No toques `META_TOKEN=`: se rellena en el paso 13. Guarda con Ctrl+O, Enter y sal con Ctrl+X.
6. En Telegram, abre tu bot y envíale `/start`.
7. Empareja (terminal aparte): `sudo -u trovefy-exec /home/trovefy-exec/.local/bin/trovefy-ejecutor emparejar`. Muestra un código de 6 dígitos: envíaselo al bot desde Telegram.
8. Pide la verificación: `trovefy arranque verificar 12`

Aquí **no** se arranca el servicio: sin `META_TOKEN` el ejecutor se niega a servir. El servicio arranca en el paso 13, cuando ya están los dos tokens.

**Errores típicos**
- Síntoma: «el ejecutor no está instalado». Arreglo: si el instalador del paso 1 no existe en tu copia, falta el instalador del plan 12; si existe, ejecútalo y repite.
- Síntoma: «tu usuario no está en el grupo trovefy». Arreglo: cierra y abre la terminal (paso 2).
- Síntoma: «Falta TELEGRAM_BOT_TOKEN en secretos.env». Arreglo: repite el paso 5; el token va en la misma línea, justo después del `=`.
- Síntoma: «No se pueden leer los secretos (ValueError)» al emparejar: casi siempre la clave quedó duplicada (escribiste otra línea `TELEGRAM_BOT_TOKEN=` en vez de usar la que ya existía) o el token va entre comillas. Arreglo: abre otra vez el archivo (paso 4), deja una sola línea `TELEGRAM_BOT_TOKEN=` con el token detrás, sin comillas, y borra la otra.
- Síntoma: «el bot de Telegram aún no está emparejado contigo». Arreglo: repite el paso 7.
- Síntoma: la verificación dice «el servicio arranca en el paso 13». Arreglo: es lo esperado; sigue con el paso 13.
- Síntoma: no llega nada a Telegram. Arreglo: revisa los dos STOP: el del cerebro (`.trovefy/STOP`, bloquea depósitos) y el del ejecutor (`/stop` en Telegram o `sudo -u trovefy-exec /home/trovefy-exec/.local/bin/trovefy-ejecutor stop "motivo"`, bloquea escrituras en Meta).

**Cómo se verifica**
`trovefy arranque verificar 12` (lo puede ejecutar Claude) lee el estado del ejecutor, sin sudo ni secretos: comprueba que el emparejamiento existe; si el servicio aún no late, te recuerda que arranca en el paso 13. Guarda solo `emparejado` y la fecha en `config/evidencia/`; nunca tu número de usuario ni el token.
