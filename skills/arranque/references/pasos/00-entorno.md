# 00 · Entorno

**Objetivo**
Dejar tu computador (Windows con WSL) con todas las herramientas que Trovefy necesita para funcionar.

**Antes de empezar**
- Windows con WSL (Ubuntu) ya abierto en una terminal.
- Unos 20 minutos y conexión a internet.
- Abre una **terminal de Ubuntu (WSL) aparte**, fuera de Claude Code. Todos los comandos de esta guía los escribes ahí, sin `!`: dentro de Claude Code el `!` no tiene terminal y no funcionan ni la contraseña de sudo ni el editor nano. Claude no ve tu contraseña.

**Pasos**
1. Pide la comprobación: `trovefy arranque verificar 00`. Te muestra una lista con ✓ y ✗; solo arreglas lo que tenga ✗.
2. Para cada ✗, aplica su arreglo. Hazlos en este orden:
   - **uv** (`uv`): `sudo apt install -y pipx` y luego `pipx install uv==0.11.26`. No ejecutes scripts descargados al vuelo de internet.
   - **Python 3.12** (`python`, necesita uv): `uv python install 3.12`
   - **Node 20 o superior** (`node`): si falta o es menor de 20, instala el LTS actual para Linux desde la página oficial https://nodejs.org/en/download: elige Linux, descarga el archivo `.tar.xz`, comprueba la descarga con el archivo de sumas (`SHASUMS256.txt`) que ofrece la misma página, descomprímelo en `~/.local/node` y añade su carpeta `bin` al `PATH` en `~/.bashrc`. Nunca uses un script descargado y ejecutado al vuelo.
   - **git** (`git`): `sudo apt install -y git`
   - **ffmpeg** (`ffmpeg`): `sudo apt install -y ffmpeg`. Debe ser el de apt, no el de snap: el de snap se queda colgado en WSL.
   - **poppler** (`poppler`, para leer PDFs): `sudo apt install -y poppler-utils`
   - **Librerías de Pango** (`weasyprint`, para generar PDFs): `sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0`
   - **Navegador de Playwright** (`playwright`): en una terminal de Ubuntu (WSL) aparte, `cd ~/trovefy/trovefy && uv run playwright install chromium`.
   - **systemd** (`systemd`): ver el paso 3.
   - **Obsidian** (`obsidian`): instala la versión **para Linux** dentro de WSL (se abre como ventana normal de Windows gracias a WSLg). La de Windows no sirve: no puede abrir una bóveda que esté dentro de WSL. Descarga el `.deb` (amd64) desde https://obsidian.md/download, comprueba `sha256sum` contra el que publica GitHub en esa versión, e instálalo con `sudo apt install ./obsidian_<versión>_amd64.deb`. Ábrelo con `obsidian &` y elige «Abrir carpeta como bóveda» → `/home/<tu-usuario>/trovefy-cerebro`.
3. Para activar systemd:
   1. Mira el archivo actual: `cat /etc/wsl.conf` (si dice que no existe, no pasa nada).
   2. Ábrelo: `sudo nano /etc/wsl.conf`
   3. Si ya hay una sección `[boot]`, añade la línea `systemd=true` debajo de ella. Si no la hay, añade al FINAL del archivo estas dos líneas: `[boot]` y debajo `systemd=true`. No borres ni reemplaces nada de lo que ya estaba. Guarda con Ctrl+O, Enter y sal con Ctrl+X.
   4. Abre **PowerShell de Windows** (no la terminal de Linux) y escribe `wsl --shutdown`. Ojo: esto también cierra Claude Code.
   5. Vuelve a abrir Ubuntu, entra con `cd ~/trovefy-cerebro` y ejecuta `claude` otra vez.
4. Repite `trovefy arranque verificar 00` hasta que no quede ningún ✗. Si solo queda ✗ algo que no puedes arreglar ahora, marca el paso con `trovefy arranque hecho 00` y continúa con los demás pasos; vuelve a verificarlo cuando lo arregles.

**Errores típicos**
- Síntoma: `ffmpeg` se queda colgado y el verificador dice que no responde. Arreglo: tienes el ffmpeg de snap; instala el de apt con `sudo apt install -y ffmpeg`.
- Síntoma: systemd sigue en ✗ tras editar `wsl.conf`. Arreglo: falta `wsl --shutdown` desde PowerShell de Windows y reabrir la terminal.
- Síntoma: Obsidian de Windows dice «EISDIR: illegal operation on a directory, watch '\\wsl.localhost\…'». Arreglo: es un fallo conocido de Obsidian para Windows con carpetas de WSL; usa la versión para Linux (arriba). Trovefy la busca en `/usr/bin/obsidian`.
- Síntoma: `playwright` en ✗. Arreglo: en una terminal de Ubuntu (WSL) aparte, `cd ~/trovefy/trovefy && uv run playwright install chromium`, y vuelve a verificar.

**Cómo se verifica**
`trovefy arranque verificar 00` revisa: Python 3.12, uv, Node 20+, git, ffmpeg (con límite de 10 s), poppler, libpango, el navegador de Playwright, systemd (`running` o `degraded`) y Obsidian para Linux en WSL. Guarda el detalle en `config/evidencia/` y el paso pasa a `verificado` solo si todos están ✓.
