"""La pantalla «Diseño de tienda → Contenido» de Impultienda (`diseno_contenido` del mapa, resolución 20).

Lo comparten la sonda (Tarea 8) y la publicación (Tarea 9). Todo clic y toda escritura van por
`trovefy.tienda.conductor.Conductor` (`poner`/`pulsar`, resolución 21): este módulo solo lee, navega y
encadena. Antes de tocar el campo se guarda lo que tenía en `landing/<PAIS>/respaldo/` del producto.

La pantalla solo es escribible con su propio `capturado`: el del mapa del repo o el que el usuario confirma con
`trovefy landing capturar` (`trovefy.tienda.confirmacion`, fuera del vault). Sin él: «no medido: mapa sin
confirmar» y no se abre el navegador.

Restaurar nunca pega a ciegas (F2-1): primero lee el campo y solo pega lo de antes si lo que hay es lo que se
pegó (mismo SHA-256). Si es otra cosa (alguien lo cambió entretanto), guarda también eso en `respaldo/`, no pega
nada y para con `CampoCambiado` nombrando los dos archivos.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import re
import sys
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
from trovefy.tienda import confirmacion
from trovefy.tienda.conductor import Conductor, FirmaNoCasa, MapaSinConfirmar
from trovefy.tienda.confirmacion import (
    SIN_TERMINAL,
    confirmada_en_vault,
    confirmar_pantalla,
    mapa_con_confirmaciones,
    ruta_evidencia,
)
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log

SERVICIO = "impultienda"
PANTALLA = "diseno_contenido"
MAPA_IMPULTIENDA = Path(__file__).resolve().parents[3] / "templates" / "impultienda" / "mapa.yaml"
_ESPERA_GUARDADO_MS = 15_000
SIN_CONFIRMAR = (f"no medido: mapa sin confirmar ({PANTALLA}). Confírmala tú con `trovefy landing capturar`: "
                 "abre «Diseño de tienda → Contenido» en la ventana, pulsa Intro y responde «sí».")


def mapa_impultienda(vault: Path) -> dict:
    """El mapa de Impultienda del repo con las pantallas que el usuario confirmó (`trovefy landing capturar`)."""
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
    (del host del mapa) para `diseno_contenido`. `MapaSinConfirmar` si la pantalla no tiene `capturado`.

    Si quien da el `capturado` es la confirmación del usuario (no el mapa del repo), `url_pantalla` tiene que ser
    la URL confirmada (I-2): se confirmó esa pantalla, no otra."""
    if mapa is None:
        confirmada = confirmada_en_vault(vault, SERVICIO, cargar_mapa(MAPA_IMPULTIENDA), PANTALLA)
        if (url_pantalla is not None and confirmada is not None
                and (not isinstance(url_pantalla, str) or urldefrag(url_pantalla.strip()).url != confirmada)):
            raise ValueError(f"esa URL no es la que confirmaste: vuelve a capturar (`trovefy landing capturar "
                             f"--url {url_pantalla}`) o lanza sin --url (la confirmada es {confirmada})")
    m = copy.deepcopy(mapa) if mapa is not None else mapa_impultienda(vault)
    if url_pantalla is not None:
        m = _con_url(m, url_pantalla.strip() if isinstance(url_pantalla, str) else url_pantalla)
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


class CampoCambiado(NavegadorError):
    """Al ir a restaurar, el campo no tenía lo que se pegó: no se pega nada (F2-1)."""


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _respaldar_en(vault: Path, carpeta: Path, contenido: str, ahora: datetime, que: str) -> Path:
    patron = buscar_secreto(contenido)
    if patron:
        raise ValueError(f"lo que tiene ahora el campo de Impultienda parece llevar un secreto ({patron}): no lo "
                         "guardo ni toco nada. Revísalo tú en la pantalla.")
    carpeta_segura(vault, carpeta, crear=True)
    marca = ahora.astimezone(ZONA_NEGOCIO).strftime("%Y-%m-%dT%H%M%S")
    ruta, n = carpeta / f"impultienda-{marca}.html", 2
    while ruta.exists() or ruta.is_symlink():
        ruta, n = carpeta / f"impultienda-{marca}-{n}.html", n + 1
    escribir_medio(ruta, contenido.encode("utf-8"), base=vault)
    anadir_log(vault, "landing", que, [ruta.relative_to(vault).as_posix()], ahora=ahora)
    return ruta


def respaldar(vault: Path, p_id: str, pais: str, contenido: str, ahora: datetime) -> Path:
    """Guarda `contenido` en `landing/<PAIS>/respaldo/impultienda-AAAA-MM-DDTHHMMSS[-N].html` (0640, nunca pisa
    uno anterior). `ValueError` si parece llevar un secreto: entonces no se guarda ni se toca nada."""
    vault = Path(vault)
    return _respaldar_en(vault, ruta_landing(vault, p_id, pais) / "respaldo", contenido, ahora,
                         f"{p_id} {pais}: respaldo del contenido de Impultienda")


# Nombres nuevos con hora (AAAA-MM-DDTHHMMSS) y los antiguos solo con fecha (cuentan como de las 00:00:00).
_RESPALDO = re.compile(r"impultienda-([0-9]{4}-[0-9]{2}-[0-9]{2})(?:T([0-9]{6}))?(?:-([0-9]+))?\.html")


def ultimo_respaldo(vault: Path, pais: str) -> Path | None:
    """El respaldo más reciente de la tienda de `pais`, buscado en `productos/*/landing/<PAIS>/respaldo/` (la
    tienda es una por país, la toque el producto que la toque; F2-3). Se ordena por fecha, hora y número, no
    por orden alfabético; None si no hay."""
    vault = Path(vault)
    candidatos = []
    for carpeta in (vault / "productos").glob(f"*/landing/{pais.upper()}/respaldo"):
        if carpeta.is_symlink() or not carpeta.is_dir():
            continue
        for p in carpeta.iterdir():
            m = _RESPALDO.fullmatch(p.name)
            if m and p.is_file() and not p.is_symlink():
                candidatos.append(((m.group(1), m.group(2) or "000000", int(m.group(3) or 1), str(p)), p))
    return max(candidatos)[1] if candidatos else None


def restaurar_desde_respaldo(vault: Path, respaldo: Path, *, esperado: str | tuple[str, ...],
                             mapa: dict | None = None, abrir=None, visible: bool = True,
                             dormir: Callable[[float], None] = time.sleep, ahora: datetime | None = None) -> None:
    """Vuelve a pegar en el campo el contenido de `respaldo` (L-4: tras una QA publicada en rojo) si el campo
    tiene `esperado` (lo que se pegó), y comprueba que quedó igual (ver `restaurar`)."""
    respaldo = Path(respaldo)
    if respaldo.is_symlink() or not respaldo.is_file():
        raise NavegadorError(f"no encuentro el respaldo {respaldo}: pega tú lo que tenías")
    original = respaldo.read_text(encoding="utf-8")
    restaurar(abrir or sesion, preparar_mapa(vault, mapa), original, respaldo, esperado=esperado, vault=vault,
              visible=visible, dormir=dormir, ahora=ahora)


def restaurar(abrir, mapa: dict, original: str, ruta: Path, *, esperado: str | tuple[str, ...], vault: Path,
              visible: bool, dormir: Callable[[float], None], ahora: datetime | None = None) -> None:
    """Vuelve a pegar `original` (guardado en `ruta`) y comprueba que quedó igual.

    Antes lee el campo: si ya tiene `original`, no hace nada; si tiene alguno de `esperado` (lo que se pegó,
    comparado por SHA-256), pega `original`; si tiene otra cosa, la guarda junto a `ruta`, no pega nada y lanza
    `CampoCambiado` con los dos archivos. Si no queda igual, `NavegadorError` con la ruta del respaldo."""
    vault = Path(vault)
    esperados = {_sha(e) for e in ((esperado,) if isinstance(esperado, str) else esperado) if isinstance(e, str)}
    motivo = f"no pude restaurar el contenido: pégalo tú desde {ruta}"
    try:
        with abrir(SERVICIO, visible=visible) as page:
            panel = Panel(page, mapa, dormir)
            panel.abrir()
            actual = panel.leer()
            if actual == original:
                return
            if _sha(actual) not in esperados:
                _campo_cambiado(vault, ruta, actual, ahora)
            releido = panel.guardar(original)
    except CampoCambiado:
        raise
    except Exception as exc:
        raise NavegadorError(motivo) from exc
    except BaseException:  # Ctrl-C a media restauración (L-1): que se sepa de dónde pegarlo, y se sigue
        print(f"INTERRUMPIDA la restauración: {motivo}", file=sys.stderr)
        raise
    if releido != original:
        raise NavegadorError(motivo)


def _campo_cambiado(vault: Path, ruta: Path, actual: str, ahora: datetime | None) -> None:
    """El campo no tiene lo que se pegó: se guarda lo que hay (junto al respaldo) y se para sin pegar nada."""
    ahora = ahora or datetime.now(ZONA_NEGOCIO)
    base = (f"el campo «HTML completo de la tienda» ya no tiene lo que pegué (alguien lo cambió entretanto): no he "
            f"pegado nada. Lo que tenías antes está en {ruta}")
    try:
        nuevo = _respaldar_en(vault, Path(ruta).parent, actual, ahora,
                              "Impultienda: el campo cambió antes de restaurar; respaldo de lo que había")
    except ValueError as e:
        raise CampoCambiado(f"{base}; lo que hay ahora no lo guardo: {e}") from None
    raise CampoCambiado(f"{base}; lo que hay ahora, en {nuevo}. Decide tú cuál dejar.")


hay_terminal = confirmacion.hay_terminal


def capturar_pantalla(vault: Path, url: str | None = None, *, mapa: dict | None = None, abrir=None,
                      esperar: Callable[[str], object] = input, preguntar: Callable[[str], str] = input,
                      visible: bool = True, dormir: Callable[[float], None] = time.sleep,
                      ahora: datetime | None = None) -> dict:
    """Confirmación guiada de `diseno_contenido` (resolución 20) sin un solo clic.

    Solo con una persona en la terminal (I-1: stdin y stdout TTY; si no, `ValueError` sin abrir nada). Abre la
    ventana visible con el perfil `impultienda` (en `url` o en la del mapa); el usuario navega a
    «Diseño de tienda → Contenido» y pulsa Intro. Se comprueban sesión, origen, firma y que el campo HTML y el
    botón «Guardar cambios» casan con un solo elemento; se guarda una captura con los campos tapados y se le
    pregunta. Solo un «sí» literal confirma (`trovefy.tienda.confirmacion.confirmar_pantalla`).
    """
    if not confirmacion.hay_terminal():
        raise ValueError(SIN_TERMINAL)
    vault = Path(vault)
    ahora = ahora or datetime.now(ZONA_NEGOCIO)
    base = copy.deepcopy(mapa) if mapa is not None else cargar_mapa(MAPA_IMPULTIENDA)
    inicio = url or base["pantallas"][PANTALLA]["url"]
    _con_url(base, inicio)  # el inicio también tiene que ser del host del mapa
    abrir = abrir or sesion
    fecha = ahora.astimezone(ZONA_NEGOCIO).date().isoformat()
    evidencia = ruta_evidencia(PANTALLA, fecha)
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
    return confirmar_pantalla(vault, SERVICIO, base, PANTALLA, real, respuesta, ahora)
