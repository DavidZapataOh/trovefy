"""Mapa versionado de pantallas de un servicio externo (Impultienda, Whop, Hotmart).

Un `mapa.yaml` describe, por pantalla, la URL, una *firma* (textos que deben aparecer para saber que
la pantalla es la esperada) y los campos que se leen con una expresión regular de un solo grupo.
Este módulo solo describe: no hace clics ni escribe en el servicio (eso lo hace, y solo él,
`trovefy.tienda.conductor.Conductor`).

`capturado` es la fecha en que el mapa se confirmó con la pantalla real del usuario; `None` significa
que se construyó a partir de documentación o páginas públicas y no se puede certificar nada con él.
Cada pantalla puede llevar su propio `capturado`. Una pantalla de solo lectura (sin `controles`) hereda el
de la raíz si no lo tiene; una pantalla con `controles` **nunca** hereda: sin `capturado` propio no se
escribe en ella (ruling R-1: confirmar el paso 09 no vuelve escribible una pantalla que nadie ha visto).

Claves opcionales (un mapa de la fase 0 carga igual):

- raíz `hosts: [str]`: hosts permitidos (por defecto, los de las `url` de las pantallas);
- raíz `limites_plan: {<Plan>: {tiendas, bumps, upsells, downsell}}` con `fuente_limites` obligatoria;
- por pantalla `prohibida: bool` (cobros, pasarelas, retiros…: nunca se escribe en ella ni se captura; una
  pantalla con una palabra prohibida en la url, la firma o un control cuenta como prohibida aunque no lo diga) y
  `controles: {<nombre>: {etiqueta | css, rol?, tipo, secreto?}}`.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

TIPOS = ("texto", "numero", "precio", "select", "interruptor", "archivo", "boton", "area")
# Las diez primeras son la lista mínima del plan 19; las siguientes, de la revisión de las tareas 1–2 (M-2), y
# la última línea, de la segunda revisión (L-c). Se comparan normalizadas (ver `palabra_prohibida`), así que
# «impul pay» también casa con «Impul-Pay», «impul%2Dpay» o «impul pаy» (con «а» cirílica).
# «checkout» NO está: las pantallas `checkout` y `checkout_hotmart` de los planes 18/19 tienen controles que el
# conductor configura (idioma, campos, temporizador…); como palabra prohibida harían inválidos esos mapas.
PALABRAS_PROHIBIDAS = (
    "pasarela", "impul pay", "retir", "tarjeta", "banco", "contraseña", "password", "payout", "withdraw",
    "datos financieros",
    "pago", "cobro", "payment", "billing", "bank", "bancari", "card", "cbu", "cvu", "iban", "mercadopago",
    "stripe", "paypal", "retiro", "impulpay",
    "financial", "balance", "pagamento", "saque", "senha", "cartao", "clave", "facturacion", "credencial",
    "apikey", "wallet", "saldo",
)
# Términos cortos que aparecen dentro de palabras corrientes («cardio», «ScoreCard», «Ibáñez», «striped», un id
# como «7xCbUq9»): solo casan como palabra entera (o su plural en -s), nunca dentro de otra.
_PALABRA_ENTERA = frozenset({"card", "cbu", "cvu", "iban", "bank", "stripe"})
_CLAVES_CONTROL = {"etiqueta", "rol", "css", "tipo", "secreto"}
_CLAVES_LIMITES = {"tiendas": int, "bumps": int, "upsells": int, "downsell": bool}


class MapaInvalido(ValueError):
    """El mapa.yaml no tiene la estructura esperada."""


class FirmaAusente(Exception):
    """Falta algún texto de la firma: la pantalla cambió o no es la esperada."""

    def __init__(self, pantalla):
        super().__init__(pantalla)
        self.pantalla = pantalla


@dataclass(frozen=True)
class Control:
    """Un control de una pantalla: se localiza por etiqueta (y rol) o por CSS."""

    pantalla: str
    nombre: str
    etiqueta: str | None
    rol: str | None
    css: str | None
    tipo: str
    secreto: bool


_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")


def _fecha(valor, ruta: Path, donde: str = "") -> str | None:
    if valor is None:
        return None
    texto = valor.isoformat() if isinstance(valor, date) else str(valor)
    if not _FECHA.fullmatch(texto):
        raise MapaInvalido(f"{ruta}: «capturado»{donde} debe ser null o una fecha AAAA-MM-DD")
    return texto


def _texto(valor) -> bool:
    return isinstance(valor, str) and bool(valor.strip())


def _validar_control(origen, pantalla: str, nombre: str, c) -> Control:
    donde = f"{origen}: el control «{pantalla}.{nombre}»"
    if not isinstance(c, dict):
        raise MapaInvalido(f"{donde} no es un mapa")
    sobran = set(c) - _CLAVES_CONTROL
    if sobran:
        raise MapaInvalido(f"{donde} tiene claves desconocidas: {', '.join(sorted(map(str, sobran)))}")
    etiqueta, rol, css = c.get("etiqueta"), c.get("rol"), c.get("css")
    for clave, valor in (("etiqueta", etiqueta), ("rol", rol), ("css", css)):
        if valor is not None and not _texto(valor):
            raise MapaInvalido(f"{donde}: «{clave}» debe ser un texto no vacío")
    if (etiqueta is None) == (css is None):
        raise MapaInvalido(f"{donde} necesita exactamente una de «etiqueta» o «css»")
    if rol is not None and etiqueta is None:
        raise MapaInvalido(f"{donde}: «rol» solo va con «etiqueta»")
    tipo = c.get("tipo")
    if tipo not in TIPOS:
        raise MapaInvalido(f"{donde}: «tipo» debe ser uno de {', '.join(TIPOS)}")
    secreto = c.get("secreto", False)
    if not isinstance(secreto, bool):
        raise MapaInvalido(f"{donde}: «secreto» debe ser true o false")
    return Control(pantalla, nombre, etiqueta, rol, css, tipo, secreto)


# Letras cirílicas y griegas que se confunden con latinas (mayúsculas y minúsculas por separado: la «ν» griega
# minúscula parece una «v», la «Ν» mayúscula una «N»).
_HOMOGLIFOS = str.maketrans({
    # cirílico
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "У": "Y", "Х": "X", "Ѕ": "S", "І": "I", "Ј": "J", "Ү": "Y", "Ԛ": "Q", "Ԝ": "W",
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "ѕ": "s", "і": "i", "ј": "j", "ԁ": "d", "һ": "h", "ԛ": "q", "ԝ": "w", "ӏ": "l",
    "ү": "y", "ɡ": "g",
    # griego
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t",
    "υ": "u", "χ": "x", "ω": "w", "ϲ": "c",
})


def _fichas(texto: str) -> list[str]:
    """Las palabras de `texto`, comparables: %-decodificado (hasta 3 veces), sin acentos (NFKD), homoglifos
    cirílicos y griegos pasados a latín, en minúsculas, sin caracteres invisibles (ancho cero, guion blando) y
    partido por cualquier separador (espacios, guiones, puntos, barras, «_»…).
    """
    t = str(texto)
    for _ in range(3):
        decodificado = unquote(t)
        if decodificado == t:
            break
        t = decodificado
    t = "".join(ch for ch in unicodedata.normalize("NFKD", t) if not unicodedata.combining(ch))
    t = t.translate(_HOMOGLIFOS).casefold()
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Cf")
    return [f for f in re.split(r"[\W_]+", t) if f]


def _normal(texto: str) -> str:
    """Texto comparable y sin separadores: «impul-pay», «Impul_Pay», «impul%20pay» e «IMPULPAY» son lo mismo.

    El precio es que una palabra puede casar a caballo de dos («mi banco» → «mibanco»); por eso los términos
    cortos de `_PALABRA_ENTERA` se buscan solo como palabra entera. Es una guarda: ante la duda se para.
    """
    return "".join(_fichas(texto))


_PROHIBIDAS_NORMALES = tuple((w, _normal(w)) for w in PALABRAS_PROHIBIDAS)


def palabra_prohibida(texto: str) -> str | None:
    """La primera de `PALABRAS_PROHIBIDAS` que aparece en `texto` (URL o texto), comparando ambos normalizados.

    Las de `_PALABRA_ENTERA` deben ser una palabra entera de `texto` (o su plural en -s); las demás pueden ir
    dentro de otra palabra o partidas por separadores.
    """
    fichas = _fichas(texto)
    normal = "".join(fichas)
    enteras = set(fichas) | {f[:-1] for f in fichas if f.endswith("s")}
    return next((w for w, n in _PROHIBIDAS_NORMALES if (n in enteras if w in _PALABRA_ENTERA else n in normal)), None)


def _zona_de_cobro(p: dict) -> str | None:
    """La palabra prohibida que aparece en la url, la firma o la etiqueta/css de algún control, o None."""
    textos = [p["url"], *p["firma"]]
    for c in (p.get("controles") or {}).values():
        if isinstance(c, dict):
            textos += [str(c[k]) for k in ("etiqueta", "css") if c.get(k) is not None]
    return next((w for w in map(palabra_prohibida, textos) if w), None)


def _validar_limites(ruta: Path, mapa: dict) -> None:
    if "limites_plan" not in mapa:
        return
    limites = mapa["limites_plan"]
    if not isinstance(limites, dict) or not limites:
        raise MapaInvalido(f"{ruta}: «limites_plan» debe ser un mapa <Plan>: {{tiendas, bumps, upsells, downsell}}")
    for plan, valores in limites.items():
        if not isinstance(valores, dict) or set(valores) != set(_CLAVES_LIMITES):
            raise MapaInvalido(f"{ruta}: «limites_plan.{plan}» necesita exactamente tiendas, bumps, upsells y downsell")
        for clave, tipo in _CLAVES_LIMITES.items():
            v = valores[clave]
            if tipo is int and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
                raise MapaInvalido(f"{ruta}: «limites_plan.{plan}.{clave}» debe ser un entero ≥ 0")
            if tipo is bool and not isinstance(v, bool):
                raise MapaInvalido(f"{ruta}: «limites_plan.{plan}.{clave}» debe ser true o false")
    if not _texto(mapa.get("fuente_limites")):
        raise MapaInvalido(f"{ruta}: «limites_plan» exige «fuente_limites» (de dónde salen y cuándo se leyeron)")


def cargar(ruta: Path) -> dict:
    """Lee y valida un mapa.yaml; `capturado` sale como `str | None`."""
    ruta = Path(ruta)
    try:
        mapa = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError, OSError) as exc:
        raise MapaInvalido(f"{ruta} no se puede leer: {type(exc).__name__}") from exc
    if not isinstance(mapa, dict):
        raise MapaInvalido(f"{ruta} no es un mapa")
    if "capturado" not in mapa:
        raise MapaInvalido(f"{ruta}: falta «capturado» (null o AAAA-MM-DD)")
    mapa["capturado"] = _fecha(mapa["capturado"], ruta)
    if not isinstance(mapa.get("fuente"), str) or not mapa["fuente"].strip():
        raise MapaInvalido(f"{ruta}: falta «fuente»")
    pantallas = mapa.get("pantallas")
    if not isinstance(pantallas, dict) or not pantallas:
        raise MapaInvalido(f"{ruta}: falta «pantallas»")
    for nombre, p in pantallas.items():
        if not isinstance(p, dict):
            raise MapaInvalido(f"{ruta}: la pantalla «{nombre}» no es un mapa")
        if not isinstance(p.get("url"), str) or not p["url"].startswith("https://"):
            raise MapaInvalido(f"{ruta}: la pantalla «{nombre}» necesita una «url» https")
        firma = p.get("firma")
        if not isinstance(firma, list) or not firma or not all(isinstance(t, str) and t for t in firma):
            raise MapaInvalido(f"{ruta}: la pantalla «{nombre}» necesita «firma» (lista de textos)")
        campos = p.get("campos", {})
        if not isinstance(campos, dict):
            raise MapaInvalido(f"{ruta}: «campos» de «{nombre}» no es un mapa")
        for campo, c in campos.items():
            patron = c.get("patron") if isinstance(c, dict) else None
            if not isinstance(patron, str):
                raise MapaInvalido(f"{ruta}: el campo «{campo}» de «{nombre}» necesita «patron»")
            try:
                compilado = re.compile(patron)
            except re.error as exc:
                raise MapaInvalido(f"{ruta}: patrón inválido en «{nombre}.{campo}»") from exc
            if compilado.groups != 1:
                raise MapaInvalido(f"{ruta}: el patrón de «{nombre}.{campo}» debe tener exactamente un grupo")
        p.setdefault("campos", {})
        if "capturado" in p:
            p["capturado"] = _fecha(p["capturado"], ruta, f" de «{nombre}»")
        # sin setdefault: las claves nuevas no se inyectan, para que la huella de un mapa de la fase 0
        # (y las confirmaciones del usuario que dependen de ella) no cambie
        prohibida = p.get("prohibida", False)
        if not isinstance(prohibida, bool):
            raise MapaInvalido(f"{ruta}: «prohibida» de «{nombre}» debe ser true o false")
        controles = p.get("controles", {})
        if not isinstance(controles, dict):
            raise MapaInvalido(f"{ruta}: «controles» de «{nombre}» no es un mapa")
        for control_nombre, c in controles.items():
            _validar_control(ruta, nombre, control_nombre, c)
        palabra = _zona_de_cobro(p)
        if controles and palabra and not prohibida:
            raise MapaInvalido(
                f"{ruta}: la pantalla «{nombre}» parece de cobros o datos sensibles («{palabra}») y tiene controles: "
                "márcala «prohibida: true» o quítale los controles"
            )
    if "hosts" in mapa:
        hosts = mapa["hosts"]
        if not isinstance(hosts, list) or not hosts or not all(_texto(h) for h in hosts):
            raise MapaInvalido(f"{ruta}: «hosts» debe ser una lista de hosts (textos no vacíos)")
    _validar_limites(ruta, mapa)
    return mapa


def _pantalla(mapa: dict, pantalla: str) -> dict:
    try:
        return mapa["pantallas"][pantalla]
    except KeyError:
        raise KeyError(f"no hay pantalla «{pantalla}» en el mapa") from None


def control(mapa: dict, pantalla: str, nombre: str) -> Control:
    """El control `nombre` de `pantalla`; `KeyError` con mensaje en español si no existe."""
    controles = _pantalla(mapa, pantalla).get("controles") or {}
    if nombre not in controles:
        raise KeyError(f"la pantalla «{pantalla}» no tiene el control «{nombre}»")
    return _validar_control("mapa", pantalla, nombre, controles[nombre])


def controles_de(mapa: dict, pantalla: str) -> list[Control]:
    """Todos los controles de `pantalla`, en el orden del mapa."""
    return [control(mapa, pantalla, n) for n in (_pantalla(mapa, pantalla).get("controles") or {})]


def prohibida(mapa: dict, pantalla: str) -> bool:
    """True si en la pantalla nunca se escribe ni se captura (cobros, pasarelas, retiros, tarjetas, bancos,
    contraseñas): marcada `prohibida: true` o con una palabra prohibida en la url, la firma o la etiqueta/css de
    algún control, tenga o no controles.
    """
    p = _pantalla(mapa, pantalla)
    return p.get("prohibida", False) is not False or _zona_de_cobro(p) is not None


def capturado_de(mapa: dict, pantalla: str) -> str | None:
    """Fecha de confirmación de la pantalla; None = sin confirmar (se lee, no se escribe).

    Una pantalla con `controles` solo cuenta con su propio `capturado` (nunca hereda la raíz: R-1); una de
    solo lectura, si no lo tiene, hereda el de la raíz.
    """
    p = _pantalla(mapa, pantalla)
    if "capturado" in p:
        valor = p["capturado"]
    else:
        valor = None if p.get("controles") else mapa.get("capturado")
    return _fecha(valor, Path("mapa"), f" de «{pantalla}»")


def hosts_de(mapa: dict) -> set[str]:
    """Hosts permitidos: la clave `hosts` o, si falta, los de las `url` de las pantallas."""
    if mapa.get("hosts"):
        return {h.strip().lower() for h in mapa["hosts"]}
    return {urlparse(p["url"]).hostname for p in mapa["pantallas"].values() if urlparse(p["url"]).hostname}


_LOCAL = "127.0.0.1"  # único host donde se admite http (páginas de prueba propias)


def origen(url: str) -> tuple[str, str, int] | None:
    """(esquema, host, puerto) de `url`, o None si no es https (http solo en 127.0.0.1) o no se entiende."""
    try:
        u = urlparse(url)
        puerto = u.port
    except ValueError:
        return None
    esquema, host = u.scheme.lower(), (u.hostname or "").lower()
    if not host or not (esquema == "https" or (esquema == "http" and host == _LOCAL)):
        return None
    return esquema, host, puerto or (443 if esquema == "https" else 80)


def origenes_de(mapa: dict) -> set[tuple[str, str, int]]:
    """Orígenes permitidos: los de las `url` del mapa cuyo host está en `hosts_de`, y https:443 de cada host."""
    hosts = hosts_de(mapa)
    salida = {o for p in mapa["pantallas"].values() if (o := origen(p["url"])) and o[1] in hosts}
    return salida | {("https", h, 443) for h in hosts}


def limites_de_plan(mapa: dict, plan: str) -> dict | None:
    """Límites del plan (copia) o None si el plan no está en el mapa («no medido»)."""
    valores = (mapa.get("limites_plan") or {}).get(plan)
    return dict(valores) if valores is not None else None


def leer_pantalla(pantalla: dict, texto: str) -> dict[str, str | None]:
    """Campos de la pantalla; lanza `FirmaAusente` si falta algún texto de la firma."""
    if any(t not in texto for t in pantalla["firma"]):
        raise FirmaAusente(pantalla)
    salida: dict[str, str | None] = {}
    for campo, c in pantalla.get("campos", {}).items():
        m = re.search(c["patron"], texto)
        salida[campo] = m.group(1).strip() if m else None
    return salida
