"""Intercepción compartida de las respuestas de datos (``/api/graphql``) de la Biblioteca.

La usan la grabadora de fixtures (``grabar``) y el cliente (``cliente``).
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit


def es_respuesta_de_datos(url: str) -> bool:
    partes = urlsplit(url)
    host = partes.hostname or ""
    return (host == "facebook.com" or host.endswith(".facebook.com")) and partes.path.startswith("/api/graphql")


def _consulta(r) -> str | None:
    """Nombre de la consulta GraphQL (campo ``fb_api_req_friendly_name`` del formulario enviado).

    No es secreto. Del formulario solo se lee ese campo; nunca cabeceras ni cookies.
    """
    try:
        datos = r.request.post_data
    except Exception:  # noqa: BLE001 (petición sin cuerpo o ya liberada)
        return None
    if not isinstance(datos, str):
        return None
    nombres = parse_qs(datos).get("fb_api_req_friendly_name")
    return nombres[0] if nombres else None


def escuchar_respuestas(pagina, max_respuestas: int) -> list[dict]:
    """Engancha ``pagina`` y devuelve la lista (viva) de ``{url, estado, cuerpo, consulta}`` de
    respuestas de datos.

    Solo guarda url, estado, cuerpo y el nombre de la consulta: ni cabeceras ni cookies ni el
    resto del formulario enviado.
    """
    from playwright.sync_api import Error as PlaywrightError

    respuestas: list[dict] = []

    def al_responder(r) -> None:
        if len(respuestas) >= max_respuestas or not es_respuesta_de_datos(r.url):
            return
        try:
            cuerpo = r.text()
        except (PlaywrightError, UnicodeDecodeError):
            return  # cuerpo no disponible (redirección, petición abortada)
        respuestas.append({"url": r.url, "estado": r.status, "cuerpo": cuerpo, "consulta": _consulta(r)})

    pagina.on("response", al_responder)
    return respuestas
