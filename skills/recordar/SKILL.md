---
name: recordar
description: Convierte una corrección del usuario (o el motivo de un Rechazar) en una regla fechada R-nnn del cerebro, actualiza los umbrales y detecta contradicciones con las reglas vigentes. Úsala cuando el usuario diga «recuerda que…», corrija una decisión o quiera cambiar un umbral.
allowed-tools: Read, Bash(trovify cerebro regla *), Bash(trovify cerebro lint *), Bash(trovify cerebro lint)
---

# /recordar: de corrección a regla fechada

Responde siempre en español. Una regla nueva solo se escribe tras la confirmación explícita del usuario en esta sesión.

1. **Redacta la regla con el usuario.** Reúne cuatro cosas: la regla (una frase), por qué, cómo se aplica y la fuente literal (lo que dijo el usuario o el motivo del Rechazar, con la fecha). Si la regla cambia un número, identifica la clave en `config/umbrales.yaml` (léela con Read) y el valor nuevo. No inventes motivos ni fuentes.
2. **Muéstrala y pide confirmación.** Presenta el borrador completo (título, regla, por qué, cómo, fuente, umbrales). No sigas sin un «sí» claro.
3. **Guárdala.** Pasa el JSON por stdin, sin crear archivos:

   ```
   trovify cerebro regla --json - <<'JSON'
   {"titulo": "…", "regla": "…", "porque": "…", "como": "…", "fuente": "…",
    "umbrales": {"clave.del.umbral": 20}, "reemplaza": []}
   JSON
   ```

   `umbrales` y `reemplaza` son opcionales. El comando imprime la ruta de la página nueva.
4. **Si sale con código 3**, imprime los ids de las reglas vigentes que chocan. Léelas (Read en `wiki/reglas/`), muéstraselas al usuario y pregunta cuál manda. Si manda la nueva, no la reescribas a escondidas: dilo.
5. **Repite con `reemplaza`** (por ejemplo `"reemplaza": ["R-006"]`) solo cuando el usuario haya dicho que la nueva sustituye a la vieja. La vieja queda como «reemplazada», no se borra.
6. **Comprueba el cerebro** con `trovify cerebro lint` y cuéntale al usuario el resultado. Si el comando sale con código 2, explica el mensaje de error y corrige el JSON.
