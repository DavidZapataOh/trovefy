# El ejecutor en Windows (WSL)

El ejecutor de Trovefy es un servicio de systemd que vive dentro de WSL (Ubuntu). Solo hace algo mientras
WSL está encendido. Esta guía deja WSL despierto y arrancando solo cuando inicias sesión en Windows.

> **Importante (§5.10):** con el PC dormido, hibernado o apagado **no se ejecuta nada**. Las propuestas que
> apruebes en Telegram mientras tanto esperan (y pueden caducar), y las alertas no salen. Nada se ejecuta
> «después» por su cuenta sin que vuelvas a aprobarlo si ya caducó.

## 1. Que WSL no se apague solo

Por defecto WSL apaga la máquina virtual cuando no hay ninguna terminal abierta. En Windows, crea o edita
el archivo `%UserProfile%\.wslconfig` (por ejemplo `C:\Users\TuNombre\.wslconfig`) con:

```ini
[wsl2]
vmIdleTimeout=-1
```

Guarda y reinicia WSL desde PowerShell: `wsl --shutdown` (la próxima vez que abras Ubuntu arranca con la
configuración nueva).

## 2. Que WSL arranque al iniciar sesión

En PowerShell o en el símbolo del sistema de Windows (no hace falta que sea como administrador):

```bat
schtasks /Create /SC ONLOGON /TN TrovefyWSL /TR "wsl.exe -d Ubuntu --exec /bin/true"
```

Esto enciende WSL cada vez que inicias sesión; systemd arranca entonces `trovefy-ejecutor` (el instalador
lo dejó habilitado). Si tu distribución no se llama `Ubuntu`, mira el nombre con `wsl -l -v` y cámbialo en
el comando. Para quitar la tarea: `schtasks /Delete /TN TrovefyWSL`.

## 3. Que el PC no se duerma enchufado

Configuración de Windows → Sistema → Inicio/apagado y suspensión (o «Energía y batería») → en
**«Cuando está enchufado, poner el equipo en suspensión después de»**, elige **Nunca**. Puedes dejar que
la pantalla se apague: eso no detiene nada. Con batería, Windows puede seguir suspendiendo el equipo, y
entonces el ejecutor se para (ver el aviso de arriba).

## 4. Comprobar que funciona

En Ubuntu:

```bash
systemctl status trovefy-ejecutor   # debe decir «active (running)»
trovefy buzon estado                # latido reciente del servicio
```

Si el servicio no arranca con `status=226/NAMESPACE`, edita `/etc/systemd/system/trovefy-ejecutor.service`
y quita `PrivateDevices=yes`; si sigue fallando, quita también `RestrictNamespaces=yes`. Después:
`sudo systemctl daemon-reload && sudo systemctl restart trovefy-ejecutor`. (Si vuelves a ejecutar el
instalador, la unidad se reescribe desde la plantilla del repo.)

Antes de reparar la auditoría del ejecutor, para el servicio: `sudo systemctl stop trovefy-ejecutor`.
