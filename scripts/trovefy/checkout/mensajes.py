"""Registro de los mensajes del usuario (plan 19, Tarea 11): la aprobación de un plan del MCP lleva sus palabras.

Un plan del MCP de Impultienda se aprueba con **la frase atada a ese plan** («sí, aplica la etapa N (xxxx)», ver
`trovefy.tienda.mcp.frase_aprobacion`), escrita entera por el usuario después de que se escribiera el plan. Lo
garantiza el hook ``UserPromptSubmit`` (`hooks/mensaje_usuario.py`): cada vez que el usuario envía un mensaje, anota
su huella (sha256 del texto plegado: sin mayúsculas, sin tildes, sin espacios de más) y la hora en
``~/.config/trovefy/mensajes-usuario.json``. Claude no puede leer ni escribir ese archivo: el hook `apimart_gasto`
le niega ``~/.config/trovefy`` y cualquier Bash que importe este módulo o lance el hook a mano.

`trovefy checkout aprobar` (que solo ejecuta el usuario; `apimart_gasto` se lo niega a Claude) **marca** el mensaje
con la huella del plan que aprueba (``u``): un mensaje aprueba un solo plan. En su terminal, sin mensaje en el chat,
anota él mismo la frase con su marca (la persona está delante, ruling I-1). Al releer la etapa, `trovefy checkout
releer` **cierra** esa aprobación (``c``): ya no vale ni para su plan. La guarda del hook
(`trovefy.tienda.mcp.escritura_aprobada`) solo acepta una aprobación cuyo mensaje está aquí, posterior al plan,
marcado para él y sin cerrar.

Solo se guardan huellas, nunca el texto: las últimas `MAX_MENSAJES` sin marcar y las últimas `MAX_MARCADOS`
marcadas. Solo biblioteca estándar: el hook lo importa con el python3 del sistema. Nunca lanza: ante un archivo roto
o un enlace, no vale (falla cerrado).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import tempfile
import time
import unicodedata
from collections.abc import Callable, Iterator
from pathlib import Path

NOMBRE = "mensajes-usuario.json"
MAX_MENSAJES = 50
MAX_MARCADOS = 20


def carpeta_config() -> Path:
    """La carpeta de configuración de trovefy (en el HOME del usuario)."""
    return Path.home() / ".config" / "trovefy"


def ruta_registro() -> Path:
    """El registro de mensajes, en la carpeta de configuración de trovefy."""
    return carpeta_config() / NOMBRE


def normalizar_mensaje(texto: str) -> str:
    """NFC, sin espacios de más (los saltos de línea cuentan como un espacio)."""
    return " ".join(unicodedata.normalize("NFC", texto).split())


def plegar(texto: str) -> str:
    """Para comparar frases: sin tildes ni mayúsculas y sin espacios de más (la puntuación cuenta)."""
    sin_marcas = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return normalizar_mensaje(sin_marcas.casefold())


def huella_mensaje(texto: str) -> str:
    return hashlib.sha256(plegar(texto).encode("utf-8")).hexdigest()


# --- archivos JSON de la carpeta de configuración (también el registro de escrituras de la guarda) -------------


def leer_lista(ruta: Path) -> list[dict] | None:
    """Las entradas (objetos) de un JSON lista; ``[]`` si no existe; None si es un enlace, no es un archivo normal
    del usuario o está roto."""
    try:
        info = os.lstat(ruta)
    except FileNotFoundError:
        return []
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(datos, list):
        return None
    return [d for d in datos if isinstance(d, dict)]


def preparar_carpeta(carpeta: Path) -> bool:
    """Crea ``carpeta`` (0700) si hace falta; False si no se puede o es un enlace."""
    try:
        carpeta.parent.mkdir(parents=True, exist_ok=True)
        carpeta.mkdir(mode=0o700, exist_ok=True)
        if carpeta.is_symlink() or not carpeta.is_dir():
            return False
        carpeta.chmod(0o700)
    except OSError:
        return False
    return True


def escribir_lista(ruta: Path, entradas: list[dict]) -> bool:
    """Escribe la lista (0600, atómico). False si no se puede."""
    contenido = json.dumps(entradas, separators=(",", ":"))
    try:
        fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=f".{ruta.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(contenido)
            os.chmod(tmp, 0o600)
            os.replace(tmp, ruta)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    except OSError:
        return False
    return True


@contextlib.contextmanager
def bloqueo(ruta: Path) -> Iterator[bool]:
    """Cerrojo exclusivo de ``ruta`` (``.<nombre>.lock`` al lado) para leer-modificar-escribir; da False si no se
    pudo tomar (quien lo usa falla cerrado)."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover - fuera de Linux/macOS
        yield True
        return
    try:
        fd = os.open(ruta.parent / f".{ruta.name}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        yield False
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield True
    finally:
        os.close(fd)


# --- el registro de mensajes --------------------------------------------------------------------------------------


def _entrada_valida(d: dict) -> bool:
    t = d.get("t")
    return (isinstance(d.get("h"), str) and isinstance(t, (int, float)) and not isinstance(t, bool)
            and (d.get("u") is None or isinstance(d.get("u"), str)) and isinstance(d.get("c", False), bool))


def _leer(ruta: Path) -> list[dict] | None:
    entradas = leer_lista(ruta)
    return None if entradas is None else [d for d in entradas if _entrada_valida(d)]


def _recortar(entradas: list[dict]) -> list[dict]:
    sueltas = [e for e in entradas if not e.get("u")][-MAX_MENSAJES:]
    marcadas = [e for e in entradas if e.get("u")][-MAX_MARCADOS:]
    return sorted(sueltas + marcadas, key=lambda e: e["t"])


def _modificar(cambio: Callable[[list[dict]], tuple[object, bool]]) -> object:
    """Lee el registro bajo cerrojo, aplica ``cambio(entradas) -> (resultado, escribir)`` y lo guarda. None si el
    registro no se puede usar."""
    ruta = ruta_registro()
    if not preparar_carpeta(ruta.parent):
        return None
    with bloqueo(ruta) as ok:
        if not ok:
            return None
        entradas = _leer(ruta)
        if entradas is None:
            return None
        resultado, escribir = cambio(entradas)
        if escribir and not escribir_lista(ruta, _recortar(entradas)):
            return None
        return resultado


def registrar_mensaje(texto: str, ahora: float | None = None) -> bool:
    """Anota la huella de un mensaje del usuario (lo llama el hook). False (sin escribir) si está vacío o el registro
    es un enlace u otra cosa que no es un archivo normal suyo; un registro roto se rehace."""
    if not isinstance(texto, str) or not normalizar_mensaje(texto):
        return False
    ruta = ruta_registro()
    if not preparar_carpeta(ruta.parent):
        return False
    with bloqueo(ruta) as ok:
        if not ok:
            return False
        previas = _leer(ruta)
        if previas is None:
            if ruta.is_symlink() or (ruta.exists() and not ruta.is_file()):
                return False
            previas = []
        entradas = [*previas, {"t": float(time.time() if ahora is None else ahora), "h": huella_mensaje(texto)}]
        return escribir_lista(ruta, _recortar(entradas))


def es_mensaje_del_usuario(cita: str, desde: float, huella: str | None = None) -> bool:
    """¿``cita`` es, entera, un mensaje del usuario enviado en ``desde`` o después? Con ``huella`` (lo que mira la
    guarda): además, marcado para ese plan por `trovefy checkout aprobar` y sin cerrar al releer."""
    if not isinstance(cita, str) or not normalizar_mensaje(cita):
        return False
    entradas = _leer(ruta_registro())
    if not entradas:
        return False
    h = huella_mensaje(cita)
    return any(e["h"] == h and e["t"] >= desde
               and (huella is None or (e.get("u") == huella and not e.get("c"))) for e in entradas)


def usar_mensaje(cita: str, desde: float, huella: str, *, terminal: bool = False,
                 ahora: float | None = None) -> dict | None:
    """Marca para el plan ``huella`` el último mensaje del usuario igual a ``cita``, posterior a ``desde``, sin marca
    de otro plan y sin cerrar; lo devuelve. Con ``terminal`` (el usuario ejecuta `aprobar` en su terminal) y sin ese
    mensaje en el chat, lo anota ya marcado. None si no hay mensaje que usar o el registro no se puede usar."""
    if not isinstance(cita, str) or not normalizar_mensaje(cita) or not huella:
        return None
    h = huella_mensaje(cita)

    def cambio(entradas: list[dict]) -> tuple[object, bool]:
        libres = [e for e in entradas if e["h"] == h and e["t"] >= desde and e.get("u") in (None, huella)
                  and not e.get("c")]
        if libres:
            e = max(libres, key=lambda x: x["t"])
            e["u"] = huella
            return dict(e), True
        usado = any(e["h"] == h and (e.get("c") or e.get("u") not in (None, huella)) for e in entradas)
        if terminal and not usado:
            e = {"t": float(time.time() if ahora is None else ahora), "h": h, "u": huella, "v": "terminal"}
            entradas.append(e)
            return dict(e), True
        return None, False

    resultado = _modificar(cambio)
    return resultado if isinstance(resultado, dict) else None


def cerrar_mensajes(huella: str) -> bool:
    """Cierra la aprobación del plan ``huella`` (al releer su etapa): su mensaje ya no vale para nada."""
    def cambio(entradas: list[dict]) -> tuple[object, bool]:
        tocadas = [e for e in entradas if e.get("u") == huella and not e.get("c")]
        for e in tocadas:
            e["c"] = True
        return True, bool(tocadas)

    return _modificar(cambio) is True
