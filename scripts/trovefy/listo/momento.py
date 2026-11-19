"""Gates de `/listo` que solo valen en el instante (plan 20, Tarea 3): la landing responde en el móvil, queda hueco
de test en la caja, el ejecutor late y no hay ningún STOP.

Reutiliza `trovefy.caja`, `trovefy.aprobaciones.fuentes.leer_estado` y `trovefy.vigia.comprobaciones` (su
``LATIDO_AVISO`` de 10 min es el «latido < 10 min» de §4.11). La landing se mide por HTTP con ``urllib``, con
tope de bytes y como mucho `MAX_REDIRECCIONES` saltos dentro del mismo host; nunca con navegador ni sesión.
"""
from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from trovefy.listo.ficha import FichaPais, campo, ruta_evidencia
from trovefy.listo.gates import Gate, falla, no_medido, ok

UA_MOVIL = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1")
MAX_BYTES = 2_000_000
MAX_REDIRECCIONES = 3
TIMEOUT = 15


class OtroSitio(urllib.error.URLError):
    """La landing redirige fuera de su host."""

    def __init__(self, host: str) -> None:
        super().__init__(f"redirige a otro sitio: {host}")
        self.host = host


def _mismo_host(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    a, b = a.lower(), b.lower()
    return a.removeprefix("www.") == b.removeprefix("www.")


class _SoloMismoHost(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECCIONES

    def __init__(self, host: str) -> None:
        super().__init__()
        self.host = host
        self.saltos = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.saltos += 1
        destino = urlsplit(newurl).hostname
        if not _mismo_host(destino, self.host):
            raise OtroSitio(destino or "?")
        if self.saltos > MAX_REDIRECCIONES:
            raise urllib.error.HTTPError(newurl, code, f"más de {MAX_REDIRECCIONES} redirecciones", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _abrir_landing(req: urllib.request.Request, timeout: float = TIMEOUT):
    """Abre la landing siguiendo solo redirecciones dentro de su host (`OtroSitio` si no)."""
    opener = urllib.request.build_opener(_SoloMismoHost(urlsplit(req.full_url).hostname or ""))
    return opener.open(req, timeout=timeout)


def _sin_query(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def gate_landing_movil(f: FichaPais, abrir: Callable = _abrir_landing, ahora: datetime | None = None) -> Gate:
    """La QA publicada midió la landing a 390 px (plan 18) y **ahora** responde 200 en HTML, con un navegador de
    móvil, sin salir de su host. Con la ruta Cloudflare, ``pixel: pendiente`` en ``landing.yaml`` bloquea (ruling B)."""
    c = "landing_movil"
    arreglo = "/trovefy:landing"
    url = campo(f.datos, "landing.url")
    if not isinstance(url, str) or urlsplit(url).scheme != "https" or not urlsplit(url).hostname:
        return no_medido(c, "falta landing.url (https)", arreglo)
    if campo(f.datos, "landing.qa.movil_390.http") != 200:
        return no_medido(c, "falta la QA publicada en móvil (landing.qa.movil_390 con HTTP 200)", arreglo)
    captura = ruta_evidencia(f, campo(f.datos, "landing.qa.movil_390.captura"))
    if captura is None:
        return no_medido(c, "falta la captura de la QA en móvil (o no está dentro del producto)", arreglo)
    pixel = _pixel_landing(f)
    if pixel == "pendiente":
        return falla(c, "la landing se publicó sin píxel (pixel: pendiente): vuelve a publicarla con TRACKING.md",
                     [captura], arreglo)
    host = urlsplit(url).hostname
    req = urllib.request.Request(url, headers={"User-Agent": UA_MOVIL, "Accept": "text/html"})
    try:
        resp = abrir(req, timeout=TIMEOUT)
    except OtroSitio as exc:
        return falla(c, f"redirige a otro sitio: {exc.host}", [captura], arreglo)
    except urllib.error.HTTPError as exc:
        return falla(c, f"la landing responde HTTP {exc.code}", [captura], arreglo)
    except (urllib.error.URLError, OSError, ValueError):
        return no_medido(c, "sin red", "comprueba tu conexión y repite /listo", [captura])
    try:
        codigo = getattr(resp, "status", None) or resp.getcode()
        final = resp.geturl() or url
        tipo = (resp.headers.get("Content-Type") or "").lower()
        resp.read(MAX_BYTES + 1)
    except (OSError, ValueError, AttributeError):
        return no_medido(c, "sin red (la respuesta se cortó)", "repite /listo", [captura])
    finally:
        cerrar = getattr(resp, "close", None)
        if callable(cerrar):
            cerrar()
    if not _mismo_host(urlsplit(final).hostname, host):
        return falla(c, f"redirige a otro sitio: {urlsplit(final).hostname}", [captura], arreglo)
    if codigo != 200:
        return falla(c, f"la landing responde HTTP {codigo}", [captura], arreglo)
    if "text/html" not in tipo:
        return falla(c, f"la landing no devuelve HTML ({tipo or 'sin Content-Type'})", [captura], arreglo)
    cuando = (ahora or datetime.now().astimezone()).isoformat(timespec="seconds")
    return ok(c, "la landing responde 200 en el móvil", (f"HTTP 200 · {_sin_query(final)} · {cuando}", captura))


def _pixel_landing(f: FichaPais) -> str | None:
    import yaml

    ruta = ruta_evidencia(f, f"landing/{f.pais}/landing.yaml")
    if ruta is None:
        return None
    try:
        datos = yaml.safe_load((f.carpeta / ruta).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    valor = datos.get("pixel") if isinstance(datos, dict) else None
    return valor if isinstance(valor, str) else None


# --- caja -----------------------------------------------------------------------------------------------------------


def gate_caja(vault: Path, hoy: date, trm_de: Callable) -> Gate:
    """Queda hueco para un test más y cabe en el tope diario (`trovefy.caja.bloqueos.puede_lanzar_test`)."""
    from trovefy.caja.bloqueos import puede_lanzar_test
    from trovefy.caja.calculo import calcular
    from trovefy.caja.config import CajaInvalida, cargar_caja
    from trovefy.caja.gasto import GastoCorrupto, gastos_de_tests
    from trovefy.caja.movimientos import MovimientosCorruptos, leer_movimientos

    c = "caja"
    try:
        config = cargar_caja(vault)
    except FileNotFoundError:
        return no_medido(c, "falta config/caja.yaml", "trovefy caja iniciar")
    except CajaInvalida as exc:
        return no_medido(c, str(exc), "/trovefy:caja")
    try:
        estado = calcular(config, leer_movimientos(vault), gastos_de_tests(vault, config, trm_de))
    except (GastoCorrupto, MovimientosCorruptos) as exc:
        return no_medido(c, str(exc), "/trovefy:caja")
    v = puede_lanzar_test(estado, config)
    if v.permitido:
        return ok(c, f"queda hueco de test ({estado.huecos}); {v.motivo}")
    if v.motivo.startswith("no medido:"):
        return no_medido(c, v.motivo, "/trovefy:caja")
    return falla(c, v.motivo, arreglo="/trovefy:caja")


# --- ejecutor y STOP -------------------------------------------------------------------------------------------------


def gate_ejecutor(ahora: datetime, spool: Path) -> Gate:
    """El ejecutor late (último latido de hace menos de 10 min)."""
    from trovefy.aprobaciones.fuentes import leer_estado
    from trovefy.vigia.comprobaciones import latido

    c = "ejecutor"
    r = latido(ahora, leer_estado("latido", spool))
    if r.nivel == "ok":
        return ok(c, r.texto)
    if r.nivel == "no_medido":
        return no_medido(c, r.texto, "/trovefy:aprobaciones estado")
    return falla(c, r.texto, arreglo="/trovefy:aprobaciones estado")


def gate_stop(vault: Path, spool: Path) -> Gate:
    """Ningún STOP activo: ni el STOP del cerebro (``.trovefy/STOP``) ni el STOP del ejecutor (``stop.json``)."""
    from trovefy.aprobaciones.fuentes import leer_estado
    from trovefy.vigia.comprobaciones import stop

    c = "stop"
    r = stop(vault, leer_estado("stop", spool))
    if r.nivel == "ok":
        return ok(c, "sin STOP del cerebro ni STOP del ejecutor")
    if r.nivel == "no_medido":
        return no_medido(c, r.texto, "/trovefy:aprobaciones estado")
    return falla(c, r.texto, arreglo="quita el STOP solo si sabes por qué se puso (/trovefy:aprobaciones)")
