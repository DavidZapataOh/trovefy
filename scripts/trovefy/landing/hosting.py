"""Capacidades de Impultienda (la sonda de P-05), elección de hosting y empaquetado en línea (plan 18, Tarea 8).

Impultienda solo aloja la landing si se comprueba que ejecuta el script UTM, respeta estilos y título, no añade
marco y sirve en el dominio propio. Si algo de eso falla → Cloudflare Pages; si algo está «no medido», no se
decide: primero `trovefy landing sonda`.

La sonda pega un HTML de prueba propio en «Diseño de tienda → Contenido», lo guarda, mira la tienda pública sin
sesión y **restaura** lo que había (guardado antes en `landing/<PAIS>/respaldo/`). Todos los clics, con el
`Conductor` (resolución 21). La evidencia (`config/evidencia/p05-impultienda-<fecha>.json`) solo lleva las
capacidades: ni cookies ni HTML de la tienda.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from trovefy.config import mercados
from trovefy.config.yaml_config import cargar_yaml
from trovefy.landing.constantes import HOSTS_META, casa_host
from trovefy.landing.panel import (
    MAPA_IMPULTIENDA,
    PANTALLA,
    SERVICIO,
    Panel,
    mapa_impultienda,
    preparar_mapa,
    respaldar,
    restaurar,
    ultimo_respaldo,
)
from trovefy.landing.plantilla import UTM_JS, tienda_valida
from trovefy.mapa import origen
from trovefy.navegador import NavegadorError, esperar_entre_navegaciones, sesion
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico

__all__ = [
    "CAPACIDADES_FASE0", "HTML_SONDA", "MAPA_IMPULTIENDA", "CapacidadNoMedida", "Capacidades", "Hosting",
    "capacidades_vigentes", "elegir_hosting", "empaquetar_en_linea", "guardar_tienda", "mapa_impultienda",
    "sondear",
]


@dataclass(frozen=True)
class Capacidades:
    """Lo que Impultienda admite en «HTML completo de la tienda». `None` = no medido."""

    html_propio: bool | None
    script: bool | None
    estilos: bool | None
    titulo_propio: bool | None
    sin_marco: bool | None
    dominio_propio: bool | None
    limite_caracteres: int | None
    tienda: str | None
    url_pantalla: str | None
    fecha: str
    fuente: str
    # Hosts que cargó la tienda pública en la sonda (sin los de Meta): la QA publicada en Impultienda los da
    # como AVISO, no como FALLA (ruling I-4). Una evidencia anterior sin el campo vale como «ninguno».
    hosts_tienda: tuple[str, ...] = ()


CAPACIDADES_FASE0 = Capacidades(
    html_propio=True, script=None, estilos=None, titulo_propio=None, sin_marco=None, dominio_propio=None,
    limite_caracteres=None, tienda=None, url_pantalla=None, fecha="2026-11-12",
    fuente="config/evidencia/09-captura-usuario-2026-11-12.png",
)

# Fragmento propio: lo que se mide va delante; el relleno (un comentario) al final, para que un recorte deje
# intacto lo medido y se vea por el largo releído.
HTML_SONDA = (
    "<style>#tf-sonda{color:rgb(1,2,3)}</style><title>tf-sonda</title><div id=\"tf-sonda\">tf-sonda</div>"
    "<script>document.getElementById(\"tf-sonda\").dataset.ok=\"1\"</script>"
    "<!-- " + "relleno-tf-sonda " * 12_500 + "-->"
)
_PREFIJO_SONDA_MIN = 16  # «<style>#tf-sonda»: un prefijo más corto no lleva ninguna marca propia
COLOR_SONDA = "rgb(1, 2, 3)"


def es_sonda_colgada(contenido: str) -> bool:
    """¿El campo tiene restos de una sonda que no se restauró? (I-5) Sus marcas o un recorte suyo."""
    if not isinstance(contenido, str):
        return False
    if 'id="tf-sonda"' in contenido or "relleno-tf-sonda" in contenido:
        return True
    return len(contenido) >= _PREFIJO_SONDA_MIN and HTML_SONDA.startswith(contenido)


def parar_si_sonda_colgada(vault: Path, pais: str, contenido: str) -> None:
    """`NavegadorError` (sin tocar nada) si el campo tiene restos de una sonda: que el usuario pegue antes el
    último respaldo de la tienda de `pais` (de cualquier producto, F2-3), con su ruta completa."""
    if not es_sonda_colgada(contenido):
        return
    ultimo = ultimo_respaldo(vault, pais)
    donde = (f"pega tú el último respaldo ({ultimo})" if ultimo else
             f"no hay respaldos en productos/*/landing/{pais}/respaldo/: pega tú lo que tenías")
    raise NavegadorError(f"el campo «HTML completo de la tienda» tiene restos de una sonda anterior: {donde} en "
                         "«Diseño de tienda → Contenido» y vuelve a lanzar. No he tocado nada.")
FUERA_MAX = 40  # caracteres visibles fuera de #tf-sonda que aún no son «marco» (un aviso de cookies corto)

_EVIDENCIA = re.compile(r"p05-impultienda-([0-9]{4}-[0-9]{2}-[0-9]{2})\.json")
_HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")
_BOOLEANAS = ("html_propio", "script", "estilos", "titulo_propio", "sin_marco", "dominio_propio")
_MOTIVOS_FALSE = {
    "html_propio": "Impultienda no sirve el HTML propio",
    "script": "Impultienda no ejecuta el script UTM",
    "estilos": "Impultienda no respeta los estilos propios",
    "titulo_propio": "Impultienda no respeta el título propio",
    "sin_marco": "Impultienda añade un marco (cabecera, pie o iframe) alrededor",
    "dominio_propio": "Impultienda no sirve en dominio propio",
}


class CapacidadNoMedida(Exception):
    """Alguna capacidad necesaria está «no medido»: no se elige hosting (primero la sonda)."""


@dataclass(frozen=True)
class Hosting:
    ruta: Literal["impultienda", "cloudflare"]
    motivo: str


# --- capacidades ---------------------------------------------------------------------------------------


def _desde_json(datos: object, nombre: str) -> Capacidades:
    if not isinstance(datos, dict):
        raise ValueError(f"{nombre}: no es un objeto JSON")  # noqa: TRY004 - dato del vault
    valores = {}
    for f in fields(Capacidades):
        v = datos.get(f.name)
        if f.name == "hosts_tienda":
            v = [] if v is None else v
            if not isinstance(v, list) or not all(isinstance(h, str) and _HOST.fullmatch(h) for h in v):
                raise ValueError(f"{nombre}: «hosts_tienda» tiene un valor que no entiendo ({v!r})")
            valores[f.name] = tuple(v)
            continue
        if f.name in _BOOLEANAS:
            ok = v is None or isinstance(v, bool)
        elif f.name == "limite_caracteres":
            ok = v is None or (isinstance(v, int) and not isinstance(v, bool) and v > 0)
        elif f.name in ("fecha", "fuente"):
            ok = isinstance(v, str) and bool(v)
        else:
            ok = v is None or isinstance(v, str)
        if not ok:
            raise ValueError(f"{nombre}: «{f.name}» tiene un valor que no entiendo ({v!r})")
        valores[f.name] = v
    return Capacidades(**valores)


def capacidades_vigentes(vault: Path, *, hoy: date | None = None) -> Capacidades:
    """Las de la evidencia más reciente `config/evidencia/p05-impultienda-AAAA-MM-DD.json` con fecha no posterior
    a `hoy` (por defecto, hoy en la zona de negocio; una fechada en el futuro no se cree, L-3); si no hay
    ninguna, `CAPACIDADES_FASE0`. Una evidencia rota es `ValueError` (nunca se cae a una anterior en silencio)."""
    hoy_iso = (hoy or datetime.now(ZONA_NEGOCIO).date()).isoformat()
    carpeta = Path(vault) / "config" / "evidencia"
    candidatas = sorted((m.group(1), p) for p in carpeta.glob("p05-impultienda-*.json")
                        if (m := _EVIDENCIA.fullmatch(p.name)) and not p.is_symlink() and m.group(1) <= hoy_iso)
    if not candidatas:
        return CAPACIDADES_FASE0
    ruta = candidatas[-1][1]
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"config/evidencia/{ruta.name} no se puede leer ({type(exc).__name__}): rehaz la sonda") from None
    return _desde_json(datos, f"config/evidencia/{ruta.name}")


def elegir_hosting(c: Capacidades) -> Hosting:
    """Cloudflare si algo es `False`; `CapacidadNoMedida` si algo es `None`; Impultienda si todo es `True`."""
    falsas = [n for n in _BOOLEANAS if getattr(c, n) is False]
    if falsas:
        return Hosting("cloudflare", "; ".join(_MOTIVOS_FALSE[n] for n in falsas) + f" (sonda del {c.fecha})")
    nulas = [n for n in _BOOLEANAS if getattr(c, n) is None]
    if nulas:
        raise CapacidadNoMedida(f"no medido: {', '.join(nulas)} — mide Impultienda con `trovefy landing sonda`")
    return Hosting("impultienda", f"Impultienda sirve HTML, script, estilos y título propios, sin marco y en "
                                  f"dominio propio (sonda del {c.fecha})")


# --- empaquetado en línea ------------------------------------------------------------------------------

_MIME = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".woff2": "font/woff2"}
_TITULO = re.compile(r"<title\b[^>]*>.*?</title>", re.IGNORECASE | re.DOTALL)
_META = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_MAIN = re.compile(r"<main\b[^>]*\bid=\"tf-landing\"[^>]*>.*?</main>", re.DOTALL)
_SECCION = re.compile(r"(<section\b[^>]*>)(.*?)(</section>)", re.DOTALL)
_IMG = re.compile(r"<(?:img|source)\b[^>]*>", re.IGNORECASE)
_URL_CSS = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
_NOMBRE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _attr(etiqueta: str, nombre: str) -> str | None:
    m = re.search(rf'\s{nombre}="([^"]*)"', etiqueta)
    return m.group(1) if m else None


def _quitar(etiqueta: str, nombre: str) -> str:
    return re.sub(rf'\s{nombre}="[^"]*"', "", etiqueta)


def _poner(etiqueta: str, nombre: str, valor: str) -> str:
    if _attr(etiqueta, nombre) is None:
        return re.sub(r"\s*/?>$", lambda m: f' {nombre}="{valor}"{m.group(0)}', etiqueta, count=1)
    return re.sub(rf'(\s{nombre}=")[^"]*(")', lambda m: m.group(1) + valor + m.group(2), etiqueta, count=1)


class _Datos:
    """Convierte `assets/<archivo>` en `data:` (sin seguir enlaces ni salir de assets/)."""

    def __init__(self, assets: Path):
        if assets.is_symlink() or not assets.is_dir():
            raise ValueError(f"{assets} no es una carpeta (o es un enlace)")
        self.assets = assets
        self._cache: dict[str, str] = {}

    def __call__(self, nombre: str) -> str:
        nombre = nombre.strip()
        nombre = nombre.removeprefix("assets/")
        if not _NOMBRE.fullmatch(nombre) or ".." in nombre:
            raise ValueError(f"recurso «{nombre}»: solo archivos de assets/ (sin carpetas ni ..)")
        if nombre not in self._cache:
            ruta = self.assets / nombre
            mime = _MIME.get(ruta.suffix.lower())
            if mime is None:
                raise ValueError(f"assets/{nombre}: tipo no admitido en línea ({', '.join(sorted(_MIME))})")
            if ruta.is_symlink():
                raise ValueError(f"assets/{nombre} es un enlace simbólico: no se empaqueta")
            if not ruta.is_file():
                raise ValueError(f"falta assets/{nombre}")
            self._cache[nombre] = f"data:{mime};base64,{base64.b64encode(ruta.read_bytes()).decode('ascii')}"
        return self._cache[nombre]


def _candidatos(srcset: str) -> list[tuple[str, str]]:
    salida = []
    for trozo in srcset.split(","):
        partes = trozo.split()
        if partes:
            salida.append((partes[0], partes[1] if len(partes) > 1 else ""))
    return salida


def _imagen(etiqueta: str, datos: _Datos, hero: bool) -> str:
    srcset = _attr(etiqueta, "srcset")
    if srcset is not None:
        cands = _candidatos(srcset)
        if hero:
            etiqueta = _poner(etiqueta, "srcset", ", ".join(f"{datos(u)} {w}".strip() for u, w in cands))
        else:
            anchos = [(int(w[:-1]) if re.fullmatch(r"\d+w", w) else 10**9, u) for u, w in cands]
            elegido = next((u for a, u in anchos if a == 480), min(anchos)[1] if anchos else None)
            etiqueta = _quitar(_quitar(etiqueta, "srcset"), "sizes")
            if elegido is not None and etiqueta.lstrip("<").lower().startswith("img"):
                etiqueta = _poner(etiqueta, "src", elegido)
    src = _attr(etiqueta, "src")
    if src is not None:
        etiqueta = _poner(etiqueta, "src", datos(src))
    return etiqueta


def _en_linea(fragmento: str, datos: _Datos, hero: bool) -> str:
    return _IMG.sub(lambda m: _imagen(m.group(0), datos, hero), fragmento)


def empaquetar_en_linea(dir_landing: Path) -> str:
    """Fragmento para el campo «HTML completo de la tienda»: `<title>`, `<meta>`, `<style>` (con
    `estilo.css`), el `<main id="tf-landing">` con las imágenes en `data:` (fuera del *hero*, solo la de 480 px)
    y, al final, `<script>` con `utm.js`. Mantiene `data-tf-version`. `ValueError` si algo no se puede meter."""
    raiz = Path(dir_landing)
    datos = _Datos(raiz / "assets")
    html = (raiz / "index.html").read_text(encoding="utf-8")
    mains = _MAIN.findall(html)
    if len(mains) != 1:
        raise ValueError('index.html necesita un único <main id="tf-landing">')
    cabeza = html[: html.find("<main")]
    titulo = _TITULO.search(cabeza)
    metas = [m for m in _META.findall(cabeza) if re.search(r'\sname="(description|viewport)"', m)]
    css_ruta = raiz / "assets" / "estilo.css"
    if css_ruta.is_symlink():
        raise ValueError("assets/estilo.css es un enlace simbólico")
    css = css_ruta.read_text(encoding="utf-8")
    css = _URL_CSS.sub(lambda m: f"url('{datos(m.group(2))}')" if not m.group(2).startswith("data:") else m.group(0),
                       css)
    utm = UTM_JS.read_text(encoding="utf-8")
    if re.search(r"</style", css, re.IGNORECASE) or re.search(r"</script", utm, re.IGNORECASE):
        raise ValueError("estilo.css o utm.js cierran su propia etiqueta: no se pueden meter en línea")

    def seccion(m: re.Match) -> str:
        hero = 'data-tf-tipo="hero"' in m.group(1)
        return m.group(1) + _en_linea(m.group(2), datos, hero) + m.group(3)

    main = _SECCION.sub(seccion, mains[0])
    partes = [*([titulo.group(0)] if titulo else []), *metas, f"<style>\n{css.strip()}\n</style>", main,
              f"<script>\n{utm.strip()}\n</script>"]
    salida = "\n".join(partes)  # sin salto final (L-6): el campo de Impultienda lo puede comer
    if "assets/" in salida:
        raise ValueError("quedan rutas assets/ en el fragmento: algún recurso no se ha podido meter en línea")
    return salida


# --- tienda en mercados.yaml (resolución 24) ---------------------------------------------------------


def _linea_bloque(lineas: list[str], i: int, tienda: str, nota: str) -> bool:
    """Pone `tienda` en el bloque del país que empieza en `lineas[i]` (estilo bloque)."""
    hijos = []
    for j in range(i + 1, len(lineas)):
        if not lineas[j].strip():
            continue
        if not lineas[j][:1].isspace():
            break
        hijos.append(j)
    if not hijos:
        return False
    for j in hijos:
        m = re.match(r"^(\s+)tienda\s*:\s*(null|~|''|\"\")?\s*(#.*)?$", lineas[j].rstrip("\n"))
        if m:
            lineas[j] = f'{m.group(1)}tienda: "{tienda}"{nota}\n'
            return True
    sangria = re.match(r"^(\s+)", lineas[hijos[0]]).group(1)
    ultimo = hijos[-1]
    if not lineas[ultimo].endswith("\n"):
        lineas[ultimo] += "\n"
    lineas.insert(ultimo + 1, f'{sangria}tienda: "{tienda}"{nota}\n')
    return True


def _linea_flujo(lineas: list[str], i: int, tienda: str, nota: str) -> bool:
    linea = lineas[i].rstrip("\n")
    m = re.match(r"^(.*\{.*)\}(\s*(#.*)?)$", linea)
    if not m:
        return False
    cuerpo, cola = m.group(1), m.group(2)
    nuevo, n = re.subn(r"\btienda\s*:\s*(null|~|''|\"\")", f'tienda: "{tienda}"', cuerpo, count=1)
    if n == 0:
        if re.search(r"\btienda\s*:", cuerpo):
            return False
        nuevo = cuerpo.rstrip() + f', tienda: "{tienda}"'
    lineas[i] = nuevo + "}" + (cola if cola.strip() else nota) + "\n"
    return True


def guardar_tienda(vault: Path, pais: str, tienda: str, ahora: datetime) -> bool:
    """Escribe `<PAIS>.tienda` en `config/mercados.yaml` (palabra del usuario, con su fecha en un comentario).

    Solo cambia esa clave (el resto del archivo, comentarios incluidos, queda igual). `False` si ya estaba;
    `ValueError` si no es https de raíz, si el país no está o si ya tiene otra tienda (no se pisa)."""
    vault = Path(vault)
    if not tienda_valida(tienda):
        raise ValueError(f"la tienda tiene que ser la URL https de su raíz (https://mitienda.impultienda.ar): «{tienda}»")
    tienda = tienda.strip().rstrip("/")
    pais = pais.strip().upper()
    ruta = vault / "config" / "mercados.yaml"
    if ruta.is_symlink():
        raise ValueError("config/mercados.yaml es un enlace simbólico: no se escribe a través de él")
    texto = ruta.read_text(encoding="utf-8")
    antes = mercados.cargar(ruta)
    if pais not in antes:
        raise ValueError(f"{pais} no está en config/mercados.yaml")
    actual = antes[pais].tienda
    if actual:
        if actual.strip().rstrip("/") == tienda:
            return False
        raise ValueError(f"{pais} ya tiene otra tienda en config/mercados.yaml ({actual}): si es a propósito, "
                         "cámbiala tú a mano")
    fecha = ahora.astimezone(ZONA_NEGOCIO).date().isoformat()
    nota = f"  # usuario, {fecha} (trovefy landing sonda)"
    lineas = texto.splitlines(keepends=True)
    hecho = False
    for i, linea in enumerate(lineas):
        if re.match(rf"^['\"]?{pais}['\"]?\s*:\s*(#.*)?$", linea.rstrip("\n")):
            hecho = _linea_bloque(lineas, i, tienda, nota)
            break
        if re.match(rf"^['\"]?{pais}['\"]?\s*:\s*\{{", linea):
            hecho = _linea_flujo(lineas, i, tienda, nota)
            break
    nuevo = "".join(lineas)
    crudo_antes, crudo_despues = cargar_yaml(texto), (cargar_yaml(nuevo) if hecho else None)
    esperado = {**crudo_antes, pais: {**crudo_antes[pais], "tienda": tienda}} if isinstance(crudo_antes, dict) else None
    if not hecho or crudo_despues != esperado:
        raise ValueError(f"no sé poner la tienda de {pais} en config/mercados.yaml sin tocar lo demás: escríbela "
                         f'tú («tienda: "{tienda}"»)')
    escribir_atomico(ruta, nuevo)
    anadir_log(vault, "landing", f"{pais}: tienda {tienda} (palabra del usuario)", ["config/mercados.yaml"],
               ahora=ahora)
    return True


# --- sonda ---------------------------------------------------------------------------------------------

_JS_MEDIR = """() => {
  const el = document.getElementById("tf-sonda");
  if (!el) return null;
  const todo = ((document.body && document.body.innerText) || "").replace(/\\s+/g, "");
  const propio = (el.innerText || "").replace(/\\s+/g, "");
  return {ok: el.dataset.ok === "1", color: getComputedStyle(el).color,
          fuera: Math.max(0, todo.length - propio.length)};
}"""


def _host_anotable(url: str) -> str | None:
    """El host de una petición de la tienda que se anota (http/https, no de Meta), o None."""
    from urllib.parse import urlsplit

    partes = urlsplit(url)
    host = (partes.hostname or "").lower().rstrip(".")
    if partes.scheme not in ("http", "https") or not _HOST.fullmatch(host) or casa_host(host, HOSTS_META):
        return None
    return host


def _medir_tienda(page, tienda: str, dormir) -> dict:
    """Abre la tienda (sin perfil) y mide lo que hizo Impultienda con el fragmento de la sonda; anota también los
    hosts que carga la página (ruling I-4: la QA publicada los da como propios de la tienda)."""
    from urllib.parse import urlparse

    hosts: set[str] = set()

    def anotar(req) -> None:
        if (h := _host_anotable(getattr(req, "url", ""))) is not None:
            hosts.add(h)

    if callable(getattr(page, "on", None)):
        page.on("request", anotar)
    esperar_entre_navegaciones(urlparse(tienda).hostname or "", dormir=dormir)
    try:
        page.goto(tienda, wait_until="load", timeout=30_000)
    except Exception as exc:
        raise NavegadorError(f"no se pudo abrir la tienda ({type(exc).__name__}); revisa la URL") from exc
    titulo = page.title() == "tf-sonda"
    principal = page.main_frame
    medidas = dict.fromkeys(("html_propio", "script", "estilos", "titulo_propio", "sin_marco"), False)
    for frame in page.frames:
        try:
            r = frame.evaluate(_JS_MEDIR)
        except Exception:  # noqa: BLE001, S112 - un marco ajeno que no deja leer cuenta como «no está aquí»
            continue
        if r:
            en_principal = frame is principal
            medidas = {"html_propio": True, "script": bool(r.get("ok")), "estilos": r.get("color") == COLOR_SONDA,
                       "titulo_propio": titulo,
                       "sin_marco": en_principal and int(r.get("fuera") or 0) <= FUERA_MAX}
            break
    return {**medidas, "hosts_tienda": tuple(sorted(hosts))}


def _escribir_evidencia(vault: Path, c: Capacidades, ahora: datetime) -> str:
    rel = f"config/evidencia/p05-impultienda-{c.fecha}.json"
    escribir_atomico(Path(vault) / rel, json.dumps(asdict(c), ensure_ascii=False, indent=2) + "\n")
    anadir_log(vault, "landing", f"sonda de Impultienda: {elegir_resumen(c)}", [rel], ahora=ahora)
    return rel


def elegir_resumen(c: Capacidades) -> str:
    """Una línea con las capacidades (sí/no/no medido) para el log y la CLI."""
    def txt(v):
        return "no medido" if v is None else ("sí" if v is True else ("no" if v is False else str(v)))

    return ", ".join(f"{n} {txt(getattr(c, n))}" for n in (*_BOOLEANAS, "limite_caracteres"))


def sondear(vault: Path, p_id: str, pais: str, tienda: str, dominio_propio: bool | None,
            url_pantalla: str | None = None, *, mapa: dict | None = None, abrir=None, visible: bool = True,
            dormir=time.sleep, ahora: datetime | None = None) -> Capacidades:
    """Mide en la tienda real qué admite «HTML completo de la tienda» y restaura su contenido.

    1. Comprueba (sin navegador) la URL de la pantalla y que `diseno_contenido` está confirmada.
    2. Perfil `impultienda` visible: firma, respaldo en `landing/<PAIS>/respaldo/`, pega `HTML_SONDA`, guarda y
       relee (un recorte da `limite_caracteres`).
    3. La tienda en un contexto **sin perfil**: script, estilos, título y marco.
    4. Siempre que se haya pegado algo: restaura (solo si el campo tiene lo que se pegó, F2-1; si no, guarda lo
       que hay y para con `CampoCambiado`), relee y compara; si no queda igual, `NavegadorError` con la ruta del
       respaldo.
    5. Escribe `config/evidencia/p05-impultienda-<fecha>.json`.

    `dominio_propio` es la respuesta del usuario (no se mide aquí; lo confirma la QA publicada).
    """
    vault = Path(vault)
    ahora = ahora or datetime.now(ZONA_NEGOCIO)
    if not isinstance(tienda, str) or origen(tienda) is None:  # https (http solo en 127.0.0.1, tests)
        raise ValueError(f"la tienda tiene que ser una URL https: «{tienda}»")
    m = preparar_mapa(vault, mapa, url_pantalla)
    abrir = abrir or sesion
    original = respaldo = releido = None
    pegado = False
    try:
        with abrir(SERVICIO, visible=visible) as page:
            panel = Panel(page, m, dormir)
            panel.abrir()
            original = panel.leer()
            parar_si_sonda_colgada(vault, pais.upper(), original)  # I-5: restos de una sonda a medias
            respaldo = respaldar(vault, p_id, pais.upper(), original, ahora)
            pegado = True  # desde aquí, pase lo que pase, se restaura
            releido = panel.guardar(HTML_SONDA)
        with abrir(SERVICIO, visible=visible, perfil_persistente=False) as page:
            medidas = _medir_tienda(page, tienda, dormir)
    finally:
        if pegado:
            esperado = tuple(x for x in (HTML_SONDA, releido) if x is not None)
            restaurar(abrir, m, original, respaldo, esperado=esperado, vault=vault, visible=visible, dormir=dormir,
                      ahora=ahora)
    if not releido:  # L-3: un campo vacío tras guardar no es un límite de 0 caracteres: no guarda HTML propio
        limite, medidas = None, {**medidas, "html_propio": False}
    else:
        limite = len(releido) if releido != HTML_SONDA and HTML_SONDA.startswith(releido) else None
    fecha = ahora.astimezone(ZONA_NEGOCIO).date().isoformat()
    palabra = {True: "sí", False: "no", None: "no preguntado"}[dominio_propio]
    c = Capacidades(
        **medidas, dominio_propio=dominio_propio, limite_caracteres=limite, tienda=tienda,
        url_pantalla=m["pantallas"][PANTALLA]["url"], fecha=fecha,
        fuente=(f"sonda del {fecha} en la tienda (respaldo {respaldo.relative_to(vault).as_posix()}); "
                f"dominio propio: palabra del usuario ({palabra}), la confirma la QA publicada"),
    )
    _escribir_evidencia(vault, c, ahora)
    return c
