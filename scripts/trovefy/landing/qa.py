"""QA de la landing en Chromium: 390 y 1280 px, peso, LCP en 4G simulado, hitos, desborde y clic con UTM.

Tres capas:

- **Medir** (`medir`, `probar_clic`): Chromium real por `trovefy.navegador.sesion` con un contexto efímero
  (sin perfil: la QA no necesita sesión). Solo lee y navega; ningún clic salvo el del botón de compra de la
  propia landing, cuyo destino se intercepta con un 204 (no se abre el checkout). Toda petición a un host
  fuera de `permitidos` se aborta y se anota; las de `silenciar` (el píxel de Meta en la ruta Cloudflare,
  resolución 23) se abortan sin anotar: una QA nunca manda eventos a Meta.
- **Evaluar** (`evaluar`): pura. Cada comprobación da una fila ``(comprobación, OK|FALLA|AVISO|NO MEDIDO,
  detalle)``; un dato ausente es «NO MEDIDO» con su motivo y bloquea igual que un fallo (contrato 9).
- **Escribir** (`render_qa`, `ejecutar_qa`): `landing/<PAIS>/QA.md` con las capturas en `qa/` (0640).
"""

from __future__ import annotations

import functools
import http.server
import statistics
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

from trovefy.landing.constantes import (
    BAJADA_BPS,
    CPU_X,
    LATENCIA_MS,
    LCP_MAX_MS,
    RONDAS_LCP,
    SUBIDA_BPS,
    TOLERANCIA_HITO,
    VIEWPORTS,
)
from trovefy.landing.entrada import (
    DatosLanding,
    EntradaInvalida,
    ruta_landing,
    wireframe,
)
from trovefy.landing.validar import HOSTS_PIXEL, Resultado, validar

UTM_PRUEBA = "?utm_source=fb&utm_medium=paid&utm_campaign=QA%7C0&utm_term=QA%7C0&utm_content=QA%7C0&fbclid=QA"
PARES_PRUEBA = {k: v[0] for k, v in parse_qs(UTM_PRUEBA[1:]).items()}
ESPERA_TRAS_LOAD_MS = 3000  # LCP tras `load` + 3 s (plan 18, Tarea 6)
ESPERA_CLIC_MS = 5000  # tope para ver salir la navegación del botón
TIEMPO_CARGA_MS = 60_000  # tope de una carga (en 4G simulado una página pesada tarda)
SERVICIO_QA = "qa-landing"  # nombre del contexto efímero (no hay perfil: perfil_persistente=False)
OK, FALLA, AVISO, NO_MEDIDO = "OK", "FALLA", "AVISO", "NO MEDIDO"
_VISIBLE = False  # la QA no necesita ventana: nadie inicia sesión


@dataclass(frozen=True)
class Medicion:
    vista: str
    lcp_ms: list[float] | None
    peso_bytes: int | None
    peticiones_externas: tuple[str, ...]
    ancho_scroll: int
    desborde_selector: str | None
    hitos: dict[int, float] | None  # {orden: top del data-tf-hito ÷ scrollHeight}
    captura: Path | None
    motivo: str | None
    http: int | None = None  # estado HTTP del documento (gate «200 en móvil», resolución 3)
    version_servida: str | None = None  # data-tf-version de la página servida


@dataclass(frozen=True)
class Clic:
    url_pedida: str | None
    motivo: str | None
    intactos: bool | None = None  # utm_intactos contra el checkout de landing.yaml (lo rellena probar_clic)


@dataclass(frozen=True)
class ResultadoQA:
    ok: bool
    filas: tuple[tuple[str, str, str], ...]


# --- formato -------------------------------------------------------------------------------------


def _miles(x: float) -> str:
    """``2600.4`` → ``2.600`` (separador de miles con punto)."""
    return f"{round(x):,}".replace(",", ".")


def _kb(n: int) -> str:
    return f"{_miles(n / 1024)} KB"


def _mediana(valores: list[float]) -> float:
    return float(statistics.median(valores))


def _rondas(valores: list[float]) -> str:
    return " / ".join(_miles(x) for x in valores)


def perfil_red() -> str:
    """La línea del perfil de red, desde las constantes (Slow 4G de Lighthouse)."""
    bajada = f"{BAJADA_BPS / 1_024_000:.1f}".replace(".", ",")
    return (f"4G simulado: {LATENCIA_MS} ms, {bajada} Mbit/s bajada, {SUBIDA_BPS // 1000} kbit/s subida, "
            f"CPU ×{CPU_X}")


# --- UTM -----------------------------------------------------------------------------------------


def _pares_intactos(url: str) -> bool:
    q = parse_qs(urlsplit(url).query, keep_blank_values=True)
    return all(q.get(k) == [v] for k, v in PARES_PRUEBA.items())


def utm_intactos(url_pedida: str, checkout_url: str, base: str) -> bool:
    """Misma ruta de checkout (``checkout_url`` resuelta contra ``base``: esquema, host, puerto y ruta) y
    todos los pares de :data:`UTM_PRUEBA` presentes una sola vez con el mismo valor."""
    if not isinstance(url_pedida, str) or not url_pedida:
        return False
    pedida, esperada = urlsplit(url_pedida), urlsplit(urljoin(base, checkout_url))
    misma = (pedida.scheme, pedida.netloc.lower(), pedida.path or "/") == \
            (esperada.scheme, esperada.netloc.lower(), esperada.path or "/")
    return misma and _pares_intactos(url_pedida)


# --- medir (Chromium) ----------------------------------------------------------------------------

_JS_LCP = """() => new Promise((listo) => {
  let v = null;
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) v = e.startTime; })
      .observe({type: "largest-contentful-paint", buffered: true});
  } catch (e) {}
  setTimeout(() => listo(v), 100);
})"""

_JS_HITOS = """() => {
  const alto = document.documentElement.scrollHeight || 1;
  const salida = {};
  for (const s of document.querySelectorAll("section[data-tf-seccion]")) {
    const h = s.querySelector("[data-tf-hito]");
    if (!h) continue;
    salida[s.getAttribute("data-tf-seccion")] = (h.getBoundingClientRect().top + window.scrollY) / alto;
  }
  return salida;
}"""

_JS_DESBORDE = """() => {
  const ancho = document.documentElement.clientWidth;
  const sale = (el) => el.getBoundingClientRect().right > ancho + 0.5;
  const nombre = (el) => {
    if (el.id) return el.tagName.toLowerCase() + "#" + el.id;
    const clases = [...el.classList].slice(0, 2);
    return el.tagName.toLowerCase() + clases.map((c) => "." + c).join("");
  };
  for (const el of document.body.querySelectorAll("*")) {
    if (sale(el) && !(el.parentElement && el.parentElement !== document.body && sale(el.parentElement))) {
      return {ancho: document.documentElement.scrollWidth, selector: nombre(el)};
    }
  }
  return {ancho: document.documentElement.scrollWidth, selector: null};
}"""


@contextmanager
def _pagina(vista: str) -> Iterator:
    from trovefy.navegador import sesion

    with sesion(SERVICIO_QA, visible=_VISIBLE, perfil_persistente=False, viewport=VIEWPORTS[vista]) as page:
        yield page


def _filtro(page, permitidos: tuple[str, ...], silenciar: tuple[str, ...], externas: list[str]) -> None:
    def ruta(route):
        url = route.request.url
        host = (urlsplit(url).hostname or "").lower()
        if host in permitidos:
            route.continue_()
            return
        if host not in silenciar and url not in externas:
            externas.append(url)
        route.abort()

    page.route("**/*", ruta)


def _red_4g(page) -> None:
    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {
        "offline": False, "latency": LATENCIA_MS,
        "downloadThroughput": BAJADA_BPS / 8, "uploadThroughput": SUBIDA_BPS / 8})
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": CPU_X})


def _sin_cache(page) -> None:
    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
    cdp.send("Network.clearBrowserCache")


def _peso(peticiones: list) -> int:
    total = 0
    for r in peticiones:
        try:
            s = r.sizes()
        except Exception:  # noqa: BLE001, S112 - una petición sin tamaños no suma
            continue
        total += max(0, s.get("responseBodySize", 0)) + max(0, s.get("responseHeadersSize", 0))
    return total


def _escribir_captura(captura: Path, png: bytes) -> Path:
    from trovefy.producto.medios import escribir_medio

    captura = Path(captura)
    captura.parent.mkdir(parents=True, exist_ok=True)
    escribir_medio(captura, png, base=captura.parent)
    return captura


def medir(url: str, vista: str, captura: Path, permitidos: tuple[str, ...], red_4g: bool,
          silenciar: tuple[str, ...] = ()) -> Medicion:
    """Mide ``url`` en la vista (``VIEWPORTS``): ``RONDAS_LCP`` cargas con caché vacía (LCP tras ``load`` +
    3 s; con ``red_4g``, Slow 4G y CPU ×4 por CDP); de la primera, peso, estado HTTP, versión, hitos, ancho de
    scroll con el selector culpable y la captura de página completa (0640). Un fallo de carga devuelve una
    medición vacía con su ``motivo``."""
    from playwright.sync_api import Error as PlaywrightError

    from trovefy.navegador import NavegadorError

    permitidos = tuple(h.lower() for h in permitidos)
    silenciar = tuple(h.lower() for h in silenciar)
    externas: list[str] = []
    vacia = {"vista": vista, "lcp_ms": None, "peso_bytes": None, "ancho_scroll": 0, "desborde_selector": None,
             "hitos": None, "captura": None}
    try:
        with _pagina(vista) as page:
            page.set_default_timeout(TIEMPO_CARGA_MS)
            _filtro(page, permitidos, silenciar, externas)
            _sin_cache(page)
            if red_4g:
                _red_4g(page)
            peticiones: list = []

            def anotar(req) -> None:
                peticiones.append(req)

            page.on("requestfinished", anotar)
            lcp: list[float | None] = []
            datos: dict = {}
            for ronda in range(RONDAS_LCP):
                respuesta = page.goto(url, wait_until="load", timeout=TIEMPO_CARGA_MS)
                page.wait_for_timeout(ESPERA_TRAS_LOAD_MS)
                lcp.append(page.evaluate(_JS_LCP))
                if ronda == 0:
                    page.remove_listener("requestfinished", anotar)
                    desborde = page.evaluate(_JS_DESBORDE)
                    datos = {
                        "http": respuesta.status if respuesta is not None else None,
                        "version": page.get_attribute("main#tf-landing", "data-tf-version", timeout=1000)
                        if page.locator("main#tf-landing").count() else None,
                        "hitos": {int(k): round(float(v), 4) for k, v in page.evaluate(_JS_HITOS).items()
                                  if str(k).isdigit()},
                        "ancho": int(desborde["ancho"]), "selector": desborde["selector"],
                        "png": page.screenshot(full_page=True),
                        "peso": _peso(peticiones),
                    }
    except (PlaywrightError, NavegadorError) as exc:
        return Medicion(**vacia, peticiones_externas=tuple(externas),
                        motivo=f"no se pudo cargar la página ({type(exc).__name__})")
    captura = _escribir_captura(captura, datos["png"])
    valido = all(isinstance(x, (int, float)) and x > 0 for x in lcp)
    return Medicion(
        vista=vista, lcp_ms=[float(x) for x in lcp] if valido else None, peso_bytes=datos["peso"],
        peticiones_externas=tuple(externas), ancho_scroll=datos["ancho"],
        desborde_selector=datos["selector"] if datos["ancho"] > VIEWPORTS[vista][0] else None,
        hitos=datos["hitos"], captura=captura,
        motivo=None if valido else "el navegador no dio LCP en alguna ronda",
        http=datos["http"], version_servida=datos["version"],
    )


def probar_clic(url: str, checkout_url: str, interceptar: bool = True) -> Clic:
    """Abre ``url + UTM_PRUEBA`` a 390 px y pulsa el primer ``a[data-tf-checkout]``.

    Con ``interceptar`` (QA de la landing) la navegación que sale del clic se responde con un 204 sin salir a
    la red, y toda petición a otro host que no sea el de la landing se aborta; devuelve la URL pedida. Sin
    ``interceptar`` (``/listo``, plan 20) sigue la navegación real y devuelve la URL final."""
    from playwright.sync_api import Error as PlaywrightError

    from trovefy.navegador import NavegadorError

    host = (urlsplit(url).hostname or "").lower()
    destino = url.split("#", 1)[0]
    destino = destino + ("&" + UTM_PRUEBA[1:] if "?" in destino else UTM_PRUEBA)
    pedidas: list[str] = []
    try:
        with _pagina("movil") as page:
            cargada = {"si": False}

            def ruta(route):
                req = route.request
                if cargada["si"] and req.is_navigation_request() and req.frame == page.main_frame:
                    pedidas.append(req.url)
                    route.fulfill(status=204, body="")
                elif (urlsplit(req.url).hostname or "").lower() == host:
                    route.continue_()
                else:
                    route.abort()

            if interceptar:
                page.route("**/*", ruta)
            page.goto(destino, wait_until="load", timeout=TIEMPO_CARGA_MS)
            cargada["si"] = True
            boton = page.locator("a[data-tf-checkout]")
            if boton.count() == 0:
                return Clic(None, "la página no tiene ningún a[data-tf-checkout]")
            antes = page.url
            boton.first.click(no_wait_after=interceptar, timeout=ESPERA_CLIC_MS)
            if interceptar:
                for _ in range(ESPERA_CLIC_MS // 100):
                    if pedidas:
                        break
                    page.wait_for_timeout(100)
                pedida = pedidas[0] if pedidas else None
            else:
                page.wait_for_load_state("load", timeout=TIEMPO_CARGA_MS)
                pedida = page.url if page.url != antes else None
    except (PlaywrightError, NavegadorError) as exc:
        return Clic(None, f"no se pudo probar el clic ({type(exc).__name__})")
    if pedida is None:
        return Clic(None, "el botón de compra no navegó")
    return Clic(pedida, None, intactos=utm_intactos(pedida, checkout_url, url))


# --- evaluar (puro) ------------------------------------------------------------------------------


def _fila_validacion(v: Resultado) -> tuple[str, str, str]:
    if v.fallos:
        return ("Validación estática", FALLA, "; ".join(v.fallos))
    if v.avisos:
        return ("Validación estática", AVISO, "; ".join(v.avisos))
    return ("Validación estática", OK, "sin fallos")


def _filas_hitos(m: Medicion, wf: list[dict]) -> tuple[str, str, str]:
    nombre = f"Hitos ({m.vista})"
    if m.hitos is None:
        return (nombre, NO_MEDIDO, f"no medido: {m.motivo or 'sin hitos'}")
    esperados = [int(s["orden"]) for s in wf]
    faltan = [o for o in esperados if o not in m.hitos]
    if faltan:
        return (nombre, FALLA, "falta el data-tf-hito de la sección " + ", ".join(map(str, faltan)))
    medido = sorted(esperados, key=lambda o: (m.hitos[o], esperados.index(o)))
    if medido != esperados:
        return (nombre, FALLA, "las secciones salen en otro orden: " + ", ".join(map(str, medido)))
    desvios = [f"sección {s['orden']}: {m.hitos[int(s['orden'])]:.2f} frente a {float(s['y_rel']):.2f}"
               for s in wf if abs(m.hitos[int(s["orden"])] - float(s["y_rel"])) > TOLERANCIA_HITO]
    if desvios:
        return (nombre, AVISO, f"lejos del wireframe (más de {TOLERANCIA_HITO:.0%}): " + "; ".join(desvios))
    return (nombre, OK, f"{len(esperados)} hitos en orden")


def _filas_medicion(m: Medicion, wf: list[dict], version: str, publicada: bool) -> list[tuple[str, str, str]]:
    ancho = VIEWPORTS[m.vista][0]
    motivo = f"no medido: {m.motivo or 'sin dato'}"
    filas = []
    if publicada:
        if m.http is None:
            filas.append((f"Respuesta ({m.vista})", NO_MEDIDO, motivo))
        else:
            filas.append((f"Respuesta ({m.vista})", OK if m.http == 200 else FALLA, f"HTTP {m.http}"))
        if m.version_servida is None:
            filas.append((f"Versión servida ({m.vista})", NO_MEDIDO, motivo))
        elif m.version_servida != version:
            filas.append((f"Versión servida ({m.vista})", FALLA,
                          f"sirve «{m.version_servida}»; la guardada es «{version}»"))
        else:
            filas.append((f"Versión servida ({m.vista})", OK, version))
    if m.vista == "movil":
        if m.lcp_ms is None:
            filas.append(("LCP (movil, 4G simulado)", NO_MEDIDO, motivo))
        else:
            med = _mediana(m.lcp_ms)
            detalle = f"mediana {_miles(med)} ms (rondas {_rondas(m.lcp_ms)}); máximo {_miles(LCP_MAX_MS)} ms"
            filas.append(("LCP (movil, 4G simulado)", FALLA if med >= LCP_MAX_MS else OK, detalle))
    if m.peso_bytes is None:
        filas.append((f"Peso ({m.vista})", NO_MEDIDO, motivo))
    else:
        filas.append((f"Peso ({m.vista})", OK, _kb(m.peso_bytes)))
    if m.peso_bytes is None and m.hitos is None:
        filas.append((f"Desborde ({m.vista})", NO_MEDIDO, motivo))
    elif m.ancho_scroll > ancho:
        culpable = m.desborde_selector or "elemento sin identificar"
        filas.append((f"Desborde ({m.vista})", FALLA, f"scrollWidth {m.ancho_scroll} px > {ancho} px: {culpable}"))
    else:
        filas.append((f"Desborde ({m.vista})", OK, f"scrollWidth {m.ancho_scroll} px"))
    if m.peticiones_externas:
        filas.append((f"Peticiones externas ({m.vista})", FALLA, ", ".join(m.peticiones_externas)))
    else:
        filas.append((f"Peticiones externas ({m.vista})", OK, "ninguna"))
    filas.append(_filas_hitos(m, wf))
    return filas


def _fila_clic(c: Clic) -> tuple[str, str, str]:
    nombre = "Clic al checkout con UTM"
    if c.url_pedida is None:
        return (nombre, NO_MEDIDO, f"no medido: {c.motivo or 'sin URL pedida'}")
    if c.intactos is False or not _pares_intactos(c.url_pedida):
        return (nombre, FALLA, f"los UTM no llegan intactos al checkout: {c.url_pedida}")
    return (nombre, OK, c.url_pedida)


def _fila_nativo(nativo: tuple[str, str] | None, version: str) -> tuple[str, str, str]:
    nombre = "Idioma (nativo)"
    if nativo is None:
        return (nombre, NO_MEDIDO, "no medido: falta el veredicto del nativo (trovefy landing nativo)")
    veredicto, de_version = nativo
    if de_version != version:
        return (nombre, NO_MEDIDO, f"no medido: el veredicto es de la versión {de_version}; la landing es {version}")
    if veredicto != "ok":
        return (nombre, FALLA, f"el nativo pide corregir (versión {version}): ver nativo.md")
    return (nombre, OK, f"ok (versión {version})")


def evaluar(validacion: Resultado, mediciones: list[Medicion], clic: Clic, wireframe: list[dict],
            nativo: tuple[str, str] | None, version: str, publicada: bool) -> ResultadoQA:
    """Filas de la QA. FALLA y NO MEDIDO bloquean; AVISO no. Sin medición de una vista, NO MEDIDO."""
    filas = [_fila_validacion(validacion)]
    vistas = {m.vista: m for m in mediciones}
    for vista in VIEWPORTS:
        if vista not in vistas:
            filas.append((f"Medición ({vista})", NO_MEDIDO, "no medido: no se midió esta vista"))
            continue
        filas += _filas_medicion(vistas[vista], wireframe, version, publicada)
    filas.append(_fila_clic(clic))
    filas.append(_fila_nativo(nativo, version))
    ok = not any(f[1] in (FALLA, NO_MEDIDO) for f in filas)
    return ResultadoQA(ok, tuple(filas))


# --- QA.md ---------------------------------------------------------------------------------------


def _celda(texto: str) -> str:
    return str(texto).replace("|", "\\|").replace("\n", " ")


def _captura_rel(m: Medicion, raiz_producto: Path | None) -> str | None:
    if m.captura is None:
        return None
    if raiz_producto is not None:
        try:
            return Path(m.captura).resolve().relative_to(raiz_producto.resolve()).as_posix()
        except ValueError:
            pass
    return Path(m.captura).as_posix()


def render_qa(datos: DatosLanding, r: ResultadoQA, mediciones: list[Medicion], ahora: datetime, url: str | None,
              *, clic: Clic | None = None, version: str | None = None, raiz_producto: Path | None = None) -> str:
    """``QA.md``: frontmatter ``{tipo: qa_landing, pais, version, ok, fecha, url, movil_390, utm_checkout}``
    (las dos últimas, con la forma de ``landing.qa`` de la resolución 3), tabla de filas y medidas."""
    from trovefy.vault.frontmatter import renderizar

    vistas = {m.vista: m for m in mediciones}
    movil = vistas.get("movil")
    meta = {
        "tipo": "qa_landing", "pais": datos.pais, "version": version, "ok": r.ok,
        "fecha": ahora.isoformat(timespec="seconds"), "url": url,
        "movil_390": {"http": movil.http if movil else None,
                      "captura": _captura_rel(movil, raiz_producto) if movil else None},
        "utm_checkout": {"ok": bool(clic and clic.url_pedida and clic.intactos is not False
                                    and _pares_intactos(clic.url_pedida)),
                         "destino": clic.url_pedida if clic else None, "captura": None, "interceptado": True},
    }
    donde = f"publicada en {url}" if url else "local (127.0.0.1)"
    lineas = [f"# QA de la landing · {datos.p_id} · {datos.pais}", "",
              f"Versión `{version}` · {donde} · {'apta' if r.ok else 'no apta'}.", "",
              perfil_red() + ".", "",
              "| Comprobación | Estado | Detalle |", "|---|---|---|"]
    lineas += [f"| {_celda(a)} | {b} | {_celda(c)} |" for a, b, c in r.filas]
    lineas += ["", "## Medidas"]
    for vista, (w, h) in VIEWPORTS.items():
        m = vistas.get(vista)
        lineas += ["", f"### {vista} ({w}×{h})", ""]
        if m is None:
            lineas.append("- no medido: no se midió esta vista")
            continue
        rel = _captura_rel(m, raiz_producto)
        lineas.append(f"- Captura: {rel}" if rel else f"- Captura: no medido: {m.motivo or 'sin captura'}")
        lineas.append(f"- Peso: {_kb(m.peso_bytes)}" if m.peso_bytes is not None
                      else f"- Peso: no medido: {m.motivo or 'sin dato'}")
        if m.lcp_ms:
            lineas.append(f"- LCP: mediana {_miles(_mediana(m.lcp_ms))} ms (rondas {_rondas(m.lcp_ms)} ms)")
        else:
            lineas.append(f"- LCP: no medido: {m.motivo or 'sin dato'}")
    return renderizar(meta, "\n".join(lineas) + "\n")


# --- ejecutar ------------------------------------------------------------------------------------


class _SoloLanding(http.server.SimpleHTTPRequestHandler):
    """Sirve solo ``index.html`` y ``assets/`` (nada de ``landing.yaml``, ``nativo.md`` ni ``qa/``)."""

    def log_message(self, *a):
        pass

    def send_head(self):
        ruta = urlsplit(self.path).path
        if ruta not in ("/", "/index.html") and not (ruta.startswith("/assets/") and ".." not in ruta):
            self.send_error(404)
            return None
        return super().send_head()


@contextmanager
def servir_local(carpeta: Path) -> Iterator[str]:
    """``http.server`` en ``127.0.0.1`` (puerto libre) con la landing; da la URL de ``index.html``."""
    handler = functools.partial(_SoloLanding, directory=str(carpeta))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    finally:
        srv.shutdown()
        srv.server_close()


def version_guardada(vault: Path, datos: DatosLanding) -> str:
    """La versión de ``landing.yaml`` (la fija ``guardar``); sin ella, ``EntradaInvalida``."""
    from trovefy.landing.plantilla import leer_landing_yaml

    version = leer_landing_yaml(vault, datos.p_id, datos.pais).get("version")
    if not isinstance(version, str) or not version:
        raise EntradaInvalida(f"la landing de {datos.pais} no está guardada: trovefy landing guardar")
    return version


def leer_hitos_esperados(vault: Path, datos: DatosLanding) -> list[dict]:
    """Las secciones de ``wireframe.yaml`` (las que valida ``validar``); sin archivo, las de la oferta."""
    import yaml

    ruta = ruta_landing(vault, datos.p_id, datos.pais) / "wireframe.yaml"
    if ruta.is_file() and not ruta.is_symlink():
        try:
            secciones = (yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}).get("secciones")
        except (yaml.YAMLError, AttributeError):
            secciones = None
        if isinstance(secciones, list) and all(isinstance(s, dict) and "orden" in s and "y_rel" in s
                                               for s in secciones):
            return secciones
    return wireframe(datos)


def _nativo(vault: Path, datos: DatosLanding) -> tuple[str, str] | None:
    try:
        from trovefy.landing.nativo import veredicto_vigente  # Tarea 7
    except ImportError:
        return None
    return veredicto_vigente(vault, datos.p_id, datos.pais)


def ejecutar_qa(vault: Path, datos: DatosLanding, url: str | None = None, *,
                ahora: datetime | None = None) -> ResultadoQA:
    """Mide la landing (local en ``127.0.0.1`` sin ``url``; la publicada con ``url``), la evalúa y escribe
    ``landing/<PAIS>/QA.md`` con las capturas ``qa/<vista>-<version>.png`` y su línea de log."""
    from trovefy.landing.plantilla import leer_landing_yaml
    from trovefy.producto.medios import carpeta_segura
    from trovefy.secretos import buscar_secreto
    from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico
    from trovefy.vault.producto import ruta_producto

    vault = Path(vault)
    version = version_guardada(vault, datos)
    landing = leer_landing_yaml(vault, datos.p_id, datos.pais)
    checkout = landing.get("checkout_url")
    if not isinstance(checkout, str) or not checkout:
        raise EntradaInvalida("landing.yaml no trae checkout_url: trovefy landing preparar")
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    try:
        carpeta_segura(vault, raiz / "qa", crear=True)
    except ValueError as exc:
        raise EntradaInvalida(str(exc)) from None
    silenciar = tuple(sorted(HOSTS_PIXEL)) if landing.get("hosting") == "cloudflare" else ()
    validacion = validar(vault, datos)
    wf = leer_hitos_esperados(vault, datos)

    def _medir_todo(pagina: str) -> tuple[list[Medicion], Clic]:
        permitidos = ((urlsplit(pagina).hostname or "").lower(),)
        meds = [medir(pagina, vista, raiz / "qa" / f"{vista}-{version}.png", permitidos,
                      red_4g=(vista == "movil"), silenciar=silenciar) for vista in VIEWPORTS]
        return meds, probar_clic(pagina, checkout)

    if url is None:
        with servir_local(raiz) as pagina:
            mediciones, clic = _medir_todo(pagina)
    else:
        mediciones, clic = _medir_todo(url)
    r = evaluar(validacion, mediciones, clic, wf, _nativo(vault, datos), version, publicada=url is not None)
    ahora = ahora or datetime.now(ZONA_NEGOCIO)
    texto = render_qa(datos, r, mediciones, ahora, url, clic=clic, version=version,
                      raiz_producto=ruta_producto(vault, datos.p_id).parent)
    patron = buscar_secreto(texto)
    if patron:
        raise EntradaInvalida(f"QA.md: aparece algo con forma de secreto ({patron}); no se guarda")
    escribir_atomico(raiz / "QA.md", texto)
    rel = raiz.relative_to(vault).as_posix()
    anadir_log(vault, "landing", f"{datos.p_id} {datos.pais}: QA {'apta' if r.ok else 'no apta'} "
               f"(versión {version}, {'publicada' if url else 'local'})",
               [f"{rel}/QA.md", *(f"{rel}/qa/{vista}-{version}.png" for vista in VIEWPORTS)])
    return r
