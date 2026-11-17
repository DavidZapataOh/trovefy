"""Publicar en Impultienda con pegado manual (plan 18b): el usuario pega la landing en su propio navegador.

Google no deja iniciar sesión en el Chromium de Playwright y el Chrome del usuario vive en Windows (trovefy, en
WSL), así que trovefy **no entra en el panel** para la landing: ni navegador, ni `Conductor`, ni sonda.

1. `preparar_pegado`: con las mismas puertas que la publicación automática (`listo_para_publicar`: `validar`
   limpio, QA local, nativo `ok` y manifiesto), escribe `landing/<PAIS>/publicar/impultienda.html` con
   `empaquetar_en_linea` (los mismos bytes que pegaría el Conductor), 0640 y revisado con `buscar_secreto`;
   `instrucciones_pegado` dice qué hacer en el panel.
2. `guardar_respaldo` (opcional): guarda la copia que el usuario hizo del campo en
   `landing/<PAIS>/respaldo/impultienda-<AAAA-MM-DDTHHMMSS>-manual.html`, sin pisar nada.
3. `verificar_manual`: la URL pública (tu dominio o el host de tu tienda) por https sin redirecciones a otro
   host, que sirva el `data-tf-version` actual, y la QA publicada con la política de Impultienda (hosts de la
   tienda como AVISO, Meta silenciado). En verde se registra igual que la ruta automática (`producido →
   con_landing`) con `publicacion: manual` en `landing.yaml`; en rojo no se registra nada y se le pide que vuelva a
   pegar su copia. Sin evidencia de la sonda: la QA prueba que la tienda guardó el HTML entero, script incluido
   (sin `utm.js` el clic al checkout no lleva los UTM y la QA sale en rojo).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from trovefy.landing.entrada import DatosLanding, EntradaInvalida, ruta_landing
from trovefy.landing.hosting import Hosting, empaquetar_en_linea, guardar_tienda
from trovefy.landing.panel import _respaldar_en, nombre_respaldo, ultimo_respaldo
from trovefy.landing.plantilla import leer_landing_yaml
from trovefy.landing.publicar import (
    CARPETA_SUBIDA,
    NoPublicable,
    _abrir_seguro,
    listo_para_publicar,
    registrar_publicacion,
    verificar_cloudflare,
)
from trovefy.landing.qa import QA_PUBLICADA, comprobar_url_publicada, hosts_publicables
from trovefy.producto.medios import carpeta_segura, escribir_medio
from trovefy.secretos import buscar_secreto
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log

ARCHIVO_PEGADO = "impultienda.html"
SUFIJO_MANUAL = "-manual"
LOGIN = "https://impultienda.ar/login"
PANTALLA = "Diseño de tienda → Contenido"
# Una tienda de Impultienda sin dominio propio: <slug>.impultienda.ar (no el panel ni la web de la plataforma).
_TIENDA_IMPULTIENDA = re.compile(r"(?!(?:app|www)\.)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.impultienda\.ar")


def _exigir_impultienda(vault: Path, datos: DatosLanding) -> dict:
    landing = leer_landing_yaml(vault, datos.p_id, datos.pais)
    if landing.get("hosting") != "impultienda":
        raise NoPublicable(f"--manual es para la ruta Impultienda y esta landing se preparó para Cloudflare "
                           f"({landing.get('hosting')}): trovefy landing publicar --producto {datos.p_id} --pais "
                           f"{datos.pais} sin --manual")
    return landing


def _puertas(vault: Path, datos: DatosLanding) -> dict:
    landing = _exigir_impultienda(vault, datos)
    motivos = listo_para_publicar(vault, datos)
    if motivos:
        raise NoPublicable("No se publica: " + "; ".join(motivos))
    return landing


# --- 1. el paquete y las instrucciones --------------------------------------------------------------


def preparar_pegado(vault: Path, datos: DatosLanding) -> Path:
    """Escribe `landing/<PAIS>/publicar/impultienda.html` (el fragmento en línea, 0640) y devuelve su ruta.
    `NoPublicable` si no pasa las puertas, si la landing es de Cloudflare o si lleva algo con forma de secreto."""
    vault = Path(vault)
    _puertas(vault, datos)
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    fragmento = empaquetar_en_linea(raiz)
    patron = buscar_secreto(fragmento)
    if patron:
        raise NoPublicable(f"la landing en línea lleva algo con forma de secreto ({patron}): no la escribo")
    carpeta = raiz / CARPETA_SUBIDA
    try:
        carpeta_segura(vault, carpeta, crear=True)
    except ValueError as e:
        raise NoPublicable(str(e)) from None
    ruta = carpeta / ARCHIVO_PEGADO
    escribir_medio(ruta, fragmento.encode("utf-8"), base=vault)
    anadir_log(vault, "landing", f"{datos.p_id} {datos.pais}: lista para pegar a mano en Impultienda",
               [ruta.relative_to(vault).as_posix()])
    return ruta


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _ruta_windows(ruta: Path) -> str | None:
    """`\\\\wsl.localhost\\<distro>\\…` si trovefy corre en WSL (el navegador del usuario está en Windows)."""
    distro = os.environ.get("WSL_DISTRO_NAME", "").strip()
    if not distro:
        return None
    return f"\\\\wsl.localhost\\{distro}" + str(ruta).replace("/", "\\")


def _urls_tienda(datos: DatosLanding) -> list[str]:
    urls = [f"https://{h}/" for h in sorted(hosts_publicables(datos, "impultienda"))]
    return urls or ["https://<tu-tienda>.impultienda.ar/"]


def instrucciones_pegado(vault: Path, datos: DatosLanding, ruta: Path, ahora: datetime | None = None) -> str:
    """Los pasos, en corto, para pegar la landing a mano en el panel y volver a verificarla."""
    ahora = ahora or datetime.now(ZONA_NEGOCIO)
    n = len(Path(ruta).read_text(encoding="utf-8"))
    raiz = ruta_landing(Path(vault), datos.p_id, datos.pais)
    sugerido = raiz / "respaldo" / nombre_respaldo(ahora, SUFIJO_MANUAL)
    base = f"--producto {datos.p_id} --pais {datos.pais}"
    windows = _ruta_windows(Path(ruta))
    version = leer_landing_yaml(Path(vault), datos.p_id, datos.pais).get("version")
    lineas = [
        f"Landing de {datos.pais} (versión {version}) lista para pegarla tú en Impultienda.",
        f"Archivo: {ruta} ({_miles(n)} caracteres)",
        *([f"Desde Windows: {windows}"] if windows else []),
        "",
        f"1. En tu panel de Impultienda ({LOGIN}), abre «{PANTALLA}».",
        ("2. Antes de tocar nada, copia todo lo que hay en el campo «HTML completo de la tienda» a un archivo y "
         f"guárdalo: es tu copia de seguridad. Por ejemplo: {sugerido}"),
        (f"   Si quieres, que la guarde trovefy: trovefy landing respaldo {base} --desde <archivo> "
         "(o sin --desde: pégala y pulsa Ctrl-D en una línea nueva)."),
        (f"3. Borra el campo, pega todo el contenido de publicar/{ARCHIVO_PEGADO} ({_miles(n)} caracteres) y "
         "guarda los cambios."),
        f"4. Cuando esté guardado: trovefy landing publicar {base} --manual --url {_urls_tienda(datos)[0]}",
        f"   (la URL pública de tu tienda: {' o '.join(_urls_tienda(datos))})",
    ]
    return "\n".join(lineas)


# --- 2. la copia del usuario ------------------------------------------------------------------------


def guardar_respaldo(vault: Path, p_id: str, pais: str, contenido: str, ahora: datetime | None = None) -> Path:
    """Guarda lo que el usuario copió del campo en `landing/<PAIS>/respaldo/impultienda-<AAAA-MM-DDTHHMMSS>-manual
    .html` (0640, sin pisar otro). `ValueError` si está vacío o lleva algo con forma de secreto."""
    vault = Path(vault)
    pais = pais.strip().upper()
    if not isinstance(contenido, str) or not contenido.strip():
        raise ValueError("el contenido está vacío: no hay nada que guardar")
    return _respaldar_en(vault, ruta_landing(vault, p_id, pais) / "respaldo", contenido,
                         ahora or datetime.now(ZONA_NEGOCIO), f"{p_id} {pais}: tu copia del contenido de Impultienda",
                         SUFIJO_MANUAL)


# --- 3. verificar lo que pegó -------------------------------------------------------------------------


@dataclass(frozen=True)
class PublicadaManual:
    url: str
    estado: str
    tienda_guardada: str | None = None  # la tienda que se apuntó en config/mercados.yaml (resolución 24)


def _origen(url: str) -> str:
    return f"https://{(urlsplit(url).hostname or '').lower()}"


def _con_tienda(datos: DatosLanding, url: str) -> tuple[DatosLanding, str | None]:
    """Sin tienda en `mercados.yaml`, una URL `https://<slug>.impultienda.ar/` es la de la tienda: se acepta y se
    apuntará. Devuelve los datos (con esa tienda) y la tienda nueva, o los datos tal cual y None."""
    if datos.tienda:
        return datos, None
    host = (urlsplit(url.strip()).hostname or "").lower() if isinstance(url, str) else ""
    if _TIENDA_IMPULTIENDA.fullmatch(host):
        tienda = _origen(url)
        return replace(datos, tienda=tienda), tienda
    return datos, None


def _qa_publicada(vault: Path, datos: DatosLanding, url: str):
    from trovefy.landing import publicar

    return publicar._qa_publicada(vault, datos, url)


def verificar_manual(vault: Path, datos: DatosLanding, url: str, *, qa=None, abrir=None,
                     ahora: datetime | None = None) -> PublicadaManual:
    """Comprueba que la tienda sirve la versión actual en `url`, pasa la QA publicada y, en verde, lo registra
    (`publicacion: manual`). `NoPublicable` con el motivo (y, con la QA en rojo, el respaldo que volver a pegar)."""
    vault = Path(vault)
    ahora = ahora or datetime.now(ZONA_NEGOCIO)
    landing = _puertas(vault, datos)
    version = landing["version"]
    url = url.strip() if isinstance(url, str) else url
    d, tienda_nueva = _con_tienda(datos, url)
    try:
        comprobar_url_publicada(d, "impultienda", url)
    except EntradaInvalida:
        raise NoPublicable(f"«{url}» no es https de tu dominio o tu tienda: usa "
                           f"{' o '.join(_urls_tienda(d))}") from None
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    if not verificar_cloudflare(url, raiz, abrir=abrir or _abrir_seguro):
        raise NoPublicable(f"{url} no sirve la versión actual de la landing ({version}), o redirige a otro sitio: "
                           f"la página de tu tienda no es la versión actual: ¿guardaste en el panel? Pega el "
                           f"contenido de landing/{datos.pais}/{CARPETA_SUBIDA}/{ARCHIVO_PEGADO} en «{PANTALLA}», "
                           "guarda y vuelve a lanzar la orden")
    r = (qa or _qa_publicada)(vault, d, url)
    if not r.ok:
        ultimo = ultimo_respaldo(vault, datos.pais)
        copia = (f"pega en «{PANTALLA}» tu copia de seguridad ({ultimo}) y guarda" if ultimo else
                 f"pega en «{PANTALLA}» la copia que guardaste en el paso 2 y guarda (no hay ninguna en "
                 f"landing/{datos.pais}/respaldo/)")
        raise NoPublicable(f"la QA publicada no pasa: mira landing/{datos.pais}/{QA_PUBLICADA}. No la doy por "
                           f"publicada y no he registrado nada. Para dejar tu tienda como estaba, {copia}.")
    if tienda_nueva is not None:
        guardar_tienda(vault, datos.pais, tienda_nueva, ahora, "trovefy landing publicar --manual")
    estado = registrar_publicacion(vault, d, url, Hosting("impultienda", "pegada a mano por el usuario"), version,
                                   r, ahora, extra={"publicacion": "manual"})
    return PublicadaManual(url, estado, tienda_nueva)
