"""Catálogo clasificado del MCP oficial de Impultienda (plan 19, Tarea 3; resoluciones 38 y 39).

`config/impultienda_tools.json` guarda, tal cual, el nombre, la descripción y el esquema de entrada de cada
herramienta que expone el servidor (la evidencia), y al lado la clase (`lectura`, `escritura` o `prohibida`) y el
motivo, que pone quien clasifica y revisa el usuario en el PR. Este módulo lo carga y se niega a dar por bueno un
catálogo mal clasificado: una herramienta que toca dinero, Meta, cuentas o secretos (por su nombre o por el de
alguno de sus parámetros, también anidados) tiene que ser `prohibida`; una de consulta no puede ser `escritura`
ni una que escribe, `lectura`.

La CLI nunca llama al MCP: solo Claude lo hace, y solo con herramientas `lectura` o `escritura` de aquí.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from trovefy.mapa import _fichas

RAIZ = Path(__file__).resolve().parents[3]
PREFIJO_MCP = "mcp__impultienda__"

Clase = Literal["lectura", "escritura", "prohibida"]
CLASES: tuple[str, ...] = ("lectura", "escritura", "prohibida")

PROHIBIDAS_POR_TEMA = (
    "pago", "pasarela", "impul pay", "whop", "stripe", "mercado pago", "retir", "transfer", "billetera", "banco",
    "tarjeta", "reembols", "refund", "payout", "withdraw", "contraseña", "password", "usuario", "seguridad", "meta",
    "facebook", "pixel_event", "creativ", "anuncio", "catalog", "token", "capi", "secret", "api_key", "webhook",
)
# Cortas que aparecen dentro de palabras corrientes («metas», «capital»): solo como palabra entera (o plural).
_ENTERAS = frozenset({"meta", "capi"})
_CONSULTA = frozenset({"get", "list", "read", "obtener", "listar", "ver", "leer"})
_ESCRIBE = re.compile(r"\bESCRIBE\b")
_NOMBRE = re.compile(r"[a-z0-9_]+")


class CatalogoInvalido(ValueError):
    """El catálogo no se puede leer o una herramienta está mal clasificada."""


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    descripcion: str
    esquema: dict
    clase: Clase
    motivo: str


class Catalogo(dict[str, Herramienta]):
    """`{nombre: Herramienta}` con los datos del listado (fuente, fecha, servidor, plan) y lo que no cubre."""

    def __init__(self, herramientas: dict[str, Herramienta], *, fuente: str, fecha: str, servidor: str,
                 plan: str, faltan: tuple[str, ...]):
        super().__init__(herramientas)
        self.fuente = fuente
        self.fecha = fecha
        self.servidor = servidor
        self.plan = plan
        self.faltan = faltan


def _normal(texto: str) -> str:
    return "".join(_fichas(texto))


_TEMAS = tuple((t, _normal(t)) for t in PROHIBIDAS_POR_TEMA)


def _temas(texto: str) -> list[str]:
    """Los temas de `PROHIBIDAS_POR_TEMA` que toca `texto` (normalizado como `trovefy.mapa`)."""
    fichas = _fichas(texto)
    junto = "".join(fichas)
    enteras = set(fichas) | {f[:-1] for f in fichas if f.endswith("s")}
    return [t for t, n in _TEMAS if (n in enteras if t in _ENTERAS else n in junto)]


def _es_token_de_vista_previa(nombre: str, prop: object) -> bool:
    """El `token` de los cambios en dos pasos: lo devuelve el servidor en la vista previa y ata lo aprobado con lo
    aplicado. No es una credencial; un `token` con otra descripción sí lo es."""
    if _fichas(nombre) != ["token"] or not isinstance(prop, dict):
        return False
    return "vistaprevia" in _normal(str(prop.get("description", "")))


def _parametros(esquema: object) -> list[tuple[str, object]]:
    """Todos los nombres de parámetro del esquema, también los de objetos y listas anidados."""
    salida: list[tuple[str, object]] = []
    if isinstance(esquema, dict):
        props = esquema.get("properties")
        if isinstance(props, dict):
            for nombre, prop in props.items():
                salida.append((str(nombre), prop))
                salida.extend(_parametros(prop))
        for clave in ("items", "anyOf", "oneOf", "allOf"):
            sub = esquema.get(clave)
            for s in sub if isinstance(sub, list) else [sub]:
                salida.extend(_parametros(s))
    return salida


def _toques(h: Herramienta) -> list[tuple[str, str]]:
    """(dónde, tema) por cada tema prohibido que toca el nombre o un parámetro de `h`."""
    toques = [(h.nombre, t) for t in _temas(h.nombre)]
    for nombre, prop in _parametros(h.esquema):
        if not _es_token_de_vista_previa(nombre, prop):
            toques.extend((nombre, t) for t in _temas(nombre))
    return toques


def _validar(h: Herramienta) -> None:
    if h.clase not in CLASES:
        raise CatalogoInvalido(f"{h.nombre}: falta la clase o no es {'/'.join(CLASES)}")
    if not h.motivo.strip():
        raise CatalogoInvalido(f"{h.nombre}: falta el motivo de la clase")
    if h.clase != "prohibida":
        toques = _toques(h)
        # Única excepción: el Pixel ID como parámetro de configuración de la tienda, sin ningún parámetro de token,
        # y dicho en el motivo.
        pixel = [(d, t) for d, t in toques if t == "meta" and d != h.nombre and "pixel" in _fichas(d)]
        resto = [x for x in toques if x not in pixel]
        if resto or (pixel and "pixel" not in _normal(h.motivo)):
            donde, tema = (resto or pixel)[0]
            raise CatalogoInvalido(f"{h.nombre}: toca «{tema}» (en {donde}) y no está en prohibida")
    consulta = _fichas(h.nombre)[:1] and _fichas(h.nombre)[0] in _CONSULTA
    escribe = bool(_ESCRIBE.search(h.descripcion))
    solo_lectura = "sololectura" in _normal(h.descripcion)
    if h.clase == "escritura" and (consulta or (solo_lectura and not escribe)):
        raise CatalogoInvalido(f"{h.nombre}: es de solo consulta y está en escritura")
    if h.clase == "lectura" and escribe:
        raise CatalogoInvalido(f"{h.nombre}: su descripción dice que ESCRIBE y está en lectura")


def _texto(valor: object, campo: str, nombre: str) -> str:
    if valor is None:
        return ""
    if not isinstance(valor, str):
        raise CatalogoInvalido(f"{nombre}: «{campo}» no es texto")
    return valor


def cargar_catalogo(ruta: Path = RAIZ / "config/impultienda_tools.json") -> Catalogo:
    """Lee y valida el catálogo. `CatalogoInvalido` si no se puede leer o alguna herramienta está mal clasificada."""
    try:
        doc = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogoInvalido(f"catálogo ilegible: {ruta} ({type(exc).__name__})") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("herramientas"), list):
        raise CatalogoInvalido("el catálogo no tiene la lista «herramientas»")
    faltan = doc.get("faltan", [])
    if not isinstance(faltan, list) or not all(isinstance(f, str) and f.strip() for f in faltan):
        raise CatalogoInvalido("«faltan» debe ser una lista de textos")
    herramientas: dict[str, Herramienta] = {}
    for i, crudo in enumerate(doc["herramientas"]):
        if not isinstance(crudo, dict) or not isinstance(crudo.get("nombre"), str):
            raise CatalogoInvalido(f"herramienta {i} sin nombre")
        nombre = crudo["nombre"]
        if not _NOMBRE.fullmatch(nombre):
            raise CatalogoInvalido(f"nombre no válido: {nombre!r}")
        if nombre in herramientas:
            raise CatalogoInvalido(f"{nombre}: nombre repetido")
        esquema = crudo.get("esquema")
        if not isinstance(esquema, dict):
            raise CatalogoInvalido(f"{nombre}: falta el esquema")
        h = Herramienta(
            nombre=nombre,
            descripcion=_texto(crudo.get("descripcion"), "descripcion", nombre),
            esquema=esquema,
            clase=_texto(crudo.get("clase"), "clase", nombre),  # type: ignore[arg-type]
            motivo=_texto(crudo.get("motivo"), "motivo", nombre),
        )
        _validar(h)
        herramientas[nombre] = h
    return Catalogo(
        herramientas,
        fuente=str(doc.get("fuente", "")),
        fecha=str(doc.get("fecha", "")),
        servidor=str(doc.get("servidor", "")),
        plan=str(doc.get("plan", "")),
        faltan=tuple(faltan),
    )


def permitidas(catalogo: dict[str, Herramienta], clase: Literal["lectura", "escritura"]) -> list[str]:
    """Nombres (ordenados) de las herramientas de esa clase. Nunca lista las `prohibida`."""
    if clase not in ("lectura", "escritura"):
        raise ValueError(f"solo «lectura» o «escritura», no {clase!r}")
    return sorted(n for n, h in catalogo.items() if h.clase == clase)


def nombre_mcp(nombre: str) -> str:
    """El nombre con que el cliente expone la herramienta (`mcp__impultienda__<nombre>`)."""
    if not _NOMBRE.fullmatch(nombre):
        raise ValueError(f"nombre de herramienta no válido: {nombre!r}")
    return PREFIJO_MCP + nombre


def huella_catalogo(catalogo: dict[str, Herramienta]) -> str:
    """sha256 del JSON canónico (herramientas por nombre, con su esquema, clase y motivo, más `faltan`)."""
    canon = {
        "herramientas": [asdict(catalogo[n]) for n in sorted(catalogo)],
        "faltan": list(getattr(catalogo, "faltan", ())),
    }
    texto = json.dumps(canon, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()
