---
name: montar
description: >-
  Monta el test del producto-país como en los vídeos: la tanda aprobada de /creativos pasa a una campaña ABO de 5 conjuntos × 1 anuncio × US$ 5/día (en la moneda de la cuenta, con la TRM del día), techo de US$ 100 y plazo de 1 semana, objetivo Ventas, país e idioma locales, Audience Network y Threads fuera, solo el catálogo apagado y salida a las 00:00. Todo lo crea el ejecutor en PAUSED, primero con validate_only, lo relee y lo audita; tú lo activas con un toque en Telegram («Activar campaña», con miniaturas). También registra la activación (listo → montado → test), el veto si rechazas y la renovación cada 48 h en la misma ABO. Nunca escribe en Meta. Úsala cuando el usuario diga «montar», «montar la campaña», «lanzar el test», «activar» o pase un id de producto listo con su tanda.
allowed-tools: Read, Bash(trovefy montar *), Bash(trovefy listo *), Bash(trovefy caja ver), Bash(trovefy aprobaciones estado), Bash(trovefy economia ver), mcp__meta-ads__ads_get_ad_accounts, mcp__meta-ads__ads_get_ad_entities
---

# /montar: el test en PAUSED y «Activar» con un toque

Responde siempre en español, con frases cortas y sin jerga. El usuario no es técnico. Uso: `/trovefy:montar <p-id> <PAIS> [tN]`. Ejecútala con el directorio de trabajo en el vault (`~/trovefy-cerebro`).

**Qué hacen los vídeos:** «5 conjuntos · 1 anuncio c/u · $5 por anuncio · Techo $100 · Plazo 1 semana» (C1 0:18:10); el admin monta en pausa y lo prende el dueño (C1 0:51:00); salida a las 00:00 (L1 0:58:29); renovaciones cada 48 h en la misma ABO (T3 18:55, T3 19:55).

Reglas de fondo:

- **Nunca escribas en Meta.** Toda escritura la hace el ejecutor sobre una propuesta; tú solo usas `trovefy montar`. De Meta solo lees con las herramientas de lectura de arriba.
- **Nunca toques `/var/spool/trovefy`** sino con la CLI. Nada con `sudo`: si hace falta, imprime el comando exacto y espera a que lo ejecute el usuario.
- **No reintentes un montaje fallido o parcial sin la palabra del usuario.** Lo creado queda en PAUSED y nunca se borra.
- Lo no medido se dice «no medido: <motivo>», nunca con un número tuyo.
- El montaje en PAUSED no gasta: no pide un «sí». Lo que gasta («Activar campaña») pide su Aceptar en Telegram.

## Pasos

0. **¿Estás en el cerebro?** Si no existe `config/umbrales.yaml` en el directorio de trabajo, para y pide que abra Claude en `~/trovefy-cerebro`.
1. **Prepara:** `trovefy montar preparar --producto <p-id> --pais <PAIS> --tanda <tN>` (sin `--tanda`, la vigente de `paises.<PAIS>.creativos.vigente`). Si sale 1, explica cada ✗ y quién lo arregla, y para:
   - economía (BE no medido) → el paso 0 de la fase (`trovefy economia ver`);
   - una excepción de `/listo` no admitida para activar → pregunta al usuario con sus palabras; si la admite, `trovefy montar excepcion --producto … --pais … --gate <gate> --cita "<sus palabras literales>" --motivo "…"`;
   - dataset viejo → el comando `sudo -u trovefy-exec …` que imprime la CLI, para que lo ejecute el usuario;
   - un límite del ejecutor que recorta el techo de US$ 100 → la propuesta `limite_ejecutor` (la acepta el usuario en Telegram);
   - falta el DSA en `config/montar.yaml` (países de la UE) → pregunta el nombre del beneficiario y del pagador tal como figuran en Meta.
2. **Enseña el resumen en seco entero** (cuenta enmascarada, campaña, 5 × presupuesto, techo y plazo, país, idioma, sexo, ubicaciones fuera, salida en Bogotá y en el país, y cada anuncio con su texto). Di que todo se crea en PAUSED y que gastar pedirá su Aceptar en Telegram.
3. **Valida:** `trovefy montar validar …` (validate_only de Meta, no crea nada). Espera el resultado: `trovefy montar estado …` cada 30–60 s, como mucho 10 min; si no llega, «el ejecutor no respondió: mira `trovefy aprobaciones estado`». Si Meta rechaza el `spend_cap` de US$ 100 por un mínimo mayor, apunta el mínimo y para (desvío D1).
4. **Monta:** `trovefy montar depositar …`; espera igual y luego `trovefy montar registrar --producto … --pais …`. Enseña el histórico (`trafico/<PAIS>/historico-<campaña>.md`).
5. **Explica el mensaje de Telegram:** primero el álbum con las miniaturas y después «Activar campaña» con Aceptar y Rechazar; caduca en 24 h; la campaña sale a las 00:00 de la cuenta. Rechazar con un motivo es el veto de los creativos: queda en `VETO-<id>.md` y `/trovefy:creativos --rehacer` reabre la misma tanda. Si caducó, `trovefy montar activar …` la propone de nuevo.
6. **Tras el Aceptar:** `trovefy montar registrar …` pasa el país a `test` y abre el test vivo en `config/caja.yaml`.

`--renovacion [--rutina]` (cada 48 h con el test vivo, T3 18:55): tras cerrar la tanda de renovación en `/trovefy:creativos --renovar`, `trovefy montar renovacion --producto … --pais … --tanda tN` y luego `--paso validar` y `--paso depositar`, como arriba. Las piezas nuevas van en conjuntos nuevos de la misma ABO a US$ 5/día; «Activar» llega por Telegram. No se renueva si venció el plazo de 1 semana o se gastó el techo.

`--rutina`: solo `trovefy montar registrar --pendientes`, sin preguntas.
