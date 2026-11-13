# Fixtures de la Biblioteca pública de anuncios de Meta

Grabadas el **2026-11-10 (UTC)** con `uv run python -m trovefy.caza.grabar` (`scripts/trovefy/caza/grabar.py`):
Chromium de Playwright 1.65.0 sin interfaz, `chromium_sandbox=True`, **contexto efímero** (`browser.new_context()`, sin
perfil, sin sesión, sin cookies previas, sin parches de sigilo), con el candado de «un navegador a la vez» de
`trovefy.navegador`. Sin login. La interfaz salió **en español** (locale por defecto del Chromium de la máquina).

Formato de cada archivo (lo consume la Tarea 3):

```json
{"url": "...", "url_final": "...", "capturado_en": "ISO-8601 UTC", "html_final": "...",
 "respuestas": [{"url": "https://www.facebook.com/api/graphql/", "estado": 200, "cuerpo": "<texto JSON>"}]}
```

## Archivos

| Archivo | URL pedida | Capturado | Anuncios | Páginas distintas | Total que muestra Meta | Tamaño |
|---|---|---|---|---|---|---|
| `pagina_therapy_toolkit.json` | `?active_status=active&ad_type=all&country=ALL&media_type=all&search_type=page&view_all_page_id=102506312071455` | 15:48:40 | 30 (todos en `html_final`; 0 en `respuestas`) | 1 (`102506312071455`) | «~230 resultados» (`count: 234`) | 83,6 kB |
| `palabra_impultienda.json` | `?active_status=all&ad_type=all&country=ALL&media_type=all&q=impultienda.ar&search_type=keyword_unordered` | 15:50:08 | 70 (30 en `html_final` + 40 en 4 `respuestas`) | 34 en total; 26 solo en `respuestas` | «>50.000 resultados» (`count: 50001`) | 219 kB |
| `vacio.json` | `?active_status=active&ad_type=all&country=RO&media_type=all&q=zzqxv+trovefy+prueba&search_type=keyword_unordered` | 15:50:31 | 0 | 0 | «No hay ningún anuncio…» (`count: 0`) | 2,6 kB |

Todas las URLs empiezan por `https://www.facebook.com/ads/library/`. Meta redirige añadiendo
`is_targeted_country=false&sort_data[mode]=total_impressions&sort_data[direction]=desc` (queda en `url_final`).

Frente a lo que suponía el plan: la página 102506312071455 tiene ≥ 20 anuncios activos (30 grabados), **pero
todos llegan en el HTML**, no en las respuestas de datos (la página no se desplazó en esa grabación, ver abajo).
La búsqueda de `impultienda.ar` trae ≥ 10 páginas distintas (26 solo en `respuestas`, 34 contando el HTML).

## Dónde vienen los anuncios

1. **Primera página de resultados (30 anuncios): en el HTML**, dentro de un
   `<script type="application/json" … data-sjs>`. Ruta dentro de ese JSON:
   `require[0][3][0].__bbox.require[0][3][1].__bbox.result.data.ad_library_main.search_results_connection`
   (precargado por `AdLibraryFoundationRootQuery`). Ahí está también `count` (el total) y
   `"xfb_ad_library_is_captcha_required": false` como hermano de `ad_library_main`.
2. **Páginas siguientes (10 anuncios cada una): respuestas de `POST https://www.facebook.com/api/graphql/`**
   que se disparan al desplazarse. Cuerpo: un único objeto JSON (sin prefijo `for (;;);`, una sola línea) con
   `data.ad_library_main.search_results_connection` = `{"edges": [...], "page_info": {"end_cursor", "has_next_page"}}`
   (estas **no** traen `count`). También hay una respuesta `data.ad_library_main.dynamic_filter_options` (filtros,
   sin anuncios); se conserva solo cuando ninguna respuesta trae anuncios.

Cada anuncio: `edges[].node.collated_results[]` con, entre otros, `ad_archive_id`, `ad_id`, `page_id`, `page_name`,
`start_date` / `end_date` (epoch en segundos), `is_active`, `publisher_platform` (lista: `FACEBOOK`, `INSTAGRAM`, …),
`collation_id`, `collation_count`, `targeted_or_reached_countries`, `total_active_time`, `spend`, `reach_estimate`,
`currency`, y `snapshot` con `body.text`, `title`, `link_url`, `link_description`, `caption`, `cta_text`, `cta_type`,
`display_format`, `page_profile_uri`, `page_like_count`, `images`, `videos`, `cards`, `extra_texts`, etc.

## Marcadores en el texto (español)

- **Total aproximado**: elemento `role="heading"` con `~230 resultados` o `&gt;50.000 resultados`
  (es decir, `>50.000 resultados`; separador de miles «.»). En inglés sería `~1,700 results`.
- **Sin resultados**: `No hay ningún anuncio que coincida con los criterios de búsqueda` (elemento `role="heading"`),
  y en el JSON `search_results_connection` con `"count": 0, "edges": []`.

## Qué se recortó (para quedar ≤ 1 MB)

- `html_final` **no es el HTML completo** (2–3 MB): solo se conservan, en este orden y dentro de
  `<html><body>…</body></html>`,
  1. el elemento más interno cuyo texto propio es el total (`[~|>]N resultados`) o el aviso de «sin resultados», con
     sus atributos originales;
  2. los `<script type="application/json">` que contienen `ad_archive_id` o `search_results_connection`
     (uno por archivo). Su `data-content-len` es el original, previo a la redacción.
- `respuestas`: solo las de `/api/graphql/` cuyo cuerpo trae `ad_archive_id`; si ninguna los trae, las que traen
  `ad_library_main`. Se quitan desde el final mientras sobre tamaño y queden ≥ 20 anuncios (aquí no hizo falta).
- No se guardan nunca cabeceras ni cookies de peticiones o respuestas.

## Redacción aplicada (antes de escribir)

- Valores de campos JSON (normales o escapados dentro de cadenas), parámetros de URL y `<input name=… value=…>` de:
  `lsd`, `fb_dtsg`, `jazoest`, `__spin_r/__spin_t/__spin_b`, `spin_*`, `__hsi`, `hsi`, `__dyn`, `__csr`, `__rev`,
  `datr`, `_js_datr`, `sessionID`/`session_id`, `haste_session`, `end_cursor` y **cualquier campo cuyo nombre contenga
  «token»** → `"<redactado>"`.
- URLs de medios (host `scontent*` o que contenga `fbcdn`) → `"<media>"`.
- Después, `trovefy.secretos.buscar_secreto` sobre el texto completo del archivo; si encuentra algo, no se escribe.

Los textos de los anuncios (públicos) se conservan como muestra del formato.

## Incidencias de la grabación

- `detectar_bloqueo` (Tarea 1) marcaba **captcha** en todas las páginas normales porque el HTML siempre trae
  `"xfb_ad_library_is_captcha_required":false`. Las dos primeras grabaciones de la página se cortaron por eso
  (15:48:07 y 15:48:33 UTC; la segunda guardó la captura redactada para diagnóstico). Corregido en
  `caza/biblioteca.py`: solo es captcha si la clave no vale `false`. `pagina_therapy_toolkit.json` se obtuvo de esa
  segunda captura (sin desplazamiento, por eso no hay anuncios en `respuestas`); no se repitió la búsqueda para
  no pasar del presupuesto (3 búsquedas, 1 reintento cada una).
- Ningún captcha, login ni checkpoint real.
- `mcp_ads_library_search.json`: lote ficticio (IDs inventados) de respuestas del MCP oficial `ads_library_search`; la forma real está por confirmar (P-01).
