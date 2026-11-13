---
name: vigia
description: >-
  Revisa la salud de todo Trovefy (solo lectura): lo urgente primero, luego los avisos y al final lo no medido con su motivo. Úsala cuando el usuario diga «vigía», «cómo está todo», «revisa el sistema» o «qué falla». Con --rutina la lanza la rutina, sin preguntas.
allowed-tools: Read, Bash(trovefy vigia *)
---

# /vigia: cómo está todo

Responde siempre en español, con frases cortas y sin jerga. El usuario no es técnico. Uso: `/trovefy:vigia`.

Reglas de fondo:

- La vigía solo mira. **Nunca intentas arreglar nada por tu cuenta.** Di qué skill o paso lo arregla (`/arranque`, `/caja`, `/aprobaciones`…).
- Nunca escribes en Meta ni en `/var/spool` a mano. Nunca apruebas nada: Aceptar y Rechazar solo existen en Telegram.
- Lo que no se midió se dice «no medido: <motivo>». Nunca lo reemplaces por un número tuyo.
- Hay dos STOP distintos y debes decir cuál ves. El STOP del cerebro es `<vault>/.trovefy/STOP`. El STOP del ejecutor se activa con `/stop` en Telegram o con `trovefy-ejecutor stop`.
- Si el ejecutor no está instalado, dilo y remite a los pasos del instalador o a `/arranque`.

Pasos:

0. **¿Estás en el cerebro?** Lee `config/umbrales.yaml` en el directorio actual. Si no existe, dile al usuario que cierre Claude Code, ejecute `cd ~/trovefy-cerebro` (o la carpeta de `TROVEFY_VAULT`) y vuelva a abrirlo allí, y **para**.
1. **Ejecutar.** Corre `trovefy vigia`. En la rutina (`--rutina`) corre `trovefy vigia --rutina`: deja el informe en `rutinas/log/<día>/vigia.md`, no hagas preguntas. Si el usuario solo quiere mirar, sin avisos a Telegram, añade `--sin-alerta`.
2. **Presentar en este orden:** primero lo urgente, luego los avisos, al final lo no medido con su motivo. Sé breve.
3. **Cerrar.** Para cada problema, di qué skill o paso lo arregla. No lo arregles tú ni propongas atajos.
