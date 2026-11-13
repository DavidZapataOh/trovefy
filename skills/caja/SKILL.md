---
name: caja
description: >-
  Muestra la caja de Trovefy: los sobres de dinero, los huecos de test que caben, el cambio USD/COP con su fuente y fecha, y los bloqueos. Mueve dinero entre sobres solo con la orden explícita del usuario y propone los límites de gasto para que los apruebe en Telegram. Úsala cuando el usuario diga «caja», «presupuesto», «huecos», «mover dinero» o «cuánto me queda».
allowed-tools: Read, Bash(trovefy caja *)
---

# /caja: sobres, huecos y límites

Responde siempre en español, con frases cortas y sin jerga. El usuario no es técnico. Uso: `/trovefy:caja`.

Reglas de fondo:

- Lo que no se midió se dice «no medido: <motivo>». Nunca lo reemplaces por un número tuyo.
- **Nunca escribes en Meta**, ni en `/var/spool` a mano, ni en la carpeta Meta del cerebro. Solo usas los comandos de abajo.
- **Nunca apruebas nada.** Aceptar y Rechazar solo existen en Telegram.
- **Nunca decides por el usuario.** Mover dinero es decisión suya.
- Hay dos STOP distintos. El STOP del cerebro es `<vault>/.trovefy/STOP`. El STOP del ejecutor se activa con `/stop` en Telegram o con `trovefy-ejecutor stop`. Si `ver` habla de un STOP, di cuál es.

Pasos:

0. **¿Estás en el cerebro?** Lee `config/umbrales.yaml` en el directorio actual. Si no existe, dile al usuario que cierre Claude Code, ejecute `cd ~/trovefy-cerebro` (o la carpeta de `TROVEFY_VAULT`) y vuelva a abrirlo allí, y **para**.
1. **Iniciar.** Si falta `config/caja.yaml`, ejecuta `trovefy caja iniciar`. Si el paso 06 de `/arranque` no guardó la moneda de la cuenta (`act_guardado` sin moneda), pregúntale antes la moneda y pásala con `--moneda XXX`. Si la salida dice que falta la cuenta, remite a `/arranque`.
2. **Ver.** Ejecuta `trovefy caja ver` y cuéntaselo: los sobres con su saldo, los huecos de test que caben («9; 8 si hay una prórroga»), el cambio USD/COP con su fuente y su fecha (la TRM), y los bloqueos con su motivo. El resumen completo queda en `wiki/analisis/caja.md`.
3. **Mover (solo si lo pide).** Solo con la orden explícita del usuario. Ejecuta
   `trovefy caja mover --de <sobre> --a <sobre> --importe <USD> --cita '<sus palabras literales>'`.
   La cita es lo que escribió, tal cual, sin resumir ni corregir. Va entre **comillas simples**; si el texto trae una comilla simple `'`, escríbela como `'\''`. Si duda o no lo dice claro, no registres nada y pregúntale. Si el comando se queja (por ejemplo, saldo corto), cuéntalo tal cual y para.
4. **Proponer límites.** Hazlo tras mover dinero, o si `ver` dice que los límites han cambiado. No depositas nada todavía. Primero explica la recomendación:
   - el importe en **USD y en COP**, con la **TRM y su fecha**;
   - si hay gasto ya hecho por encima del límite (sobregasto), explica que el tope propuesto para la cuenta es igual a lo ya gastado: la cuenta deja de gastar;
   - si la moneda, el cambio o algo más es «no medido», dilo así y no propongas importes.

   Pregunta: «¿La envío para que la apruebes en Telegram?». **Solo con su sí** ejecuta `trovefy caja proponer-limites`. Dile que la propuesta llegará a Telegram y que solo allí puede pulsar Aceptar o Rechazar. Tú no puedes hacerlo.
   Si el ejecutor no está instalado, dilo y remite al instalador o a `/arranque`.
5. **Gastos de herramientas.** Si el usuario cuenta un gasto, anótalo con
   `trovefy caja anotar --importe <n> --moneda USD|COP --nota '<lo que dijo>'`.
   Si el comando dice que el sobre se agotó, **para** y avísalo. No sigas gastando.
