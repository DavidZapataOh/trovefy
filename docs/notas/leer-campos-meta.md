# Campos de Meta que lee `/leer` (plan 23, Tarea 0)

**Estado: provisional.** La lista sale del plan 23 (Tarea 0, paso 2) y de la forma que entiende
`scripts/trovefy/meta/insights.py`. Falta comprobarla con `ads_get_field_context` sobre la cuenta real y sustituir las
fixtures sintéticas de `tests/fixtures/leer/` por respuestas reales saneadas (ids ficticios del contrato 11). Hasta
entonces, un campo que no aparezca con estos nombres queda «no medido»: el lector nunca lo inventa.

| Dato | Nombres que se aceptan (el primero que aparezca) | Nivel | Uso |
|---|---|---|---|
| Gasto | `amount_spent`, `spend` | conjunto, anuncio | cortes por gasto, ROAS, surf |
| Impresiones | `impressions` | conjunto, anuncio | CPM, CTR |
| Clics en el enlace | `link_click`, `inline_link_clicks`, `clicks` | conjunto, anuncio | CPC, CTR, llegada |
| Visitas | `landing_page_view` | conjunto, anuncio | 15 % de pagos iniciados (C1 54:20) |
| Pagos iniciados | `omni_initiated_checkout`, `initiated_checkout`, `offsite_conversion.fb_pixel_initiate_checkout` | conjunto, anuncio | corte por PI (si el IC es fiable) |
| Compras del píxel | `omni_purchase`, `purchase`, `offsite_conversion.fb_pixel_purchase` | conjunto, anuncio | respaldo de la tienda |
| Valor de compras | `omni_purchase_values` o `action_values` de las compras | conjunto, anuncio | solo informativo |
| Frecuencia | `frequency` | conjunto | parte |
| Estado | `effective_status` (o `status`) | campaña, conjunto, anuncio | solo se proponen cortes de lo `ACTIVE`; `DISAPPROVED`/`WITH_ISSUES` → aviso |
| Presupuesto | `daily_budget` (unidades mínimas de la cuenta) | conjunto | `de_esperado` del surf y de la base |
| Ids | `id`, `campaign_id`, `adset_id` | todos | emparejar con `paises.<PAIS>.trafico` |
| Fecha | `date_start`, `date_stop` | todos | TRM del día del gasto |
| Cuenta | `currency`, `timezone_name` (de `ads_get_ad_accounts`) | cuenta | COP y America/Bogota (P-21) |

Las métricas pueden venir planas en la fila, dentro de `insights` (objeto o `{data: [objeto]}`) o en la lista
`actions` (`{action_type, value}`). La lista de entidades se busca en `ad_entities`, `entities`, `data`, `results` o
`items` (también dentro de `structuredContent` o `result`).

Atribución pedida: 7 días clic + 1 día visualización (§4.15, resolución 16). `object_state: live` siempre.
