# 01 · Cerebro

**Objetivo**
Tener el cerebro (la carpeta de Obsidian con el método y las reglas) construido, ordenado y comprobado con preguntas de control.

**Antes de empezar**
- Paso 00 verificado.
- El vault en `~/trovify-cerebro` con el método ya destilado en `wiki/metodo/`.
- Abre la terminal dentro del vault.

**Pasos**
1. Comprueba el orden del vault: `trovify vault lint`. Si señala algo, corrígelo con Claude y repite hasta que no haya problemas.
2. Comprueba que existen páginas del método en `wiki/metodo/`. Si no las hay, destílalas con `/trovify:destilar`.
3. Pasa los canarios, que son preguntas de control cuya respuesta Claude debe sacar solo del cerebro: `trovify cerebro canarios` (dentro del vault).
4. Si algún canario falla, corrige la página del cerebro que corresponde o su cita y repite el paso 3.
5. Los canarios valen 30 días: pasado ese tiempo hay que repetirlos.

**Errores típicos**
- Síntoma: «el vault tiene N problemas de lint». Arreglo: `trovify vault lint` y corrige lo que señala.
- Síntoma: «no hay resultado de canarios». Arreglo: corre `trovify cerebro canarios` dentro del vault.
- Síntoma: «no hay páginas del método». Arreglo: `/trovify:destilar`.
- Síntoma: «problemas en wiki/metodo/». Arreglo: corrige las citas y fuentes de esas páginas.
- Síntoma: «los canarios son de hace más de 30 días» o «el sha del canarios.yaml cambió». Arreglo: vuelve a correr `trovify cerebro canarios`.

**Cómo se verifica**
`trovify arranque verificar 01` comprueba que el vault no tiene problemas de lint, que hay páginas válidas del método con sus citas, y que el último resultado de canarios (`data/canarios/ultimo.json`) es de los últimos 30 días, cubre exactamente los canarios actuales y los pasa todos. Deja la evidencia en `config/evidencia/`.
