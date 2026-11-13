---
name: aprobaciones
description: >-
  Consulta y prueba el aprobador de Telegram: lista las propuestas, muestra el estado del ejecutor, el STOP y los límites, deposita una propuesta de prueba y explica una propuesta. No aprueba nada. Úsala cuando el usuario diga «aprobaciones», «propuestas», «probar Telegram» o «estado del ejecutor».
allowed-tools: Read, Bash(trovefy aprobaciones *)
---

# /aprobaciones: propuestas y Telegram

Responde siempre en español, con frases cortas y sin jerga. El usuario no es técnico. Uso: `/trovefy:aprobaciones [listar|estado|probar|explicar P-…]`.

Reglas de fondo:

- **Nunca apruebas ni rechazas nada.** Aceptar y Rechazar solo existen en Telegram. Si el usuario te pide aprobar, dile que lo haga él allí.
- Nunca escribes en Meta ni en `/var/spool` a mano. Solo usas los comandos de abajo.
- Lo que no se midió se dice «no medido: <motivo>». Nunca pongas un número tuyo.
- Hay dos STOP distintos y debes decir cuál es. El STOP del cerebro es `<vault>/.trovefy/STOP`. El STOP del ejecutor se activa con `/stop` en Telegram o con `trovefy-ejecutor stop`.
- Si el ejecutor no está instalado, dilo con esas palabras y remite a los pasos del instalador o a `/arranque`. No intentes instalarlo ni arreglarlo tú.

Pasos:

0. **¿Estás en el cerebro?** Lee `config/umbrales.yaml` en el directorio actual. Si no existe, dile al usuario que cierre Claude Code, ejecute `cd ~/trovefy-cerebro` (o la carpeta de `TROVEFY_VAULT`) y vuelva a abrirlo allí, y **para**.
1. **Elegir la acción** según lo que pida el usuario. Sin indicación, empieza por `estado`.
   - `trovefy aprobaciones listar` (con `--todas` para incluir las ejecutadas, caducadas y otras): lista las propuestas por grupo. Cuéntalas con su id y su estado.
   - `trovefy aprobaciones estado`: dice si el ejecutor está vivo, si hay algún STOP (di cuál), los límites y la auditoría. Si falta algo, di «no medido: <motivo>».
   - `trovefy aprobaciones probar`: deposita una propuesta de prueba que no hace nada. Dile que le llegará a Telegram y que pruebe Aceptar y Rechazar allí. Tú no puedes pulsarlos. Después, con `listar --todas`, mira cómo terminó y cuéntaselo.
   - `trovefy aprobaciones explicar <P-AAAAMMDD-NNN>`: explica en palabras simples qué pide la propuesta, cuánto y por qué.
2. **Presentar.** Cuenta el resultado tal como salió, sin añadir cifras. Si algo falla, di el error y qué paso lo arregla.
