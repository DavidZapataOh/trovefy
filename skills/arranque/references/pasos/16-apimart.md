# 16 · APIMart

**Objetivo**
Dejar tu cuenta de APIMart conectada, con clave guardada de forma segura y saldo comprobado.

**Antes de empezar**
- Una cuenta en APIMart con saldo y una clave de API creada en su panel (la creas tú, con tu contraseña).
- Abre una **terminal de Ubuntu (WSL) aparte**, fuera de Claude Code. Los comandos de los pasos 1 a 4 los escribes ahí, sin `!`: dentro de Claude Code el `!` no tiene terminal y nano no funciona.
- Tu clave es secreta: **la pegas tú en un archivo; Claude no la ve** ni debe pedírtela por el chat.

**Pasos**
1. Crea la carpeta: `mkdir -p ~/.config/trovify`
2. Crea el archivo ya protegido (permisos 0600, solo tú puedes leerlo): `install -m 600 /dev/null ~/.config/trovify/claude.env`
3. Ábrelo con tu editor: `nano ~/.config/trovify/claude.env`
4. Pega esta línea con tu clave real y guarda (Ctrl+O, Enter, Ctrl+X): `APIMART_API_KEY=tu_clave_aqui`
5. Opcional: si APIMart te dio otra dirección, añade `APIMART_BASE_URL=https://...`. Solo se acepta https. Si no la pones, se usa la oficial.
6. Pide la verificación: `trovify arranque verificar 16`.

**Errores típicos**
- Síntoma: «no existe claude.env». Arreglo: repite los pasos 1 y 2.
- Síntoma: «tiene permisos … deben ser 600». Arreglo, en la terminal aparte: `chmod 600 ~/.config/trovify/claude.env`
- Síntoma: «falta APIMART_API_KEY». Arreglo: abre el archivo y añade la línea del paso 4.
- Síntoma: «APIMART_BASE_URL debe ser https». Arreglo: corrige la dirección o bórrala.
- Síntoma: «clave rechazada por APIMart». Arreglo: revisa o regenera la clave en el panel de APIMart y pégala de nuevo.
- Síntoma: «no medido: sin red» o «respuesta inesperada». Arreglo: comprueba tu conexión y repite más tarde; no es culpa de tu clave.
- Síntoma: el archivo es un enlace o no es de texto. Arreglo: usa un archivo normal tuyo.

**Cómo se verifica**
`trovify arranque verificar 16` (esto sí lo puede ejecutar Claude por ti) lee `claude.env` (exige permisos 600), consulta el saldo en APIMart y, si responde, guarda el saldo en `config/evidencia/`. La clave nunca se imprime ni se guarda. Si tu cuenta tiene cuota ilimitada, el saldo se guarda como «ilimitado» y sin moneda. APIMart no indica la moneda del saldo: Trovify la infiere (USD) y la marca «inferida».
