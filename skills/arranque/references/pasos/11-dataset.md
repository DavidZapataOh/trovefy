# 11 · Dataset/píxel

**Objetivo**
Que el producto-país tenga su dataset (el píxel) en Meta, con el nombre exacto «MARCA PAÍS», y que tu tienda de Impultienda lo cargue: sin él no se puede medir ninguna venta ni lanzar anuncios.

**Antes de empezar**
- Es un paso de la fase 2: llega cuando el país ya tiene la landing publicada (`con_landing`). Antes no hay nada que medir.
- Este paso no se hace desde `/arranque`: lo guía **`/trovefy:tracking`**, que sabe el nombre exacto del dataset y lo que va en cada sitio. Lánzala con el p-id y el país.
- El dataset lo creas tú en Meta y el Pixel ID y el token CAPI los pegas tú en tu panel de Impultienda (`https://impultienda.ar/login`), en tu navegador. Claude no abre ningún panel, no inicia sesión y nunca escribe en Meta.
- El token CAPI lo generas y lo pegas tú. Nunca se lo pases a Claude ni le mandes una captura donde se vea.

**Pasos**
1. Ejecuta `/trovefy:tracking <p-id> <PAÍS>` y sigue sus pasos.
2. Claude te da el nombre exacto del dataset (`trovefy tracking preparar`). Créalo tú en Meta con ese nombre.
3. Claude lo busca por el MCP de Meta, solo lectura (`trovefy tracking dataset`), y te dice su id.
4. Pega tú el Pixel ID y el token CAPI en «Meta / Tracking» de tu panel de Impultienda.
5. Claude mira desde fuera que tu tienda carga ese píxel (`trovefy tracking tienda`).
6. Los comandos del ejecutor (`sudo -u trovefy-exec …`) para meter el dataset y la página en sus límites los ejecutas tú en una terminal de Ubuntu (WSL) **aparte**, sin `!`. Claude te los da con `trovefy tracking ejecutor`.
7. Cuando `/trovefy:tracking` diga que el píxel está puesto, pide la verificación: `trovefy arranque verificar 11`.

**Errores típicos**
- Síntoma: «no medido: aún no hay TRACKING.md». Arreglo: el producto-país todavía no pasó por `/trovefy:tracking`; empieza por el paso 1.
- Síntoma: «falta el dataset de …». Arreglo: crea el dataset en Meta con el nombre exacto que te dio Claude y repite el paso 3.
- Síntoma: «el píxel aún no está visto en tu tienda». Arreglo: pega el Pixel ID en «Meta / Tracking» de tu panel, guarda y repite el paso 5.
- Síntoma: el motivo dice «no medido: ViewContent no llegó». Arreglo: con la tienda de Impultienda ya no se pide (la plataforma no envía ViewContent); vuelve a pasar los eventos con `/trovefy:tracking`.
- Síntoma: el motivo dice «no medido: InitiateCheckout no llegó». Arreglo: no bloquea este paso; sí bloquea el cierre del checkout hasta que llegue o hasta que tú apruebes una excepción con tus palabras.

**Cómo se verifica**
`trovefy arranque verificar 11` lee `productos/*/checkout/*/TRACKING.md` (sin red, sin navegador y sin ningún panel): da el paso por bueno si un producto-país tiene el dataset con su id y el píxel visto en la tienda (estado `configurado` o `verificado`), y dice lo que siga «no medido». Deja el id del dataset en los datos del paso (lo usa el ensayo general) y la evidencia en `config/evidencia/11-dataset-<fecha>.json`.
