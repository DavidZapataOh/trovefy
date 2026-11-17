"""La pantalla «Diseño de tienda → Contenido» de Impultienda (`diseno_contenido` del mapa, resolución 20).

Lo comparten la sonda (Tarea 8) y la publicación (Tarea 9). Todo clic y toda escritura van por
`trovefy.tienda.conductor.Conductor` (`poner`/`pulsar`, resolución 21): este módulo solo lee, navega y
encadena. Antes de tocar el campo se guarda lo que tenía en `landing/<PAIS>/respaldo/` del producto.

La pantalla solo es escribible con su propio `capturado`: el del mapa del repo o el que el usuario confirma en
su vault con `trovefy landing capturar` (`trovefy.tienda.confirmacion`). Sin él: «no medido: mapa sin
confirmar» y no se abre el navegador.
"""

from __future__ import annotations

import contextlib
import copy
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import urldefrag

from trovefy.landing.entrada import ruta_landing
from trovefy.mapa import capturado_de, hosts_de, origen, origenes_de
from trovefy.mapa import cargar as cargar_mapa
from trovefy.navegador import NavegadorError, sesion
from trovefy.producto.medios import carpeta_segura, escribir_medio
from trovefy.secretos import buscar_secreto
from trovefy.tienda.conductor import Conductor, FirmaNoCasa, MapaSinConfirmar
from trovefy.tienda.confirmacion import confirmar_pantalla, mapa_con_confirmaciones
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log

SERVICIO = "impultienda"
PANTALLA = "diseno_contenido"
MAPA_IMPULTIENDA = Path(__file__).resolve().parents[3] / "templates" / "impultienda" / "mapa.yaml"
_ESPERA_GUARDADO_MS = 15_000
SIN_CONFIRMAR = (f"no medido: mapa sin confirmar ({PANTALLA}). Confírmala tú con `trovefy landing capturar`: "
                 "abre «Diseño de tienda → Contenido» en la ventana, pulsa Intro y responde «sí».")


def mapa_impultienda(vault: Path) -> dict:
    """El mapa de Impultienda del repo con las pantallas que el usuario confirmó en su vault."""
    return mapa_con_confirmaciones(vault, SERVICIO, cargar_mapa(MAPA_IMPULTIENDA))


def _con_url(mapa: dict, url: str) -> dict:
    """Copia del mapa con la URL de `diseno_contenido` cambiada; `ValueError` si no es de un origen del mapa."""
    if not isinstance(url, str) or origen(url) not in origenes_de(mapa):
        hosts = ", ".join(sorted(hosts_de(mapa)))
        raise ValueError(f"la URL de la pantalla tiene que ser https de {hosts}: «{url}» no lo es")
    m = copy.deepcopy(mapa)
    m["pantallas"][PANTALLA]["url"] = urldefrag(url).url
    return m


def preparar_mapa(vault: Path, mapa: dict | None = None, url_pantalla: str | None = None) -> dict:
    """El mapa con el que se trabaja: el inyectado o el del repo + confirmaciones; con `url_pantalla`, esa URL
    (del host del mapa) para `diseno_contenido`. `MapaSinConfirmar` si la pantalla no tiene `capturado`."""
    m = copy.deepcopy(mapa) if mapa is not None else mapa_impultienda(vault)
    if url_pantalla is not None:
        m = _con_url(m, url_pantalla)
    if capturado_de(m, PANTALLA) is None:
        raise MapaSinConfirmar(PANTALLA, SIN_CONFIRMAR)
    return m


def _esperar_red(page) -> None:
    """Deja terminar el guardado (petición en curso) antes de releer; no hace clics."""
    esperar = getattr(page, "wait_for_load_state", None)
    if esperar is not None:
        with contextlib.suppress(Exception):
            esperar("networkidle", timeout=_ESPERA_GUARDADO_MS)


class Panel:
    """`diseno_contenido` conducida por el `Conductor` (el único que escribe y pulsa)."""

    def __init__(self, page, mapa: dict, dormir: Callable[[float], None] = time.sleep):
        self.page = page
        self.conductor = Conductor(page, mapa, SERVICIO, dormir=dormir)

    def abrir(self) -> None:
        """Va a la pantalla y comprueba sesión, origen y firma; si la firma no casa, para sin tocar nada."""
        try:
            self.conductor.ir(PANTALLA)
        except FirmaNoCasa as e:
            raise FirmaNoCasa(PANTALLA, f"{e.motivo} Abre tú «Diseño de tienda → Contenido» y vuelve a lanzar con "
                                        "--url <la de esa pantalla>.") from e

    def leer(self) -> str:
        """Lo que tiene ahora el campo «HTML completo de la tienda» (puede llevar datos: revisa secretos)."""
        valor = self.conductor.leer(PANTALLA, "html")
        return valor if isinstance(valor, str) else ""

    def guardar(self, html: str) -> str:
        """Pega `html`, pulsa «Guardar cambios», vuelve a abrir la pantalla y devuelve lo que quedó guardado."""
        self.conductor.poner(PANTALLA, "html", html)
        self.conductor.pulsar(PANTALLA, "guardar")
        _esperar_red(self.page)
        self.abrir()
        return self.leer()


def respaldar(vault: Path, p_id: str, pais: str, contenido: str, ahora: datetime) -> Path:
    """Guarda `contenido` en `landing/<PAIS>/respaldo/impultienda-<fecha>[-N].html` (0640, nunca pisa uno
    anterior). `ValueError` si parece llevar un secreto: entonces no se guarda ni se toca nada."""
    patron = buscar_secreto(contenido)
    if patron:
        raise ValueError(f"lo que tiene ahora el campo de Impultienda parece llevar un secreto ({patron}): no lo "
                         "guardo ni toco nada. Revísalo tú en la pantalla.")
    vault = Path(vault)
    carpeta = ruta_landing(vault, p_id, pais) / "respaldo"
    carpeta_segura(vault, carpeta, crear=True)
    fecha = ahora.astimezone(ZONA_NEGOCIO).date().isoformat()
    ruta, n = carpeta / f"impultienda-{fecha}.html", 2
    while ruta.exists() or ruta.is_symlink():
        ruta, n = carpeta / f"impultienda-{fecha}-{n}.html", n + 1
    escribir_medio(ruta, contenido.encode("utf-8"), base=vault)
    rel = ruta.relative_to(vault).as_posix()
    anadir_log(vault, "landing", f"{p_id} {pais}: respaldo del contenido de Impultienda", [rel], ahora=ahora)
    return ruta


def restaurar(abrir, mapa: dict, original: str, ruta: Path, *, visible: bool,
              dormir: Callable[[float], None]) -> None:
    """Vuelve a pegar `original` y comprueba que quedó igual; si no, `NavegadorError` con la ruta del respaldo."""
    motivo = f"no pude restaurar el contenido: pégalo tú desde {ruta}"
    try:
        with abrir(SERVICIO, visible=visible) as page:
            panel = Panel(page, mapa, dormir)
            panel.abrir()
            releido = panel.guardar(original)
    except Exception as exc:
        raise NavegadorError(motivo) from exc
    if releido != original:
        raise NavegadorError(motivo)


def capturar_pantalla(vault: Path, url: str | None = None, *, mapa: dict | None = None, abrir=None,
                      esperar: Callable[[str], object] = input, preguntar: Callable[[str], str] = input,
                      visible: bool = True, dormir: Callable[[float], None] = time.sleep,
                      ahora: datetime | None = None) -> dict:
    """Confirmación guiada de `diseno_contenido` (resolución 20) sin un solo clic.

    Abre la ventana visible con el perfil `impultienda` (en `url` o en la del mapa); el usuario navega a
    «Diseño de tienda → Contenido» y pulsa Intro. Se comprueban sesión, origen, firma y que el campo HTML y el
    botón «Guardar cambios» casan con un solo elemento; se guarda una captura con los campos tapados y se le
    pregunta. Solo un «sí» literal confirma (`trovefy.tienda.confirmacion.confirmar_pantalla`).
    """
    vault = Path(vault)
    ahora = ahora or datetime.now(ZONA_NEGOCIO)
    base = copy.deepcopy(mapa) if mapa is not None else cargar_mapa(MAPA_IMPULTIENDA)
    inicio = url or base["pantallas"][PANTALLA]["url"]
    _con_url(base, inicio)  # el inicio también tiene que ser del host del mapa
    abrir = abrir or sesion
    fecha = ahora.astimezone(ZONA_NEGOCIO).date().isoformat()
    evidencia = f"config/evidencia/p05-diseno-contenido-{fecha}.png"
    with abrir(SERVICIO, visible=visible) as page:
        try:
            page.goto(inicio, wait_until="load", timeout=30_000)
        except Exception as exc:
            raise NavegadorError(f"no se pudo cargar {inicio} ({type(exc).__name__}); revisa tu conexión") from exc
        esperar("Navega tú, en la ventana, a «Diseño de tienda → Contenido» (sin guardar nada) y pulsa Intro aquí. ")
        real = urldefrag(page.url).url
        m = _con_url(base, real)
        c = Conductor(page, m, SERVICIO, dormir=dormir)
        c.ir(PANTALLA)  # vuelve a cargar la misma URL: sesión, origen y firma
        c.leer(PANTALLA, "html")  # el campo casa con un solo elemento (el valor no se guarda)
        guardar = m["pantallas"][PANTALLA]["controles"]["guardar"]
        n = page.get_by_role(guardar["rol"], name=guardar["etiqueta"], exact=True).count()
        if n != 1:
            raise FirmaNoCasa(PANTALLA, f"el botón «{guardar['etiqueta']}» casa con {n} elementos: no se confirma.")
        c.capturar(vault / evidencia)
    respuesta = preguntar(f"¿Es esta la pantalla «Diseño de tienda → Contenido» de tu tienda ({real})? "
                          "Escribe «sí» para confirmarla: ")
    return confirmar_pantalla(vault, SERVICIO, base, PANTALLA, real, respuesta, ahora, evidencia=evidencia)
