"""Microsoft Clarity solo tras el consentimiento (plan 19, cabecera punto 7; Tarea 7).

Los vídeos ponen Clarity en la landing y el checkout (S1 5:12, S2 9:23). Aprobado por el usuario el 2026-11-17,
con una condición (regla europea): se carga **solo después de que el visitante acepte** en un aviso de cookies
propio de la landing. Por eso Clarity **no** se pega en el panel de Impultienda (la tienda lo cargaría sin
preguntar) y no va en el checkout (es una página de Impultienda: no podemos poner el aviso delante).

- ``bloque_consentimiento``: el HTML del aviso, oculto de entrada, con «aceptar» y «rechazar» del mismo peso
  (los textos, en el idioma de la landing, los escribe Claude y pasan el revisor nativo del 18).
- ``templates/landing/consentimiento.js``: muestra el aviso si no hay elección, guarda la elección en el navegador
  y solo con «aceptar» añade ``https://www.clarity.ms/tag/<proyecto>``; un enlace ``data-tf-consentimiento-cambiar``
  vuelve a abrirlo (retirar el consentimiento es tan fácil como darlo).
- ``validar_consentimiento``: la comprobación estática para ``trovefy landing validar``.
- ``peticiones_sin_consentimiento``: la de la QA (sin pulsar nada no sale ninguna petición a Clarity). La QA del 18
  ya aborta y cuenta como FALLA cualquier tercero que no sea de Meta ni de la tienda, y nunca pulsa «aceptar».

El cableado en la landing (plantilla, validar, empaquetar en línea, QA) es del plan 18: ver el informe de la
Tarea 7.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urlsplit

CONSENTIMIENTO_JS = Path(__file__).resolve().parents[3] / "templates" / "landing" / "consentimiento.js"
SCRIPT = "assets/consentimiento.js"
HOST_CLARITY = "clarity.ms"
_PROYECTO = re.compile(r"[a-z0-9]{6,20}")
_AVISO = re.compile(r"<(\w+)\b[^>]*\bid=[\"']tf-consentimiento[\"'][^>]*>", re.IGNORECASE)
_SCRIPT = re.compile(r"<script\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)


def es_peticion_clarity(url: str) -> bool:
    """``True`` si la URL va a ``clarity.ms`` o a un subdominio suyo."""
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return host == HOST_CLARITY or host.endswith("." + HOST_CLARITY)


def peticiones_sin_consentimiento(urls) -> list[str]:
    """Las peticiones a Clarity entre las de una carga sin pulsar nada (deben ser ninguna)."""
    return [u for u in urls if es_peticion_clarity(u)]


def bloque_consentimiento(proyecto: str, texto: str, aceptar: str, rechazar: str) -> str:
    """El HTML del aviso (oculto: lo muestra el script si el visitante aún no eligió). ``ValueError`` si el id
    de proyecto de Clarity no es 6–20 minúsculas y cifras o falta algún texto."""
    if not isinstance(proyecto, str) or not _PROYECTO.fullmatch(proyecto):
        raise ValueError(f"id de proyecto de Clarity mal escrito «{proyecto}»: 6 a 20 minúsculas y cifras")
    for nombre, valor in (("texto", texto), ("aceptar", aceptar), ("rechazar", rechazar)):
        if not isinstance(valor, str) or not valor.strip():
            raise ValueError(f"falta el texto «{nombre}» del aviso de cookies")
    t, si, no = (html.escape(x.strip()) for x in (texto, aceptar, rechazar))
    return (f'<div id="tf-consentimiento" class="tf-consentimiento" data-tf-clarity="{proyecto}" role="region" '
            f'aria-label="{t}" hidden>'
            f'<p>{t}</p>'
            f'<button type="button" class="tf-consentimiento-boton" data-tf-consentimiento="si">{si}</button>'
            f'<button type="button" class="tf-consentimiento-boton" data-tf-consentimiento="no">{no}</button>'
            "</div>")


def validar_consentimiento(html_landing: str) -> list[str]:
    """Problemas del aviso en el HTML de la landing (``[]`` si está bien o si no hay aviso). Clarity no puede
    aparecer fuera del script; el aviso, una sola vez, oculto de entrada, con el id del proyecto y los dos botones."""
    problemas: list[str] = []
    avisos = _AVISO.findall(html_landing)
    if HOST_CLARITY in html_landing.lower():
        problemas.append("clarity.ms aparece en el HTML: Clarity solo lo carga assets/consentimiento.js tras «aceptar»")
    if not avisos:
        return problemas
    if len(avisos) > 1:
        problemas.append("el aviso de cookies (#tf-consentimiento) debe ir una sola vez")
    apertura = _AVISO.search(html_landing).group(0)
    if not re.search(r"\shidden(?:[\s>=]|$)", apertura):
        problemas.append("#tf-consentimiento debe salir con hidden: lo muestra el script si no hay elección")
    m = re.search(r"data-tf-clarity=[\"']([^\"']*)[\"']", apertura)
    if not m or not _PROYECTO.fullmatch(m.group(1)):
        problemas.append("#tf-consentimiento sin data-tf-clarity válido (el id del proyecto de Clarity)")
    if not re.search(r"<button\b[^>]*data-tf-consentimiento=[\"']si[\"']", html_landing):
        problemas.append("al aviso de cookies le falta el botón de aceptar (data-tf-consentimiento=\"si\")")
    if not re.search(r"<button\b[^>]*data-tf-consentimiento=[\"']no[\"']", html_landing):
        problemas.append("al aviso de cookies le falta el botón de rechazar (data-tf-consentimiento=\"no\"), "
                         "con el mismo peso que aceptar")
    if SCRIPT not in _SCRIPT.findall(html_landing):
        problemas.append(f"hay aviso de cookies pero falta <script src=\"{SCRIPT}\" defer>")
    return problemas
