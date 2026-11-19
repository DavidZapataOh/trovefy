---
name: listo
description: >-
  Dice, con evidencia, si un producto-país se puede comprar antes de gastar: once gates (landing en el móvil, UTM hasta el checkout, compra de prueba vista en la plataforma y una sola vez en Events Manager, entrega, reembolso, dominio, dataset, creativos, caja, ejecutor y STOP), el informe en PRODUCTO.md y el paso de con_checkout a listo. Acepta las excepciones que el usuario aprobó con sus palabras, sin contarlas como verde. Nunca abre un panel ni escribe en Meta. Úsala cuando el usuario diga «listo», «¿está listo?», «gates», «¿se puede comprar?» o pase un id de producto con checkout cerrado y un país.
allowed-tools: Read, Bash(trovefy listo *), Bash(trovefy checkout excepcion *)
---

# /listo: ¿se puede comprar?

Responde siempre en español, con frases cortas y sin jerga. El usuario no es técnico. Uso: `/trovefy:listo <p-id> <PAIS>`. Ejecútala con el directorio de trabajo en el vault (`~/trovefy-cerebro`).

Reglas de fondo:

- **Nunca abras ni inicies sesión en ningún panel** (Impultienda, Meta, Hotmart, Whop). `/listo` solo lee la evidencia que dejaron `/landing`, `/tracking` y `/checkout`, y mide por HTTP público la landing.
- **Nunca escribas en Meta** ni toques la carpeta del ejecutor (`/var/spool/trovefy`). No ejecutes nada con `sudo`.
- Lo que no se pudo medir se dice «no medido: <motivo>», nunca con un número tuyo.
- Los dos STOP se nombran por separado: «STOP del cerebro» y «STOP del ejecutor».
- No arregles un gate «a mano» por otra vía: cada fallo lo arregla su skill.

## Pasos

0. **¿Estás en el cerebro?** Si no existe `config/umbrales.yaml` en el directorio de trabajo, para y pide que abra Claude en `~/trovefy-cerebro`.
1. **Evalúa:** `trovefy listo <p-id> --pais <PAIS>` (salida 0: pasa; 1: rojo; 2: error de uso o de datos). Escribe el informe en `PRODUCTO.md` (`paises.<PAIS>.listo` y una sección `## /listo · <PAIS> · <fecha>`) y una línea en `log.md`.
2. **Presenta** primero lo que falla (✗), después lo no medido (?), las excepciones (!) y por último lo verde (✓). Explica el gate de creativos así: **no aplica hasta la fase 3: aún no hay creativos**; activar anuncios exigirá su revisión y los once gates en verde (`--para-activar`).
3. **Excepciones.** Una excepción es la aprobación del usuario, con sus palabras literales, de seguir sin un gate en verde. **Nunca cuenta como verde**: el informe la marca con «!» y el país puede pasar a `listo` con ella. Son las mismas del cierre del checkout (`productos/<p-id>/decisiones/<fecha>-excepcion-<clave>.md`): una ya aprobada allí vale aquí si el gate mide lo mismo.
   - `reembolso` → «reembolso registrado» (la misma del cierre).
   - `dataset` → «tracking verificado» (la misma del cierre), solo para los eventos de `TRACKING.md`; un dataset compartido, mal nombrado o con dos emisores no se excusa.
   - `utm_checkout` → «utm hasta el checkout» (solo de `/listo`).
   - `dominio` → «dominio verificado» (solo de `/listo`).
   - **No admiten excepción:** `compra` (vista en la plataforma y una sola vez en Events Manager), `entrega`, `landing_movil`, `creativos`, `caja`, `ejecutor` y `stop`.
   - Solo si el usuario la pide él, con sus palabras, en un mensaje aparte: `trovefy checkout excepcion --producto <p-id> --pais <PAIS> --requisito "<requisito>" --dicho "<su mensaje entero>" --motivo "<por qué no está en verde>"`. Tú nunca la propones como atajo ni escribes sus palabras por él. Después repite el paso 1.
4. **Para cada fallo, di qué skill lo arregla:** `/landing` → landing en el móvil y UTM; `/checkout` → compra, entrega y reembolso; `/tracking` → dataset y Events Manager; `/caja` → hueco de test; `/aprobaciones estado` → ejecutor y STOP. Dominio: el paso 08 se toma tal como está (su verificador lee un panel con sesión y ya no se ejecuta); si la landing no está en el dominio del paso 07, publícala ahí con `/landing` o pide su excepción.
5. **Con todo en verde (o con sus excepciones),** di que el producto-país queda `listo` y que lo siguiente es la fase 3 (`/creativos`, `/montar`). Si volvió a pasar `/listo` estando ya en `listo` y algo se rompió, el estado no retrocede, pero dile que no se puede activar hasta arreglarlo.
