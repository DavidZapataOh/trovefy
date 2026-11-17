"""Publicar la landing con relectura, QA publicada, `PRODUCTO.md` y estado (plan 18, Tarea 9).

Solo se publica lo que pasó la QA local y el `nativo` en su versión actual, con `validar` limpio. La ruta sale de
la sonda (`elegir_hosting`) y tiene que ser la misma con la que se preparó la landing.

- **Impultienda**: se pega `empaquetar_en_linea(...)` en «Diseño de tienda → Contenido» con el `Conductor`
  (respaldo previo en `landing/<PAIS>/respaldo/`), se guarda, se relee y se compara el SHA-256. Si Impultienda
  lo recortó o le quitó el script, se restaura lo que había y no se da por publicada; el mensaje da la salida:
  `trovefy landing preparar … --hosting cloudflare` (I1).
- **Cloudflare**: la subida es guiada (la hace el usuario) desde `landing/<PAIS>/publicar/`, una carpeta limpia
  con solo `index.html` y `assets/` (ni `respaldo/`, ni `landing.yaml`, `QA.md`, `nativo.md` o `qa/`); aquí solo
  se verifica por HTTPS que la URL sirve la versión local.

La ruta: una landing preparada para Cloudflare se publica en Cloudflare diga lo que diga la sonda (Cloudflare no
depende de nada de Impultienda: es la salida cuando Impultienda no sirve, I1); una preparada para Impultienda
solo si la sonda dice Impultienda.

Después, la QA publicada (`trovefy.landing.qa.ejecutar_qa(..., url=...)`, en `QA-publicada.md`, aparte de la
`QA.md` local). Solo si está en verde se escribe `PRODUCTO.md` (`paises.<PAIS>.landing`, resolución 3, con
`qa.utm_checkout.interceptado: true`, resolución 22) y el estado pasa `producido → con_landing` con
`trovefy.vault.producto.avanzar_estado` (resolución 1).

Desde que se pega hasta que acaba la QA publicada, cualquier excepción (Ctrl-C, una entrada inválida, un fallo
inesperado) devuelve lo de antes a Impultienda como una QA en rojo (F2-2), dice dónde está el respaldo y se
vuelve a lanzar. Devolver lo de antes nunca pega a ciegas (`trovefy.landing.panel.restaurar`, F2-1) y deja en
`landing.yaml` la URL y la versión publicadas que había (las de `PRODUCTO.md`).
"""

from __future__ import annotations

import re
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
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
    parar_si_sonda_colgada,
)
from trovefy.landing.panel import (
    SERVICIO,
    Panel,
    parar_si_vacio,
    preparar_mapa,
    respaldar,
    restaurar,
    restaurar_desde_respaldo,
    sha_texto,
)
from trovefy.landing.plantilla import (
    leer_landing_yaml,
    manifiesto_landing,
    pixel_js,
    version_guardada,
)
from trovefy.landing.qa import QA_LOCAL, QA_PUBLICADA, comprobar_url_publicada
from trovefy.navegador import NavegadorError, sesion
from trovefy.producto.medios import carpeta_segura, escribir_medio
from trovefy.secretos import buscar_secreto
from trovefy.tienda.conductor import Parada
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
    version = version_guardada(vault, datos.p_id, datos.pais, exigir=False)
    if version is None:
        return [*motivos, f"la landing de {datos.pais} no está guardada: trovefy landing guardar"]
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    qa = _frontmatter(raiz / QA_LOCAL)  # la local: la publicada va en QA-publicada.md y no cuenta aquí (M2)
    try:
        manifiesto = manifiesto_landing(raiz)
    except (OSError, ValueError) as e:
        manifiesto = None
        motivos.append(f"landing/{datos.pais}: {e}")
    if qa is None or qa.get("tipo") != "qa_landing" or qa.get("url") is not None:
        motivos.append("falta la QA local: trovefy landing qa")
    elif qa.get("version") != version:
        motivos.append(f"la QA es de otra versión ({qa.get('version')}; la actual es {version}): trovefy landing qa")
    elif manifiesto is not None and qa.get("manifiesto") != manifiesto:  # I-6: CSS, js, imágenes…
        motivos.append("los archivos de la landing cambiaron después de la QA (estilo.css, utm.js, pixel.js o "
                       "alguna imagen de assets/): vuelve a trovefy landing qa")
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


def orden_cloudflare(datos: DatosLanding) -> str:
    """La salida cuando Impultienda no guarda la landing entera (I1): prepararla para Cloudflare y repetir."""
    base = f"--producto {datos.p_id} --pais {datos.pais}"
    return (f"publícala en Cloudflare: trovefy landing preparar {base} --hosting cloudflare (si ya estaba publicada, "
            f"con --rehacer), corrige en el borrador el href de a[data-tf-checkout] si validar lo pide, y después "
            f"guardar, validar, nativo, qa y trovefy landing publicar {base}")


def _motivo_distinto(pegado: str, releido: str) -> str:
    n, m = len(releido), len(pegado)
    sin_scripts = re.sub(r"<script\b.*?</script>", "", pegado, flags=re.IGNORECASE | re.DOTALL)
    if releido.strip() == sin_scripts.strip() != pegado.strip():  # va al final: quitarlo parece un recorte
        return "Impultienda quitó el script (utm.js): la landing no reenviaría los UTM"
    if n < m and pegado.startswith(releido):
        return f"Impultienda recortó el HTML ({n} de {m} caracteres)"
    if re.search(r"<script\b", pegado, re.IGNORECASE) and not re.search(r"<script\b", releido, re.IGNORECASE):
        return "Impultienda quitó el script (utm.js): la landing no reenviaría los UTM"
    return f"Impultienda cambió el HTML al guardarlo ({n} de {m} caracteres, SHA-256 distinto)"


@dataclass(frozen=True)
class Pegada:
    """Resultado de `publicar_impultienda`: la URL pública, el respaldo de lo que había (None si la misma
    versión ya estaba en el campo y no se pegó nada) y lo que se pegó. Con el respaldo, una QA publicada en rojo
    lo devuelve, solo si el campo sigue teniendo lo pegado (F2-1)."""

    url: str
    respaldo: Path | None
    pegado: str | None = None


def publicar_impultienda(vault: Path, datos: DatosLanding, capacidades: Capacidades, *, mapa: dict | None = None,
                         abrir=None, visible: bool = True, dormir=time.sleep, ahora: datetime | None = None,
                         campo_vacio: bool = False) -> Pegada:
    """Pega la landing en línea en «HTML completo de la tienda», guarda, relee y compara el SHA-256.

    Antes de tocar nada: dominio propio (la ruta Impultienda solo existe con él: `elegir_hosting` manda a
    Cloudflare sin dominio propio, M8), límite de caracteres medido, mapa confirmado, que el campo no se lea
    vacío (salvo `campo_vacio`, I3) y que no tenga restos de una sonda (I-5). Si lo releído no es lo pegado, o
    algo falla tras pegar (una parada, Ctrl-C), restaura lo de antes. Devuelve la URL pública
    (`https://<dominio propio>/`; la QA publicada confirma el host final) y el respaldo."""
    vault = Path(vault)
    ahora = ahora or datetime.now(ZONA_NEGOCIO)
    if capacidades.dominio_propio is not True:
        raise NoPublicable("la ruta Impultienda necesita tu dominio propio conectado a la tienda (la sonda dice "
                           f"dominio propio: {capacidades.dominio_propio}); sin él, {orden_cloudflare(datos)}")
    if not datos.dominio:
        raise NoPublicable("no medido: falta el dominio propio (paso 07 de config/arranque.yaml)")
    url = f"https://{datos.dominio}/"
    fragmento = empaquetar_en_linea(ruta_landing(vault, datos.p_id, datos.pais))
    limite = capacidades.limite_caracteres
    if limite and len(fragmento) > limite:
        raise HtmlRecortado(f"la landing en línea ocupa {len(fragmento)} caracteres e Impultienda guarda como mucho "
                            f"{limite}. No he tocado nada. Aligera las imágenes o {orden_cloudflare(datos)}.")
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
                return Pegada(url, None)  # ya estaba publicada esta misma versión: no se pega nada
            parar_si_vacio(original, campo_vacio)  # I3: vacío solo con la palabra del usuario
            parar_si_sonda_colgada(vault, datos.pais, original)  # I-5: no se respalda una sonda
            respaldo = respaldar(vault, datos.p_id, datos.pais, original, ahora)
            pegado = True
            releido = panel.guardar(fragmento)
    except BaseException:
        if pegado:
            try:
                restaurar(abrir, m, original, respaldo, esperado=(fragmento,), vault=vault, visible=visible,
                          dormir=dormir, ahora=ahora)
            except Exception as e:  # noqa: BLE001 - se dice y sigue la excepción de verdad
                print(f"Y además: {e}", file=sys.stderr)
        raise
    if sha_texto(releido) != sha_texto(fragmento):
        motivo = _motivo_distinto(fragmento, releido)
        try:
            restaurar(abrir, m, original, respaldo, esperado=(fragmento, releido), vault=vault, visible=visible,
                      dormir=dormir, ahora=ahora)
        except NavegadorError as e:
            raise HtmlRecortado(f"{motivo}. Y además {e}. Cuando esté, {orden_cloudflare(datos)}") from e
        raise HtmlRecortado(f"{motivo}. He vuelto a dejar lo que había; no la doy por publicada. Para publicarla, "
                            f"{orden_cloudflare(datos)}.")
    rel = respaldo.relative_to(vault).as_posix()
    anadir_log(vault, "landing", f"{datos.p_id} {datos.pais}: pegada en Impultienda y releída igual", [rel],
               ahora=ahora)
    return Pegada(url, respaldo, fragmento)


# --- Cloudflare ----------------------------------------------------------------------------------

CARPETA_SUBIDA = "publicar"


def preparar_subida(vault: Path, datos: DatosLanding) -> Path:
    """Escribe `landing/<PAIS>/publicar/` desde cero con **solo** `index.html` y `assets/` (lo que se sube a
    Cloudflare Pages): ni `respaldo/` (el contenido de Impultienda del usuario), ni `landing.yaml`, `QA.md`,
    `nativo.md` o `qa/`. Devuelve la carpeta. `ValueError` con un enlace simbólico."""
    vault = Path(vault)
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    manifiesto_landing(raiz)  # enlaces o subcarpetas en assets/: ValueError
    carpeta = raiz / CARPETA_SUBIDA
    if carpeta.is_symlink():
        raise ValueError(f"landing/{datos.pais}/{CARPETA_SUBIDA} es un enlace simbólico: no se usa")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta_segura(vault, carpeta / "assets", crear=True)
    escribir_medio(carpeta / "index.html", (raiz / "index.html").read_bytes(), base=vault)
    assets = raiz / "assets"
    if assets.is_dir():
        for ruta in sorted(assets.iterdir()):
            escribir_medio(carpeta / "assets" / ruta.name, ruta.read_bytes(), base=vault)
    return carpeta


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _abrir_seguro(url: str, timeout: float = _TIMEOUT_S, *, contexto: ssl.SSLContext | None = None):
    """GET https sin seguir redirecciones (un 3xx es `HTTPError`). `contexto`: el TLS (por defecto, el del
    sistema; los tests de integración pasan uno con su certificado de 127.0.0.1)."""
    if urlparse(url).scheme != "https":
        raise ValueError("solo https")
    https = urllib.request.HTTPSHandler(context=contexto or ssl.create_default_context())
    # Impultienda va detrás de Cloudflare, que responde 403 al agente por defecto de urllib.
    peticion = urllib.request.Request(url, headers={"User-Agent": AGENTE_NAVEGADOR})
    return urllib.request.build_opener(_SinRedireccion, https).open(peticion, timeout=timeout)


AGENTE_NAVEGADOR = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


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


def _dia(valor: object, defecto: str) -> str:
    """`AAAA-MM-DD` de la fecha de la QA (M3): un `datetime` (o su texto ISO) con zona pasa a la de negocio;
    algo que no es fecha, `defecto`."""
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.strip())
        except ValueError:
            return defecto
    if isinstance(valor, datetime):
        return (valor.astimezone(ZONA_NEGOCIO) if valor.tzinfo else valor).date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    return defecto


def _bloque_qa(vault: Path, datos: DatosLanding, version: str, url: str, fecha: str) -> dict:
    """`landing.qa` (resolución 3) desde el frontmatter de `QA-publicada.md`, la QA publicada de esta versión y
    esta URL (L-5; si no lo es, `NoPublicable`), con su `fecha` como día (M3); `utm_checkout` con
    `interceptado: true` (resolución 22: el checkout aún no existe; el recorrido del 19 lo sobrescribe)."""
    rel = f"landing/{datos.pais}/{QA_PUBLICADA}"
    meta = _frontmatter(ruta_landing(vault, datos.p_id, datos.pais) / QA_PUBLICADA) or {}
    if meta.get("tipo") != "qa_landing" or meta.get("version") != version or meta.get("url") != url:
        raise NoPublicable(f"{rel} no es la QA publicada de la versión {version} en {url} (es de "
                           f"{meta.get('version') or '¿?'} en {meta.get('url') or 'local'}): vuelve a "
                           "trovefy landing publicar")
    bloque: dict = {"archivo": rel, "fecha": _dia(meta.get("fecha"), fecha), "version": version}
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
                          ahora: datetime, extra: dict | None = None) -> str:
    """Deja la publicación en `PRODUCTO.md` (fusionando: `paises.<PAIS>.landing` y una línea en el cuerpo), pasa
    `producido → con_landing` (un estado posterior no se toca) y anota `landing.yaml` (con `extra`, p. ej.
    `{"publicacion": "manual"}` en el pegado manual). Devuelve el estado.

    `EstadoNoPermite` (sin escribir nada) si el país no está en `producido` o después; `NoPublicable` si la QA
    publicada no está en verde."""
    vault = Path(vault)
    estado = estado_pais(vault, datos.p_id, datos.pais)
    if estado not in ESTADOS_LANDING:
        raise EstadoNoPermite(f"{datos.pais} está en {estado or 'sin estado'}: la landing se publica desde producido")
    if not getattr(qa, "ok", False):
        raise NoPublicable(f"la QA publicada no está en verde: mira landing/{datos.pais}/{QA_PUBLICADA}")
    fecha = ahora.astimezone(ZONA_NEGOCIO).date().isoformat()
    landing = {"url": url, "hosting": hosting.ruta, "version": version, "fecha": fecha,
               "qa": _bloque_qa(vault, datos, version, url, fecha)}
    linea = f"- Landing {datos.pais} v{version}: {url} ({fecha}, {hosting.ruta})"
    if estado == "producido":  # L-5: primero el estado (avanzar_estado relee y para si cambió entretanto)
        avanzar_estado(vault, datos.p_id, datos.pais, "producido", "con_landing",
                       [f"landing/{datos.pais}/{QA_PUBLICADA}", url], "landing", ahora)
        estado = "con_landing"
    actualizar_producto(vault, datos.p_id, {"paises": {datos.pais: {"landing": landing}}}, [linea], "landing", ahora)
    cambios = {"url": url, "publicada": fecha, "version": version, "version_publicada": version,
               "hosting": hosting.ruta}
    if hosting.ruta == "cloudflare":  # ruling B: sin TRACKING.md, publicada sin píxel y pendiente de él
        cambios["pixel"] = "pendiente" if _sin_pixel(vault, datos) else "activo"
    cambios.update(extra or {})
    _escribir_landing_yaml(vault, datos, cambios, f"publicada en {url} ({hosting.ruta})", ahora)
    return estado


# --- todo junto ----------------------------------------------------------------------------------


def _qa_publicada(vault: Path, datos: DatosLanding, url: str):
    from trovefy.landing.qa import ejecutar_qa

    return ejecutar_qa(vault, datos, url)


def _slug(p_id: str) -> str:
    return re.sub(r"^p-\d{4}-", "", p_id)


_PUBLICADA = ("url", "publicada", "version_publicada")  # lo de landing.yaml que dice qué está publicado


def _qa_en_rojo(vault: Path, datos: DatosLanding, pegada: Pegada | None, restaurar_imp, previo: dict,
                ahora: datetime) -> str:
    """Tras una QA publicada en rojo (o una excepción entre la pegada y el final de la QA): en Impultienda, si
    se pegó algo, vuelve a dejar lo de antes desde el respaldo (ruling L-4), solo si el campo sigue teniendo lo
    pegado (F2-1), y deja en `landing.yaml` la URL, la fecha y la versión publicadas de antes (`previo`; las de
    `PRODUCTO.md`). Devuelve qué pasó, para el mensaje, con la ruta completa del respaldo."""
    if pegada is None:  # Cloudflare: lo sube y lo quita el usuario
        return "la URL queda en landing.yaml sin dar por publicada"
    if pegada.respaldo is None:
        return "la misma versión ya estaba en Impultienda (no se pegó nada, no hay nada que devolver)"
    try:
        (restaurar_imp or restaurar_desde_respaldo)(vault, pegada.respaldo, esperado=pegada.pegado or (),
                                                    ahora=ahora)
    except (NavegadorError, Parada, ValueError) as e:
        return (f"NO he devuelto lo de antes a Impultienda ({e}). Lo que tenías está en {pegada.respaldo}: pégalo "
                "tú en «Diseño de tienda → Contenido»")
    antes = {k: previo.get(k) for k in _PUBLICADA if k in previo or k != "version_publicada"}
    _escribir_landing_yaml(vault, datos, antes,
                           f"restaurado lo de antes en Impultienda desde {pegada.respaldo.relative_to(vault).as_posix()}",
                           ahora)
    sigue = (f"sigue publicada la anterior ({previo['url']})" if previo.get("url") and previo.get("publicada")
             else "la landing no queda publicada")
    return f"He vuelto a dejar en Impultienda lo que había (desde {pegada.respaldo}); {sigue}"


def _ruta(vault: Path, landing: dict) -> tuple[Hosting, Capacidades | None]:
    """La ruta de publicación (I1). Cloudflare, si la landing se preparó para Cloudflare, sea cual sea la sonda
    (o aunque no la haya): no depende de nada de Impultienda. Impultienda solo si la sonda dice Impultienda
    (`elegir_hosting`); con algo «no medido» o si dice Cloudflare, `NoPublicable`."""
    if landing.get("hosting") == "cloudflare":
        try:
            h = elegir_hosting(capacidades_vigentes(vault))
        except (CapacidadNoMedida, ValueError):
            h = None
        if h is None or h.ruta != "cloudflare":
            h = Hosting("cloudflare", "preparada para Cloudflare (no depende de lo que admita Impultienda)")
        return h, None
    try:
        c = capacidades_vigentes(vault)
        h = elegir_hosting(c)
    except (CapacidadNoMedida, ValueError) as e:
        raise NoPublicable(f"{e}; o pégala tú en tu panel, sin sonda: trovefy landing publicar … --manual") from None
    if landing.get("hosting") != h.ruta:
        raise NoPublicable(f"la landing se preparó para {landing.get('hosting')} y la sonda dice {h.ruta} ({h.motivo}): "
                           "trovefy landing preparar --rehacer, guardar, validar, nativo y qa")
    return h, c


def publicar(vault: Path, datos: DatosLanding, url_cloudflare: str | None = None, *, qa=None, publicar_imp=None,
             verificar=None, restaurar_imp=None, ahora: datetime | None = None, campo_vacio: bool = False) -> str:
    """Publica (Impultienda) o verifica la subida (Cloudflare), pasa la QA publicada y, si está en verde, lo
    registra. Devuelve la URL. `NoPublicable` con los motivos si algo lo impide. Con la QA en rojo: en
    Impultienda se devuelve lo que había desde el respaldo (L-4) y se dice; en Cloudflare la URL queda en
    `landing.yaml` con `publicada: null`. `QA-publicada.md` dice por qué. `campo_vacio`: el `--campo-vacio`
    del usuario (I3)."""
    vault = Path(vault)
    ahora = ahora or datetime.now(ZONA_NEGOCIO)
    motivos = listo_para_publicar(vault, datos)
    if motivos:
        raise NoPublicable("No se publica: " + "; ".join(motivos))
    landing = leer_landing_yaml(vault, datos.p_id, datos.pais)
    version = landing["version"]
    h, c = _ruta(vault, landing)
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    if h.ruta == "impultienda" and url_cloudflare:
        raise NoPublicable("--url es solo para la ruta Cloudflare; la sonda dice Impultienda")
    if h.ruta == "cloudflare":
        if not datos.dominio:
            raise NoPublicable("no medido: falta el dominio propio (paso 07 de config/arranque.yaml)")
        sub = f"{datos.pais.lower()}.{datos.dominio}"
        if not url_cloudflare:
            carpeta = preparar_subida(vault, datos)
            raise NoPublicable(f"ruta Cloudflare: sube a Cloudflare Pages (proyecto {_slug(datos.p_id)}-"
                               f"{datos.pais.lower()}) el contenido de {carpeta} (solo index.html y assets/), "
                               f"conecta {sub} y vuelve con --url https://{sub}/")
        try:  # la misma regla que la QA publicada (I2): https, sin usuario, puerto 443, dominio o <pais>.<dominio>
            comprobar_url_publicada(datos, "cloudflare", url_cloudflare)
        except EntradaInvalida:
            raise NoPublicable(f"«{url_cloudflare}» no es https de tu dominio ({datos.dominio}): usa "
                               f"https://{sub}/") from None
        if not (verificar or verificar_cloudflare)(url_cloudflare, raiz):
            raise NoPublicable(f"{url_cloudflare} no sirve la versión {version} (o redirige a otro sitio): revisa la "
                               "subida a Cloudflare Pages y vuelve a lanzar")
    pegada = None
    try:  # F2-2: de la pegada al final de la QA publicada, cualquier excepción devuelve lo de antes
        if h.ruta == "impultienda":
            pegada = (publicar_imp or publicar_impultienda)(vault, datos, c, ahora=ahora, campo_vacio=campo_vacio)
            url = pegada.url
        else:
            url = url_cloudflare
        _escribir_landing_yaml(vault, datos, {"url": url, "publicada": None},
                               f"subida a {url}; falta la QA publicada", ahora)
        r = (qa or _qa_publicada)(vault, datos, url)
    except BaseException as exc:
        if pegada is not None and pegada.respaldo is not None:
            que = _qa_en_rojo(vault, datos, pegada, restaurar_imp, landing, ahora)
            print(f"La publicación se cortó ({type(exc).__name__}) antes de acabar la QA publicada. {que}. "
                  f"Respaldo: {pegada.respaldo}", file=sys.stderr)
        raise
    if not r.ok:
        que = _qa_en_rojo(vault, datos, pegada, restaurar_imp, landing, ahora)
        raise NoPublicable(f"la QA publicada no pasa: mira landing/{datos.pais}/{QA_PUBLICADA}. {que}.")
    registrar_publicacion(vault, datos, url, h, version, r, ahora)
    return url
