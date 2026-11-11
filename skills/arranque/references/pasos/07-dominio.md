# 07 · Dominio propio con Cloudflare

**Objetivo**
Tener un dominio propio gestionado por Cloudflare, que será la dirección pública de tu negocio y lo que Meta verificará en el paso 08.

**Antes de empezar**
- Una cuenta de Cloudflare a tu nombre (gratis) y una tarjeta para pagar el dominio.
- Presupuesto: un dominio `.com` en Cloudflare Registrar cuesta unos US$ 10 al año (sale del sobre de herramientas).
- Decide el nombre antes de pagar; un dominio comprado no se devuelve.

**Pasos**
1. Entra en https://dash.cloudflare.com/ con tu cuenta (contraseña y 2FA los escribes tú).
2. En «Registro de dominios» (Domain Registration) busca el nombre y cómpralo en Cloudflare Registrar. Los datos de contacto son los tuyos reales.
3. Comprobar que el dominio quedó en Cloudflare: en «Sitios web» (Websites) debe aparecer con estado «Activo». Con Registrar, los servidores de nombres ya son los de Cloudflare.
4. Si lo compraste en otro registrador, añade el dominio en «Sitios web» y cambia en ese registrador los servidores de nombres por los dos que te da Cloudflare (terminan en `.ns.cloudflare.com`).
5. Guarda el dominio en Trovefy (comando de Trovefy, no de sistema):
   `trovefy arranque hecho 07 --dato dominio=<tu-dominio>`
   Escribe el dominio principal (por ejemplo `midominio.com`), no un subdominio como `tienda.midominio.com`.
   Trovefy lo guarda en minúsculas y sin `https://` ni `www.`.
6. Verifica: `trovefy arranque verificar 07`.

**Errores típicos**
- Síntoma: «el dominio no usa los servidores de nombres de Cloudflare». Arreglo: revisa el paso 4; si acabas de cambiarlos, la propagación del DNS puede tardar desde minutos hasta unas horas. Repite la verificación más tarde.
- Síntoma: «el dominio no responde con servidores de nombres». Arreglo: el dominio es nuevo o está mal escrito; comprueba el nombre y espera.
- Síntoma: «no medido: sin red». Arreglo: comprueba tu conexión y repite.
- Síntoma: `--dato dominio` rechazado. Arreglo: escribe solo el dominio (`midominio.com`), sin IP ni espacios.

**Cómo se verifica**
`trovefy arranque verificar 07` pregunta por DNS sobre HTTPS a Cloudflare (`cloudflare-dns.com`, consulta pública, sin cuenta) por los servidores de nombres del dominio y es ✓ si alguno termina en `.ns.cloudflare.com`. Guarda la lista y la fecha en `config/evidencia/07-ns-<fecha>.json`.
