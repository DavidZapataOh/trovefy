# 01 · Cerebro

**Objetivo**
Tener el cerebro (la carpeta de Obsidian con el método y las reglas) construido, ordenado y comprobado con preguntas de control.

**Antes de empezar**
- Paso 00 verificado.
- El vault en `~/trovefy-cerebro` con el método ya destilado en `wiki/metodo/`.
- Abre la terminal dentro del vault.

**Pasos**
1. Abre la terminal de Ubuntu (WSL) y escribe `whoami`: lo que responde es tu `<tu-usuario>`. WSL tiene que estar en marcha (la terminal de Ubuntu abierta).
2. En esa terminal escribe `obsidian &` (es Obsidian para Linux, instalado en el paso 00; se abre como ventana de Windows) y elige **Abrir carpeta como bóveda**.
3. Elige la carpeta `/home/<tu-usuario>/trovefy-cerebro`. No uses Obsidian para Windows con la ruta `\\wsl.localhost\…`: falla con «EISDIR».
4. Confirma que ves las carpetas del cerebro (`wiki`, `raw`, `config`…) y sigue con las comprobaciones.
5. Comprueba el orden del vault: `trovefy cerebro lint`. Si señala algo, corrígelo con Claude y repite hasta que no haya problemas.
6. Comprueba que existen páginas del método en `wiki/metodo/`. Si no las hay, destílalas con `/trovefy:destilar`.
7. Pasa los canarios, que son preguntas de control cuya respuesta Claude debe sacar solo del cerebro: `trovefy cerebro canarios` (dentro del vault).
8. Si algún canario falla, corrige la página del cerebro que corresponde o su cita y repite el paso 7.
9. Los canarios valen 30 días: pasado ese tiempo hay que repetirlos.

**Errores típicos**
- Síntoma: «el vault tiene N problemas de lint». Arreglo: `trovefy cerebro lint` y corrige lo que señala.
- Síntoma: «no existe el vault». Arreglo: `trovefy cerebro init`.
- Síntoma: «no hay resultado de canarios». Arreglo: corre `trovefy cerebro canarios` dentro del vault.
- Síntoma: «no hay páginas del método». Arreglo: `/trovefy:destilar`.
- Síntoma: «problemas en wiki/metodo/». Arreglo: corrige las citas y fuentes de esas páginas.
- Síntoma: «los canarios no pasaron todos» o «canarios que no están ok». Arreglo: corrige las páginas del cerebro que responden mal y repite `trovefy cerebro canarios`.
- Síntoma: «la fecha de los canarios está en el futuro» o «ultimo.json está ilegible». Arreglo: repite `trovefy cerebro canarios` para que se escriba de nuevo.
- Síntoma: «los canarios son de hace más de 30 días» o «el sha del canarios.yaml cambió». Arreglo: vuelve a correr `trovefy cerebro canarios`.

**Cómo se verifica**
`trovefy arranque verificar 01` comprueba que el vault no tiene problemas de lint, que hay páginas válidas del método con sus citas, y que el último resultado de canarios (`data/canarios/ultimo.json`) es de los últimos 30 días, cubre exactamente los canarios actuales y los pasa todos. Deja la evidencia en `config/evidencia/`.
