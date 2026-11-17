"""Entrada de /landing: lo que la landing de un país necesita de la oferta, el entregable y la config.

Toda la lectura de los formatos de los planes 16 y 17 vive aquí (un solo sitio que ajustar):

- ``OFERTA.md`` → ``estructura_landing`` (resolución 5, tipos de ``trovefy.modelar.esquema``) y
  ``core.{promesa_h1, angulo, garantia_dias, formato}`` (resolución 4);
- ``ESCALERA.md`` → ``paises.<PAIS>.pasos.front.precio`` y ``paises.<PAIS>.moneda`` (resolución 6);
- ``BRANDBOOK.md`` → ``nombre_local`` (marca) y ``tokens_css`` (resolución 7);
- ``PRODUCTO.md`` → estado del país y ``entregable.<idioma>.principal.pdf`` (resolución 14);
- ``entregable/medios/medios.json`` → imágenes propias (resolución 15);
- ``config/mercados.yaml`` → idioma, moneda y ``tienda`` (resolución 24);
- ``config/arranque.yaml`` → paso 07 ``datos.dominio``.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

import yaml

from trovefy.config import mercados
from trovefy.landing.constantes import ESTADOS_LANDING, SECCIONES_MAX, SECCIONES_MIN
from trovefy.modelar.esquema import TIPOS_SECCION
from trovefy.modelar.salida import cargar_brandbook, cargar_escalera, cargar_oferta
from trovefy.pdf.maqueta import tokens_brandbook
from trovefy.pdf.render import PdfinfoNoMedido, paginas_pdfinfo
from trovefy.producto.medios import leer_manifiesto
from trovefy.vault import frontmatter
from trovefy.vault import producto as vproducto

__all__ = ["TIPOS_SECCION", "DatosLanding", "EntradaInvalida", "EstadoNoPermite", "SeccionRef", "cargar_datos",
           "leer_resenas", "resena_completa", "ruta_landing", "wireframe"]

_EXT_IMAGEN = (".png", ".jpg", ".jpeg", ".webp")
_CAMPOS_RESENA = ("id", "texto", "fecha", "pais", "fuente")


class EntradaInvalida(ValueError):
    """Falta algo o algo no cuadra en lo que /landing lee; el mensaje dice qué y dónde."""


class EstadoNoPermite(EntradaInvalida):
    """El país no está en un estado desde el que se pueda hacer su landing (contrato 3)."""


@dataclass(frozen=True)
class SeccionRef:
    orden: int
    tipo: str
    palabras: int
    cta: bool


@dataclass(frozen=True)
class DatosLanding:
    p_id: str
    pais: str
    idioma: str
    moneda: str
    estado: str
    secciones: tuple[SeccionRef, ...]
    promesa_h1: str
    angulo: str
    garantia_dias: int
    formato: str
    precio: Decimal
    pdf: Path
    pdf_sha256: str
    pdf_paginas: int
    imagenes: tuple[Path, ...]
    tokens_css: str
    marca: str
    dominio: str | None
    tienda: str | None
    resenas: int = 0  # reseñas reales completas en landing/<PAIS>/resenas.yaml (decide la sustitución)


def ruta_landing(vault: Path, p_id: str, pais: str) -> Path:
    """``productos/<p-id>/landing/<PAIS>/``."""
    return vproducto.ruta_producto(vault, p_id).parent / "landing" / pais


def leer_resenas(vault: Path, p_id: str, pais: str) -> list:
    """Entradas de ``landing/<PAIS>/resenas.yaml`` (lista ``resenas``), tal cual; ``[]`` si no hay archivo."""
    ruta = ruta_landing(vault, p_id, pais) / "resenas.yaml"
    if not ruta.is_file():
        return []
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise EntradaInvalida(f"landing/{pais}/resenas.yaml no se puede leer: {exc}") from None
    lista = datos.get("resenas") if isinstance(datos, dict) else None
    if not isinstance(lista, list):
        raise EntradaInvalida(f"landing/{pais}/resenas.yaml no trae la lista «resenas»")
    return lista


def resena_completa(r: object) -> bool:
    return isinstance(r, dict) and all(isinstance(r.get(c), str) and r[c].strip() for c in _CAMPOS_RESENA)


def _pais(pais: str) -> str:
    codigo = pais.strip().upper() if isinstance(pais, str) else ""
    if len(codigo) != 2 or not codigo.isascii() or not codigo.isalpha():
        raise EntradaInvalida(f"país mal escrito: «{pais}»; usa su código de dos letras (por ejemplo BG)")
    return codigo


def _leer(lector, p_id: str, nombre: str):
    try:
        return lector()
    except FileNotFoundError:
        raise EntradaInvalida(f"falta productos/{p_id}/{nombre}.md: /modelar") from None


def _secciones(oferta: dict) -> tuple[SeccionRef, ...]:
    lista = oferta.get("estructura_landing")
    if not isinstance(lista, list):
        raise EntradaInvalida("OFERTA.md no trae estructura_landing: revisa /modelar")
    n = len(lista)
    if not SECCIONES_MIN <= n <= SECCIONES_MAX:
        raise EntradaInvalida(f"la estructura de OFERTA.md tiene {n} secciones; /landing pide "
                              f"{SECCIONES_MIN}–{SECCIONES_MAX}: revisa /modelar")
    secciones = []
    for i, s in enumerate(lista):
        donde = f"OFERTA.md estructura_landing[{i}]"
        if not isinstance(s, dict):
            raise EntradaInvalida(f"{donde} no es {{orden, tipo, palabras, cta}}")
        orden, tipo, palabras, cta = (s.get(k) for k in ("orden", "tipo", "palabras", "cta"))
        if isinstance(orden, bool) or not isinstance(orden, int):
            raise EntradaInvalida(f"{donde}.orden no es un entero")
        if tipo not in TIPOS_SECCION:
            raise EntradaInvalida(f"{donde}.tipo «{tipo}» no está en TIPOS_SECCION ({', '.join(TIPOS_SECCION)})")
        if isinstance(palabras, bool) or not isinstance(palabras, int) or palabras < 1:
            raise EntradaInvalida(f"{donde}.palabras tiene que ser un entero ≥ 1")
        if not isinstance(cta, bool):
            raise EntradaInvalida(f"{donde}.cta tiene que ser true o false")
        secciones.append(SeccionRef(orden, tipo, palabras, cta))
    if [s.orden for s in secciones] != list(range(1, n + 1)):
        raise EntradaInvalida("OFERTA.md estructura_landing: el orden tiene que ir de 1 a N, sin huecos")
    if not any(s.cta for s in secciones):
        raise EntradaInvalida("OFERTA.md estructura_landing: ninguna sección lleva cta: hace falta al menos una")
    return tuple(secciones)


def _texto(nodo: dict, clave: str, donde: str) -> str:
    valor = nodo.get(clave)
    if not isinstance(valor, str) or not valor.strip():
        raise EntradaInvalida(f"falta {donde}.{clave}: /modelar")
    return valor.strip()


def _precio(bloque: object, pais: str) -> tuple[Decimal, str]:
    pasos = bloque.get("pasos") if isinstance(bloque, dict) else None
    front = pasos.get("front") if isinstance(pasos, dict) else None
    crudo = front.get("precio") if isinstance(front, dict) else None
    if crudo is None or isinstance(crudo, (bool, float)):
        raise EntradaInvalida(f"ESCALERA.md no trae el precio del front de {pais} (texto «14.90»): /modelar")
    try:
        precio = Decimal(str(crudo))
    except InvalidOperation:
        raise EntradaInvalida(f"ESCALERA.md: precio del front de {pais} ilegible: «{crudo}»") from None
    if not precio.is_finite() or precio <= 0 or precio.as_tuple().exponent < -2:
        raise EntradaInvalida(f"ESCALERA.md: precio del front de {pais} no válido: «{crudo}» "
                              "(mayor que 0 y con 2 decimales como mucho)")
    moneda = bloque.get("moneda")
    if not isinstance(moneda, str) or not moneda:
        raise EntradaInvalida(f"ESCALERA.md no trae la moneda de {pais}: /modelar")
    return precio, moneda


def _pdf(vault: Path, p_id: str, idioma: str) -> Path:
    raiz = vproducto.ruta_producto(vault, p_id).parent
    meta, _ = frontmatter.leer(raiz / "PRODUCTO.md")
    entregable = meta.get("entregable") if isinstance(meta, dict) else None
    por_idioma = entregable.get(idioma) if isinstance(entregable, dict) else None
    principal = por_idioma.get("principal") if isinstance(por_idioma, dict) else None
    rel = principal.get("pdf") if isinstance(principal, dict) else None
    if not isinstance(rel, str) or not rel:
        raise EntradaInvalida(f"PRODUCTO.md no trae el PDF vigente (entregable.{idioma}.principal.pdf): "
                              "cierra el entregable con /producto")
    partes = PurePosixPath(rel).parts
    if (PurePosixPath(rel).is_absolute() or ".." in partes or not partes or partes[0] != "entregable"
            or not rel.endswith(".pdf")):
        raise EntradaInvalida(f"PRODUCTO.md: el PDF vigente «{rel}» no está dentro de entregable/")
    ruta = raiz.joinpath(*partes)
    if ruta.is_symlink() or not ruta.is_file():
        raise EntradaInvalida(f"el PDF vigente {rel} no existe: vuelve a /producto")
    return ruta


def _imagenes(vault: Path, p_id: str) -> tuple[Path, ...]:
    raiz = vproducto.ruta_producto(vault, p_id).parent / "entregable"
    try:
        manifiesto = leer_manifiesto(raiz, verificar=True)
    except ValueError as exc:
        raise EntradaInvalida(f"entregable/medios/medios.json: {exc}") from None
    archivos = sorted(e["archivo"] for e in manifiesto.values())
    return tuple(raiz / "medios" / a for a in archivos if Path(a).suffix.lower() in _EXT_IMAGEN)


def _dominio(vault: Path) -> str | None:
    ruta = vault / "config" / "arranque.yaml"
    if not ruta.is_file():
        return None
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise EntradaInvalida(f"config/arranque.yaml no se puede leer: {exc}") from None
    pasos = datos.get("pasos") if isinstance(datos, dict) else None
    for paso in pasos if isinstance(pasos, list) else []:
        if isinstance(paso, dict) and str(paso.get("id")) == "07":
            dominio = (paso.get("datos") or {}).get("dominio") if isinstance(paso.get("datos"), dict) else None
            return dominio.strip() if isinstance(dominio, str) and dominio.strip() else None
    return None


def _tokens_css(vault: Path, p_id: str) -> str:
    ruta = vproducto.ruta_producto(vault, p_id).parent / "BRANDBOOK.md"
    try:
        tokens = tokens_brandbook(ruta.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise EntradaInvalida(str(exc)) from None
    return ":root {\n" + "".join(f"  {k}: {v};\n" for k, v in tokens.items()) + "}\n"


def cargar_datos(vault: Path, p_id: str, pais: str, exigir_estado: tuple[str, ...] = ESTADOS_LANDING,
                 *, correr=subprocess.run) -> DatosLanding:
    """Lo que necesita la landing de ``pais``; ``EntradaInvalida`` (o ``EstadoNoPermite``) con un mensaje claro."""
    vault = Path(vault)
    pais = _pais(pais)
    try:
        ruta = vproducto.ruta_producto(vault, p_id)
    except ValueError as exc:
        raise EntradaInvalida(str(exc)) from None
    if not ruta.is_file():
        raise EntradaInvalida(f"falta productos/{p_id}/PRODUCTO.md: el producto sale de /auditar")
    oferta = _leer(lambda: cargar_oferta(vault, p_id), p_id, "OFERTA")
    escalera = _leer(lambda: cargar_escalera(vault, p_id), p_id, "ESCALERA")
    brandbook = _leer(lambda: cargar_brandbook(vault, p_id), p_id, "BRANDBOOK")
    ruta_mercados = vault / "config" / "mercados.yaml"
    if not ruta_mercados.is_file():
        raise EntradaInvalida("falta config/mercados.yaml")
    try:
        mercado = mercados.cargar(ruta_mercados).get(pais)
    except ValueError as exc:
        raise EntradaInvalida(str(exc)) from None
    if mercado is None:
        raise EntradaInvalida(f"{pais} no está en config/mercados.yaml")

    estado = vproducto.estado_pais(vault, p_id, pais)
    if estado not in exigir_estado:
        raise EstadoNoPermite(f"{pais} está en «{estado or 'sin estado'}»; /landing pide "
                              f"{' o '.join(exigir_estado)}: primero termina /producto")

    secciones = _secciones(oferta)
    core = oferta.get("core")
    if not isinstance(core, dict):
        raise EntradaInvalida("OFERTA.md no trae core: /modelar")
    garantia = core.get("garantia_dias")
    if isinstance(garantia, bool) or not isinstance(garantia, int) or garantia < 1:
        raise EntradaInvalida("falta OFERTA.md core.garantia_dias (días, entero ≥ 1): /modelar")
    precio, moneda = _precio(escalera.get(pais), pais)
    if moneda != mercado.moneda:
        raise EntradaInvalida(f"ESCALERA.md cobra {pais} en {moneda} y config/mercados.yaml dice {mercado.moneda}")
    marca = brandbook.get("nombre_local")
    if not isinstance(marca, str) or not marca.strip():
        raise EntradaInvalida("BRANDBOOK.md no trae nombre_local: /modelar")

    pdf = _pdf(vault, p_id, mercado.idioma)
    try:
        paginas = paginas_pdfinfo(pdf, correr=correr)
    except PdfinfoNoMedido as exc:
        raise EntradaInvalida(f"páginas del PDF: {exc}") from None
    resenas = sum(1 for r in leer_resenas(vault, p_id, pais) if resena_completa(r))
    return DatosLanding(
        p_id=p_id, pais=pais, idioma=mercado.idioma, moneda=moneda, estado=estado, secciones=secciones,
        promesa_h1=_texto(core, "promesa_h1", "OFERTA.md core"), angulo=_texto(core, "angulo", "OFERTA.md core"),
        garantia_dias=garantia, formato=_texto(core, "formato", "OFERTA.md core"), precio=precio, pdf=pdf,
        pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(), pdf_paginas=paginas,
        imagenes=_imagenes(vault, p_id), tokens_css=_tokens_css(vault, p_id), marca=marca.strip(),
        dominio=_dominio(vault), tienda=mercado.tienda, resenas=resenas,
    )


def wireframe(datos: DatosLanding) -> list[dict]:
    """Una entrada por sección con su posición relativa; sin reseñas reales, ``prueba_social`` → ``vista_previa``."""
    total = sum(s.palabras for s in datos.secciones)
    salida, acumulado = [], 0
    for s in datos.secciones:
        entrada = {"orden": s.orden, "tipo": s.tipo, "palabras": s.palabras, "cta": s.cta,
                   "y_rel": round(acumulado / total, 3)}
        if s.tipo == "prueba_social" and datos.resenas == 0:
            entrada["tipo"] = "vista_previa"
            entrada["sustituye"] = "prueba_social"
        salida.append(entrada)
        acumulado += s.palabras
    return salida
