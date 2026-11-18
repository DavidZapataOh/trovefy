"""Catálogo clasificado del MCP oficial de Impultienda (plan 19, Tarea 3; resoluciones 38 y 39; ronda de revisión).

`config/impultienda_tools.json` guarda, tal cual, el nombre, la descripción y el esquema de entrada de cada
herramienta que expone el servidor (la evidencia), y al lado la clase (`lectura`, `escritura` o `prohibida`), el
motivo y, si hace falta, sus restricciones. Este módulo lo carga y se niega a dar por bueno un catálogo mal
clasificado:

- una herramienta que toca dinero, Meta, cuentas o secretos (por su nombre o por el de alguno de sus parámetros, en
  cualquier rincón del esquema, camelCase incluido) tiene que ser `prohibida`, salvo que ese parámetro esté en sus
  `parametros_prohibidos` (nunca se envía) o en `parametros_permitidos_por_ruling` (con el id del ruling);
- una `lectura` necesita un verbo de consulta o «SOLO LECTURA» en la descripción, y no puede decir «escribe» ni
  llevar `confirmar`, `token` o `modo` (``lectura_por_ruling: "R-x"`` dispensa solo del verbo/«SOLO LECTURA»);
  una de consulta no puede ser `escritura`.

Restricciones por herramienta (las aplica `violaciones`, y con ella el hook `hooks/impultienda_guard.py`), con
rutas de parámetro del tipo ``a.b`` o ``bloques[].tipo``:

- ``parametros_prohibidos``: nunca se envían;
- ``valores_prohibidos``: ``{ruta: [valores]}`` que no se envían nunca (``escasez``, ``countdown``…);
- ``valores_obligatorios``: ``{ruta: valor}`` que toda llamada lleva, exacto (``minutos_timer_bump: 0``);
- ``parametros_permitidos_por_ruling``: ``{ruta: "R-x"}``, excepción explícita del tema;
- ``devuelve_url_firmada``: la respuesta trae URLs firmadas de corta vida (M-5): pásala por
  `redactar_urls_firmadas` antes de guardarla.

Escrituras (contrato mínimo hasta la Tarea 11): solo las que lista un ``checkout/<PAIS>/PLAN-MCP.json``
(``{"operaciones": [{herramienta, argumentos}], "huella": sha256}``) cuya huella está en el ``plan_huella`` de un
``APROBACION.md`` al lado, con la cita literal del usuario en ``cita`` (ver `escritura_aprobada`).

Solo biblioteca estándar: el hook lo importa con el python3 del sistema. La CLI nunca llama al MCP.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlsplit

from trovefy.fichas import fichas

RAIZ = Path(__file__).resolve().parents[3]
PREFIJO_MCP = "mcp__impultienda__"
PREFIJO_SERVIDOR = "impultienda_"

Clase = Literal["lectura", "escritura", "prohibida"]
CLASES: tuple[str, ...] = ("lectura", "escritura", "prohibida")

PROHIBIDAS_POR_TEMA = (
    "pago", "pasarela", "impul pay", "whop", "stripe", "mercado pago", "retir", "transfer", "billetera", "banco",
    "tarjeta", "reembols", "refund", "payout", "withdraw", "contraseña", "password", "usuario", "seguridad", "meta",
    "facebook", "pixel_event", "creativ", "anuncio", "catalog", "token", "capi", "secret", "api_key", "webhook",
    # ronda de revisión (M-1)
    "fb", "ig", "instagram", "whatsapp", "ads", "ad_account", "dataset", "cobr", "pagar", "payment", "gateway",
    "devol", "reintegr", "bank", "card", "iban", "cbu", "cvu", "clave", "credencial", "key", "auth", "login",
    "pixel", "metaads",
)
# Cortas que aparecen dentro de palabras corrientes («metas», «capital», «configurar»): solo como palabra entera
# (o su plural).
_ENTERAS = frozenset({"meta", "capi", "fb", "ig", "ads", "card", "key", "cbu", "cvu", "iban"})
_CONSULTA = frozenset({"get", "list", "read", "obtener", "listar", "ver", "leer"})
_PARAMS_DE_ESCRITURA = frozenset({"confirmar", "token", "modo"})
_ESCRIBE = re.compile(r"\bescribe\b", re.IGNORECASE)
_NOMBRE = re.compile(r"[a-z0-9_]+")
_RULING = re.compile(r"R-[a-z0-9]+")

# L-2: herramientas en las que un parámetro «pixel» de Meta (sin token) puede ir fuera de `prohibida`. Vacía: R-d
# deja `configurar_tracking` prohibida y ninguna otra lo necesita.
EXCEPCION_PIXEL: frozenset[str] = frozenset()

# L-1: las descripciones exactas del `token` de la vista previa en el servidor.
_DESCRIPCIONES_TOKEN = frozenset({
    "Token de la vista previa",
    "token de la vista previa",
    "Token que devolvió la vista previa",
    "Solo formato archivo: token de la vista previa",
    "El token de la vista previa. OBLIGATORIO con confirmar: true",
    "El `token` que devolvió la vista previa. OBLIGATORIO con confirmar: true",
    ("El `token` que devolvió la vista previa. OBLIGATORIO con confirmar: true — ata lo que el vendedor aprobó con "
     "lo que se aplica"),
})
_MAX_TOKEN = 64
_PATRON_HEX = re.compile(r"\^\[0-9a-f\]\{(\d+)\}\$")

_CLAVES_HERRAMIENTA = frozenset({
    "nombre", "descripcion", "esquema", "clase", "motivo", "parametros_prohibidos", "valores_prohibidos",
    "valores_obligatorios", "parametros_permitidos_por_ruling", "devuelve_url_firmada", "lectura_por_ruling",
})

PLAN_MCP = "PLAN-MCP.json"
APROBACION = "APROBACION.md"
_P_ID = re.compile(r"p-\d{4}-[a-z0-9-]+")
_PAIS = re.compile(r"[A-Z]{2}")
_HUELLA = re.compile(r"[0-9a-f]{64}")


class CatalogoInvalido(ValueError):
    """El catálogo no se puede leer o una herramienta está mal clasificada."""


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    descripcion: str
    esquema: dict
    clase: Clase
    motivo: str
    parametros_prohibidos: tuple[str, ...] = ()
    valores_prohibidos: dict[str, tuple] = field(default_factory=dict)
    valores_obligatorios: dict[str, object] = field(default_factory=dict)
    parametros_permitidos_por_ruling: dict[str, str] = field(default_factory=dict)
    devuelve_url_firmada: bool = False
    lectura_por_ruling: str | None = None


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
    return "".join(fichas(texto))


_TEMAS = tuple((t, _normal(t)) for t in PROHIBIDAS_POR_TEMA)


def _temas(texto: str) -> list[str]:
    """Los temas de `PROHIBIDAS_POR_TEMA` que toca `texto` (normalizado como `trovefy.mapa`, camelCase partido)."""
    partes = fichas(texto, camel=True)
    junto = "".join(partes)
    enteras = set(partes) | {f[:-1] for f in partes if f.endswith("s")}
    return [t for t, n in _TEMAS if (n in enteras if t in _ENTERAS else n in junto)]


# --- recorrido del esquema -------------------------------------------------------------------------------------


def _resolver_ref(raiz: dict, ref: object, donde: str) -> object:
    """El destino de un ``$ref`` local (``#/…``); `CatalogoInvalido` si no se puede resolver."""
    if not isinstance(ref, str) or not (ref == "#" or ref.startswith("#/")):
        raise CatalogoInvalido(f"{donde}: $ref no resoluble: {ref!r} (solo referencias locales «#/…»)")
    nodo: object = raiz
    for parte in ref[2:].split("/") if ref != "#" else []:
        parte = unquote(parte).replace("~1", "/").replace("~0", "~")
        if isinstance(nodo, dict) and parte in nodo:
            nodo = nodo[parte]
        elif isinstance(nodo, list) and parte.isdigit() and int(parte) < len(nodo):
            nodo = nodo[int(parte)]
        else:
            raise CatalogoInvalido(f"{donde}: $ref no resoluble: {ref!r}")
    return nodo


def _unir(prefijo: str, nombre: str) -> str:
    return f"{prefijo}.{nombre}" if prefijo else nombre


def _parametros(raiz: dict, donde: str) -> list[tuple[str, str, object]]:
    """``(ruta, nombre, subesquema)`` de cada parámetro del esquema, en cualquier rincón: ``properties``,
    ``patternProperties``, ``additionalProperties``, ``items``/``prefixItems``, combinadores, ``not``,
    ``if/then/else``, ``$defs``/``definitions`` y lo que apunta un ``$ref``. `CatalogoInvalido` si un ``$ref`` no
    se resuelve."""
    salida: list[tuple[str, str, object]] = []

    def andar(esquema: object, prefijo: str, refs: frozenset[str]) -> None:
        if isinstance(esquema, list):
            for s in esquema:
                andar(s, prefijo, refs)
            return
        if not isinstance(esquema, dict):
            return
        if "$ref" in esquema:
            ref = esquema["$ref"]
            destino = _resolver_ref(raiz, ref, donde)
            if ref not in refs:
                andar(destino, prefijo, refs | {ref})
        props = esquema.get("properties")
        if isinstance(props, dict):
            for nombre, prop in props.items():
                ruta = _unir(prefijo, str(nombre))
                salida.append((ruta, str(nombre), prop))
                andar(prop, ruta, refs)
        patrones = esquema.get("patternProperties")
        if isinstance(patrones, dict):
            for patron, prop in patrones.items():
                ruta = f"{prefijo}{{{patron}}}"
                salida.append((ruta, str(patron), prop))
                andar(prop, ruta, refs)
        adicionales = esquema.get("additionalProperties")
        if isinstance(adicionales, dict):
            andar(adicionales, f"{prefijo}{{}}", refs)
        for clave in ("items", "prefixItems"):
            andar(esquema.get(clave), f"{prefijo}[]", refs)
        for clave in ("anyOf", "oneOf", "allOf", "not", "if", "then", "else"):
            andar(esquema.get(clave), prefijo, refs)
        for clave in ("$defs", "definitions"):
            defs = esquema.get(clave)
            if isinstance(defs, dict):
                for nombre, sub in defs.items():
                    andar(sub, f"#{clave}/{nombre}", refs)

    andar(raiz, "", frozenset())
    return salida


def _token_de_vista_previa(esquema: dict) -> dict | None:
    """El `token` de los cambios en dos pasos (L-1): en la raíz, con una descripción exacta del servidor, longitud
    acotada (``maxLength`` ≤ 64 o un patrón ``^[0-9a-f]{N}$`` con N ≤ 64) y un `confirmar` booleano al lado. Lo
    devuelve el servidor y ata lo aprobado con lo aplicado: no es una credencial."""
    props = esquema.get("properties")
    if not isinstance(props, dict):
        return None
    token, confirmar = props.get("token"), props.get("confirmar")
    if not isinstance(token, dict) or not isinstance(confirmar, dict) or confirmar.get("type") != "boolean":
        return None
    if token.get("type") != "string" or token.get("description") not in _DESCRIPCIONES_TOKEN:
        return None
    largo = token.get("maxLength")
    patron = _PATRON_HEX.fullmatch(str(token.get("pattern", "")))
    acotado = (isinstance(largo, int) and not isinstance(largo, bool) and 0 < largo <= _MAX_TOKEN) or (
        patron is not None and 0 < int(patron.group(1)) <= _MAX_TOKEN)
    return token if acotado else None


def _token_valido(token_esquema: dict, valor: object) -> bool:
    if not isinstance(valor, str) or not valor:
        return False
    patron = token_esquema.get("pattern")
    if isinstance(patron, str) and not re.fullmatch(patron.removeprefix("^").removesuffix("$"), valor):
        return False
    largo = token_esquema.get("maxLength")
    return len(valor) <= (largo if isinstance(largo, int) else _MAX_TOKEN)


# --- validación del catálogo -----------------------------------------------------------------------------------


def _toques(h: Herramienta, parametros: list[tuple[str, str, object]]) -> list[tuple[str, str]]:
    """(dónde, tema) por cada tema prohibido que toca el nombre o un parámetro de `h` y no está exento."""
    toques = [(h.nombre, t) for t in _temas(h.nombre)]
    token_vp = _token_de_vista_previa(h.esquema) is not None
    prohibidos = h.parametros_prohibidos
    for ruta, nombre, _prop in parametros:
        if token_vp and ruta == "token":
            continue
        if ruta in h.parametros_permitidos_por_ruling:
            continue
        if any(ruta == p or ruta.startswith((p + ".", p + "[", p + "{")) for p in prohibidos):
            continue
        toques.extend((ruta, t) for t in _temas(nombre))
    return toques


def _validar(h: Herramienta) -> None:
    if h.clase not in CLASES:
        raise CatalogoInvalido(f"{h.nombre}: falta la clase o no es {'/'.join(CLASES)}")
    if not h.motivo.strip():
        raise CatalogoInvalido(f"{h.nombre}: falta el motivo de la clase")
    parametros = _parametros(h.esquema, h.nombre)
    _validar_restricciones(h, {ruta for ruta, _, _ in parametros})
    if h.lectura_por_ruling is not None:
        if not isinstance(h.lectura_por_ruling, str) or not _RULING.fullmatch(h.lectura_por_ruling):
            raise CatalogoInvalido(f"{h.nombre}: «lectura_por_ruling» necesita el id del ruling (R-x)")
        if h.clase != "lectura":
            raise CatalogoInvalido(f"{h.nombre}: «lectura_por_ruling» solo va en una herramienta lectura")
    if h.clase != "prohibida":
        toques = _toques(h, parametros)
        # L-2: el Pixel ID como parámetro de configuración, solo en las herramientas nombradas.
        if h.nombre in EXCEPCION_PIXEL:
            toques = [(d, t) for d, t in toques
                      if not (t in ("meta", "pixel") and d != h.nombre and "pixel" in fichas(d, camel=True))]
        if toques:
            donde, tema = toques[0]
            raise CatalogoInvalido(f"{h.nombre}: toca «{tema}» (en {donde}) y no está en prohibida")
    corto = h.nombre.removeprefix(PREFIJO_SERVIDOR)
    verbo = (fichas(corto) or [""])[0]
    consulta = verbo in _CONSULTA
    escribe = bool(_ESCRIBE.search(h.descripcion))
    solo_lectura = "sololectura" in _normal(h.descripcion)
    if h.clase == "escritura" and (consulta or (solo_lectura and not escribe)):
        raise CatalogoInvalido(f"{h.nombre}: es de solo consulta y está en escritura")
    if h.clase == "lectura":
        if escribe:
            raise CatalogoInvalido(f"{h.nombre}: su descripción dice que escribe y está en lectura")
        # R-g: la única dispensa es la del verbo/«SOLO LECTURA», por ruling explícito; lo demás se exige igual.
        if not (consulta or solo_lectura or h.lectura_por_ruling):
            raise CatalogoInvalido(f"{h.nombre}: lectura sin verbo de consulta ni «SOLO LECTURA» en la descripción")
        de_escritura = sorted({n for _, n, _ in parametros} & _PARAMS_DE_ESCRITURA)
        if de_escritura:
            raise CatalogoInvalido(f"{h.nombre}: lectura con parámetro de escritura ({', '.join(de_escritura)})")


def _escalar(valor: object) -> bool:
    return valor is None or isinstance(valor, (str, int, float, bool))


def _validar_restricciones(h: Herramienta, rutas: set[str]) -> None:
    def conocida(ruta: str, que: str) -> None:
        if ruta not in rutas:
            raise CatalogoInvalido(f"{h.nombre}: {que} «{ruta}» no es un parámetro del esquema")

    for ruta in h.parametros_prohibidos:
        conocida(ruta, "parámetro prohibido")
    for ruta, valores in h.valores_prohibidos.items():
        conocida(ruta, "valores prohibidos de")
        if not valores or not all(_escalar(v) for v in valores):
            raise CatalogoInvalido(f"{h.nombre}: valores prohibidos de «{ruta}» vacíos o no escalares")
    for ruta, valor in h.valores_obligatorios.items():
        conocida(ruta, "valor obligatorio de")
        if not _escalar(valor):
            raise CatalogoInvalido(f"{h.nombre}: el valor obligatorio de «{ruta}» no es escalar")
    for ruta, ruling in h.parametros_permitidos_por_ruling.items():
        conocida(ruta, "parámetro permitido por ruling")
        if not isinstance(ruling, str) or not _RULING.fullmatch(ruling):
            raise CatalogoInvalido(f"{h.nombre}: «{ruta}» necesita el id de su ruling (R-x), no {ruling!r}")


def _texto(valor: object, campo: str, nombre: str) -> str:
    if valor is None:
        return ""
    if not isinstance(valor, str):
        raise CatalogoInvalido(f"{nombre}: «{campo}» no es texto")
    return valor


def _lista_textos(valor: object, campo: str, nombre: str) -> tuple[str, ...]:
    if valor is None:
        return ()
    if not isinstance(valor, list) or not all(isinstance(x, str) and x for x in valor):
        raise CatalogoInvalido(f"{nombre}: «{campo}» debe ser una lista de textos")
    return tuple(valor)


def _mapa(valor: object, campo: str, nombre: str) -> dict:
    if valor is None:
        return {}
    if not isinstance(valor, dict) or not all(isinstance(k, str) and k for k in valor):
        raise CatalogoInvalido(f"{nombre}: «{campo}» debe ser un mapa {{ruta: …}}")
    return dict(valor)


def _herramienta(crudo: dict, nombre: str) -> Herramienta:
    sobran = set(crudo) - _CLAVES_HERRAMIENTA
    if sobran:
        raise CatalogoInvalido(f"{nombre}: claves desconocidas: {', '.join(sorted(sobran))}")
    esquema = crudo.get("esquema")
    if not isinstance(esquema, dict):
        raise CatalogoInvalido(f"{nombre}: falta el esquema")
    prohibidos = _mapa(crudo.get("valores_prohibidos"), "valores_prohibidos", nombre)
    for ruta, valores in prohibidos.items():
        if not isinstance(valores, list):
            raise CatalogoInvalido(f"{nombre}: valores prohibidos de «{ruta}» deben ser una lista")
    firmada = crudo.get("devuelve_url_firmada", False)
    if not isinstance(firmada, bool):
        raise CatalogoInvalido(f"{nombre}: «devuelve_url_firmada» debe ser true o false")
    return Herramienta(
        nombre=nombre,
        descripcion=_texto(crudo.get("descripcion"), "descripcion", nombre),
        esquema=esquema,
        clase=_texto(crudo.get("clase"), "clase", nombre),  # type: ignore[arg-type]
        motivo=_texto(crudo.get("motivo"), "motivo", nombre),
        parametros_prohibidos=_lista_textos(crudo.get("parametros_prohibidos"), "parametros_prohibidos", nombre),
        valores_prohibidos={r: tuple(v) for r, v in prohibidos.items()},
        valores_obligatorios=_mapa(crudo.get("valores_obligatorios"), "valores_obligatorios", nombre),
        parametros_permitidos_por_ruling=_mapa(crudo.get("parametros_permitidos_por_ruling"),
                                               "parametros_permitidos_por_ruling", nombre),
        devuelve_url_firmada=firmada,
        lectura_por_ruling=crudo.get("lectura_por_ruling"),
    )


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
        h = _herramienta(crudo, nombre)
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


def _sha(valor: object) -> str:
    texto = json.dumps(valor, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def huella_catalogo(catalogo: dict[str, Herramienta]) -> str:
    """sha256 del JSON canónico (herramientas por nombre, con esquema, clase, motivo y restricciones, más `faltan`)."""
    return _sha({
        "herramientas": [asdict(catalogo[n]) for n in sorted(catalogo)],
        "faltan": list(getattr(catalogo, "faltan", ())),
    })


def huella_evidencia(catalogo: dict[str, Herramienta]) -> str:
    """sha256 solo de lo que dice el servidor (nombre, descripción y esquema de cada herramienta): cambia si cambia
    el MCP, no si cambia la clasificación."""
    return _sha([{"nombre": n, "descripcion": catalogo[n].descripcion, "esquema": catalogo[n].esquema}
                 for n in sorted(catalogo)])


# --- llamadas: restricciones por herramienta -------------------------------------------------------------------


def _alternativas(raiz: dict, esquema: object, refs: frozenset[str] = frozenset()) -> list[dict]:
    """El esquema y sus alternativas (``$ref``, ``anyOf``/``oneOf``/``allOf``) ya resueltos."""
    if not isinstance(esquema, dict):
        return []
    salida = [esquema]
    ref = esquema.get("$ref")
    if isinstance(ref, str) and ref not in refs:
        salida += _alternativas(raiz, _resolver_ref(raiz, ref, "esquema"), refs | {ref})
    for clave in ("anyOf", "oneOf", "allOf"):
        sub = esquema.get(clave)
        for s in sub if isinstance(sub, list) else []:
            salida += _alternativas(raiz, s, refs)
    return salida


def _claves_desconocidas(raiz: dict, esquema: object, valor: object, ruta: str, problemas: list[str]) -> None:
    alts = _alternativas(raiz, esquema)
    if isinstance(valor, dict):
        props: dict[str, object] = {}
        for a in alts:
            if isinstance(a.get("properties"), dict):
                for k, v in a["properties"].items():
                    props.setdefault(k, v)
        for clave, sub in valor.items():
            donde = _unir(ruta, str(clave))
            if clave not in props:
                problemas.append(f"{donde}: parámetro que no está en el esquema del catálogo")
            else:
                _claves_desconocidas(raiz, props[clave], sub, donde, problemas)
    elif isinstance(valor, list):
        for i, elemento in enumerate(valor):
            sub = None
            for a in alts:
                previos = a.get("prefixItems")
                if isinstance(previos, list) and i < len(previos):
                    sub = previos[i]
                elif isinstance(a.get("items"), dict):
                    sub = a["items"]
                if sub is not None:
                    break
            if sub is None:
                if isinstance(elemento, (dict, list)):
                    problemas.append(f"{ruta}[]: elemento sin esquema en el catálogo")
            else:
                _claves_desconocidas(raiz, sub, elemento, f"{ruta}[]", problemas)


def _valores_en(argumentos: object, ruta: str) -> Iterator[object]:
    """Los valores presentes en `argumentos` en la ruta (``a.b``, ``bloques[].tipo``)."""
    nodos = [argumentos]
    for parte in re.findall(r"\[\]|[^.\[\]]+", ruta):
        siguientes: list[object] = []
        for n in nodos:
            if parte == "[]":
                if isinstance(n, list):
                    siguientes.extend(n)
            elif isinstance(n, dict) and parte in n:
                siguientes.append(n[parte])
        nodos = siguientes
    yield from nodos


def _mismo(valor: object, otro: object) -> bool:
    if isinstance(valor, str) and isinstance(otro, str):
        return _normal(valor) == _normal(otro)
    return type(valor) is type(otro) and valor == otro


def violaciones(h: Herramienta, argumentos: object) -> list[str]:
    """Lo que la llamada `argumentos` incumple de su herramienta: parámetros fuera del esquema (recursivo),
    parámetros prohibidos, valores prohibidos y valores obligatorios. ``[]`` = bien."""
    if not isinstance(argumentos, dict):
        return ["los argumentos no son un objeto"]
    problemas: list[str] = []
    try:
        _claves_desconocidas(h.esquema, h.esquema, argumentos, "", problemas)
    except CatalogoInvalido as exc:
        problemas.append(str(exc))
    for ruta in h.parametros_prohibidos:
        if any(True for _ in _valores_en(argumentos, ruta)):
            problemas.append(f"{ruta}: parámetro prohibido en {h.nombre} (nunca se envía)")
    for ruta, prohibidos in h.valores_prohibidos.items():
        for valor in _valores_en(argumentos, ruta):
            for p in prohibidos:
                if _mismo(valor, p):
                    problemas.append(f"{ruta}: el valor «{p}» está prohibido en {h.nombre}")
    for ruta, obligatorio in h.valores_obligatorios.items():
        valores = list(_valores_en(argumentos, ruta))
        if not valores or not all(type(v) is type(obligatorio) and v == obligatorio for v in valores):
            problemas.append(f"{ruta}: {h.nombre} lo lleva siempre y exactamente en {obligatorio!r}")
    return problemas


# --- plan aprobado (contrato mínimo hasta la Tarea 11) -----------------------------------------------------------


def huella_plan(operaciones: list[dict]) -> str:
    """sha256 del JSON canónico de ``[{herramienta, argumentos}]`` (claves ordenadas, sin espacios)."""
    return _sha(operaciones)


def _frontmatter(texto: str) -> dict[str, str]:
    """Las claves de primer nivel ``clave: valor`` del frontmatter (sin YAML: el hook no lo tiene)."""
    lineas = texto.splitlines()
    if not lineas or lineas[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for linea in lineas[1:]:
        if linea.strip() == "---":
            return meta
        m = re.fullmatch(r"([A-Za-z_][\w-]*):\s*(.*?)\s*", linea)
        if not m:
            continue
        valor = m.group(2)
        if valor.startswith('"'):
            try:
                valor = json.loads(valor)
            except ValueError:
                continue
        elif valor.startswith("'") and valor.endswith("'") and len(valor) >= 2:
            valor = valor[1:-1].replace("''", "'")
        meta[m.group(1)] = valor if isinstance(valor, str) else ""
    return {}


def _canon(valor: object) -> str:
    return json.dumps(valor, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _casa(op: object, h: Herramienta, argumentos: dict) -> bool:
    if not isinstance(op, dict) or op.get("herramienta") != h.nombre or not isinstance(op.get("argumentos"), dict):
        return False
    esperado = _canon(op["argumentos"])
    if _canon(argumentos) == esperado:
        return True
    token = _token_de_vista_previa(h.esquema)
    if token is None:
        return False
    base = {k: v for k, v in argumentos.items() if k not in ("confirmar", "token")}
    if "token" in argumentos:
        # Segundo paso: confirmar con el token que devolvió la vista previa de esos mismos argumentos.
        if argumentos.get("confirmar") is not True or not _token_valido(token, argumentos["token"]):
            return False
    elif argumentos.get("confirmar", False) is not False:
        return False
    return _canon(base) == esperado


def escritura_aprobada(vault: Path, h: Herramienta, argumentos: dict) -> str | None:
    """``None`` si algún ``productos/<p>/checkout/<PAIS>/APROBACION.md`` aprueba (``plan_huella`` + ``cita``) un
    ``PLAN-MCP.json`` íntegro que lista esta herramienta con estos argumentos exactos (en los cambios en dos pasos,
    también su confirmación con el token de la vista previa). Si no, el motivo para denegar."""
    vault = Path(vault)
    motivo = (f"esa escritura no está en un plan aprobado: hace falta checkout/<PAIS>/{APROBACION} con el "
              f"plan_huella de un {PLAN_MCP} que liste {h.nombre} con estos argumentos exactos")
    try:
        raiz = vault.resolve()
        candidatos = sorted((vault / "productos").glob(f"*/checkout/*/{APROBACION}"))
    except OSError:
        return motivo
    for aprobacion in candidatos:
        carpeta = aprobacion.parent
        plan_ruta = carpeta / PLAN_MCP
        try:
            if (not _PAIS.fullmatch(carpeta.name) or not _P_ID.fullmatch(carpeta.parent.parent.name)
                    or aprobacion.is_symlink() or plan_ruta.is_symlink()
                    or raiz not in plan_ruta.resolve().parents):
                continue
            meta = _frontmatter(aprobacion.read_text(encoding="utf-8"))
            plan = json.loads(plan_ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        huella = meta.get("plan_huella", "")
        if not _HUELLA.fullmatch(huella) or not meta.get("cita", "").strip():
            continue
        if not isinstance(plan, dict) or not isinstance(plan.get("operaciones"), list):
            continue
        if plan.get("huella") != huella or huella_plan(plan["operaciones"]) != huella:
            continue
        if any(_casa(op, h, argumentos) for op in plan["operaciones"]):
            return None
    return motivo


# --- URLs firmadas (M-5) -----------------------------------------------------------------------------------------

URL_REDACTADA = "[url firmada redactada]"
_URL = re.compile(r"https?://[^\s\"'<>\\)\]}]+", re.IGNORECASE)
_CLAVES_FIRMA = frozenset({
    "signature", "sig", "token", "access_token", "upload_token", "jwt", "auth", "expires", "policy", "key-pair-id",
    "se", "sp", "sv", "sr", "skoid",
})
_SEGMENTO_SECRETO = re.compile(r"[A-Za-z0-9_\-]{20,}")


def _firmada(url: str) -> bool:
    try:
        partes = urlsplit(url)
        claves = {k.casefold() for k, _ in parse_qsl(partes.query, keep_blank_values=True)}
    except ValueError:
        return True
    if claves & _CLAVES_FIRMA or any(k.startswith(("x-amz-", "x-goog-")) for k in claves):
        return True
    for segmento in partes.path.split("/"):
        if (_SEGMENTO_SECRETO.fullmatch(segmento) and re.search(r"[0-9]", segmento)
                and re.search(r"[A-Za-z]", segmento)):
            return True
    return False


def redactar_urls_firmadas(texto: str) -> str:
    """`texto` con cada URL firmada (firma o token en la consulta, o un segmento de ruta con forma de clave)
    cambiada por `URL_REDACTADA`, para guardar en caché o en el vault la respuesta de una herramienta con
    ``devuelve_url_firmada``. Ante la duda se redacta."""
    return _URL.sub(lambda m: URL_REDACTADA if _firmada(m.group(0)) else m.group(0), texto)
