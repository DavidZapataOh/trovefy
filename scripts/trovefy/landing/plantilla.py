"""Esqueleto propio de la landing, ``preparar`` (borrador + wireframe + ``landing.yaml``) y ``guardar``.

Contrato de marcado (lo usan validar, qa y publicar): ``<html lang>``; un ``<main id="tf-landing"
data-tf-version="">``; cada sección ``<section data-tf-seccion="<orden>" data-tf-tipo="<tipo>">`` con un
único ``data-tf-hito`` (su titular); botones ``<a data-tf-checkout href="<checkout_url>">``;
``data-tf-precio``, ``data-tf-formato``, ``data-tf-garantia``; reseñas ``data-tf-resena="<id>"``; vista
previa ``<img data-tf-vista src="assets/vista-p<N>-480.webp" srcset="… 480w, … 960w">``. CSS en
``assets/estilo.css`` y el único script en ``assets/utm.js`` (``defer``).

Claude escribe el texto y el diseño en el borrador (fuera del vault); ``guardar`` lo copia al vault tras
buscar secretos, con el ``utm.js`` del repo (nunca el del borrador) y la versión fijada.
"""

from __future__ import annotations

import hashlib
import html as html_mod
import json
import re
from decimal import Decimal
from pathlib import Path

import yaml

from trovefy.landing.constantes import ANCHOS_IMAGEN
from trovefy.landing.entrada import (
    DatosLanding,
    EntradaInvalida,
    ruta_landing,
    wireframe,
)
from trovefy.producto.medios import escribir_medio
from trovefy.secretos import buscar_secreto
from trovefy.vault.escritura import anadir_log, escribir_atomico
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


def checkout_url(hosting: str, tienda: str | None) -> str:
    """``/checkout`` en Impultienda; ``<tienda>/checkout`` absoluto en Cloudflare (tienda https obligatoria)."""
    if hosting == "impultienda":
        return "/checkout"
    if hosting != "cloudflare":
        raise EntradaInvalida(f"hosting desconocido: «{hosting}» (impultienda o cloudflare)")
    if not isinstance(tienda, str) or not _TIENDA.fullmatch(tienda.strip()):
        raise EntradaInvalida(f"la ruta Cloudflare necesita la tienda en https (config/mercados.yaml → tienda), "
                              f"tiene «{tienda}»: trovefy landing sonda --tienda https://…")
    return tienda.strip().rstrip("/") + "/checkout"


def precio_texto(precio: Decimal, moneda: str) -> str:
    """``14,90 €``: coma decimal y símbolo (o el código ISO si no hay símbolo)."""
    return f"{precio:.2f}".replace(".", ",") + " " + _SIMBOLOS.get(moneda, moneda)


def version_de(html: str) -> str:
    """SHA-256 (12 hex) del HTML con ``data-tf-version`` vaciado."""
    return hashlib.sha256(_VERSION.sub('data-tf-version=""', html).encode("utf-8")).hexdigest()[:12]


def _e(texto: object) -> str:
    return html_mod.escape(str(texto), quote=True)


def _vistas(vault: Path, datos: DatosLanding) -> list[int]:
    ruta = ruta_landing(vault, datos.p_id, datos.pais) / "assets" / "vistas.json"
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
        lineas.append(f"  <p data-tf-precio>{_e(precio_texto(datos.precio, datos.moneda))}</p>")
    elif s["tipo"] == "vista_previa":
        lineas += [_img_vista(n) for n in vistas] or ["  <!-- vistas: trovefy landing medios -->"]
    elif s["tipo"] == "prueba_social":
        lineas.append('  <!-- solo reseñas reales de resenas.yaml: <blockquote data-tf-resena="<id>"> -->')
    lineas.append(f"  <p>{TEXTO_PROPIO}</p>")
    if s["cta"]:
        lineas.append(f'  <a data-tf-checkout href="{_e(checkout)}">{TEXTO_PROPIO}</a>')
    lineas.append("</section>")
    return "\n".join(lineas)


def _guardar_texto(vault: Path, ruta: Path, texto: str, datos_yaml: object = None) -> None:
    nombre = (secreto_en(datos_yaml) if datos_yaml is not None else None) or buscar_secreto(texto)
    if nombre:
        raise EntradaInvalida(f"{ruta.name}: aparece algo con forma de secreto ({nombre}); no se guarda")
    escribir_atomico(ruta, texto)


def _leer_yaml(ruta: Path) -> dict:
    if not ruta.is_file():
        return {}
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise EntradaInvalida(f"{ruta.name} no se puede leer: {exc}") from None
    return datos if isinstance(datos, dict) else {}


def preparar(vault: Path, datos: DatosLanding, hosting: str, borrador: Path, *, rehacer: bool = False) -> Path:
    """Borrador (``index.html`` desde ``base.html``, ``assets/estilo.css`` y ``assets/utm.js``) y, en el vault,
    ``wireframe.yaml`` y ``landing.yaml``. Un ``index.html`` que ya esté en el borrador no se pisa sin ``rehacer``
    (es el trabajo de Claude); ``utm.js`` se renueva siempre. Devuelve la carpeta del borrador."""
    vault, borrador = Path(vault), Path(borrador)
    checkout = checkout_url(hosting, datos.tienda)
    w = wireframe(datos)
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    ruta_ly = raiz / "landing.yaml"
    previo = _leer_yaml(ruta_ly)
    landing = {"p_id": datos.p_id, "pais": datos.pais, "idioma": datos.idioma, "moneda": datos.moneda,
               "precio": str(datos.precio), "angulo": datos.angulo, "promesa_h1": datos.promesa_h1,
               "hosting": hosting, "checkout_url": checkout,
               "version": previo.get("version"), "url": previo.get("url"), "publicada": previo.get("publicada")}

    (borrador / "assets").mkdir(parents=True, exist_ok=True)
    indice = borrador / "index.html"
    if rehacer or not indice.exists():
        secciones = "\n".join(_seccion(s, datos, checkout, _vistas(vault, datos)) for s in w)
        base = BASE_HTML.read_text(encoding="utf-8")
        indice.write_text(base.replace("{{idioma}}", _e(datos.idioma)).replace("{{secciones}}", secciones),
                          encoding="utf-8")
        (borrador / "assets" / "estilo.css").write_text(datos.tokens_css + "\n" + BASE_CSS.read_text(encoding="utf-8"),
                                                        encoding="utf-8")
    (borrador / "assets" / "utm.js").write_bytes(UTM_JS.read_bytes())

    meta_w = {"p_id": datos.p_id, "pais": datos.pais, "secciones": w}
    _guardar_texto(vault, raiz / "wireframe.yaml", yaml.safe_dump(meta_w, allow_unicode=True, sort_keys=False), meta_w)
    _guardar_texto(vault, ruta_ly, yaml.safe_dump(landing, allow_unicode=True, sort_keys=False), landing)
    rel = raiz.relative_to(vault).as_posix()
    anadir_log(vault, "landing", f"{datos.p_id} {datos.pais}: preparar ({hosting}, {len(w)} secciones)",
               [f"{rel}/wireframe.yaml", f"{rel}/landing.yaml"])
    return borrador


def guardar(vault: Path, datos: DatosLanding, borrador: Path) -> str:
    """Copia ``index.html`` y ``assets/estilo.css`` del borrador al vault (sin secretos), ``utm.js`` del repo,
    fija ``data-tf-version`` y lo anota en ``landing.yaml``. Devuelve la versión."""
    vault, borrador = Path(vault), Path(borrador)
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
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
    landing = _leer_yaml(ruta_ly)
    if not landing:
        raise EntradaInvalida(f"falta landing/{datos.pais}/landing.yaml: trovefy landing preparar")

    version = version_de(html)
    html = _VERSION.sub(f'data-tf-version="{version}"', html)
    escribir_atomico(raiz / "index.html", html)
    escribir_medio(raiz / "assets" / "estilo.css", textos["assets/estilo.css"].encode("utf-8"), base=vault)
    escribir_medio(raiz / "assets" / "utm.js", UTM_JS.read_bytes(), base=vault)
    landing["version"] = version
    _guardar_texto(vault, ruta_ly, yaml.safe_dump(landing, allow_unicode=True, sort_keys=False), landing)
    rel = raiz.relative_to(vault).as_posix()
    anadir_log(vault, "landing", f"{datos.p_id} {datos.pais}: guardar (versión {version})",
               [f"{rel}/index.html", f"{rel}/assets/estilo.css", f"{rel}/landing.yaml"])
    return version
