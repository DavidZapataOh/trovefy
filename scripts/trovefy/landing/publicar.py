"""Publicar la landing con relectura, QA publicada, `PRODUCTO.md` y estado (plan 18, Tarea 9).

Solo se publica lo que pasó la QA local y el `nativo` en su versión actual, con `validar` limpio. La ruta sale de
la sonda (`elegir_hosting`) y tiene que ser la misma con la que se preparó la landing.

- **Impultienda**: se pega `empaquetar_en_linea(...)` en «Diseño de tienda → Contenido» con el `Conductor`
  (respaldo previo en `landing/<PAIS>/respaldo/`), se guarda, se relee y se compara el SHA-256. Si Impultienda
  lo recortó o le quitó el script, se restaura lo que había y no se da por publicada.
- **Cloudflare**: la subida es guiada (la hace el usuario); aquí solo se verifica por HTTPS que la URL sirve la
  versión local.

Después, la QA publicada (`trovefy.landing.qa.ejecutar_qa(..., url=...)`). Solo si está en verde se escribe
`PRODUCTO.md` (`paises.<PAIS>.landing`, resolución 3, con `qa.utm_checkout.interceptado: true`, resolución 22)
y el estado pasa `producido → con_landing` con `trovefy.vault.producto.avanzar_estado` (resolución 1).
"""

from __future__ import annotations

import hashlib
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

from trovefy.landing.constantes import ESTADOS_LANDING
from trovefy.landing.entrada import (
    DatosLanding,
    EntradaInvalida,
    EstadoNoPermite,
    ruta_landing,
)
from trovefy.landing.hosting import (
    Capacidades,
    CapacidadNoMedida,
    Hosting,
    capacidades_vigentes,
    elegir_hosting,
    empaquetar_en_linea,
)
from trovefy.landing.panel import SERVICIO, Panel, preparar_mapa, respaldar, restaurar
from trovefy.landing.plantilla import leer_landing_yaml, pixel_js
from trovefy.landing.qa import comprobar_url_publicada
from trovefy.navegador import NavegadorError, sesion
from trovefy.producto.medios import escribir_medio
from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log
from trovefy.vault.producto import (
    actualizar_producto,
    avanzar_estado,
    estado_pais,
    secreto_en,
)

MAX_BYTES = 5 * 1024 * 1024  # tope de la página servida que se lee para verificar la versión
_TIMEOUT_S = 15
_VERSION = re.compile(r'data-tf-version="([0-9a-f]{12})"')
_APROBADO = "ok"  # resolución 17: el nativo responde ok|corregir


class NoPublicable(Exception):
    """Algo impide publicar o dar por publicada la landing; el mensaje dice qué."""


class HtmlRecortado(NoPublicable):
    """Impultienda no guardó el HTML tal cual (recorte, script quitado u otro cambio)."""


# --- puerta --------------------------------------------------------------------------------------


def _version_actual(vault: Path, datos: DatosLanding) -> str | None:
    version = leer_landing_yaml(vault, datos.p_id, datos.pais).get("version")
    return version if isinstance(version, str) and version else None


def _frontmatter(ruta: Path) -> dict | None:
    if ruta.is_symlink() or not ruta.is_file():
        return None
    try:
        meta, _ = frontmatter.leer(ruta)
    except (OSError, ValueError, UnicodeDecodeError, yaml.YAMLError):
        return None
    return meta if isinstance(meta, dict) else None


def listo_para_publicar(vault: Path, datos: DatosLanding) -> list[str]:
    """Motivos que impiden publicar (lista vacía = se puede): estado, QA local, `nativo`, `validar` y, en la ruta
    Cloudflare, un `TRACKING.md` roto. Que falte no bloquea (ruling B): `avisos_publicacion` lo dice y
    `landing.yaml` queda con `pixel: pendiente`."""
    from trovefy.landing.nativo import veredicto_vigente
    from trovefy.landing.validar import validar

    vault = Path(vault)
    motivos: list[str] = []
    if datos.estado not in ESTADOS_LANDING:
        motivos.append(f"{datos.pais} está en {datos.estado}: /landing publica desde producido")
    version = _version_actual(vault, datos)
    if version is None:
        return [*motivos, f"la landing de {datos.pais} no está guardada: trovefy landing guardar"]
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    qa = _frontmatter(raiz / "QA.md")
    if qa is None or qa.get("tipo") != "qa_landing":
        motivos.append("falta la QA local: trovefy landing qa")
    elif qa.get("version") != version:
        motivos.append(f"la QA es de otra versión ({qa.get('version')}; la actual es {version}): trovefy landing qa")
    elif qa.get("ok") is not True:
        motivos.append("la QA no está en verde: arregla lo que dice QA.md y vuelve a trovefy landing qa")
    nativo = veredicto_vigente(vault, datos.p_id, datos.pais)
    if nativo is None:
        motivos.append("falta el veredicto del nativo: trovefy landing texto → agente nativo → trovefy landing nativo")
    elif nativo[1] != version:
        motivos.append(f"el veredicto del nativo es de otra versión ({nativo[1]}): vuelve a pasarle el texto")
    elif nativo[0] != _APROBADO:
        motivos.append("el nativo pidió corregir: corrige y vuelve a pasarle el texto")
    r = validar(vault, datos)
    if r.fallos:
        motivos.append(f"validar: {len(r.fallos)} fallo(s), el primero: {r.fallos[0]}")
    if leer_landing_yaml(vault, datos.p_id, datos.pais).get("hosting") == "cloudflare":
        try:
            pixel_js(vault, datos)  # un TRACKING.md roto bloquea; que falte no (ruling B: avisos_publicacion)
        except EntradaInvalida as e:
            motivos.append(str(e))
    return motivos


def _sin_pixel(vault: Path, datos: DatosLanding) -> bool:
    """Ruta Cloudflare sin ``TRACKING.md``: se publica sin píxel (ruling B)."""
    if leer_landing_yaml(vault, datos.p_id, datos.pais).get("hosting") != "cloudflare":
        return False
    try:
        return pixel_js(vault, datos) is None
    except EntradaInvalida:
        return False  # roto: ya lo para listo_para_publicar


def avisos_publicacion(vault: Path, datos: DatosLanding) -> list[str]:
    """Lo que no impide publicar pero hay que decir (ruling B: Cloudflare sin píxel; ``landing.yaml`` queda
    con ``pixel: pendiente`` y el 19 y /listo lo exigen antes de anunciar)."""
    from trovefy.landing.validar import aviso_sin_pixel

    return [aviso_sin_pixel(datos.pais)] if _sin_pixel(Path(vault), datos) else []


# --- Impultienda ---------------------------------------------------------------------------------


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _motivo_distinto(pegado: str, releido: str) -> str:
    n, m = len(releido), len(pegado)
    if n < m and pegado.startswith(releido):
        return f"Impultienda recortó el HTML ({n} de {m} caracteres)"
    if re.search(r"<script\b", pegado, re.IGNORECASE) and not re.search(r"<script\b", releido, re.IGNORECASE):
        return "Impultienda quitó el script (utm.js): la landing no reenviaría los UTM"
    return f"Impultienda cambió el HTML al guardarlo ({n} de {m} caracteres, SHA-256 distinto)"


def publicar_impultienda(vault: Path, datos: DatosLanding, capacidades: Capacidades, *, mapa: dict | None = None,
                         abrir=None, visible: bool = True, dormir=time.sleep,
                         ahora: datetime | None = None) -> str:
    """Pega la landing en línea en «HTML completo de la tienda», guarda, relee y compara el SHA-256.

    Antes de tocar nada: dominio (si `dominio_propio`), límite de caracteres medido y mapa confirmado. Si lo
    releído no es lo pegado, restaura lo de antes y lanza `HtmlRecortado`. Devuelve la URL pública
    (`https://<dominio propio>/`; la QA publicada confirma el host final)."""
    vault = Path(vault)
    ahora = ahora or datetime.now(ZONA_NEGOCIO)
    if capacidades.dominio_propio:
        if not datos.dominio:
            raise NoPublicable("no medido: falta el dominio propio (paso 07 de config/arranque.yaml)")
        url = f"https://{datos.dominio}/"
    else:
        url = capacidades.tienda or datos.tienda
        if not url:
            raise NoPublicable("no medido: falta la URL de la tienda (trovefy landing sonda --tienda …)")
    fragmento = empaquetar_en_linea(ruta_landing(vault, datos.p_id, datos.pais))
    limite = capacidades.limite_caracteres
    if limite and len(fragmento) > limite:
        raise HtmlRecortado(f"la landing en línea ocupa {len(fragmento)} caracteres e Impultienda guarda como mucho "
                            f"{limite}: aligera imágenes o publica en Cloudflare. No he tocado nada.")
    m = preparar_mapa(vault, mapa)
    abrir = abrir or sesion
    original = respaldo = releido = None
    pegado = False
    try:
        with abrir(SERVICIO, visible=visible) as page:
            panel = Panel(page, m, dormir)
            panel.abrir()
            original = panel.leer()
            if original == fragmento:
                return url  # ya estaba publicada esta misma versión
            respaldo = respaldar(vault, datos.p_id, datos.pais, original, ahora)
            pegado = True
            releido = panel.guardar(fragmento)
    except BaseException:
        if pegado:
            restaurar(abrir, m, original, respaldo, visible=visible, dormir=dormir)
        raise
    if _sha(releido) != _sha(fragmento):
        motivo = _motivo_distinto(fragmento, releido)
        try:
            restaurar(abrir, m, original, respaldo, visible=visible, dormir=dormir)
        except NavegadorError as e:
            raise HtmlRecortado(f"{motivo}. Y además {e}") from e
        raise HtmlRecortado(f"{motivo}. He vuelto a dejar lo que había; no la doy por publicada.")
    rel = respaldo.relative_to(vault).as_posix()
    anadir_log(vault, "landing", f"{datos.p_id} {datos.pais}: pegada en Impultienda y releída igual", [rel],
               ahora=ahora)
    return url


# --- Cloudflare ----------------------------------------------------------------------------------


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _abrir_seguro(url: str, timeout: float = _TIMEOUT_S):
    if urlparse(url).scheme != "https":
        raise ValueError("solo https")
    return urllib.request.build_opener(_SinRedireccion).open(url, timeout=timeout)


def verificar_cloudflare(url: str, dir_landing: Path, abrir=_abrir_seguro) -> bool:
    """`True` si `url` (HTTPS, sin redirecciones a otro host, ≤ 5 MB) sirve el `data-tf-version` local."""
    host = urlparse(url).hostname
    if urlparse(url).scheme != "https" or not host:
        return False
    try:
        with abrir(url, timeout=_TIMEOUT_S) as r:
            final = getattr(r, "geturl", None)
            if callable(final) and urlparse(final()).hostname != host:
                return False
            datos = r.read(MAX_BYTES + 1)
    except (OSError, ValueError, urllib.error.URLError):
        return False
    if len(datos) > MAX_BYTES:
        return False
    try:
        local = _VERSION.search((Path(dir_landing) / "index.html").read_text(encoding="utf-8"))
    except OSError:
        return False
    servida = _VERSION.search(datos.decode("utf-8", errors="replace"))
    return bool(local and servida and local.group(1) == servida.group(1))


# --- registro ------------------------------------------------------------------------------------


def _bloque_qa(vault: Path, datos: DatosLanding, version: str, fecha: str) -> dict:
    """`landing.qa` (resolución 3) desde el frontmatter de `QA.md`; `utm_checkout` con `interceptado: true`
    (resolución 22: el checkout aún no existe; el recorrido del 19 lo sobrescribe)."""
    rel = f"landing/{datos.pais}/QA.md"
    meta = _frontmatter(ruta_landing(vault, datos.p_id, datos.pais) / "QA.md") or {}
    bloque: dict = {"archivo": rel, "fecha": str(meta.get("fecha") or fecha), "version": version}
    if isinstance(meta.get("movil_390"), dict):
        bloque["movil_390"] = meta["movil_390"]
    utm = meta.get("utm_checkout") if isinstance(meta.get("utm_checkout"), dict) else {}
    bloque["utm_checkout"] = {**utm, "interceptado": True, "fuente": rel}
    return bloque


def _escribir_landing_yaml(vault: Path, datos: DatosLanding, cambios: dict, que: str, ahora: datetime) -> None:
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    ruta = raiz / "landing.yaml"
    landing = {**leer_landing_yaml(vault, datos.p_id, datos.pais), **cambios}
    texto = yaml.safe_dump(landing, allow_unicode=True, sort_keys=False)
    if secreto_en(landing) or buscar_secreto(texto):
        raise EntradaInvalida("landing.yaml: aparece algo con forma de secreto; no se guarda")
    escribir_medio(ruta, texto.encode("utf-8"), base=vault)
    anadir_log(vault, "landing", f"{datos.p_id} {datos.pais}: {que}", [ruta.relative_to(vault).as_posix()],
               ahora=ahora)


def registrar_publicacion(vault: Path, datos: DatosLanding, url: str, hosting: Hosting, version: str, qa,
                          ahora: datetime) -> str:
    """Deja la publicación en `PRODUCTO.md` (fusionando: `paises.<PAIS>.landing` y una línea en el cuerpo), pasa
    `producido → con_landing` (un estado posterior no se toca) y anota `landing.yaml`. Devuelve el estado.

    `EstadoNoPermite` (sin escribir nada) si el país no está en `producido` o después; `NoPublicable` si la QA
    publicada no está en verde."""
    vault = Path(vault)
    estado = estado_pais(vault, datos.p_id, datos.pais)
    if estado not in ESTADOS_LANDING:
        raise EstadoNoPermite(f"{datos.pais} está en {estado or 'sin estado'}: la landing se publica desde producido")
    if not getattr(qa, "ok", False):
        raise NoPublicable(f"la QA publicada no está en verde: mira landing/{datos.pais}/QA.md")
    fecha = ahora.astimezone(ZONA_NEGOCIO).date().isoformat()
    landing = {"url": url, "hosting": hosting.ruta, "version": version, "fecha": fecha,
               "qa": _bloque_qa(vault, datos, version, fecha)}
    linea = f"- Landing {datos.pais} v{version}: {url} ({fecha}, {hosting.ruta})"
    actualizar_producto(vault, datos.p_id, {"paises": {datos.pais: {"landing": landing}}}, [linea], "landing", ahora)
    if estado == "producido":
        avanzar_estado(vault, datos.p_id, datos.pais, "producido", "con_landing",
                       [f"landing/{datos.pais}/QA.md", url], "landing", ahora)
        estado = "con_landing"
    cambios = {"url": url, "publicada": fecha, "version": version, "hosting": hosting.ruta}
    if hosting.ruta == "cloudflare":  # ruling B: sin TRACKING.md, publicada sin píxel y pendiente de él
        cambios["pixel"] = "pendiente" if _sin_pixel(vault, datos) else "activo"
    _escribir_landing_yaml(vault, datos, cambios, f"publicada en {url} ({hosting.ruta})", ahora)
    return estado


# --- todo junto ----------------------------------------------------------------------------------


def _qa_publicada(vault: Path, datos: DatosLanding, url: str):
    from trovefy.landing.qa import ejecutar_qa

    return ejecutar_qa(vault, datos, url)


def _slug(p_id: str) -> str:
    return re.sub(r"^p-\d{4}-", "", p_id)


def publicar(vault: Path, datos: DatosLanding, url_cloudflare: str | None = None, *, qa=None, publicar_imp=None,
             verificar=None, ahora: datetime | None = None) -> str:
    """Publica (Impultienda) o verifica la subida (Cloudflare), pasa la QA publicada y, si está en verde, lo
    registra. Devuelve la URL. `NoPublicable` con los motivos si algo lo impide; la URL ya publicada pero con la
    QA en rojo queda en `landing.yaml` con `publicada: null` y `QA.md` dice por qué."""
    vault = Path(vault)
    ahora = ahora or datetime.now(ZONA_NEGOCIO)
    motivos = listo_para_publicar(vault, datos)
    if motivos:
        raise NoPublicable("No se publica: " + "; ".join(motivos))
    landing = leer_landing_yaml(vault, datos.p_id, datos.pais)
    version = landing["version"]
    c = capacidades_vigentes(vault)
    try:
        h = elegir_hosting(c)
    except CapacidadNoMedida as e:
        raise NoPublicable(str(e)) from None
    if landing.get("hosting") != h.ruta:
        raise NoPublicable(f"la landing se preparó para {landing.get('hosting')} y la sonda dice {h.ruta} ({h.motivo}): "
                           "trovefy landing preparar --rehacer, guardar, validar, nativo y qa")
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    if h.ruta == "impultienda":
        if url_cloudflare:
            raise NoPublicable("--url es solo para la ruta Cloudflare; la sonda dice Impultienda")
        url = (publicar_imp or publicar_impultienda)(vault, datos, c, ahora=ahora)
    else:
        if not datos.dominio:
            raise NoPublicable("no medido: falta el dominio propio (paso 07 de config/arranque.yaml)")
        sub = f"{datos.pais.lower()}.{datos.dominio}"
        if not url_cloudflare:
            raise NoPublicable(f"ruta Cloudflare: sube la carpeta landing/{datos.pais}/ a Cloudflare Pages (proyecto "
                               f"{_slug(datos.p_id)}-{datos.pais.lower()}), conecta {sub} y vuelve con "
                               f"--url https://{sub}/")
        try:  # la misma regla que la QA publicada (I2): https, sin usuario, puerto 443, dominio o <pais>.<dominio>
            comprobar_url_publicada(datos, "cloudflare", url_cloudflare)
        except EntradaInvalida:
            raise NoPublicable(f"«{url_cloudflare}» no es https de tu dominio ({datos.dominio}): usa "
                               f"https://{sub}/") from None
        if not (verificar or verificar_cloudflare)(url_cloudflare, raiz):
            raise NoPublicable(f"{url_cloudflare} no sirve la versión {version} (o redirige a otro sitio): revisa la "
                               "subida a Cloudflare Pages y vuelve a lanzar")
        url = url_cloudflare
    _escribir_landing_yaml(vault, datos, {"url": url, "publicada": None}, f"subida a {url}; falta la QA publicada",
                           ahora)
    r = (qa or _qa_publicada)(vault, datos, url)
    if not r.ok:
        raise NoPublicable(f"la QA publicada no pasa: mira landing/{datos.pais}/QA.md (la URL queda en landing.yaml "
                           "sin dar por publicada)")
    registrar_publicacion(vault, datos, url, h, version, r, ahora)
    return url
