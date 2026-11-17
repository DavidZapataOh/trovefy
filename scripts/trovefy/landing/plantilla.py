"""Esqueleto propio de la landing, ``preparar`` (borrador + wireframe + ``landing.yaml``) y ``guardar``.

Contrato de marcado (lo usan validar, qa y publicar): ``<html lang>``; un ``<main id="tf-landing"
data-tf-version="">``; cada sección ``<section data-tf-seccion="<orden>" data-tf-tipo="<tipo>">`` con un
único ``data-tf-hito`` (su titular); botones ``<a data-tf-checkout href="<checkout_url>">``;
``data-tf-precio``, ``data-tf-formato``, ``data-tf-garantia``; reseñas ``data-tf-resena="<id>"``; vista
previa ``<img data-tf-vista src="assets/vista-p<N>-480.webp" srcset="… 480w, … 960w">``. CSS en
``assets/estilo.css`` y el único script en ``assets/utm.js`` (``defer``).

Claude escribe el texto y el diseño en el borrador (fuera del vault); ``guardar`` lo copia al vault tras
buscar secretos, con el ``utm.js`` del repo (nunca el del borrador) y la versión fijada.

Escritura: todo va con ``escribir_medio`` (temporal en la misma carpeta + ``os.replace``, 0640, sin seguir
enlaces) y con las carpetas revisadas por ``carpeta_segura``. Un enlace simbólico en lo que se lee
(``landing.yaml``, el borrador) es un error, no algo que se siga.
"""

from __future__ import annotations

import hashlib
import html as html_mod
import json
import os
import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from trovefy.landing.constantes import ANCHOS_IMAGEN
from trovefy.landing.entrada import (
    DatosLanding,
    EntradaInvalida,
    ruta_landing,
    wireframe,
)
from trovefy.producto.medios import carpeta_segura, escribir_medio
from trovefy.secretos import buscar_secreto
from trovefy.vault.escritura import anadir_log
from trovefy.vault.producto import secreto_en

PLANTILLAS = Path(__file__).resolve().parents[3] / "templates" / "landing"
BASE_HTML = PLANTILLAS / "base.html"
BASE_CSS = PLANTILLAS / "base.css"
UTM_JS = PLANTILLAS / "utm.js"
HOSTINGS = ("impultienda", "cloudflare")
TEXTO_PROPIO = "<!-- texto propio -->"
_VERSION = re.compile(r'data-tf-version="[^"]*"')
_TIENDA = re.compile(r"https://[a-z0-9.-]+\.[a-z]{2,}(?::\d+)?/?", re.IGNORECASE)
_SIMBOLOS = {"EUR": "€", "USD": "$", "GBP": "£"}
_MONEDA_POR_IDIOMA = {("ro", "RON"): "lei"}  # R5: cómo se escribe la moneda en el idioma del país


def tienda_valida(tienda: object) -> bool:
    """La tienda de ``mercados.yaml`` es una URL https de raíz (la misma regla que usa :func:`checkout_url`)."""
    return isinstance(tienda, str) and bool(_TIENDA.fullmatch(tienda.strip()))


def host_tienda(tienda: object) -> str | None:
    """Host de la tienda si es válida (:func:`tienda_valida`); si no, ``None``."""
    return urlsplit(tienda.strip()).hostname if tienda_valida(tienda) else None


def checkout_url(hosting: str, tienda: str | None) -> str:
    """``/checkout`` en Impultienda; ``<tienda>/checkout`` absoluto en Cloudflare (tienda https obligatoria)."""
    if hosting == "impultienda":
        return "/checkout"
    if hosting != "cloudflare":
        raise EntradaInvalida(f"hosting desconocido: «{hosting}» (impultienda o cloudflare)")
    if not tienda_valida(tienda):
        raise EntradaInvalida(f"la ruta Cloudflare necesita la tienda en https (config/mercados.yaml → tienda), "
                              f"tiene «{tienda}»: trovefy landing sonda --tienda https://…")
    return tienda.strip().rstrip("/") + "/checkout"


def precio_texto(precio: Decimal, moneda: str, idioma: str | None = None) -> str:
    """``14,90 €``: coma decimal y la moneda como se escribe en el idioma (``79,00 lei`` en rumano), su
    símbolo o, si no tiene, el código ISO."""
    simbolo = _MONEDA_POR_IDIOMA.get((idioma, moneda)) or _SIMBOLOS.get(moneda, moneda)
    return f"{precio:.2f}".replace(".", ",") + " " + simbolo


def version_de(html: str) -> str:
    """SHA-256 (12 hex) del HTML con ``data-tf-version`` vaciado."""
    return hashlib.sha256(_VERSION.sub('data-tf-version=""', html).encode("utf-8")).hexdigest()[:12]


def _e(texto: object) -> str:
    return html_mod.escape(str(texto), quote=True)


def _vistas(vault: Path, datos: DatosLanding) -> list[int]:
    ruta = ruta_landing(vault, datos.p_id, datos.pais) / "assets" / "vistas.json"
    if ruta.is_symlink():
        return []
    try:
        paginas = json.loads(ruta.read_text(encoding="utf-8")).get("paginas")
    except (FileNotFoundError, ValueError, AttributeError):
        return []
    return [n for n in paginas if isinstance(n, int) and not isinstance(n, bool)] if isinstance(paginas, list) else []


def _img_vista(n: int) -> str:
    srcset = ", ".join(f"assets/vista-p{n}-{w}.webp {w}w" for w in ANCHOS_IMAGEN)
    return (f'  <img data-tf-vista src="assets/vista-p{n}-{min(ANCHOS_IMAGEN)}.webp" srcset="{srcset}" '
            f'sizes="(max-width: 600px) 100vw, 480px" alt="" loading="lazy">')


def _seccion(s: dict, datos: DatosLanding, checkout: str, vistas: list[int]) -> str:
    etiqueta = "h1" if s["orden"] == 1 else "h2"
    lineas = [f'<section data-tf-seccion="{s["orden"]}" data-tf-tipo="{_e(s["tipo"])}">',
              f"  <{etiqueta} data-tf-hito>{TEXTO_PROPIO}</{etiqueta}>"]
    if s["tipo"] == "formato":
        lineas.append(f"  <p data-tf-formato><!-- texto propio: PDF, {datos.pdf_paginas} páginas --></p>")
    elif s["tipo"] == "garantia":
        lineas.append(f"  <p data-tf-garantia><!-- texto propio: {datos.garantia_dias} días --></p>")
    elif s["tipo"] == "precio":
        lineas.append(f"  <p data-tf-precio>{_e(precio_texto(datos.precio, datos.moneda, datos.idioma))}</p>")
    elif s["tipo"] == "vista_previa":
        lineas += [_img_vista(n) for n in vistas] or ["  <!-- vistas: trovefy landing medios -->"]
    elif s["tipo"] == "prueba_social":
        lineas.append('  <!-- solo reseñas reales de resenas.yaml: <blockquote data-tf-resena="<id>"> -->')
    lineas.append(f"  <p>{TEXTO_PROPIO}</p>")
    if s["cta"]:
        lineas.append(f'  <a data-tf-checkout href="{_e(checkout)}">{TEXTO_PROPIO}</a>')
    lineas.append("</section>")
    return "\n".join(lineas)


def _sin_enlace(ruta: Path) -> None:
    """``EntradaInvalida`` si ``ruta`` es un enlace simbólico (también uno colgante)."""
    if os.path.islink(ruta):
        raise EntradaInvalida(f"{ruta} es un enlace simbólico: no se lee ni se escribe a través de él")


def _carpetas(base: Path, carpeta: Path, *, crear: bool) -> bool:
    """``carpeta_segura`` con el error de entrada de /landing."""
    try:
        return carpeta_segura(base, carpeta, crear=crear)
    except ValueError as exc:
        raise EntradaInvalida(str(exc)) from None


def _yaml_texto(ruta: Path, datos: dict) -> bytes:
    """El YAML de ``datos`` listo para escribir; ``EntradaInvalida`` si algo tiene forma de secreto."""
    texto = yaml.safe_dump(datos, allow_unicode=True, sort_keys=False)
    nombre = secreto_en(datos) or buscar_secreto(texto)
    if nombre:
        raise EntradaInvalida(f"{ruta.name}: aparece algo con forma de secreto ({nombre}); no se guarda")
    return texto.encode("utf-8")


def _leer_yaml(ruta: Path) -> dict:
    """Mapa de un YAML del vault; ``{}`` si no existe. Roto o enlazado → ``EntradaInvalida``."""
    _sin_enlace(ruta)
    if not ruta.is_file():
        return {}
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise EntradaInvalida(f"{ruta.name} no se puede leer: {exc}") from None
    return datos if isinstance(datos, dict) else {}


def leer_landing_yaml(vault: Path, p_id: str, pais: str) -> dict:
    """``landing/<PAIS>/landing.yaml`` (``{}`` si aún no existe); roto o enlazado → ``EntradaInvalida``."""
    raiz = ruta_landing(Path(vault), p_id, pais)
    if not _carpetas(Path(vault), raiz, crear=False):
        return {}
    return _leer_yaml(raiz / "landing.yaml")


def _no_cambia_publicada(previo: dict, hosting: str, checkout: str, pais: str) -> None:
    """M7: una landing publicada no cambia de hosting ni de checkout sin ``rehacer`` (los anuncios apuntan ahí)."""
    if not (previo.get("url") or previo.get("publicada")):
        return
    cambios = [f"{clave} «{previo[clave]}» → «{nuevo}»" for clave, nuevo in (("hosting", hosting),
                                                                         ("checkout_url", checkout))
               if previo.get(clave) is not None and previo.get(clave) != nuevo]
    if cambios:
        raise EntradaInvalida(f"la landing de {pais} ya está publicada ({previo.get('url') or 'sin url'}) y esto "
                              f"cambia {'; '.join(cambios)}: rompe los enlaces de los anuncios. Si es a propósito, "
                              "vuelve con --rehacer")


def preparar(vault: Path, datos: DatosLanding, hosting: str, borrador: Path, *, rehacer: bool = False) -> Path:
    """Borrador (``index.html`` desde ``base.html``, ``assets/estilo.css`` y ``assets/utm.js``) y, en el vault,
    ``wireframe.yaml`` y ``landing.yaml``. Cada archivo del borrador se decide aparte: ``index.html`` y
    ``estilo.css`` que ya estén (el trabajo de Claude) no se pisan sin ``rehacer``; ``utm.js`` se renueva
    siempre. Un enlace simbólico en el borrador (aunque cuelgue) es un error. Una landing publicada no
    cambia de ``hosting`` ni de ``checkout_url`` sin ``rehacer``. Devuelve la carpeta del borrador."""
    vault, borrador = Path(vault), Path(borrador)
    checkout = checkout_url(hosting, datos.tienda)
    w = wireframe(datos)
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    ruta_ly = raiz / "landing.yaml"
    previo = leer_landing_yaml(vault, datos.p_id, datos.pais)
    if not rehacer:
        _no_cambia_publicada(previo, hosting, checkout, datos.pais)
    landing = {"p_id": datos.p_id, "pais": datos.pais, "idioma": datos.idioma, "moneda": datos.moneda,
               "precio": str(datos.precio), "angulo": datos.angulo, "promesa_h1": datos.promesa_h1,
               "hosting": hosting, "checkout_url": checkout,
               "version": previo.get("version"), "url": previo.get("url"), "publicada": previo.get("publicada")}
    meta_w = {"p_id": datos.p_id, "pais": datos.pais, "secciones": w}
    textos_vault = {raiz / "wireframe.yaml": _yaml_texto(raiz / "wireframe.yaml", meta_w),
                    ruta_ly: _yaml_texto(ruta_ly, landing)}

    _sin_enlace(borrador)
    borrador.mkdir(parents=True, exist_ok=True)
    _carpetas(borrador, borrador / "assets", crear=True)
    indice, css, utm = borrador / "index.html", borrador / "assets" / "estilo.css", borrador / "assets" / "utm.js"
    for ruta in (indice, css, utm):
        _sin_enlace(ruta)
    if rehacer or not indice.exists():
        secciones = "\n".join(_seccion(s, datos, checkout, _vistas(vault, datos)) for s in w)
        base = BASE_HTML.read_text(encoding="utf-8")
        escribir_medio(indice, base.replace("{{idioma}}", _e(datos.idioma)).replace("{{secciones}}", secciones)
                       .encode("utf-8"), base=borrador)
    if rehacer or not css.exists():
        escribir_medio(css, (datos.tokens_css + "\n" + BASE_CSS.read_text(encoding="utf-8")).encode("utf-8"),
                       base=borrador)
    escribir_medio(utm, UTM_JS.read_bytes(), base=borrador)

    for ruta, contenido in textos_vault.items():
        escribir_medio(ruta, contenido, base=vault)
    rel = raiz.relative_to(vault).as_posix()
    anadir_log(vault, "landing", f"{datos.p_id} {datos.pais}: preparar ({hosting}, {len(w)} secciones)",
               [f"{rel}/wireframe.yaml", f"{rel}/landing.yaml"])
    return borrador


def guardar(vault: Path, datos: DatosLanding, borrador: Path) -> str:
    """Copia ``index.html`` y ``assets/estilo.css`` del borrador al vault (sin secretos), ``utm.js`` del repo,
    fija ``data-tf-version`` y lo anota en ``landing.yaml``. Devuelve la versión.

    Transaccional: primero se revisan las carpetas (``carpeta_segura``), se leen el borrador y
    ``landing.yaml`` y se buscan secretos; solo entonces se escribe, en este orden: los assets,
    ``index.html`` y al final ``landing.yaml`` (la versión se anota cuando todo está en su sitio)."""
    vault, borrador = Path(vault), Path(borrador)
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    hay_raiz = _carpetas(vault, raiz, crear=False)
    if hay_raiz and os.path.lexists(raiz / "assets"):
        _carpetas(vault, raiz / "assets", crear=False)
    _sin_enlace(borrador)
    if borrador.is_dir():
        _carpetas(borrador, borrador / "assets", crear=False)
    textos = {}
    for rel in ("index.html", "assets/estilo.css"):
        ruta = borrador / rel
        if ruta.is_symlink() or not ruta.is_file():
            raise EntradaInvalida(f"falta {rel} en el borrador {borrador}: trovefy landing preparar")
        textos[rel] = ruta.read_text(encoding="utf-8")
        patron = buscar_secreto(textos[rel])
        if patron:
            raise EntradaInvalida(f"el borrador parece llevar un secreto ({patron}): no se guarda")
    html = textos["index.html"]
    if len(_VERSION.findall(html)) != 1:
        raise EntradaInvalida('index.html necesita un único data-tf-version="" en <main id="tf-landing">')
    ruta_ly = raiz / "landing.yaml"
    landing = _leer_yaml(ruta_ly) if hay_raiz else {}
    if not landing:
        raise EntradaInvalida(f"falta landing/{datos.pais}/landing.yaml: trovefy landing preparar")

    version = version_de(html)
    html = _VERSION.sub(f'data-tf-version="{version}"', html)
    landing["version"] = version
    landing_bytes = _yaml_texto(ruta_ly, landing)

    escribir_medio(raiz / "assets" / "estilo.css", textos["assets/estilo.css"].encode("utf-8"), base=vault)
    escribir_medio(raiz / "assets" / "utm.js", UTM_JS.read_bytes(), base=vault)
    escribir_medio(raiz / "index.html", html.encode("utf-8"), base=vault)
    escribir_medio(ruta_ly, landing_bytes, base=vault)
    rel = raiz.relative_to(vault).as_posix()
    anadir_log(vault, "landing", f"{datos.p_id} {datos.pais}: guardar (versión {version})",
               [f"{rel}/index.html", f"{rel}/assets/estilo.css", f"{rel}/landing.yaml"])
    return version
