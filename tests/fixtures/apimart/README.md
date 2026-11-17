# Fixtures de APIMart

Respuestas reales o copiadas de la documentación oficial. El código se ajusta a esta forma: si difiere
del plan 17, manda la fixture. Ninguna lleva clave ni datos de cuenta.

| Archivo | Origen | Fecha |
|---|---|---|
| `pricing-gpt-image-2.json` | Consulta pública, **sin clave**, a `GET https://api.apimart.ai/api/pricing/model?model=gpt-image-2` (respuesta real, sin tocar) | 2026-11-16 |
| `generacion-enviada.json` | Ejemplo «200» de `POST /v1/images/generations` en https://docs.apimart.ai/en/api-reference/images/gpt-image-2/generation.md | 2026-11-16 |
| `tarea-completada.json` | Ejemplo «200 - Image Generation Task» de `GET /v1/tasks/{task_id}` en https://docs.apimart.ai/en/api-reference/tasks/status.md | 2026-11-16 |
| `tarea-en-proceso.json` | Construida con el esquema de esa misma página (`status: processing`, sin `result`); la documentación no trae el ejemplo | 2026-11-16 |
| `tarea-fallida.json` | Construida con el esquema de esa misma página (`status: failed` + `error {code, message, type}`); la documentación no trae el ejemplo | 2026-11-16 |
| `subida-imagen.json` | Ejemplo «200» de `POST /v1/uploads/images?retention_days=3` (multipart, campo `file`) en https://docs.apimart.ai/en/api-reference/uploads/images.md | 2026-11-16 |
| `png-1x1.png` | PNG de 1×1 generado con Pillow para los tests | 2026-11-16 |

## Lo que dicen las fuentes (y en qué difiere del plan)

- **Precio:** `data.resolution_paid_prices` = `{"1K": 0.0085, "2K": 0.015, "4K": 0.022}`: USD por imagen ya
  con el descuento de la cuenta (la ficha pública dice «0.085 Credits ≈ $0.0085»). Las claves van en
  mayúsculas (`1K`); la petición usa `1k`.
- **Coste real de una tarea:** `data.cost` (USD) y `data.credits_cost` (créditos). En el ejemplo, 0,15 USD =
  1,5 créditos, lo que confirma 1 crédito = 0,1 USD (`CREDITO_USD`).
- **Envío:** el `task_id` va en `data[0].task_id` (una lista, no un objeto).
- **URL del resultado:** `data.result.images[0].url[0]`.
- **Proporciones (`size`) de `gpt-image-2`:** 15, no 13: `1:1 3:2 2:3 4:3 3:4 5:4 4:5 16:9 9:16 2:1 1:2 3:1 1:3 21:9 9:21`
  (más `auto`, que no usamos). La documentación dice «4K supports the 15 ratios listed above»: las 15 admiten 4k.
- **Referencias (`image_urls`):** como mucho **15** («Up to 15 reference images, exceeding returns
  `image_urls exceeds max 15`»), no 16.
- **Errores:** cuerpo `{"error": {"code", "message", "type"}}`; 402 lleva `type: payment_required`
  (generación) o `insufficient_user_quota` (subidas).
- **Subidas:** la URL va en la raíz (`url`); con `retention_days=3` el archivo dura 72 h.
