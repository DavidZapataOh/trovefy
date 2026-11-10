"""Intercepción compartida de las respuestas de datos (``/api/graphql``) de la Biblioteca.

La usan la grabadora de fixtures (``grabar``) y el cliente (``cliente``).
"""

from __future__ import annotations

from urllib.parse import urlsplit


def es_respuesta_de_datos(url: str) -> bool:
    partes = urlsplit(url)
    host = partes.hostname or ""
    return (host == "facebook.com" or host.endswith(".facebook.com")) and partes.path.startswith("/api/graphql")


def escuchar_respuestas(pagina, max_respuestas: int) -> list[dict]:
    """Engancha ``pagina`` y devuelve la lista (viva) de ``{url, estado, cuerpo}`` de respuestas de datos.

    Solo guarda url, estado y cuerpo: ni cabeceras ni cookies.
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
        respuestas.append({"url": r.url, "estado": r.status, "cuerpo": cuerpo})

    pagina.on("response", al_responder)
    return respuestas
