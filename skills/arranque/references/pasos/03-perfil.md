# 03 · Perfil de Facebook

**Objetivo**
Tener un perfil de Facebook tuyo, real y con 2FA, que será el dueño de tu portfolio comercial y de tu página.

**Antes de empezar**
- Paso 00 y 01 verificados.
- Por qué tu identidad real: una cuenta que dura es una cuenta que no se pierde. Los perfiles inventados, prestados o comprados son los que Meta cierra, y con ellos se van el Business, la página y la cuenta publicitaria. Trovify solo trabaja con tu propia identidad.
- Tu teléfono a mano (para el 2FA).

**Pasos**
1. Si ya tienes un perfil tuyo y real, úsalo. Si no, créalo en https://www.facebook.com/ con tu nombre y apellidos reales, tu fecha de nacimiento real y un correo o teléfono tuyos. No uses el de otra persona.
2. Activa el 2FA en Facebook: Configuración y privacidad → Configuración → Centro de cuentas → Contraseña y seguridad → Autenticación en dos pasos. Elige una app de autenticación (mejor que SMS). Los códigos los ves y los escribes tú; Claude no los ve nunca.
3. Decide que el día que crees el Business (paso 04) no usarás VPN: Meta desconfía de los cambios de país o de IP en las cuentas nuevas.
4. Responde la lista a Claude con tus tres «sí» (o «no» si algo no se cumple):
   `trovify arranque checklist 03 --respuesta perfil_propio=si --respuesta dos_fa=si --respuesta sin_vpn=si`

**Errores típicos**
- Síntoma: «no se cumple: Tiene 2FA activo». Arreglo: termina el paso 2 y vuelve a responder con `dos_fa=si`.
- Síntoma: «faltan respuestas». Arreglo: repite el comando con las tres `--respuesta`.
- Síntoma: Facebook te pide subir un documento al crear el perfil. Arreglo: hazlo tú con tu documento real; nunca se lo des a Claude.

**Cómo se verifica**
`trovify arranque checklist 03 …` (también vale `trovify arranque verificar 03`, que te recuerda el comando). Meta no deja comprobar desde fuera si un perfil es real o tiene 2FA, así que la evidencia es tu respuesta con la fecha, guardada en `config/evidencia/03-checklist-<fecha>.json`. Solo pasa si las tres respuestas son «sí».
