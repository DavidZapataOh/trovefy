"""Validación estática de ``landing/<PAIS>/`` (``html.parser``): estructura, botones, idioma, prueba social y
origen de todo. Cada fallo es una frase que dice qué y dónde; los avisos no bloquean.

Prueba social solo real (D-01): una reseña entra solo desde ``resenas.yaml`` con :func:`anadir_resena`
(fecha, país y fuente: el pedido o el email de origen).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from trovefy.landing.constantes import SECCIONES_MAX, SECCIONES_MIN
from trovefy.landing.diacriticos import revisar_texto
from trovefy.landing.entrada import (
    DatosLanding,
    EntradaInvalida,
    leer_resenas,
    resena_completa,
    ruta_landing,
)
from trovefy.landing.medios import FIJOS, MANIFIESTO, ORIGENES, VISTAS
from trovefy.landing.plantilla import UTM_JS, precio_texto, version_de
from trovefy.secretos import buscar_secreto
from trovefy.vault.escritura import anadir_log, escribir_atomico
from trovefy.vault.producto import secreto_en

PERMITIDAS_FIJAS = frozenset({"PDF", "A4"})
DESCRIPCION_MAX = 160  # caracteres que muestran los buscadores
LARGO_MIN, LARGO_MAX = 0.5, 2.0  # fracción de las palabras de la referencia (aviso)
PIXEL_JS = "pixel.js"  # resolución 23: solo en la ruta Cloudflare
HOSTS_PIXEL = frozenset({"connect.facebook.net", "www.facebook.com"})
_VACIOS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track",
                     "wbr"})
_INVISIBLES = frozenset({"head", "title", "script", "style", "noscript", "template"})
_URL_CSS = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_IMPORT_CSS = re.compile(r"@import\s+(['\"])(.*?)\1", re.IGNORECASE)
_ESTRELLAS = re.compile("[★☆⭐\U0001f31f]")
_PAGINAS = re.compile(r"(\d+)\s*(?:страниц|pagin|págin|page)", re.IGNORECASE)
_EVENTO_PIXEL = re.compile(r"fbq\(\s*['\"](?:track|trackCustom|trackSingle)['\"]\s*,\s*['\"]([^'\"]+)['\"]")


@dataclass(frozen=True)
class Resultado:
    ok: bool
    fallos: tuple[str, ...]
    avisos: tuple[str, ...]


@dataclass(eq=False)  # se compara por identidad: dos secciones iguales siguen siendo dos
class _Seccion:
    orden: str
    tipo: str
    hitos: int = 0
    botones: list[str] = field(default_factory=list)
    texto: list[str] = field(default_factory=list)
    vistas: int = 0


class _Lector(HTMLParser):
    """Recorre el HTML una vez y guarda lo que comprueban las reglas."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pila: list[tuple[str, list[str]]] = []  # (etiqueta, capturas abiertas en ella)
        self.lang: str | None = None
        self.titulo: list[str] | None = None
        self.descripcion: str | None = None
        self.versiones: list[str] = []
        self.secciones: list[_Seccion] = []
        self._abiertas: list[_Seccion | None] = []  # sección de cada nivel de la pila
        self.botones: list[tuple[int | None, str]] = []  # (índice de sección, href)
        self.capturas: dict[str, list[list[str]]] = {"precio": [], "formato": [], "garantia": [], "resena": []}
        self.resenas: list[str] = []
        self.urls: list[tuple[str, str, bool]] = []  # (dónde, url, es recurso que se carga)
        self.scripts: list[tuple[str | None, bool]] = []  # (src, lleva código en línea)
        self.prohibidas: list[str] = []
        self.manejadores: list[str] = []
        self.estilos: list[str] = []
        self.visible: list[str] = []
        self._en_script = False

    # -- utilidades
    def _seccion(self) -> _Seccion | None:
        return next((s for s in reversed(self._abiertas) if s is not None), None)

    def _invisible(self) -> bool:
        return any(t in _INVISIBLES for t, _ in self.pila)

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        for k in a:
            if k.startswith("on"):
                self.manejadores.append(f"{k} en <{tag}>")
        if "style" in a:
            self.estilos.append(a["style"])
        if tag in ("iframe", "form", "object", "embed", "frame", "frameset"):
            self.prohibidas.append(f"<{tag}>")
        if tag == "html" and "lang" in a:
            self.lang = a["lang"]
        if tag == "title":
            self.titulo = []
        if tag == "meta" and a.get("name", "").lower() == "description":
            self.descripcion = a.get("content", "")
        if tag == "main" and a.get("id") == "tf-landing" and "data-tf-version" in a:
            self.versiones.append(a["data-tf-version"])
        if tag == "script":
            self.scripts.append((a.get("src"), False))
        seccion_nueva = None
        if tag == "section" and "data-tf-seccion" in a:
            seccion_nueva = _Seccion(a["data-tf-seccion"], a.get("data-tf-tipo", ""))
            self.secciones.append(seccion_nueva)
        actual = seccion_nueva or self._seccion()
        if "data-tf-hito" in a and actual is not None:
            actual.hitos += 1
        if tag == "a" and "data-tf-checkout" in a:
            href = a.get("href", "")
            idx = next((i for i, s in enumerate(self.secciones) if s is actual), None)
            self.botones.append((idx, href))
            if actual is not None:
                actual.botones.append(href)
        if tag == "img" and "data-tf-vista" in a and actual is not None:
            actual.vistas += 1
        if tag == "img" and a.get("alt") and actual is not None:
            actual.texto.append(a["alt"])
            self.visible.append(a["alt"])
        for k in ("src", "href", "srcset", "poster", "data", "action"):
            if k in a:
                carga = not (tag == "a" and k == "href")
                if k == "srcset":
                    for parte in a[k].split(","):
                        if parte.strip():
                            self.urls.append((f"srcset de <{tag}>", parte.strip().split()[0], True))
                else:
                    self.urls.append((f"{k} de <{tag}>", a[k], carga))
        if "data-tf-resena" in a:
            self.resenas.append(a["data-tf-resena"])
        capturas = []
        for clave in ("precio", "formato", "garantia", "resena"):
            if f"data-tf-{clave}" in a:
                self.capturas[clave].append([a[f"data-tf-{clave}"]] if clave == "resena" else [])
                capturas.append(clave)
        if tag not in _VACIOS:
            self.pila.append((tag, capturas))
            self._abiertas.append(seccion_nueva)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VACIOS and self.pila and self.pila[-1][0] == tag:
            self.pila.pop()
            self._abiertas.pop()

    def handle_endtag(self, tag):
        if not any(t == tag for t, _ in self.pila):
            return
        while self.pila:
            t, _ = self.pila.pop()
            self._abiertas.pop()
            if t == tag:
                break

    def handle_data(self, data):
        if self.titulo is not None and any(t == "title" for t, _ in self.pila):
            self.titulo.append(data)
        if any(t == "script" for t, _ in self.pila) and data.strip():
            src, _ = self.scripts[-1]
            self.scripts[-1] = (src, True)
        if any(t == "style" for t, _ in self.pila):
            self.estilos.append(data)
        if self._invisible():
            return
        self.visible.append(data)
        s = self._seccion()
        if s is not None:
            s.texto.append(data)
        for _, capturas in self.pila:
            for clave in capturas:
                self.capturas[clave][-1].append(data)


def _palabras(texto: str) -> int:
    return len(re.findall(r"\w+", texto))


def _limpio(partes: list[str]) -> str:
    return " ".join(" ".join(partes).split())


def _leer_yaml(ruta: Path) -> dict | None:
    if not ruta.is_file():
        return None
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return datos if isinstance(datos, dict) else None


def _leer_json(ruta: Path) -> dict | None:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


class _Origen:
    """Qué URL puede aparecer: relativa (los recursos bajo ``assets/``), ``#…``, el checkout, el dominio
    propio y la tienda; en la ruta Cloudflare, además, los hosts del píxel (resolución 23)."""

    def __init__(self, checkout: str, dominio: str | None, tienda: str | None, pixel: bool) -> None:
        self.checkout = checkout
        self.hosts = {h for h in (dominio, f"www.{dominio}" if dominio else None) if h}
        if tienda:
            self.hosts.add(urlsplit(tienda).hostname or "")
        if pixel:
            self.hosts |= HOSTS_PIXEL

    def motivo(self, url: str, carga: bool) -> str | None:
        u = url.strip()
        if not u or u.startswith("#") or u == self.checkout:
            return None
        sp = urlsplit(u)
        if not sp.scheme and not sp.netloc:
            if carga and (not sp.path.startswith("assets/") or ".." in sp.path.split("/")):
                return "un recurso propio va dentro de assets/"
            return None
        if sp.scheme == "https" and sp.hostname in self.hosts:
            return None
        return "origen no permitido (solo relativo, el dominio propio, la tienda o el checkout)"


def _r_estructura(lec: _Lector, wf: list[dict], fallos: list[str]) -> None:
    n = len(lec.secciones)
    if not SECCIONES_MIN <= n <= SECCIONES_MAX:
        fallos.append(f"la landing tiene {n} secciones; hacen falta {SECCIONES_MIN}–{SECCIONES_MAX}")
    for i, s in enumerate(lec.secciones, 1):
        if s.orden != str(i):
            fallos.append(f"sección {i}: data-tf-seccion=\"{s.orden}\" (van de 1 a N en orden)")
    esperados = [str(x.get("tipo")) for x in wf]
    reales = [s.tipo for s in lec.secciones]
    if reales != esperados:
        for i, (r, e) in enumerate(zip(reales, esperados, strict=False), 1):
            if r != e:
                fallos.append(f"sección {i}: es «{r}» y el wireframe pide «{e}» en ese orden")
        if len(reales) != len(esperados):
            fallos.append(f"el wireframe tiene {len(esperados)} secciones y la landing {len(reales)}")
    for i, s in enumerate(lec.secciones, 1):
        if s.hitos != 1:
            fallos.append(f"sección {i} ({s.tipo}): tiene {s.hitos} data-tf-hito; va uno (su titular)")


def _r_botones(lec: _Lector, wf: list[dict], checkout: str, fallos: list[str]) -> None:
    for i, (s, ref) in enumerate(zip(lec.secciones, wf, strict=False), 1):
        if ref.get("cta") and not s.botones:
            fallos.append(f"sección {i} ({s.tipo}): la referencia lleva botón aquí y falta a[data-tf-checkout]")
    primera_cta = next((i for i, ref in enumerate(wf) if ref.get("cta")), None)
    if lec.botones and primera_cta is not None and lec.botones[0][0] != primera_cta:
        donde = "fuera de las secciones" if lec.botones[0][0] is None else f"en la sección {lec.botones[0][0] + 1}"
        fallos.append(f"el botón principal está {donde}: va donde lo tenía la referencia (sección {primera_cta + 1})")
    if not lec.botones:
        fallos.append("no hay ningún botón a[data-tf-checkout]")
    for _, href in lec.botones:
        if href != checkout:
            fallos.append(f"a[data-tf-checkout] con href «{href}»; landing.yaml dice «{checkout}»")


def _r_idioma(lec: _Lector, datos: DatosLanding, fallos: list[str]) -> None:
    permitidas = PERMITIDAS_FIJAS | {datos.marca, *datos.marca.split()}
    titulo = _limpio(lec.titulo or [])
    if not titulo:
        fallos.append("falta <title>")
    if lec.descripcion is None or not lec.descripcion.strip():
        fallos.append('falta <meta name="description">')
    if lec.lang != datos.idioma:
        fallos.append(f"<html lang=\"{lec.lang or ''}\">; el país habla «{datos.idioma}»")
    for nombre, texto in (("título", titulo), ("descripción", lec.descripcion or ""),
                          ("texto visible", _limpio(lec.visible))):
        for h in revisar_texto(texto, datos.idioma, permitidas):
            if h.bloquea:
                fallos.append(f"{nombre}: {h.regla}: {h.detalle}")


def _r_datos(lec: _Lector, datos: DatosLanding, fallos: list[str]) -> None:
    formatos = [_limpio(x) for x in lec.capturas["formato"]]
    if not formatos:
        fallos.append("falta data-tf-formato (PDF y su número de páginas)")
    for f in formatos:
        numeros = re.findall(r"\d+", f)
        falsas = [n for n in _PAGINAS.findall(f) if int(n) != datos.pdf_paginas]
        if "PDF" not in f or str(datos.pdf_paginas) not in numeros or falsas:
            fallos.append(f"data-tf-formato «{f}»: debe decir PDF y {datos.pdf_paginas} páginas (las del PDF vigente)")
    garantias = [_limpio(x) for x in lec.capturas["garantia"]]
    if not garantias:
        fallos.append("falta data-tf-garantia")
    for g in garantias:
        if str(datos.garantia_dias) not in re.findall(r"\d+", g):
            fallos.append(f"data-tf-garantia «{g}»: no dice los {datos.garantia_dias} días de OFERTA.md")
    esperado = precio_texto(datos.precio, datos.moneda)
    importe, simbolo = esperado.split(" ")
    precios = [_limpio(x) for x in lec.capturas["precio"]]
    if not precios:
        fallos.append("falta data-tf-precio")
    for p in precios:
        if importe not in p or simbolo not in p:
            fallos.append(f"data-tf-precio «{p}»: debe decir {importe} y {simbolo}")


def _r_prueba_social(lec: _Lector, datos: DatosLanding, vault: Path, fallos: list[str]) -> None:
    try:
        resenas = leer_resenas(vault, datos.p_id, datos.pais)
    except EntradaInvalida as exc:
        fallos.append(str(exc))
        resenas = []
    reales = {}
    for r in resenas:
        if not resena_completa(r):
            ident = r.get("id") if isinstance(r, dict) else None
            fallos.append(f"resenas.yaml: la reseña «{ident}» está incompleta (id, texto, fecha, pais, fuente)")
        elif r["pais"] != datos.pais:
            fallos.append(f"resenas.yaml: la reseña {r['id']} es de {r['pais']}, no de {datos.pais}")
        else:
            reales[r["id"]] = r
    textos = {}
    for captura in lec.capturas["resena"]:
        textos.setdefault(captura[0], []).append(_limpio(captura[1:]))
    for rid in lec.resenas:
        if rid not in reales:
            fallos.append(f"data-tf-resena=\"{rid}\" no está en resenas.yaml: solo reseñas reales (D-01)")
            continue
        real = " ".join(reales[rid]["texto"].split())
        if any(real not in t for t in textos.get(rid, [])):
            fallos.append(f"data-tf-resena=\"{rid}\": el texto no es el de resenas.yaml")
    if _ESTRELLAS.search(_limpio(lec.visible)):
        fallos.append("hay estrellas (★/⭐): una valoración que no sale de reseñas reales no va (D-01)")
    tipos = [s.tipo for s in lec.secciones]
    if not reales:
        if "prueba_social" in tipos:
            fallos.append("sección prueba_social sin reseñas reales: va vista previa + garantía (D-01)")
        vistas = [s for s in lec.secciones if s.tipo == "vista_previa"]
        if not vistas or max(s.vistas for s in vistas) < 2:
            fallos.append("sin reseñas reales falta la vista previa: una sección vista_previa con ≥ 2 "
                          "img[data-tf-vista]")
        if "garantia" not in tipos:
            fallos.append("sin reseñas reales falta la sección garantia")


def _r_assets(raiz: Path, datos: DatosLanding, lec: _Lector, pixel: bool, fallos: list[str]) -> None:
    assets = raiz / "assets"
    vistas = _leer_json(assets / VISTAS)
    if vistas is None:
        fallos.append(f"falta assets/{VISTAS}: trovefy landing medios")
    elif vistas.get("sha256") != datos.pdf_sha256:
        fallos.append(f"la vista previa es de {vistas.get('pdf')}: rehaz los medios con `trovefy landing medios` "
                      f"(el PDF vigente es {datos.pdf.name})")
    manifiesto = _leer_json(assets / MANIFIESTO)
    medios = {}
    if manifiesto is None or not isinstance(manifiesto.get("medios"), list):
        fallos.append(f"falta assets/{MANIFIESTO} (el origen de cada medio): trovefy landing medios")
    else:
        for m in manifiesto["medios"]:
            if isinstance(m, dict) and m.get("origen") in ORIGENES and isinstance(m.get("archivo"), str):
                medios[m["archivo"]] = m
            else:
                fallos.append(f"assets/{MANIFIESTO}: entrada sin origen válido: {m!r:.80}")
    fijos = set(FIJOS) | ({PIXEL_JS} if pixel else set())
    presentes = set()
    if assets.is_dir():
        for p in sorted(assets.iterdir()):
            presentes.add(p.name)
            if p.name in fijos:
                continue
            if p.is_symlink() or not p.is_file():
                fallos.append(f"assets/{p.name} no es un archivo normal")
            elif p.name not in medios:
                fallos.append(f"assets/{p.name} no tiene origen en {MANIFIESTO}: material sin origen no va (contrato 4)")
            elif hashlib.sha256(p.read_bytes()).hexdigest() != medios[p.name].get("sha256"):
                fallos.append(f"assets/{p.name}: su sha256 no es el de {MANIFIESTO} (rehaz los medios)")
    for _, url, carga in lec.urls:
        sp = urlsplit(url.strip())
        if carga and not sp.scheme and not sp.netloc and sp.path.startswith("assets/"):
            nombre = sp.path[len("assets/"):]
            if "/" not in nombre and nombre not in presentes:
                fallos.append(f"el HTML usa assets/{nombre} y no existe")


def _r_scripts(raiz: Path, lec: _Lector, pixel: bool, fallos: list[str]) -> None:
    validos = {"assets/utm.js"} | ({f"assets/{PIXEL_JS}"} if pixel else set())
    for src, en_linea in lec.scripts:
        if en_linea or src not in validos:
            fallos.append(f"<script{f' src={src!r}' if src else ''}>: el único script es assets/utm.js"
                          + (" (y assets/pixel.js en Cloudflare)" if pixel else ""))
    utm = raiz / "assets" / "utm.js"
    if not utm.is_file() or utm.read_bytes() != UTM_JS.read_bytes():
        fallos.append("assets/utm.js no es el de templates/landing/: vuelve a trovefy landing guardar")
    if pixel and (raiz / "assets" / PIXEL_JS).is_file():
        eventos = set(_EVENTO_PIXEL.findall((raiz / "assets" / PIXEL_JS).read_text(encoding="utf-8")))
        if eventos - {"PageView", "ViewContent"}:
            fallos.append(f"assets/{PIXEL_JS}: solo PageView y ViewContent (lleva {', '.join(sorted(eventos))})")
    for x in sorted(set(lec.prohibidas)):
        fallos.append(f"{x}: no va en la landing")
    for m in lec.manejadores:
        fallos.append(f"manejador {m}: no va en la landing (sin JS en línea)")


def validar(vault: Path, datos: DatosLanding) -> Resultado:
    """Comprueba ``landing/<PAIS>/`` contra el wireframe, la oferta, el PDF vigente y sus manifiestos."""
    vault = Path(vault)
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    fallos: list[str] = []
    avisos: list[str] = []
    indice = raiz / "index.html"
    if not indice.is_file():
        return Resultado(False, (f"falta landing/{datos.pais}/index.html: trovefy landing guardar",), ())
    html = indice.read_text(encoding="utf-8")
    css_ruta = raiz / "assets" / "estilo.css"
    css = css_ruta.read_text(encoding="utf-8") if css_ruta.is_file() else ""
    if not css:
        fallos.append("falta assets/estilo.css")
    wf_yaml = _leer_yaml(raiz / "wireframe.yaml")
    wf = wf_yaml.get("secciones") if wf_yaml else None
    landing = _leer_yaml(raiz / "landing.yaml") or {}
    if not isinstance(wf, list):
        fallos.append("falta wireframe.yaml: trovefy landing preparar")
        wf = []
    checkout = landing.get("checkout_url")
    if not isinstance(checkout, str) or not checkout:
        fallos.append("landing.yaml no trae checkout_url: trovefy landing preparar")
        checkout = ""
    pixel = landing.get("hosting") == "cloudflare"

    lec = _Lector()
    lec.feed(html)
    lec.close()

    _r_estructura(lec, wf, fallos)
    _r_botones(lec, wf, checkout, fallos)
    _r_idioma(lec, datos, fallos)
    _r_datos(lec, datos, fallos)
    _r_prueba_social(lec, datos, vault, fallos)
    _r_assets(raiz, datos, lec, pixel, fallos)
    origen = _Origen(checkout, datos.dominio, datos.tienda, pixel)
    for donde, url, carga in lec.urls:
        if (motivo := origen.motivo(url, carga)) is not None:
            fallos.append(f"{donde}: «{url}»: {motivo}")
    for nombre, texto in (("estilo en línea", "\n".join(lec.estilos)), ("assets/estilo.css", css)):
        for m in [*_URL_CSS.finditer(texto), *_IMPORT_CSS.finditer(texto)]:
            url = m.group(2)
            if url.startswith("data:"):
                fallos.append(f"{nombre}: «{url[:40]}…»: sin data: en el CSS")
            elif (motivo := origen.motivo(url, carga=False)) is not None:
                fallos.append(f"{nombre}: «{url}»: {motivo}")
    _r_scripts(raiz, lec, pixel, fallos)
    if len(lec.versiones) != 1:
        fallos.append('falta <main id="tf-landing" data-tf-version="…"> (uno solo)')
    elif lec.versiones[0] != version_de(html):
        fallos.append("data-tf-version no cuadra con el HTML (¿editado a mano tras guardar?): vuelve a "
                      "trovefy landing guardar")
    for nombre, texto in (("index.html", html), ("assets/estilo.css", css)):
        patron = buscar_secreto(texto)
        if patron:
            fallos.append(f"{nombre}: aparece algo con forma de secreto ({patron})")

    refs = {str(s.orden): s for s in datos.secciones}
    for s in lec.secciones:
        ref = refs.get(s.orden)
        if ref is None:
            continue
        n = _palabras(_limpio(s.texto))
        if not LARGO_MIN * ref.palabras <= n <= LARGO_MAX * ref.palabras:
            avisos.append(f"sección {s.orden} ({s.tipo}): {n} palabras; la referencia tiene {ref.palabras}")
    if lec.descripcion and len(lec.descripcion) > DESCRIPCION_MAX:
        avisos.append(f"la meta description tiene {len(lec.descripcion)} caracteres (más de {DESCRIPCION_MAX})")
    fallos = list(dict.fromkeys(fallos))
    return Resultado(not fallos, tuple(fallos), tuple(avisos))


def anadir_resena(vault: Path, p_id: str, pais: str, texto: str, fecha: date, fuente: str) -> str:
    """Añade una reseña real a ``landing/<PAIS>/resenas.yaml`` con id ``r-<AAAAMMDD>-<n>``; devuelve el id.

    ``ValueError`` si falta el texto o la fuente (el pedido o el email de origen) o si algo parece un secreto.
    """
    vault = Path(vault)
    pais = pais.strip().upper()
    if not isinstance(fuente, str) or not fuente.strip():
        raise ValueError("una reseña sin fuente (el pedido o el email de origen) no entra")
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("la reseña no trae texto")
    if not isinstance(fecha, date):
        raise ValueError("fecha de la reseña mal escrita (AAAA-MM-DD)")  # noqa: TRY004 - error de uso
    raiz = ruta_landing(vault, p_id, pais)
    try:
        previas = leer_resenas(vault, p_id, pais)
    except EntradaInvalida as exc:
        raise ValueError(str(exc)) from None
    prefijo = f"r-{fecha:%Y%m%d}-"
    usados = {r.get("id") for r in previas if isinstance(r, dict)}
    n = 1
    while f"{prefijo}{n}" in usados:
        n += 1
    rid = f"{prefijo}{n}"
    nueva = {"id": rid, "texto": " ".join(texto.split()), "fecha": fecha.isoformat(), "pais": pais,
             "fuente": fuente.strip()}
    datos = {"resenas": [*previas, nueva]}
    contenido = yaml.safe_dump(datos, allow_unicode=True, sort_keys=False)
    if secreto_en(datos) or buscar_secreto(contenido):
        raise ValueError("la reseña trae algo con forma de secreto; no se guarda")
    ruta = raiz / "resenas.yaml"
    escribir_atomico(ruta, contenido)
    anadir_log(vault, "landing", f"{p_id} {pais}: reseña real {rid} (fuente: {nueva['fuente']})",
               [ruta.relative_to(vault).as_posix()])
    return rid
