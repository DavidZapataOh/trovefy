---
name: cerrar
description: Cierra la sesión dejando todo guardado. Resume lo hecho, lo pendiente, las decisiones del usuario y los archivos tocados; comprueba que existen y que el cerebro pasa el lint, y escribe el traspaso en sesiones/. Úsala cuando el usuario diga «cerremos», «me voy» o «déjalo guardado», o cuando el recordatorio de fin de sesión lo pida.
allowed-tools: Read, Bash(trovify cerebro *)
---

# /cerrar: que mañana arranques en 15 segundos

Responde siempre en español. Es una nota para el usuario de mañana: corta y concreta.

1. **Reúne cuatro listas** de lo que pasó en esta sesión:
   - `hecho`: lo que quedó terminado, cada punto con su archivo.
   - `pendiente`: lo que quedó a medias o por hacer; el primer punto es el próximo paso exacto.
   - `decisiones`: lo que el usuario decidió, con sus palabras literales y no resumidas.
   - `archivos`: rutas relativas al vault de cada archivo creado o cambiado.

   No inventes nada. Si no hubo decisiones, la lista va vacía.
2. **Verifica antes de decir «listo» (regla 17).** Con Read, comprueba que cada archivo de `archivos` existe en el vault y tiene el contenido que dices. Después ejecuta `trovify cerebro lint`. Si falta un archivo o el lint informa problemas (enlaces rotos, páginas huérfanas, frontmatter incompleto), dilo tal cual, corrígelos con el usuario o déjalos anotados en `pendiente`. No digas «listo» con problemas sin resolver.
3. **Muestra el borrador** de las cuatro listas y pide confirmación del usuario.
4. **Escribe el traspaso** pasando el JSON por stdin:

   ```
   trovify cerebro traspaso --json - <<'JSON'
   {"hecho": ["…"], "pendiente": ["…"], "decisiones": ["…"], "archivos": ["…"]}
   JSON
   ```

   Imprime la ruta `sesiones/AAAA-MM-DD-HHMM.md`.
5. **Cierra con una línea**: la ruta del traspaso y «Mañana: `/trovify:retomar`».
