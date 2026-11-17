"""Paso 1 de ``/producto``: precondiciones (estado y tres señales) y ``entregable/FICHA.md``.

Precondiciones (contrato 3, resoluciones 8 y 9, Ruling M6): ``paises.<PAIS>.estado`` es ``modelado`` o
posterior; ``OFERTA.md`` está aprobada (``trovefy.modelar.aprobacion.oferta_aprobada``) y es de ese país;
``AUDITORIA.md`` trae ``ya_se_vende`` y ``hueco_por_pais`` en ``true``; y la tercera señal está en
``PRODUCTO.md`` → ``senales.se_puede_mejorar: true`` o hay una excepción de R16 vigente
(``trovefy.modelar.aprobacion.excepcion_vigente``). ``decisiones/*-excepcion-senales.md`` ya no vale.
``crear_ficha`` las comprueba siempre antes de escribir nada.

Piezas (resolución 13 y Ruling R1): ``principal``, un ``bono-N`` por cada ``core.bonos`` de ``OFERTA.md``
(sin id: su id es su posición desde 1), el ``bump`` siempre y ``u1|u2|u3|downsell`` solo con
``activo: true`` en ``ESCALERA.md`` → ``paises.<PAIS>.pasos``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, get_args

from trovefy.config import mercados as mercados_cfg
from trovefy.modelar.aprobacion import excepcion_vigente, oferta_aprobada
from trovefy.modelar.salida import cargar_brandbook, cargar_escalera, cargar_oferta
from trovefy.producto.config import cargar_config
from trovefy.producto.rutas import UPSELLS, entregable
from trovefy.vault import frontmatter
from trovefy.vault.escritura import anadir_log, escribir_atomico
from trovefy.vault.producto import (
    ESTADOS_FASE2,
    EstadoInesperado,
    ruta_producto,
    secreto_en,
)

Exigencia = Literal["normal", "sanitario", "educativo"]
TipoProducto = Literal["ebook", "kit"]
TipoPiezaFicha = Literal["ebook", "kit", "bono", "bump", "upsell"]
EXIGENCIAS: tuple[str, ...] = get_args(Exigencia)
TIPOS: tuple[str, ...] = get_args(TipoProducto)
ESTADOS_PRODUCIBLES = ESTADOS_FASE2[ESTADOS_FASE2.index("modelado"):]
SENALES_AUDITORIA = ("ya_se_vende", "hueco_por_pais")
_SKILL = "producto"

# Transliteración búlgara propia (30 letras; base: sistema oficial de 2009, con «й» → «i» para que
# «Дишай» dé «dishai»). Sin dependencias.
_BG = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z", "и": "i", "й": "i",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "a", "ь": "y", "ю": "yu", "я": "ya",
}
_NO_SLUG = re.compile(r"[^a-z0-9]+")
_PAIS = re.compile(r"[A-Z]{2}")


def _pais(pais: str) -> str:
    if not isinstance(pais, str) or not _PAIS.fullmatch(pais):
        raise ValueError(f"país mal escrito: «{pais}»; usa su código de dos letras en mayúsculas")
    return pais


class SinTresSenales(Exception):
    """Falta alguna de las tres señales de §4.1 (o la excepción de R16 vigente)."""


class OfertaNoAprobada(Exception):
    """``OFERTA.md`` no está aprobada (``oferta_aprobada``) o es de otro país (Ruling M6)."""


class EstadoNoValido(EstadoInesperado):
    """El país no está en ``modelado`` o posterior. Envuelve ``EstadoInesperado`` solo por el mensaje."""


@dataclass(frozen=True)
class PiezaFicha:
    id: str
    titulo: str
    tipo: TipoPiezaFicha
    paginas_objetivo: int


@dataclass(frozen=True)
class Ficha:
    p_id: str
    pais: str
    idioma: str
    slug: str
    unidad_venta: str
    promesa: str
    avatar: str
    exigencia: Exigencia
    tipo: TipoProducto
    piezas: tuple[PiezaFicha, ...]


# --- precondiciones ---------------------------------------------------------------------------------


def comprobar_precondiciones(vault: Path, p_id: str, pais: str, *, ahora: datetime | None = None) -> None:
    vault, pais = Path(vault), _pais(pais)
    ruta = ruta_producto(vault, p_id)
    if not ruta.is_file():
        raise FileNotFoundError(f"no existe productos/{p_id}/PRODUCTO.md: el producto sale de /trovefy:auditar")
    meta, _ = frontmatter.leer(ruta)
    meta = meta if isinstance(meta, dict) else {}
    paises = meta.get("paises")
    bloque = paises.get(pais) if isinstance(paises, dict) else None
    estado = bloque.get("estado") if isinstance(bloque, dict) else None
    if estado not in ESTADOS_PRODUCIBLES:
        raise EstadoNoValido(f"{pais} está en «{estado or 'sin estado'}»: primero /modelar")

    aprobada, motivo = oferta_aprobada(vault, p_id)
    if not aprobada:
        raise OfertaNoAprobada(f"{motivo}; sin oferta aprobada no se produce")
    pais_oferta = cargar_oferta(vault, p_id).get("pais")
    if pais_oferta != pais:
        raise OfertaNoAprobada(f"OFERTA.md es de {pais_oferta or 'ningún país'}, no de {pais}: "
                               f"modela la oferta de {pais} en /modelar")

    auditoria = ruta.parent / "AUDITORIA.md"
    if not auditoria.is_file():
        raise SinTresSenales("falta AUDITORIA.md: sin las tres señales no se produce (/auditar)")
    meta_aud, _ = frontmatter.leer(auditoria)
    senales_aud = meta_aud.get("senales") if isinstance(meta_aud, dict) else None
    senales_aud = senales_aud if isinstance(senales_aud, dict) else {}
    faltan = [s.replace("_", " ") for s in SENALES_AUDITORIA if senales_aud.get(s) is not True]
    if faltan:
        raise SinTresSenales(f"AUDITORIA.md no confirma: {', '.join(faltan)}; sin las tres señales no se produce")

    senales = meta.get("senales")
    tercera = senales.get("se_puede_mejorar") if isinstance(senales, dict) else None
    if tercera is not True and excepcion_vigente(vault, p_id, ahora) is None:
        valor = "no" if tercera is False else "no medida"
        raise SinTresSenales(f"falta la tercera señal (se puede mejorar: {valor}) y no hay excepción de R16 "
                             "vigente: o mejoras la oferta en /modelar o registras la excepción con las "
                             "palabras del usuario")


# --- ficha ------------------------------------------------------------------------------------------


def slug_de(nombre_local: str) -> str:
    """``nombre_local`` en ASCII ``[a-z0-9-]``: búlgaro con la tabla propia y tildes latinas fuera."""
    texto = "".join(_BG.get(c, c) for c in str(nombre_local).lower())
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    slug = _NO_SLUG.sub("-", texto).strip("-")
    if not slug:
        raise ValueError(f"nombre_local «{nombre_local}» no da un nombre de archivo: revisa BRANDBOOK.md")
    return slug


def _texto(valor: object, donde: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"falta {donde}: /modelar")
    return valor.strip()


def _paginas(minimo: int, pedido: object) -> int:
    if isinstance(pedido, int) and not isinstance(pedido, bool) and pedido > minimo:
        return pedido
    return minimo


def _idioma(vault: Path, pais: str) -> str:
    ruta = vault / "config" / "mercados.yaml"
    if not ruta.is_file():
        raise FileNotFoundError("falta config/mercados.yaml")
    mercado = mercados_cfg.cargar(ruta).get(pais)
    if mercado is None:
        raise ValueError(f"{pais} no está en config/mercados.yaml")
    return mercado.idioma


def _piezas(oferta: dict, pasos: dict, tipo: str, minimos: dict[str, int]) -> tuple[PiezaFicha, ...]:
    core = oferta.get("core") if isinstance(oferta.get("core"), dict) else {}
    front = pasos.get("front") if isinstance(pasos.get("front"), dict) else {}
    titulo_principal = front.get("titulo") if isinstance(front.get("titulo"), str) else None
    piezas = [PiezaFicha("principal", titulo_principal or _texto(core.get("promesa_h1"), "core.promesa_h1"),
                         tipo, _paginas(minimos[tipo], core.get("paginas")))]
    bonos = core.get("bonos") or []
    if not isinstance(bonos, list):
        raise ValueError("OFERTA.md: core.bonos no es una lista: /modelar")  # noqa: TRY004 - error de datos
    for n, bono in enumerate(bonos, 1):
        bono = bono if isinstance(bono, dict) else {}
        piezas.append(PiezaFicha(f"bono-{n}", _texto(bono.get("nombre"), f"core.bonos[{n}].nombre"), "bono",
                                 _paginas(minimos["bono"], bono.get("paginas"))))
    for paso in ("bump", *UPSELLS):
        datos = pasos.get(paso)
        if not isinstance(datos, dict):
            raise ValueError(f"ESCALERA.md no trae el paso {paso}: /modelar")  # noqa: TRY004 - error de datos
        if paso != "bump" and datos.get("activo") is not True:
            continue
        clave = "bump" if paso == "bump" else "upsell"
        piezas.append(PiezaFicha(paso, _texto(datos.get("titulo"), f"ESCALERA.md pasos.{paso}.titulo"), clave,
                                 _paginas(minimos[clave], datos.get("paginas"))))
    return tuple(piezas)


def _ruta_ficha(vault: Path, p_id: str) -> Path:
    return entregable(vault, p_id) / "FICHA.md"


def crear_ficha(vault: Path, p_id: str, pais: str, exigencia: str, tipo: str, ahora: datetime) -> Path:
    vault, pais = Path(vault), _pais(pais)
    if exigencia not in EXIGENCIAS:
        raise ValueError(f"exigencia «{exigencia}» no admitida: {', '.join(EXIGENCIAS)}")
    if tipo not in TIPOS:
        raise ValueError(f"tipo «{tipo}» no admitido: {', '.join(TIPOS)}")
    comprobar_precondiciones(vault, p_id, pais, ahora=ahora)
    cfg = cargar_config(vault)
    oferta = cargar_oferta(vault, p_id)
    escalera = cargar_escalera(vault, p_id).get(pais)
    pasos = escalera.get("pasos") if isinstance(escalera, dict) else None
    if not isinstance(pasos, dict):
        raise ValueError(f"ESCALERA.md no trae los pasos de {pais}: /modelar")  # noqa: TRY004 - error de datos
    brandbook = cargar_brandbook(vault, p_id)
    core = oferta.get("core") if isinstance(oferta.get("core"), dict) else {}

    ruta = _ruta_ficha(vault, p_id)
    avatar = _texto(core.get("avatar"), "core.avatar")
    if ruta.is_file():
        previa, _ = frontmatter.leer(ruta)
        anterior = previa.get("avatar") if isinstance(previa, dict) else None
        if isinstance(anterior, str) and anterior.strip():
            avatar = anterior.strip()

    ficha = Ficha(
        p_id=p_id, pais=pais, idioma=_idioma(vault, pais),
        slug=slug_de(_texto(brandbook.get("nombre_local"), "BRANDBOOK.md nombre_local")),
        unidad_venta=_texto(core.get("unidad_venta"), "core.unidad_venta"),
        promesa=_texto(core.get("promesa_h1"), "core.promesa_h1"),
        avatar=avatar, exigencia=exigencia, tipo=tipo,
        piezas=_piezas(oferta, pasos, tipo, cfg.paginas_min),
    )
    meta = asdict(ficha)
    meta["piezas"] = [asdict(p) for p in ficha.piezas]
    meta = {"tipo_documento": "ficha", "fecha": ahora.date().isoformat(), **meta}
    lineas = [f"# Ficha · {p_id} · {pais}", "",
              "Paso 1 de /producto. Claude puede afinar el avatar; el resto sale de OFERTA, ESCALERA y BRANDBOOK.",
              "", "| Pieza | Título | Tipo | Páginas objetivo |", "|---|---|---|---|"]
    lineas += [f"| {p.id} | {p.titulo} | {p.tipo} | {p.paginas_objetivo} |" for p in ficha.piezas]
    texto = frontmatter.renderizar(meta, "\n".join(lineas) + "\n")
    nombre = secreto_en(meta)
    if nombre:
        raise ValueError(f"FICHA.md: aparece un secreto ({nombre}); no se escribe nada")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    escribir_atomico(ruta, texto)
    anadir_log(vault, _SKILL, f"{p_id} {pais}: ficha del entregable ({len(ficha.piezas)} piezas)",
               [ruta.relative_to(vault).as_posix()], ahora=ahora)
    return ruta


def leer_ficha(vault: Path, p_id: str) -> Ficha:
    ruta = _ruta_ficha(Path(vault), p_id)
    if not ruta.is_file():
        raise FileNotFoundError(f"falta productos/{p_id}/entregable/FICHA.md: paso 1 de /producto")
    meta, _ = frontmatter.leer(ruta)
    try:
        piezas = tuple(PiezaFicha(id=p["id"], titulo=p["titulo"], tipo=p["tipo"],
                                  paginas_objetivo=int(p["paginas_objetivo"])) for p in meta["piezas"])
        ficha = Ficha(p_id=meta["p_id"], pais=meta["pais"], idioma=meta["idioma"], slug=meta["slug"],
                      unidad_venta=meta["unidad_venta"], promesa=meta["promesa"], avatar=meta["avatar"],
                      exigencia=meta["exigencia"], tipo=meta["tipo"], piezas=piezas)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"FICHA.md está incompleta o rota ({exc}): rehaz el paso 1") from None
    if ficha.exigencia not in EXIGENCIAS or ficha.tipo not in TIPOS or ficha.p_id != p_id:
        raise ValueError("FICHA.md trae valores no admitidos: rehaz el paso 1")
    return ficha
