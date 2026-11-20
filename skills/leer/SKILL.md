---
name: leer
description: >-
  Lee el test del producto-país como en los vídeos y propone los movimientos: parte diario (07:30, día cerrado) e intradía cada 2 h, de día y de noche, con la tabla por conjunto (gasto, ROAS neto, CPM, CTR, CPC, visitas y pagos iniciados, estado y por qué); cortes propuestos (conjunto con US$ 3 sin pagos iniciados, CPC > US$ 0,60 o menos del 15 % de pagos iniciados sobre visitas; campaña sin ventas a los US$ 25; con ventas, tras 72 h con ROAS neto < 1,4; plazo de 1 semana); surf (×2 con ROAS ≥ 2 y ventas nuevas, −50 % con ROAS ≤ 1,75) y todo a la base a las 23:00 del país; fiabilidad del dato y diagnóstico por etapa. Solo lee Meta y la tienda; cada pausa o cambio de presupuesto es una propuesta que aceptas o rechazas en Telegram. Úsala cuando el usuario diga «leer», «parte», «cómo va el test», «qué apago» o «surf». Con --rutina la lanzan los timers, sin preguntas.
allowed-tools: Read, Write(~/.cache/trovefy/leer/**), Bash(trovefy leer *), Bash(trovefy montar registrar *), Bash(trovefy economia ver), Bash(trovefy economia fijar *), Bash(trovefy modelar recalcular *), mcp__meta-ads__ads_get_ad_accounts, mcp__meta-ads__ads_get_field_context, mcp__meta-ads__ads_get_ad_entities, mcp__meta-ads__ads_get_dataset_stats, mcp__impultienda__impultienda_listar_tiendas, mcp__impultienda__impultienda_listar_ventas, mcp__impultienda__impultienda_campanas_utm, mcp__impultienda__impultienda_carritos_abandonados, mcp__impultienda__impultienda_estadisticas, mcp__impultienda__impultienda_ver_plan, mcp__impultienda__impultienda_faq, mcp__impultienda__impultienda_conocimiento
---

# /leer: el parte, los cortes y el surf, como en los vídeos

Responde siempre en español, con frases cortas y sin jerga. El usuario no es técnico. Uso: `/trovefy:leer [--parte | --intradia --pais XX | --base --pais XX] [--rutina]`. Ejecútala con el directorio de trabajo en el vault (`~/trovefy-cerebro`).

**Qué hacen los vídeos:** «Claude lee tus campañas todos los días» y responde con la tabla por conjunto, el número puesto y el motivo (C1 54:20). Apaga a los US$ 3 sin pagos iniciados o con CPC > US$ 0,60 (C1 20:05) o con menos del 15 % de pagos iniciados sobre visitas (C1 54:20); mata la oferta sin ventas a los US$ 25 (C1 1:24:15); aguanta 72 h lo que vende (T3 11:22); surfea ×2 cada 2 h con ROAS ≥ 2 y ventas nuevas (S1 10:27, T3 12:35), −50 % con ROAS ≤ 1,75 (S2 14:10) y a las 23:00 del país todo a la base (S2 14:40).

Reglas de fondo:

- **Nunca escribas en Meta.** Solo lees con las herramientas de arriba. Toda pausa o cambio de presupuesto lo deposita `trovefy leer` como propuesta, y solo el ejecutor lo aplica tras el Aceptar del usuario en Telegram. Las `next_actions` de Meta con `requires_user_confirmation: true` no se llaman nunca.
- **Nunca toques `/var/spool/trovefy`** sino con la CLI. Nada con `sudo`.
- **Respuestas crudas fuera del vault:** cada lectura de un MCP la guardas tal cual en `~/.cache/trovefy/leer/<p-id>/<PAIS>/<fuente>-<AAAAMMDDTHHMM>.json`. Al vault solo pasan números, ids y nombres, y eso lo hace la CLI.
- Lo no medido se dice «no medido: <motivo>», nunca con un número tuyo. Nada de datos de compradores.
- Ningún id real en lo que escribas fuera del vault (ni en el chat de otras personas): las cuentas salen enmascaradas.

## Pasos

0. **¿Estás en el cerebro?** Si no existe `config/umbrales.yaml` en el directorio de trabajo, para y pide que abra Claude en `~/trovefy-cerebro`. ¿Existe `.trovefy/STOP`? Entonces lees y escribes el parte, pero no se deposita nada: dilo.
   - `trovefy leer completar` (una vez por versión: añade los umbrales nuevos sin tocar los tuyos).
   - `trovefy montar registrar --pendientes` (resolución 12: recoge una activación aceptada fuera de la sesión).
   - ¿Hay país en `test` o `candidato`? Si no, di «no hay test vivo» y termina.
   - `trovefy leer economia --producto <p-id> --pais <PAIS>`. Si sale 1 (comisiones sin fijar): en sesión, **para y guía el paso 0** de abajo; con `--rutina`, sigue (los cortes por gasto no necesitan comisiones) y la CLI deja una alerta «falta fijar la economía».
1. **Qué leer:** `trovefy leer preparar --producto <p-id> --pais <PAIS> [--intradia]` te dice la ventana (de `t0` al día cerrado, o hoy en la ronda) y el archivo de cada lectura. Haz esas llamadas, todas de lectura:
   - Meta: `ads_get_ad_accounts` (moneda y zona de la cuenta, una vez por sesión); `ads_get_ad_entities` nivel `adset` y nivel `ad` de la campaña, `object_state: live`, con los campos de `docs/notas/leer-campos-meta.md` del repo y atribución 7 días clic + 1 día visualización; y nivel `adset` solo del día leído (`meta-dia`).
   - Tienda: `impultienda_listar_tiendas` (el `store_id`), `impultienda_campanas_utm` nivel `anuncio` de la ventana y del día leído, nivel `campana` de la ventana, e `impultienda_carritos_abandonados` de la ventana.
   Guarda cada respuesta en su archivo (permisos 0600).
2. **Normaliza:** `trovefy leer importar --producto … --pais … [--intradia] --meta-adset <archivo> --meta-ad <archivo> --meta-dia <archivo> --utm-campana <archivo> --utm-anuncio <archivo> --utm-dia <archivo> --carritos <archivo>`.
3. **Decide y propone:**
   - Parte de la mañana: `trovefy leer parte --producto … --pais …`.
   - Ronda de cada 2 h: `trovefy leer intradia --producto … --pais …` (cortes por gasto y surf; nunca mata una oferta con ventas).
   - 23:00 del país: `trovefy leer base --producto … --pais …` (todos los conjuntos a la base).
   Para probar sin depositar nada: `--seco`. `trovefy leer estado …` aplica lo que ya ejecutó el ejecutor (pausa ejecutada → `muerto`, con su enlace al parte; presupuesto ejecutado → surf vivo).
4. **Enséñaselo al usuario** (en sesión): primero las propuestas depositadas («te llegó a Telegram P-…: pausar 2 conjuntos»; «P-…: ×2 a AD03, ROAS 2,6 y una venta nueva»), después la tabla, la fiabilidad y lo no medido, y los avisos del diagnóstico (van a `/creativos`, `/landing` o `/checkout`; `/leer` no toca la campaña por ellos). Recuerda: **se aceptan o rechazan en Telegram**; tú no pausas ni subes nada.
5. **Si la tienda no responde por el MCP** (plan Free tras el 2026-12-28): pide al usuario el número de ventas del día de la campaña (lo ve en su panel, en su navegador) o una captura, y anótalo con sus palabras como `fuente: dicho` o `captura`; sin eso, las ventas son «no medido» y la fiabilidad baja.

## Paso 0 de la fase: fijar la economía (una sola vez, la decide el usuario)

Sin comisiones no hay ROAS neto, y sin ROAS neto no hay surf ni corte con ventas. Tú no inventas ninguna comisión:

1. Lee con `impultienda_ver_plan`, `impultienda_faq` e `impultienda_conocimiento` (solo lectura) el plan, la comisión de la tienda y la de Impul Pay. Enséñale una tabla «clave · valor que leíste · de dónde sale» para `ruta_activa` (`impultienda_whop`) y `plataformas.impultienda.{comision_pct, comision_fija_usd, impuestos_pct}` y `plataformas.whop.{…}`. Lo que no salga de ninguna lectura queda «no medido»: el usuario lo mira en la página oficial de precios, en su navegador, y te lo dicta.
2. Solo con su «sí» literal: `trovefy economia fijar --clave <clave> --valor <v> --fuente "<URL oficial>; <herramienta> <fecha>; confirmado por el usuario: «…»"` (la fuente de `plataformas.*` empieza por la URL oficial). Anota que son las del plan Max en prueba: el 2026-12-28 se vuelven a leer.
3. `trovefy modelar recalcular --producto <p-id>` y `trovefy economia ver`; comprueba en `ESCALERA.md` que `cpa_be_usd` ya tiene número.

## Lo que queda distinto de los vídeos

- **Pagos iniciados sin InitiateCheckout (desvío D1):** mientras el dataset no reciba InitiateCheckout, los pagos iniciados del píxel por anuncio no apagan solos y el anuncio se juzga por el CPC; el parte dice «PI del píxel no fiable». En cuanto Meta registre un IC real, la rama vuelve sola. Se quita arreglando el IC (L2 0:19:45).
- **Gasto en COP:** se pasa a USD con la TRM del día del gasto (Banco de la República), al alza; sin TRM, «no medido» y no se propone nada por importe.

## `--rutina`

Sin preguntas: paso 0 (sin guiar la economía), las lecturas del paso 1, `importar` y el comando del modo (`parte`, `intradia` o `base`) con `--rutina`. La CLI deja el log en `rutinas/log/<día>/`. Si un MCP no responde, no inventes: la CLI sale con 2 y la rutina queda «parada».
