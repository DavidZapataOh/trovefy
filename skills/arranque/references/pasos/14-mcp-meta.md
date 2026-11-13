# 14 · MCP de Meta Ads

**Objetivo**
Conectar el servidor MCP oficial de Meta Ads a Claude Code y registrar sus herramientas para que cada una tenga permiso explícito.

**Antes de empezar**
- Paso 13 verificado. Una terminal de Ubuntu (WSL) **aparte** para `claude mcp add`.
- El inicio de sesión (OAuth) lo haces tú; Claude no escribe contraseñas.
- Mientras no se importan las herramientas, el hook `meta_guard` para toda herramienta de Meta que no sea de lectura conocida: aunque se quite el deny general de la fase 0, nada escribe en Meta.

**Pasos**
1. En la terminal aparte, entra al vault: `cd ~/trovefy-cerebro`
2. Ahí mismo añade el servidor (la dirección sale de la documentación de Meta para su MCP de anuncios; confírmala allí antes de pegarla): `claude mcp add --transport http meta-ads https://mcp.facebook.com/ads`
3. Claude ejecuta `trovefy meta herramientas preparar`: quita el deny general de la fase 0 (`mcp__meta-ads__ads_*`) para que Claude pueda ver las herramientas; lo de escritura lo sigue parando `meta_guard`.
4. Cierra y abre Claude Code (en `~/trovefy-cerebro`) para que cargue el servidor y los permisos.
5. En Claude Code escribe `/mcp`, elige meta-ads y completa el OAuth en el navegador.
6. Pide solo lectura si la pantalla lo deja (P-02) y regístralo: `trovefy arranque hecho 14 --dato oauth=lectura` (o `oauth=completo` si no dejó elegir).
7. Claude vuelca las herramientas que ve del servidor (nombre, descripción e `inputSchema` tal cual, sin inventar) en `data/meta/tools_list-<AAAA-MM-DD>.json`.
8. Claude ejecuta: `trovefy meta herramientas importar data/meta/tools_list-<AAAA-MM-DD>.json --servidor meta-ads`. Cada herramienta queda con su nombre exacto: las de lectura en `allow` y el resto en `deny`.
9. Cierra y abre Claude Code otra vez para que cargue los permisos definitivos.
10. Pide la verificación: `trovefy arranque verificar 14`

**Errores típicos**
- Síntoma: `/mcp` no lista meta-ads. Arreglo: repite los pasos 1 y 2 (el servidor se añade con el vault como carpeta actual) y reinicia Claude Code.
- Síntoma: Claude no ve las herramientas de meta-ads tras el OAuth. Arreglo: repite el paso 3 y reinicia Claude Code (paso 4).
- Síntoma: el OAuth falla o pide verificación. Arreglo: complétala tú en el navegador y repite el paso 5.
- Síntoma: «nombre de servidor MCP no válido». Arreglo: usa un nombre con solo letras, números, «_» o «-» (por ejemplo `meta-ads`).
- Síntoma: «falta config/meta_tools.json o no trae herramientas». Arreglo: haz los pasos 3 a 8 (preparar, volcado e importación).
- Síntoma: «config/meta_tools.json no se puede leer». Arreglo: repite el paso 7 con el volcado tal cual y el paso 8.
- Síntoma: «permissions.deny no está al día: faltan …». Arreglo: repite el paso 8, que regenera permissions.deny con los nombres exactos; una herramienta nueva o renombrada se deniega hasta revisarla.
- Síntoma: «.claude/settings.json falta o no se puede leer; no se toca». Arreglo: abre Claude Code una vez en el vault y repite el paso 8.
- Síntoma: «permissions.deny bloquea lecturas (…)». Arreglo: si la regla la añadiste tú, quítala de `.claude/settings.json`; si no, repite el paso 8.
- Síntoma: «OAuth: no medido (P-02)». Arreglo: registra lo que elegiste con el paso 6.
- Síntoma: «/cazar no podrá usar el MCP (falta ads_library_search)». Arreglo: no es un fallo; /cazar seguirá con la Biblioteca de anuncios web.

**Cómo se verifica**
`trovefy arranque verificar 14` lee `config/meta_tools.json` y `.claude/settings.json`: comprueba que todas las herramientas de escritura del servidor están en `permissions.deny` con su nombre exacto (un comodín no cuenta), que ninguna de lectura queda tapada y anota el OAuth del paso 6. Deja la evidencia en `config/evidencia/`.
