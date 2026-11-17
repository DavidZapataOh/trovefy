"""Contexto del producto-país para /tracking y /checkout (plan 19, Tarea 4; resoluciones 1, 6, 7, 14 y 24).

Junta en un objeto lo que el embudo necesita leer del vault, sin escribir nada:

- ``PRODUCTO.md`` → ``paises.<PAIS>.estado`` y el PDF vigente de cada pieza (``entregable.<idioma>.<pieza>.pdf``,
  ``front`` = ``principal``; resolución 14);
- ``ESCALERA.md`` → ``paises.<PAIS>.moneda`` y ``pasos.{front,bump,u1,u2,u3,downsell}`` (resolución 6);
- ``BRANDBOOK.md`` → ``nombre_local`` (la marca; resolución 7);
- ``config/mercados.yaml`` → idioma, moneda y ``tienda`` (resolución 24);
- ``landing/<PAIS>/landing.yaml`` → ``hosting``, ``url``, ``checkout_url``;
- ``config/arranque.yaml`` → la ruta de cobro (pasos 09 y 10).

Ruta Hotmart fuera («DESVÍOS RESUELTOS» de la cabecera del plan 19): la única ruta es Impultienda.
Un dato que falta es «no medido: <motivo>» en ``motivos``, nunca un valor inventado.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml

from trovefy.config import mercados
from trovefy.landing.plantilla import EntradaInvalida, leer_landing_yaml
from trovefy.vault import frontmatter
from trovefy.vault.producto import EstadoInesperado, estado_pais, ruta_producto

ClavePieza = Literal["front", "bump", "u1", "u2", "u3", "downsell"]
CLAVES: tuple[str, ...] = ("front", "bump", "u1", "u2", "u3", "downsell")
# Pieza del 19 → pieza del 17 en PRODUCTO.md (resolución 14).
_PIEZA_17 = {"front": "principal", "bump": "bump", "u1": "u1", "u2": "u2", "u3": "u3", "downsell": "downsell"}
_HECHO = ("hecho", "verificado")


class EstadoIncorrecto(EstadoInesperado):
    """El país no está en el estado que el paso del embudo admite (envuelve `EstadoInesperado`, resolución 1)."""


@dataclass(frozen=True)
class Pieza:
    clave: ClavePieza
    titulo: str
    precio: Decimal
    activo: bool
    motivo_inactivo: str | None
    pdf: Path | None


@dataclass(frozen=True)
class Contexto:
    vault: Path
    producto: str
    pais: str
    estado: str | None
    idioma: str
    moneda: str
    marca: str | None
    piezas: dict[str, Pieza]
    tienda: str | None
    landing_url: str | None
    landing_hosting: Literal["impultienda", "cloudflare"] | None
    checkout_url: str | None
    ruta: Literal["impultienda"]
    motivos: tuple[str, ...]


def ruta_de_cobro(arranque: dict) -> Literal["impultienda"]:
    """Con los pasos 09 (Impultienda) y 10 (cobro) en ``hecho|verificado`` → ``impultienda``; si no, ``ValueError``.

    `arranque` es el contenido de ``config/arranque.yaml`` (``{"pasos": [{"id", "estado", …}]}``)."""
    pasos = arranque.get("pasos") if isinstance(arranque, dict) else None
    if not isinstance(pasos, list):
        raise ValueError("config/arranque.yaml no tiene la lista «pasos»")  # noqa: TRY004 - dato del vault mal escrito
    estado = {str(p.get("id")): p.get("estado") for p in pasos if isinstance(p, dict)}
    if estado.get("09") in _HECHO and estado.get("10") in _HECHO:
        return "impultienda"
    if estado.get("10") == "bloqueado" and estado.get("10b") in _HECHO:
        raise ValueError("la ruta Hotmart está fuera (plan 19, «DESVÍOS RESUELTOS»): el cobro va por Impultienda; "
                         "termina los pasos 09 y 10 de /arranque")
    raise ValueError("no hay ruta de cobro: los pasos 09 (Impultienda) y 10 (cobro) de /arranque deben estar hechos")


def _leer_arranque(vault: Path) -> dict:
    ruta = Path(vault) / "config" / "arranque.yaml"
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("falta config/arranque.yaml: no hay ruta de cobro (/arranque)") from None
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ValueError(f"config/arranque.yaml no se puede leer: {exc}") from None
    return datos if isinstance(datos, dict) else {}


def _precio(valor: object, clave: str) -> Decimal:
    if isinstance(valor, float):
        raise ValueError(  # noqa: TRY004 - dato del vault mal escrito
            f"precio sin comillas: escríbelo como texto (por ejemplo \"13.90\") en ESCALERA.md, paso {clave}")
    if isinstance(valor, bool) or not isinstance(valor, (str, int)):
        raise ValueError(f"ESCALERA.md: el paso {clave} no tiene precio")  # noqa: TRY004 - dato del vault mal escrito
    try:
        precio = Decimal(str(valor).strip())
    except InvalidOperation:
        raise ValueError(f"ESCALERA.md: precio no válido en el paso {clave}: «{valor}»") from None
    if not precio.is_finite() or precio < 0:
        raise ValueError(f"ESCALERA.md: precio no válido en el paso {clave}: «{valor}»")
    return precio


def _meta(ruta: Path) -> dict:
    if not ruta.is_file():
        return {}
    meta, _ = frontmatter.leer(ruta)
    return meta if isinstance(meta, dict) else {}


def _pdf(dir_producto: Path, entregable: dict, clave: str) -> Path | None:
    """El PDF vigente de la pieza si está dentro de ``entregable/`` y existe; si no, None."""
    datos = entregable.get(_PIEZA_17[clave])
    rel = datos.get("pdf") if isinstance(datos, dict) else None
    if not isinstance(rel, str) or not rel:
        return None
    partes = PurePosixPath(rel).parts
    if PurePosixPath(rel).is_absolute() or ".." in partes or not partes or partes[0] != "entregable":
        return None
    ruta = dir_producto / rel
    return ruta if ruta.is_file() and not ruta.is_symlink() else None


def _piezas(pasos: dict, dir_producto: Path, entregable: dict, motivos: list[str]) -> dict[str, Pieza]:
    piezas: dict[str, Pieza] = {}
    for clave in CLAVES:
        paso = pasos.get(clave)
        if paso is None:
            continue
        if not isinstance(paso, dict):
            raise ValueError(f"ESCALERA.md: el paso {clave} no es un mapa")  # noqa: TRY004 - dato del vault mal escrito
        activo = paso.get("activo") is True
        pdf = _pdf(dir_producto, entregable, clave)
        if activo and pdf is None:
            motivos.append(f"no medido: falta el PDF vigente de {clave} (plan 17)")
        motivo = paso.get("motivo_inactivo")
        piezas[clave] = Pieza(
            clave=clave,  # type: ignore[arg-type]
            titulo=str(paso.get("titulo") or ""),
            precio=_precio(paso.get("precio"), clave),
            activo=activo,
            motivo_inactivo=str(motivo) if motivo else None,
            pdf=pdf,
        )
    if "front" not in piezas:
        raise ValueError("ESCALERA.md: falta el paso front")
    return piezas


def _absoluta(url: str | None, tienda: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("https://"):
        return url
    if url.startswith("/") and tienda:
        return tienda.rstrip("/") + url
    return None


def cargar_contexto(vault: Path, producto: str, pais: str) -> Contexto:
    vault = Path(vault)
    dir_producto = ruta_producto(vault, producto).parent
    motivos: list[str] = []
    ruta = ruta_de_cobro(_leer_arranque(vault))

    m = mercados.cargar(vault / "config" / "mercados.yaml").get(pais)
    if m is None:
        raise ValueError(f"el país {pais} no está en config/mercados.yaml")
    escalera = _meta(dir_producto / "ESCALERA.md").get("paises")
    bloque = escalera.get(pais) if isinstance(escalera, dict) else None
    if not isinstance(bloque, dict) or not isinstance(bloque.get("pasos"), dict):
        raise ValueError(f"ESCALERA.md no trae paises.{pais}.pasos: /modelar")  # noqa: TRY004 - dato del vault mal escrito
    moneda = str(bloque.get("moneda") or m.moneda)
    if moneda != m.moneda:
        motivos.append(f"no medido: la moneda de ESCALERA.md ({moneda}) no es la del mercado ({m.moneda})")

    producto_meta = _meta(dir_producto / "PRODUCTO.md")
    por_idioma = producto_meta.get("entregable", {})
    entregable = por_idioma.get(m.idioma) if isinstance(por_idioma, dict) else None
    piezas = _piezas(bloque["pasos"], dir_producto, entregable if isinstance(entregable, dict) else {}, motivos)

    marca = _meta(dir_producto / "BRANDBOOK.md").get("nombre_local")
    marca = marca.strip() if isinstance(marca, str) and marca.strip() else None
    if marca is None:
        motivos.append("no medido: falta nombre_local en BRANDBOOK.md (/modelar)")

    tienda = m.tienda.rstrip("/") if m.tienda else None
    if tienda is None:
        motivos.append(f"no medido: falta la tienda de {pais} en config/mercados.yaml (trovefy landing sonda --tienda)")
    try:
        landing = leer_landing_yaml(vault, producto, pais)
    except EntradaInvalida as exc:
        motivos.append(f"no medido: landing.yaml ilegible ({exc})")
        landing = {}
    hosting = landing.get("hosting") if landing.get("hosting") in ("impultienda", "cloudflare") else None
    landing_url = _absoluta(landing.get("url") if isinstance(landing.get("url"), str) else None, tienda)
    checkout = landing.get("checkout_url") if isinstance(landing.get("checkout_url"), str) else None
    checkout_url = _absoluta(checkout, tienda) or (tienda + "/checkout" if tienda else None)
    if landing_url is None:
        motivos.append(f"no medido: la landing de {pais} no está publicada (/landing)")

    return Contexto(
        vault=vault, producto=producto, pais=pais, estado=estado_pais(vault, producto, pais),
        idioma=m.idioma, moneda=moneda, marca=marca, piezas=piezas, tienda=tienda, landing_url=landing_url,
        landing_hosting=hosting, checkout_url=checkout_url, ruta=ruta, motivos=tuple(motivos),
    )


def exigir_estado(ctx: Contexto, permitido: str | tuple[str, ...]) -> None:
    permitidos = (permitido,) if isinstance(permitido, str) else tuple(permitido)
    if ctx.estado not in permitidos:
        raise EstadoIncorrecto(f"{ctx.producto} {ctx.pais} está en «{ctx.estado}»; este paso necesita "
                               f"{' o '.join(f'«{p}»' for p in permitidos)}")


def ruta_pais(ctx: Contexto) -> Path:
    """``productos/<p-id>/checkout/<PAIS>/`` (no la crea)."""
    return ruta_producto(ctx.vault, ctx.producto).parent / "checkout" / ctx.pais
