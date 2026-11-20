"""Lo que la tanda necesita del vault (plan 21, Tarea 2): oferta, brandbook, escalera, landing, entregable y
referencia. Solo lectura. Dato ausente = «no medido: …» en ``motivos``, nunca una estimación (§4.0).

La tanda vive en ``productos/<p-id>/creativos/<PAIS>/t<N>/`` (N = 1, 2…; el grupo es ``G<N>``, L1 1:02:20).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from trovefy.config import mercados
from trovefy.producto.medios import leer_manifiesto
from trovefy.tracking.modelo import PLANTILLA_UTM
from trovefy.vault import frontmatter
from trovefy.vault.producto import estado_pais, ruta_producto

ESTADOS_TANDA = ("con_checkout", "listo")
ESTADOS_REHACER = (*ESTADOS_TANDA, "montado")  # resolución 7: rehacer tras un veto con el país en montado
ESTADOS_RENOVAR = ("test", "candidato", "pre_escala", "variaciones", "agresiva", "portfolio")
_TANDA = re.compile(r"t([1-9]\d{0,2})")
_PAIS = re.compile(r"[A-Z]{2}")
_SIMBOLOS = {"EUR": "€", "USD": "US$", "GBP": "£"}


class EstadoNoPermite(ValueError):
    """El producto-país no está en un estado en el que /creativos pueda trabajar."""


@dataclass(frozen=True)
class Contexto:
    vault: Path
    producto: str
    pais: str
    idioma: str
    moneda: str
    estado: str
    marca: str | None
    tono: str | None
    paleta: dict
    tipografias: dict[str, str]
    precio_front: Decimal | None
    landing_url: str | None
    url_anuncio: str | None
    angulo_oferta: str | None
    promesa: str | None
    villano: str | None
    mecanismo: str | None
    mecanismo_pasos: tuple[str, ...]
    avatar: str | None
    objeciones: tuple[str, ...]
    angulos_referencia: tuple[str, ...]
    hooks_referencia: tuple[str, ...]
    mezcla_imagenes_pct: int | None
    pdf_vigente: Path | None
    medios_propios: dict[str, Path]
    oferta: dict = field(default_factory=dict, repr=False)
    motivos: tuple[str, ...] = ()

    @property
    def carpeta(self) -> Path:
        return Path(self.vault) / "productos" / self.producto

    @property
    def precio_texto(self) -> str | None:
        return precio_local(self.precio_front, self.moneda)


def precio_local(precio: Decimal | None, moneda: str) -> str | None:
    """«13,90 €»: el precio del front en el formato del país (coma decimal y el símbolo detrás)."""
    if precio is None:
        return None
    return f"{precio.quantize(Decimal('0.01'))}".replace(".", ",") + f" {_SIMBOLOS.get(moneda, moneda)}"


def url_con_utm(landing_url: str) -> str:
    """``landing_url`` + ``?``/``&`` + la plantilla UTM literal (§4.9). La landing va en https y sin espacios."""
    if not isinstance(landing_url, str) or not landing_url.startswith("https://") or any(c.isspace()
                                                                                          for c in landing_url):
        raise ValueError(f"la landing debe ser https:// y sin espacios: «{landing_url}»")
    return landing_url + ("&" if "?" in landing_url else "?") + PLANTILLA_UTM


def ruta_tanda(vault: Path, producto: str, pais: str, tanda: str) -> Path:
    ruta_producto(vault, producto)  # valida el p-id
    if not isinstance(pais, str) or not _PAIS.fullmatch(pais):
        raise ValueError(f"país mal escrito: «{pais}»; dos letras en mayúsculas")
    if not isinstance(tanda, str) or not _TANDA.fullmatch(tanda):
        raise ValueError(f"tanda mal escrita: «{tanda}»; usa t1, t2…")
    return Path(vault) / "productos" / producto / "creativos" / pais / tanda


def numero_tanda(tanda: str) -> int:
    m = _TANDA.fullmatch(tanda or "")
    if not m:
        raise ValueError(f"tanda mal escrita: «{tanda}»; usa t1, t2…")
    return int(m.group(1))


def tandas(vault: Path, producto: str, pais: str) -> list[str]:
    base = ruta_tanda(vault, producto, pais, "t1").parent
    if not base.is_dir():
        return []
    return sorted((p.name for p in base.iterdir() if p.is_dir() and _TANDA.fullmatch(p.name)), key=numero_tanda)


def siguiente_tanda(vault: Path, producto: str, pais: str) -> tuple[str, int]:
    """``("t1", 1)`` si no hay ninguna; si no, la siguiente al número más alto (nunca reutiliza uno)."""
    hechas = tandas(vault, producto, pais)
    n = numero_tanda(hechas[-1]) + 1 if hechas else 1
    return f"t{n}", n


def _meta(ruta: Path) -> dict:
    if not ruta.is_file():
        return {}
    try:
        meta, _ = frontmatter.leer(ruta)
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _txt(v: object) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


_MEZCLA = re.compile(r"imagen\D{0,3}(\d{1,3})\s*%|(\d{1,3})\s*%\s*imagen", re.IGNORECASE)


def mezcla_imagenes(texto: str) -> int | None:
    """% de imágenes del top de ``referencia/mezcla.md`` (sección «Top»); ``None`` si no está medido."""
    top = texto.split("## Top", 1)[1] if "## Top" in texto else texto
    top = top.split("\n## ", 1)[0]
    if "no medido" in top.lower() and not _MEZCLA.search(top):
        return None
    m = _MEZCLA.search(top)
    if not m:
        return None
    pct = int(m.group(1) or m.group(2))
    return pct if 0 <= pct <= 100 else None


def _precio(v: object) -> Decimal | None:
    if v is None or isinstance(v, (bool, float)):
        return None
    try:
        d = Decimal(str(v).strip().replace(",", "."))
    except InvalidOperation:
        return None
    return d if d.is_finite() and d > 0 else None


def cargar_contexto(vault: Path, producto: str, pais: str, cfg=None, *, renovar: bool = False,
                    rehacer: bool = False) -> Contexto:
    vault = Path(vault)
    estado = estado_pais(vault, producto, pais)
    permitidos = ESTADOS_RENOVAR if renovar else (ESTADOS_REHACER if rehacer else ESTADOS_TANDA)
    if estado not in permitidos:
        if renovar:
            raise EstadoNoPermite(f"{pais} está en «{estado or 'sin estado'}»: la renovación es con el test vivo")
        raise EstadoNoPermite(f"{pais} está en «{estado or 'sin estado'}»: primero /listo")
    carpeta = vault / "productos" / producto
    motivos: list[str] = []
    mercado = None
    ruta_mercados = vault / "config" / "mercados.yaml"
    if ruta_mercados.is_file():
        mercado = mercados.cargar(ruta_mercados).get(pais)
    if mercado is None:
        raise ValueError(f"{pais} no está en config/mercados.yaml")

    producto_meta = _meta(carpeta / "PRODUCTO.md")
    bloque = ((producto_meta.get("paises") or {}).get(pais) or {}) if isinstance(producto_meta.get("paises"),
                                                                                 dict) else {}
    landing = bloque.get("landing") if isinstance(bloque.get("landing"), dict) else {}
    landing_url = _txt(landing.get("url"))
    url_anuncio = None
    if landing_url is None:
        motivos.append("no medido: falta paises.<PAIS>.landing.url en PRODUCTO.md")
    else:
        url_anuncio = url_con_utm(landing_url)

    oferta = _meta(carpeta / "OFERTA.md")
    core = oferta.get("core") if isinstance(oferta.get("core"), dict) else {}
    if not core:
        motivos.append("no medido: OFERTA.md sin core")
    bonos = core.get("bonos") if isinstance(core.get("bonos"), list) else []
    objeciones = tuple(o for b in bonos if isinstance(b, dict) and (o := _txt(b.get("objecion"))))

    brand = _meta(carpeta / "BRANDBOOK.md")
    tipos = {}
    for t in brand.get("tipografias") or []:
        if isinstance(t, dict) and _txt(t.get("uso")) and _txt(t.get("familia")):
            tipos[t["uso"].strip()] = t["familia"].strip()
    if not brand:
        motivos.append("no medido: falta BRANDBOOK.md")

    escalera = _meta(carpeta / "ESCALERA.md")
    esc_pais = ((escalera.get("paises") or {}).get(pais) or {}) if isinstance(escalera.get("paises"), dict) else {}
    pasos = esc_pais.get("pasos") if isinstance(esc_pais.get("pasos"), dict) else {}
    front = pasos.get("front") if isinstance(pasos.get("front"), dict) else {}
    precio = _precio(front.get("precio"))
    if precio is None:
        motivos.append("no medido: precio del front en ESCALERA.md")
    moneda = _txt(esc_pais.get("moneda")) or mercado.moneda

    mezcla_pct = None
    ruta_mezcla = carpeta / "referencia" / "mezcla.md"
    if ruta_mezcla.is_file():
        mezcla_pct = mezcla_imagenes(ruta_mezcla.read_text(encoding="utf-8"))
    if mezcla_pct is None:
        motivos.append("no medido: mezcla del competidor (referencia/mezcla.md)")
    angulos_ref = tuple(a for a in (oferta.get("angulos_referencia") or []) if isinstance(a, str) and a.strip())
    hooks_ref = ()
    ruta_anuncios = carpeta / "referencia" / "anuncios.md"
    if ruta_anuncios.is_file():
        hooks_ref = tuple(dict.fromkeys(m.strip() for m in re.findall(r"(?im)^\s*-?\s*hook:\s*(.+)$",
                                                                       ruta_anuncios.read_text(encoding="utf-8"))))

    pdf = None
    entregable = producto_meta.get("entregable") if isinstance(producto_meta.get("entregable"), dict) else {}
    vigente = entregable.get(mercado.idioma) if isinstance(entregable.get(mercado.idioma), dict) else {}
    principal = vigente.get("principal") if isinstance(vigente.get("principal"), dict) else {}
    if _txt(principal.get("pdf")):
        candidato = (carpeta / principal["pdf"]).resolve()
        if candidato.is_file() and carpeta.resolve() in candidato.parents:
            pdf = candidato
    if pdf is None:
        motivos.append("no medido: PDF vigente del entregable")

    medios: dict[str, Path] = {}
    try:
        for id_, e in leer_manifiesto(carpeta / "entregable").items():
            medios[id_] = carpeta / "entregable" / "medios" / e["archivo"]
    except ValueError as exc:
        motivos.append(f"no medido: medios del entregable ({exc})")

    return Contexto(
        vault=vault, producto=producto, pais=pais, idioma=mercado.idioma, moneda=moneda, estado=estado,
        marca=_txt(brand.get("nombre_local")), tono=_txt(brand.get("tono")),
        paleta=dict(brand.get("paleta") or {}) if isinstance(brand.get("paleta"), dict) else {},
        tipografias=tipos, precio_front=precio, landing_url=landing_url, url_anuncio=url_anuncio,
        angulo_oferta=_txt(core.get("angulo")), promesa=_txt(core.get("promesa_h1")), villano=_txt(core.get("villano")),
        mecanismo=_txt(core.get("mecanismo_nombre")),
        mecanismo_pasos=tuple(p for p in core.get("mecanismo_pasos") or [] if isinstance(p, str)),
        avatar=_txt(core.get("avatar")), objeciones=objeciones, angulos_referencia=angulos_ref,
        hooks_referencia=hooks_ref, mezcla_imagenes_pct=mezcla_pct, pdf_vigente=pdf, medios_propios=medios,
        oferta=oferta, motivos=tuple(motivos))


def resumen(ctx: Contexto) -> dict:
    """El contexto como mapa legible (lo imprime ``trovefy creativos contexto`` para que Claude lo lea)."""
    def rel(p: Path | None) -> str | None:
        return None if p is None else Path(p).relative_to(ctx.vault).as_posix()

    return {
        "producto": ctx.producto, "pais": ctx.pais, "idioma": ctx.idioma, "moneda": ctx.moneda, "estado": ctx.estado,
        "marca": ctx.marca, "tono": ctx.tono, "paleta": ctx.paleta, "tipografias": ctx.tipografias,
        "precio_front": ctx.precio_texto, "landing_url": ctx.landing_url, "url_anuncio": ctx.url_anuncio,
        "angulo_oferta": ctx.angulo_oferta, "promesa": ctx.promesa, "villano": ctx.villano,
        "mecanismo": ctx.mecanismo, "mecanismo_pasos": list(ctx.mecanismo_pasos), "avatar": ctx.avatar,
        "objeciones": list(ctx.objeciones), "angulos_referencia": list(ctx.angulos_referencia),
        "hooks_referencia": list(ctx.hooks_referencia),
        "mezcla_imagenes_pct": ctx.mezcla_imagenes_pct if ctx.mezcla_imagenes_pct is not None else "no medido",
        "pdf_vigente": rel(ctx.pdf_vigente), "medios_propios": sorted(ctx.medios_propios),
        "no_medido": list(ctx.motivos),
    }
