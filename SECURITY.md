# Seguridad

## Cómo se manejan los secretos

- Los secretos (por ejemplo, `FIRECRAWL_API_KEY`) viven solo en `~/.config/trovify/*.env`, fuera de este repositorio y fuera del vault.
- Trovify exige que esos archivos tengan permisos `0600`, que sean archivos regulares del usuario y que no sean enlaces simbólicos; si no, se niega a leerlos.
- Los valores nunca se imprimen, ni se guardan en el vault, ni aparecen en mensajes de error. En el vault solo se anota *dónde* está cada secreto.
- Los perfiles de navegador por servicio (`~/.config/trovify/pw-<servicio>/`) se crean con modo `0700`. El usuario inicia sesión él mismo; Trovify no escribe contraseñas ni lee códigos 2FA.
- `.gitignore` excluye `*.env` y `.env*`.

## Qué imponen los hooks

Los hooks de `hooks/` se ejecutan antes de cada herramienta de Claude Code, usan solo la biblioteca estándar de Python y **fallan cerrados** (ante una entrada ilegible, deniegan):

| Hook | Evento | Qué impide |
| --- | --- | --- |
| `meta_guard.py` | PreToolUse | Cualquier escritura en Meta (MCP, `Bash` o `WebFetch` hacia la Graph API). Solo se permiten lecturas. |
| `secretos.py` | PreToolUse | Escribir tokens o claves (Meta, bot de Telegram, `sk-…`, Firecrawl, `access_token=`…) fuera de los `.env`. El motivo nombra el patrón, nunca el valor. |
| `raw_inmutable.py` | PreToolUse | Modificar o borrar fuentes de `raw/`, o reescribir `log.md` (solo se amplía). |
| `stop.py` | PreToolUse | Con `<vault>/.trovify/STOP`, depositar nada en el buzón o en `propuestas/`. |
| `contexto.py` | SessionStart | Informativo: resume el cerebro. Nunca bloquea. |
| `cierre_sesion.py` | Stop | Informativo: recuerda cerrar la sesión. Nunca bloquea. |

Además, `trovify cerebro permisos` escribe en el vault un `.claude/settings.json` que deniega las herramientas de escritura en Meta.

## Cómo informar de una vulnerabilidad

No abras un issue público. Usa el informe privado de vulnerabilidades de GitHub:

1. Ve a la pestaña **Security** del repositorio.
2. Pulsa **Report a vulnerability**.
3. Describe el problema, cómo reproducirlo y su impacto.

Responderemos por ese mismo canal. Agradecemos los informes responsables.
