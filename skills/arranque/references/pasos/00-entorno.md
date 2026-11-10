# 00 · Entorno

**Objetivo**
Dejar tu computador (Windows con WSL) con todas las herramientas que Trovify necesita para funcionar.

**Antes de empezar**
- Windows con WSL (Ubuntu) ya abierto en una terminal.
- Unos 20 minutos y conexión a internet.
- Los comandos que empiezan por `!` los escribes tú en la terminal; piden tu contraseña de Linux y Claude no la ve.

**Pasos**
1. Pide la comprobación: `trovify arranque verificar 00`. Te muestra una lista con ✓ y ✗; solo arreglas lo que tenga ✗.
2. Para cada ✗, aplica su arreglo de esta lista:
   - **Python 3.12** (`python`): `! uv python install 3.12`
   - **uv** (`uv`): instálalo con una versión fijada, por ejemplo `! pipx install uv==<versión>`. No ejecutes scripts descargados al vuelo de internet.
   - **Node 20 o superior** (`node`): instala Node LTS (20 o superior) con una versión fijada.
   - **git** (`git`): `! sudo apt install -y git`
   - **ffmpeg** (`ffmpeg`): `! sudo apt install -y ffmpeg`. Debe ser el de apt, no el de snap: el de snap se queda colgado en WSL.
   - **poppler** (`poppler`, para leer PDFs): `! sudo apt install -y poppler-utils`
   - **Librerías de Pango** (`weasyprint`, para generar PDFs): `! sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0`
   - **Navegador de Playwright** (`playwright`): llega con el plan 05; no puedes arreglarlo todavía. Después se instala con `! uv run playwright install chromium`.
   - **systemd** (`systemd`): ver el paso 3.
   - **Obsidian** (`obsidian`): instálalo en Windows (no en WSL) desde https://obsidian.md.
3. Para activar systemd:
   1. Abre el archivo: `! sudo nano /etc/wsl.conf`
   2. Añade estas dos líneas: `[boot]` y debajo `systemd=true`. Guarda con Ctrl+O, Enter y sal con Ctrl+X.
   3. Abre **PowerShell de Windows** (no la terminal de Linux) y escribe `wsl --shutdown`.
   4. Vuelve a abrir tu terminal de WSL.
4. Repite `trovify arranque verificar 00` hasta que no quede ningún ✗.

**Errores típicos**
- Síntoma: `ffmpeg` se queda colgado y el verificador dice que no responde. Arreglo: tienes el ffmpeg de snap; instala el de apt con `! sudo apt install -y ffmpeg`.
- Síntoma: systemd sigue en ✗ tras editar `wsl.conf`. Arreglo: falta `wsl --shutdown` desde PowerShell de Windows y reabrir la terminal.
- Síntoma: Obsidian instalado pero marcado ✗. Arreglo: instálalo para tu usuario de Windows (el instalador normal); Trovify lo busca en `AppData\Local\Programs\Obsidian`.
- Síntoma: `playwright` en ✗ y no sabes qué hacer. Arreglo: es normal antes del plan 05; el paso queda pendiente solo por eso.

**Cómo se verifica**
`trovify arranque verificar 00` revisa: Python 3.12, uv, Node 20+, git, ffmpeg (con límite de 10 s), poppler, libpango, el navegador de Playwright, systemd (`running` o `degraded`) y Obsidian en Windows. Guarda el detalle en `config/evidencia/` y el paso pasa a `verificado` solo si todos están ✓.
