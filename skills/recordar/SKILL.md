---
name: recordar
description: Convierte una corrección del usuario (o el motivo de un Rechazar) en una regla fechada R-nnn del cerebro, actualiza los umbrales y detecta contradicciones con las reglas vigentes. Úsala cuando el usuario diga «recuerda que…», corrija una decisión o quiera cambiar un umbral.
allowed-tools: Read, Bash(trovefy cerebro regla *), Bash(trovefy cerebro lint)
---

# /recordar: de corrección a regla fechada

Responde siempre en español. Una regla nueva solo se escribe tras la confirmación explícita del usuario en esta sesión.

1. **Redacta la regla con el usuario.** Reúne cuatro cosas: la regla (una frase), por qué, cómo se aplica y la fuente literal (lo que dijo el usuario o el motivo del Rechazar, con la fecha). Si la regla cambia un número, identifica la clave en `config/umbrales.yaml` (léela con Read) y el valor nuevo. No inventes motivos ni fuentes.
2. **Muéstrala.** Presenta el borrador completo (título, regla, por qué, cómo, fuente, umbrales).
3. **Busca contradicciones antes de simular, también las que no tienen clave numérica.** Lee el CLAUDE.md del cerebro (las reglas duras y el bloque «Reglas aprendidas») y las páginas R-nnn relacionadas con Read. Si la regla nueva contradice alguna de ellas, aunque no comparta una clave de `umbrales`, muestra el choque al usuario y pregunta cuál manda; no sigas hasta tener su respuesta. PU-01 (R-006, el corte de oferta sin ventas) solo se reabre por una decisión explícita del usuario.
4. **Simula.** Pasa el JSON por stdin, sin crear archivos, con `--simular` (valida todo y no escribe nada):

   ```
   trovefy cerebro regla --simular --json - <<'JSON'
   {"titulo": "…", "regla": "…", "porque": "…", "como": "…", "fuente": "…",
    "umbrales": {"clave.del.umbral": 20}, "reemplaza": []}
   JSON
   ```

   `umbrales` y `reemplaza` son opcionales. Muestra al usuario exactamente la salida: el id nuevo, los archivos que cambian, los valores de umbral que cambian, las páginas cuyo valor citado se actualiza («Se actualiza el valor citado en R-009, R-010») y las líneas «R-nnn pasa a ser dueña de <clave> (valor sin cambios)» (umbrales heredados de la regla reemplazada). Pide confirmación explícita; solo entonces ejecuta el mismo comando **sin** `--simular`, que escribe y repite el resumen y la ruta.
5. **Si sale con código 3**, imprime los ids de las reglas vigentes que chocan. Léelas (Read en `wiki/reglas/`), muéstraselas al usuario y pregunta cuál manda. Si manda la nueva, no la reescribas a escondidas: dilo.
6. **Repite (simulación y luego real) con `reemplaza`** (por ejemplo `"reemplaza": ["R-006"]`) solo cuando el usuario haya dicho que la nueva sustituye a la vieja. La vieja queda como «reemplazada», no se borra.
7. **Comprueba el cerebro** con `trovefy cerebro lint` y cuéntale al usuario el resultado. Si el comando sale con código 2, explica el mensaje de error y corrige el JSON.
