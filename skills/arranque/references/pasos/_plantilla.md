# NN · <nombre del paso>

**Objetivo**
Una frase: qué queda listo al terminar y para qué sirve.

**Antes de empezar**
Qué necesitas tener a mano (cuentas, documentos, tiempo, pasos anteriores verificados).

**Pasos**
1. Lo que hace el usuario, en una acción por número.
2. Los comandos de sistema o interactivos (`sudo`, `apt`, `nano`, editar archivos de sistema) los escribe el usuario en una terminal de Ubuntu (WSL) **aparte**, sin `!` (dentro de Claude Code el `!` no tiene terminal y no funcionan ni la contraseña de sudo ni nano):
   `sudo apt install -y <paquete>`
3. Contraseñas, KYC y 2FA los hace el usuario; Claude no los escribe ni los lee.

**Errores típicos**
- Síntoma: lo que ves. Arreglo: lo que haces.

**Cómo se verifica**
`trovify arranque verificar NN` — qué comprueba exactamente y qué evidencia deja en `config/evidencia/`.
