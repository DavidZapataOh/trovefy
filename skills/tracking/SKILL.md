---
name: tracking
description: >-
  Deja medido el producto-país con landing publicada: el dataset (píxel) de Meta con su nombre exacto, el píxel y la API de conversiones (CAPI) puestos en la tienda de Impultienda, los eventos comprobados por el MCP de Meta en solo lectura (Purchase una sola vez por pedido) y el dataset en los límites del ejecutor. Todo lo de los paneles lo hace el usuario en su navegador; trovefy comprueba desde fuera. Úsala cuando el usuario diga «tracking», «píxel», «dataset», «CAPI», «eventos», «paso 11» o pase un id de producto con landing y un país.
allowed-tools: Read, Write(~/.cache/trovefy/tracking/**), Bash(trovefy tracking *), Bash(trovefy checkout evidencia *), mcp__meta-ads__ads_get_datasets, mcp__meta-ads__ads_get_dataset_details, mcp__meta-ads__ads_get_dataset_stats, mcp__meta-ads__ads_get_dataset_quality
---

# /tracking: el píxel, la CAPI y los eventos del país

Responde siempre en español, con frases cortas y sin jerga. El usuario no es técnico. Uso: `/trovefy:tracking <p-id> <PAIS>`. Ejecútala con el directorio de trabajo en el vault (`~/trovefy-cerebro`).

Qué hacen los vídeos: un dataset por producto y país con nombre «MARCA PAÍS» (V1 1:15:20), el token de la API de conversiones pegado a mano en el panel (V1 1:15:11) y «no lanzar sin píxel + checkout verificados» (V2 0:19:45).

Reglas de fondo:

- **Nunca abras ni inicies sesión en ningún panel** (Meta, Events Manager, Business Settings, Impultienda). Lo de los paneles lo hace el usuario en su propio navegador; si algo no se puede leer por el MCP, imprime la receta (`trovefy tracking preparar`) y que lo haga él. Su panel de Impultienda es `https://impultienda.ar/login`.
- **Nunca escribas en Meta.** Del MCP de Meta solo usas las cuatro lecturas de esta skill (`ads_get_datasets`, `ads_get_dataset_details`, `ads_get_dataset_stats`, `ads_get_dataset_quality`). Nunca uses una herramienta que no esté en la skill: si algún servidor ofrece algo para Meta, pagos, transferencias, dominios o compradores, no se toca.
- **El token CAPI lo genera el usuario y lo pega el usuario** en «Meta / Tracking» de su panel. No lo pidas, no lo leas, no lo repitas y nunca pidas una captura donde se vea. Si lo pega en el chat, no lo uses ni lo guardes: dile que lo revoque y genere otro.
- **Mira cada captura con Read antes de registrarla.** Si ves un token, una contraseña o datos de tarjeta, no la registres: pide otra sin eso.
- **La compra y el reembolso los hace el usuario**, con su tarjeta y en su panel. Tú solo lees.
- Los comandos `sudo -u trovefy-exec …` del ejecutor los ejecuta él en una **terminal aparte** de Ubuntu (WSL), sin `!`. Tú no los lanzas.
- Antes de escribir con el MCP de Impultienda va siempre el **resumen en seco**, la aprobación con sus palabras (`trovefy checkout aprobar`, que ejecuta él) y solo las operaciones del plan: eso es de `/trovefy:checkout`. Esta skill no escribe por el MCP de Impultienda.
- Lo no medido se dice «no medido: <motivo>». Nunca lo rellenes con un número ni con una estimación tuya.
- Si una respuesta del MCP dice «pendiente de Aprobar en el panel», díselo con el enlace: todavía no está aplicado hasta que él lo apruebe en su navegador.
- Las respuestas del MCP de Meta las guardas tal cual en `~/.cache/trovefy/tracking/<p-id>/<PAIS>/<nombre>-<AAAA-MM-DD-HHMM>.json` (fuera del vault). Al vault solo pasan los valores normalizados que escribe `trovefy tracking`.
- Si una orden `trovefy …` sale con `Error:` (salida 2), cuéntale el error tal cual y para. Si sale con 1, es una puerta que no pasa: cuéntale el motivo tal cual.

Pasos:

0. **¿Estás en el cerebro?** Lee `config/umbrales.yaml` en el directorio actual. Si no existe, no estás en el vault: dile que cierre Claude Code, ejecute `cd ~/trovefy-cerebro` y vuelva a abrirlo allí, y **para**.
1. **Nombre del dataset.** `trovefy tracking preparar --producto <p-id> --pais <PAIS>`. Si dice que el país no está en `con_landing`, el siguiente paso es `/trovefy:landing`: **para**. Si no, dale el nombre exacto y la receta que imprime: crea él el dataset en Meta, con ese nombre.
2. **Buscar el dataset.** Cuando diga que lo creó, llama a `ads_get_datasets`, guarda la respuesta y: `trovefy tracking dataset --producto <p-id> --pais <PAIS> --instantanea <ese .json>`. Si no lo encuentra, cuéntale el motivo (nombre distinto, otra cuenta) y repite.
3. **Píxel y CAPI en la tienda.** El Pixel ID y el token CAPI los pega él en «Meta / Tracking» de su panel. Después:
   - `trovefy tracking tienda --producto <p-id> --pais <PAIS>` mira el píxel desde fuera, en el HTML público de la tienda, la landing y el checkout (sin ejecutar nada en el navegador).
   - Cuando diga que pegó el token: `trovefy tracking capi --producto <p-id> --pais <PAIS> --dicho "<sus palabras literales>"` (nunca el token).
   - Avísale: la CAPI de Impultienda corre en su servidor y puede mandar eventos por cualquier visita a la tienda.
4. **Eventos.** Antes de la prueba, llama a `ads_get_dataset_stats` (agregado por evento) y guarda la respuesta («antes»). Él hace la compra de prueba con `/trovefy:checkout`. Después, otra vez `ads_get_dataset_stats` («después») y `ads_get_dataset_details` del dataset, y:
   `trovefy tracking eventos --producto <p-id> --pais <PAIS> --antes <antes.json> --despues <despues.json> --detalles <detalles.json>`.
   - Purchase tiene que llegar exactamente una vez por pedido; dos es «Purchase duplicado».
   - Con la tienda de Impultienda, ViewContent no se exige: la plataforma no lo envía nunca. InitiateCheckout sí.
   - Respaldo, si el MCP no da el conteo: él pega su captura de «Probar eventos» (`trovefy checkout evidencia --producto <p-id> --pais <PAIS> --clave test-events --desde <captura>`, después de mirarla con Read) y `trovefy tracking eventos … --manual PageView=N,ViewContent=N,InitiateCheckout=N,Purchase=N --captura test-events --antes-hora <hora de la lectura «antes»>`.
5. **Límites del ejecutor.** `trovefy tracking ejecutor --producto <p-id> --pais <PAIS>` imprime lo que hace él: asignar el dataset al usuario del sistema en su navegador y los comandos `sudo -u trovefy-exec …`, que ejecuta en su terminal aparte. Cuando diga que terminó, repite la orden: lee lo que dejó el ejecutor y lo anota.
6. **UTM.** `trovefy tracking utm` da la plantilla literal para cada anuncio; enséñasela tal cual.
7. **Presentar.** Lee `productos/<p-id>/checkout/<PAIS>/TRACKING.md` y cuéntale: el dataset y su id, el estado, cada evento con su emisor y su conteo, lo que siga «no medido» con su motivo, y si el ejecutor ya lo lee. El paso 11 de `/trovefy:arranque` se verifica con `trovefy arranque verificar 11`. El cierre del país (con el checkout, la compra y el reembolso) es de `/trovefy:checkout`.
