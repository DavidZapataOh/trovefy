# 01 · Cerebro

**Objetivo**
Tener el cerebro (la carpeta de Obsidian con el método y las reglas) construido, ordenado y comprobado con preguntas de control.

**Antes de empezar**
- Paso 00 verificado.
- El vault en `~/trovify-cerebro` con el método ya destilado en `wiki/metodo/`.
- Abre la terminal dentro del vault.

**Pasos**
1. Abre la terminal de Ubuntu (WSL) y escribe `whoami`: lo que responde es tu `<tu-usuario>`. WSL tiene que estar en marcha (la terminal de Ubuntu abierta).
2. Abre Obsidian en Windows y elige **Abrir carpeta como bóveda**.
3. Escribe esta ruta cambiando `<tu-usuario>` por tu usuario: `\\wsl.localhost\Ubuntu\home\<tu-usuario>\trovify-cerebro`
4. Confirma que ves las carpetas del cerebro (`wiki`, `raw`, `config`…) y sigue con las comprobaciones.
5. Comprueba el orden del vault: `trovify cerebro lint`. Si señala algo, corrígelo con Claude y repite hasta que no haya problemas.
6. Comprueba que existen páginas del método en `wiki/metodo/`. Si no las hay, destílalas con `/trovify:destilar`.
7. Pasa los canarios, que son preguntas de control cuya respuesta Claude debe sacar solo del cerebro: `trovify cerebro canarios` (dentro del vault).
8. Si algún canario falla, corrige la página del cerebro que corresponde o su cita y repite el paso 7.
9. Los canarios valen 30 días: pasado ese tiempo hay que repetirlos.

**Errores típicos**
- Síntoma: «el vault tiene N problemas de lint». Arreglo: `trovify cerebro lint` y corrige lo que señala.
- Síntoma: «no existe el vault». Arreglo: `trovify cerebro init`.
- Síntoma: «no hay resultado de canarios». Arreglo: corre `trovify cerebro canarios` dentro del vault.
- Síntoma: «no hay páginas del método». Arreglo: `/trovify:destilar`.
- Síntoma: «problemas en wiki/metodo/». Arreglo: corrige las citas y fuentes de esas páginas.
- Síntoma: «los canarios no pasaron todos» o «canarios que no están ok». Arreglo: corrige las páginas del cerebro que responden mal y repite `trovify cerebro canarios`.
- Síntoma: «la fecha de los canarios está en el futuro» o «ultimo.json está ilegible». Arreglo: repite `trovify cerebro canarios` para que se escriba de nuevo.
- Síntoma: «los canarios son de hace más de 30 días» o «el sha del canarios.yaml cambió». Arreglo: vuelve a correr `trovify cerebro canarios`.

**Cómo se verifica**
`trovify arranque verificar 01` comprueba que el vault no tiene problemas de lint, que hay páginas válidas del método con sus citas, y que el último resultado de canarios (`data/canarios/ultimo.json`) es de los últimos 30 días, cubre exactamente los canarios actuales y los pasa todos. Deja la evidencia en `config/evidencia/`.
