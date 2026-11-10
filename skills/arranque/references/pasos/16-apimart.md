# 16 · APIMart

**Objetivo**
Dejar tu cuenta de APIMart conectada, con clave guardada de forma segura y saldo comprobado.

**Antes de empezar**
- Abre una **terminal de Ubuntu (WSL) aparte**, fuera de Claude Code. Los comandos de los pasos 5 a 8 los escribes ahí, sin `!`: dentro de Claude Code el `!` no tiene terminal y nano no funciona.
- Tu clave es secreta: **la pegas tú en un archivo; Claude no la ve** ni debe pedírtela por el chat.
- Tarjeta o medio de pago para una recarga pequeña.

**Pasos**
1. Crea tu cuenta en APIMart (gratis): entra a https://apimart.ai/ y regístrate. La contraseña la escribes tú.
2. Recarga saldo desde la consola de APIMart (https://apimart.ai/overview, sección de saldo o recarga): **US$ 5 a 10 y no más**. Es suficiente para empezar y limita lo que puedes perder.
3. Crea la clave de API en la consola, en https://apimart.ai/keys (botón de crear clave). Suele parecerse a una cadena larga de letras y números (cópiala completa). Cópiala; no la compartas con nadie.
4. Comprueba en https://apimart.ai/overview que el saldo aparece.
5. Crea el archivo sin borrar uno que ya exista y protégelo (permisos 0600, solo tú puedes leerlo), todo en una línea: `mkdir -p ~/.config/trovify && touch ~/.config/trovify/claude.env && chmod 600 ~/.config/trovify/claude.env`
6. Ábrelo con tu editor: `nano ~/.config/trovify/claude.env`
7. Escribe `APIMART_API_KEY=` y pega justo después tu clave. En Windows Terminal, pega con clic derecho o con Ctrl+Shift+V (Ctrl+V no pega en nano).
8. Guarda con Ctrl+O, Enter, y sal con Ctrl+X.
9. Opcional: si APIMart te dio otra dirección, añade `APIMART_BASE_URL=https://...`. Solo se acepta https. Si no la pones, se usa la oficial.
10. Pide la verificación: `trovify arranque verificar 16`.

**Errores típicos**
- Síntoma: «no existe claude.env». Arreglo: repite el paso 5.
- Síntoma: «tiene permisos … deben ser 600». Arreglo, en la terminal aparte: `chmod 600 ~/.config/trovify/claude.env`
- Síntoma: «falta APIMART_API_KEY». Arreglo: abre el archivo y añade la línea del paso 7.
- Síntoma: «APIMART_BASE_URL debe ser https». Arreglo: corrige la dirección o bórrala.
- Síntoma: «saldo agotado». Arreglo: recarga US$ 5–10 en la consola de APIMart (no más).
- Síntoma: «la clave tiene caracteres raros». Arreglo: vuelve a pegarla con Ctrl+Shift+V, sin espacios ni comillas raras.
- Síntoma: «clave rechazada por APIMart». Arreglo: revisa o regenera la clave en el panel de APIMart y pégala de nuevo.
- Síntoma: «no medido: sin red» o «respuesta inesperada». Arreglo: comprueba tu conexión y repite más tarde; no es culpa de tu clave.
- Síntoma: el archivo es un enlace o no es de texto. Arreglo: usa un archivo normal tuyo.

**Cómo se verifica**
`trovify arranque verificar 16` (esto sí lo puede ejecutar Claude por ti) lee `claude.env` (exige permisos 600), consulta el saldo en APIMart y, si responde, guarda el saldo en `config/evidencia/`. La clave nunca se imprime ni se guarda. Si tu cuenta tiene cuota ilimitada, el saldo se guarda como «ilimitado» y sin moneda. APIMart no indica la moneda del saldo: Trovify la infiere (USD) y la marca «inferida».
