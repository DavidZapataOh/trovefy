"""Paso 06: la cuenta publicitaria con moneda y zona horaria correctas y límite de gasto.

Moneda y zona horaria no se pueden cambiar sin crear otra cuenta (cambiarlas cierra la cuenta y crea otra, una vez
cada 60 días: https://www.facebook.com/business/help/291404291014138). Por defecto la guía pide USD y la zona del
mercado elegido; el usuario puede decidir otra cosa y guardarla (`--dato moneda=COP --dato zona=America/Bogota`):
entonces se compara con su decisión y se dice «decisión del usuario: …».

Pantallas (solo lectura):
- Facturación: https://www.facebook.com/ads/manager/account_settings/account_billing/?act=<id>, que lleva a
  business.facebook.com/latest/billing_hub/accounts/details/. Captura real del 2026-11-11: «Información del
  negocio» trae «Divisa» en su línea y el valor en la siguiente («Peso colombiano COP»), y «Límite de gasto de la
  cuenta» sin cantidad cuando no hay límite. No muestra la zona horaria.
- Ajustes de la cuenta: https://www.facebook.com/ads/manager/account_settings/information/?act=<id>, para la zona
  horaria (aún sin captura real: se guarda como evidencia provisional).
Rótulos de la documentación oficial (leída el 2026-11-10): 754049591334898 («Currency and time zone» en Business info)
y 141820733085330 («ad account spending limit»).
Un límite en otra moneda que USD no se convierte: no hay una fuente de cambio fiable y comprobable sin red para COP
(el BCE no la publica); se acepta y se dice «equivalencia en USD no medida». Nunca se inventa un tipo de cambio.
"""

import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trovefy.arranque.estado import ResultadoVerificacion, cargar
from trovefy.arranque.verificadores import verificador
from trovefy.arranque.verificadores.base import (
    Confirmacion,
    PantallaProvisional,
    confirmacion_de,
    guardar_evidencia,
    huella_de,
    registrar_lector,
    resultado_provisional,
)
from trovefy.arranque.verificadores.meta_ids import (
    SIN_SESION,
    capturar_por_defecto,
    leer_pagina,
    no_medido,
)
from trovefy.config import mercados, umbrales
from trovefy.vault import frontmatter
from trovefy.vault.rutas import vault_root

URL_AJUSTES = "https://www.facebook.com/ads/manager/account_settings/account_billing/"
URL_INFO_CUENTA = "https://www.facebook.com/ads/manager/account_settings/information/?act={act}"
CLAVE_LIMITE = "cuenta.limite_gasto_inicial_usd"
COMANDO_DECISION = "trovefy arranque hecho 06 --dato moneda={moneda} --dato zona=<zona horaria de la cuenta>"

CONFIRMACION_06 = Confirmacion(
    fecha=None,
    fuente=(
        "facturación real capturada el 2026-11-11 (Divisa, límite) y documentación Meta Business Help Center "
        "754049591334898 y 141820733085330; falta la captura real de la zona horaria"
    ),
)

ILEGIBLE = "ilegible"  # la línea del límite existe, pero el número es ambiguo
SIN_LIMITE = "sin_limite"  # el rótulo del límite está, pero sin cantidad

_INVISIBLES = " \t\u200b\u200c\u200d\u2060\ufeff\xa0"
_ROT_MONEDA = r"Currency|Moneda|Divisa"
_ROT_ZONA = r"Zona horaria(?: de la cuenta(?: publicitaria)?)?|(?:Ad account )?Time zone"
_ROT_AMBAS = r"Currency and time zone|(?:Divisa|Moneda) y zona horaria"
_ROT_LIMITE = r"Account spending limit|Límite de gasto de la cuenta"
_ISO = re.compile(r"\b(?!GMT\b|UTC\b)[A-Z]{3}\b")
_IANA = re.compile(r"\b[A-Z][A-Za-z]+(?:/[A-Za-z_+\-0-9]+)+")
_DESFASE = re.compile(r"\b(?:GMT|UTC)(?:[+\-]\d{1,2}(?::\d{2})?)?(?![\w:])")
_CANTIDAD = re.compile(r"(?:[A-Z]{2,3}\$?|US\$|\$|€)?\s*\d[\d.,]*\s*(?:[A-Z]{3}|US\$|\$|€)?")
_ROTULO_LIMITE = re.compile(_ROT_LIMITE, re.IGNORECASE)
# Monedas que Meta muestra sin decimales: «COP$ 164.150» (captura real) son miles, no decimales.
_SIN_DECIMALES = frozenset({"COP", "CLP", "PYG", "JPY", "KRW", "VND", "IDR", "HUF", "ISK", "TWD"})


def _numero(texto: str, sin_decimales: bool = False) -> str | None:
    """Número en formato inglés o español → cadena con punto decimal; None si es ambiguo."""
    t = re.sub(r"US\$|[A-Z]{3}\$?|\$|€|\s", "", texto)
    if not re.fullmatch(r"\d[\d.,]*", t):
        return None
    if sin_decimales and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
        return t.replace(".", "")  # COP$ 1.000.000: miles con punto
    puntos, comas = t.count("."), t.count(",")
    if puntos and comas:
        dec = "." if t.rfind(".") > t.rfind(",") else ","
        mil = "," if dec == "." else "."
        ent, _, frac = t.rpartition(dec)
        if not re.fullmatch(r"\d{1,2}", frac) or t.count(dec) != 1:
            return None
        grupos = ent.split(mil)
        if mil in frac or not re.fullmatch(r"\d{1,3}", grupos[0]) or not all(re.fullmatch(r"\d{3}", g) for g in grupos[1:]):
            return None
        return "".join(grupos) + "." + frac
    sep = "." if puntos else "," if comas else None
    if sep is None:
        return t
    partes = t.split(sep)
    if len(partes) == 2 and re.fullmatch(r"\d{1,2}", partes[1]) and partes[0]:
        return partes[0] + "." + partes[1]
    if sep == "," and re.fullmatch(r"\d{1,3}", partes[0]) and all(re.fullmatch(r"\d{3}", g) for g in partes[1:]):
        return "".join(partes)  # 1,000 o 1,000,000: miles
    if sep == "." and len(partes) > 2 and re.fullmatch(r"\d{1,3}", partes[0]) and all(re.fullmatch(r"\d{3}", g) for g in partes[1:]):
        return "".join(partes)  # 1.000.000: miles sin ambigüedad
    return None  # «1.000» o «12,345,6»: no se sabe si son miles o decimales


def extraer_act(url: str) -> str | None:
    for valor in parse_qs(urlparse(url).query).get("act", []):
        if re.fullmatch(r"\d+", valor):
            return valor
    return None


def _lineas(texto: str) -> list[str]:
    """Líneas sin espacios ni caracteres invisibles alrededor; se quitan las vacías (Meta mete «\u200b» sueltos)."""
    return [x for x in (ln.strip(_INVISIBLES) for ln in texto.splitlines()) if x]


def _valores_de(lineas: list[str], rotulos: str):
    """Valores de un rótulo: «Rótulo: valor» en la misma línea o «Rótulo» solo y el valor en la línea siguiente."""
    patron = re.compile(rf"(?:{rotulos})\s*(?::\s*(.*))?", re.IGNORECASE)
    for i, ln in enumerate(lineas):
        m = patron.fullmatch(ln)
        if m:
            yield m.group(1) if m.group(1) else (lineas[i + 1] if i + 1 < len(lineas) else "")


def _moneda_de(valor: str) -> str | None:
    codigos = _ISO.findall(valor)
    return codigos[-1] if codigos else None


def _zona_de(valor: str) -> str | None:
    m = _IANA.search(valor) or _DESFASE.search(valor)
    return m.group(0) if m else None


def _primero(lineas: list[str], extraer: Callable[[str], str | None], *rotulos: str) -> str | None:
    for rotulo in rotulos:
        for valor in _valores_de(lineas, rotulo):
            leido = extraer(valor)
            if leido:
                return leido
    return None


def _limite_bruto(lineas: list[str]) -> str | None:
    """La cantidad del límite de gasto de la cuenta: en la misma línea del rótulo o en la siguiente."""
    misma = re.compile(rf"(?:{_ROT_LIMITE})\s*:\s*(.+)", re.IGNORECASE)
    for ln in lineas:
        m = misma.fullmatch(ln)
        if m:
            return m.group(1)
    sola = re.compile(rf"(?:{_ROT_LIMITE})", re.IGNORECASE)
    for i, ln in enumerate(lineas):
        if sola.fullmatch(ln) and i + 1 < len(lineas) and _CANTIDAD.fullmatch(lineas[i + 1]):
            return lineas[i + 1]
    return None


def leer_ajustes_cuenta(texto: str) -> dict[str, str | None]:
    lineas = _lineas(texto)
    moneda = _primero(lineas, _moneda_de, _ROT_MONEDA, _ROT_AMBAS)
    zona = _primero(lineas, _zona_de, _ROT_ZONA, _ROT_AMBAS)
    bruto = _limite_bruto(lineas)
    if bruto is None:
        limite = SIN_LIMITE if _ROTULO_LIMITE.search(texto) else None  # rótulo sin cantidad / ni rótulo
    elif not re.search(r"\d", bruto):
        limite = SIN_LIMITE
    else:
        sin_decimales = (moneda or _moneda_de(bruto.replace("$", " ")) or "") in _SIN_DECIMALES
        limite = _numero(bruto, sin_decimales) or ILEGIBLE
    return {"moneda": moneda, "zona": zona, "limite_gasto": limite}


def mercado_elegido(vault: Path) -> str | None:
    """Zona horaria del mercado del `*-eleccion.md` válido más reciente (lo crea /auditar); None si no hay.

    Se saltan las decisiones de un país que no está en config/mercados.yaml (una errata como «RU»,
    marcada ``fuera_de_mercados``): nunca tapan una elección válida anterior."""
    archivos = sorted(
        Path(vault).glob("productos/*/decisiones/*-eleccion.md"),
        key=lambda p: (p.name, p.stat().st_mtime),
    )
    if not archivos:
        return None
    try:
        todos = mercados.cargar(Path(vault) / "config" / "mercados.yaml")
    except (OSError, ValueError):
        return None
    for archivo in reversed(archivos):
        try:
            meta, _ = frontmatter.leer(archivo)
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or meta.get("fuera_de_mercados") is True:
            continue
        pais = meta.get("pais")
        mercado = todos.get(pais) if isinstance(pais, str) else None
        if mercado:
            return mercado.zona
    return None


def _desfase_minutos(zona: str) -> int | None:
    m = re.fullmatch(r"(?:GMT|UTC)(?:([+\-])(\d{1,2})(?::(\d{2}))?)?", zona)
    if not m:
        return None
    if not m.group(1):
        return 0
    minutos = int(m.group(2)) * 60 + int(m.group(3) or 0)
    return minutos if m.group(1) == "+" else -minutos


def _misma_zona(vista: str, esperada: str) -> bool:
    """La zona de la pantalla es la esperada; si Meta solo muestra el desfase («GMT-05:00»), se compara el desfase de hoy."""
    if vista == esperada:
        return True
    desfase = _desfase_minutos(vista)
    if desfase is None:
        return False
    try:
        tz = ZoneInfo(esperada)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    offset = datetime.now(tz).utcoffset()
    return offset is not None and int(offset.total_seconds() // 60) == desfase


def _cantidad(x: float) -> str:
    return str(int(x)) if x.is_integer() else f"{x:.2f}"


def evaluar_cuenta(
    ajustes: dict, zona_esperada: str | None, limite_max: float,
    moneda_decidida: str | None = None, zona_decidida: str | None = None,
) -> ResultadoVerificacion:
    """Compara lo leído con la guía (USD, zona del mercado, límite ≤ umbral) o con la decisión guardada del usuario."""

    def resultado(ok: bool | None, motivo: str, *arreglos: str) -> ResultadoVerificacion:
        marca = "?" if ok is None else "✗"
        return ResultadoVerificacion(ok, [], motivo, list(arreglos), {}, [f"{marca} {motivo}"])

    moneda = ajustes.get("moneda")
    moneda_esperada = moneda_decidida or "USD"
    if moneda != moneda_esperada:  # primero: una moneda equivocada es irreversible, haya mercado o no
        if moneda_decidida:
            return resultado(
                False,
                f"la moneda de la cuenta es {moneda or 'desconocida'}, no {moneda_esperada} (tu decisión guardada)",
                "revisa la Divisa en Facturación y pagos → Información del negocio; si cambiaste de cuenta, guarda la decisión nueva con "
                f"`{COMANDO_DECISION.format(moneda='<código>')}`",
            )
        arreglos = ["la moneda no se puede cambiar sin crear otra cuenta: crea otra cuenta publicitaria con USD"]
        if moneda:
            arreglos.append(f"si decides quedarte con esta cuenta en {moneda}, guárdalo: `{COMANDO_DECISION.format(moneda=moneda)}`")
        return resultado(False, f"la moneda de la cuenta es {moneda or 'desconocida'}, no USD", *arreglos)
    linea_moneda = f"✓ moneda {moneda}"
    if moneda != "USD":
        linea_moneda += f" — decisión del usuario: moneda {moneda} (la guía pide USD)"

    zona_mercado = zona_esperada
    zona_esperada = zona_decidida or zona_mercado
    if not zona_esperada:
        return resultado(
            None,
            "no medido: elige primero el mercado con /auditar (la zona horaria no se puede cambiar después)",
            "ejecuta /trovefy:auditar y elige el mercado antes de crear o revisar la cuenta",
        )
    zona = ajustes.get("zona")
    if zona is None:
        return resultado(
            None,
            "no medido: no se ve la zona horaria en las pantallas de Meta",
            "revísala tú en Facturación y pagos → Información del negocio → Editar; si Meta la muestra en otra pantalla, "
            "avisa para actualizar el patrón (cambio en el repo)",
        )
    if not _misma_zona(zona, zona_esperada):
        return resultado(
            False,
            f"la zona horaria es {zona}, no {zona_esperada}" + (" (tu decisión guardada)" if zona_decidida else ""),
            "cambiarla cierra la cuenta y crea otra (Ajustes de pago → Información del negocio → Editar); hazlo antes de crear campañas",
        )
    linea_zona = f"✓ zona {zona}" + ("" if zona == zona_esperada else f" (coincide con {zona_esperada})")
    if zona_decidida and zona_decidida != zona_mercado:
        pide = f"el mercado elegido pide {zona_mercado}" if zona_mercado else "aún no hay mercado elegido"
        linea_zona += f" — decisión del usuario: zona {zona_decidida} ({pide})"

    en_usd = moneda == "USD"
    tope = f"hasta US$ {limite_max:g}" if en_usd else f"en {moneda}, equivalente a unos US$ {limite_max:g} (usa el cambio del día de tu banco)"
    if ajustes.get("limite_gasto") is None:
        return resultado(None, "no medido: no se ve el límite de gasto en la pantalla", f"revisa el límite en Ajustes de pago ({tope})")
    if ajustes.get("limite_gasto") == ILEGIBLE:
        return resultado(None, "no medido: no se entiende el número del límite de gasto", f"revisa el límite en Ajustes de pago ({tope})")
    try:
        limite = float(ajustes.get("limite_gasto"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return resultado(
            False,
            "la cuenta no tiene límite de gasto",
            f"pon un límite de gasto de la cuenta {tope}; si tu cuenta usa fondos prepagados no admite límite: "
            "cambia a pago automático con tarjeta",
        )
    if limite <= 0:
        return resultado(False, "límite de gasto inválido (debe ser mayor que 0)", f"pon un límite {tope}")
    if en_usd and limite > limite_max:
        return resultado(False, f"el límite de gasto (US$ {limite:g}) supera el máximo (US$ {limite_max:g})", f"bájalo a US$ {limite_max:g} o menos")
    if en_usd:
        linea_limite = f"✓ límite de gasto US$ {limite:g}"
        limite_txt = f"US$ {limite:g}"
    else:
        limite_txt = f"{moneda} {_cantidad(limite)}"
        linea_limite = f"✓ límite de gasto {limite_txt} — límite en {moneda}; equivalencia en USD no medida"
    decision = " (decisión del usuario)" if (moneda_decidida and moneda_decidida != "USD") or zona_decidida else ""
    return ResultadoVerificacion(
        True, [], f"moneda {moneda}, zona {zona_esperada}, límite {limite_txt}{decision}", [], {},
        [linea_moneda, linea_zona, linea_limite],
    )


def _act_guardado(vault: Path) -> str | None:
    p = next((p for p in cargar(vault) if p.id == "06"), None)
    valor = p.datos.get("act_id") if p else None
    return valor if valor and re.fullmatch(r"\d+", valor) else None


def _decision_guardada(vault: Path) -> tuple[str | None, str | None]:
    """(moneda, zona) que el usuario decidió y guardó en el paso 06 (`--dato moneda=… --dato zona=…`)."""
    p = next((p for p in cargar(vault) if p.id == "06"), None)
    datos = p.datos if p else {}
    moneda = (datos.get("moneda") or "").strip().upper()
    zona = (datos.get("zona") or "").strip()
    return (moneda if re.fullmatch(r"[A-Z]{3}", moneda) else None), (zona or None)


def verificar_cuenta(
    vault: Path | None = None, capturar: Callable | None = None, confirmacion: Confirmacion = CONFIRMACION_06
) -> ResultadoVerificacion:
    vault = vault_root() if vault is None else Path(vault)
    confirmacion = confirmacion_de(vault, "06", confirmacion)
    act = _act_guardado(vault)
    moneda_decidida, zona_decidida = _decision_guardada(vault)
    urls = {"facturacion": f"{URL_AJUSTES}?act={act}" if act else URL_AJUSTES}
    if act:
        urls["cuenta"] = URL_INFO_CUENTA.format(act=act)
    capturas: dict = {}
    for nombre, url in urls.items():
        cap, png, motivo = leer_pagina(url, capturar or capturar_por_defecto)
        if cap is None:
            return no_medido(motivo or SIN_SESION)
        capturas[nombre] = (cap, png)
    if not confirmacion.confirmada:
        pantallas = [PantallaProvisional(n, cap.url_final, png, cap.texto) for n, (cap, png) in capturas.items()]
        return resultado_provisional(vault, "06", None, None, pantallas=pantallas, motivo=confirmacion.aviso)
    ajustes = leer_ajustes_cuenta("\n".join(cap.texto for cap, _png in capturas.values()))
    if ajustes["moneda"] is None and ajustes["zona"] is None:
        return no_medido("no medido: la pantalla de ajustes no muestra moneda ni zona horaria")
    act = next((a for a in (extraer_act(cap.url_final) for cap, _png in capturas.values()) if a), None) or act
    if act is None:
        return no_medido("no medido: no se ve el número de la cuenta (`act=`) en la dirección")
    r = evaluar_cuenta(ajustes, mercado_elegido(vault), umbrales.valor(vault, CLAVE_LIMITE), moneda_decidida, zona_decidida)
    if r.ok is not True:
        return r
    ev = [
        guardar_evidencia(vault, "06", "captura" if nombre == "facturacion" else f"captura-{nombre}", png)
        for nombre, (_cap, png) in capturas.items() if png
    ]
    resumen: dict = {"act_id": act, **ajustes}
    if moneda_decidida or zona_decidida:
        resumen["decision_usuario"] = {"moneda": moneda_decidida, "zona": zona_decidida}
    ev.append(guardar_evidencia(vault, "06", "ajustes", resumen))
    return ResultadoVerificacion(True, ev, r.motivo, [], {"act_id": act}, r.lineas)


def _aceptar_06(valores: dict[str, str | None]) -> str | None:
    limite = valores.get("limite_gasto")
    if limite in (None, SIN_LIMITE):
        return "pon primero el límite de gasto (paso 5 de la guía) y vuelve a capturar"
    if limite == ILEGIBLE:
        return "el número del límite de gasto no se entiende; hay que ajustar el patrón (cambio en el repo)"
    return None


registrar_lector(
    "06", lambda textos, _v: leer_ajustes_cuenta("\n".join(textos.values())), ("moneda", "zona"), _aceptar_06,
    huella_de("06", _ROT_MONEDA, _ROT_ZONA, _ROT_AMBAS, _ROT_LIMITE, _ISO, _IANA, _DESFASE, _CANTIDAD, *sorted(_SIN_DECIMALES)),
)


@verificador("06")
def _v06(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_cuenta(vault)
