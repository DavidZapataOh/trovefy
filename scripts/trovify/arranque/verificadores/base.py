"""Utilidades comunes de los verificadores: ejecutar comandos sin colgarse y guardar evidencia."""

import json
import os
import re
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from trovify.arranque.estado import ResultadoVerificacion
from trovify.vault.escritura import ZONA_NEGOCIO

_SEGURO = re.compile(r"^[A-Za-z0-9_-]+$")


def correr(cmd: list[str], timeout: float = 10) -> tuple[int | None, str]:
    """Ejecuta `cmd`; devuelve (código, salida). `None` si no existe o se agota el tiempo."""
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # grupo propio: un snap colgado se mata entero
        )
    except (FileNotFoundError, PermissionError):  # PermissionError: un directorio del PATH no es legible
        return None, "no instalado"
    except OSError as exc:
        return None, f"no se pudo ejecutar: {exc.strerror or exc}"
    try:
        salida, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            proc.communicate(timeout=1)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None, "tiempo agotado"
    return proc.returncode, salida.decode("utf-8", errors="replace").strip()


def guardar_evidencia(vault: Path, id: str, nombre: str, datos: dict | bytes) -> str:
    """Escribe la evidencia en config/evidencia/ y devuelve su ruta relativa al vault."""
    if not _SEGURO.match(id) or not _SEGURO.match(nombre):
        raise ValueError("id y nombre de evidencia solo admiten letras, números, - y _")
    ext = "png" if isinstance(datos, bytes) else "json"
    rel = f"config/evidencia/{id}-{nombre}-{datetime.now(ZONA_NEGOCIO):%Y-%m-%d}.{ext}"
    destino = Path(vault) / rel
    destino.parent.mkdir(parents=True, exist_ok=True)
    contenido = datos if isinstance(datos, bytes) else json.dumps(datos, ensure_ascii=False, indent=2).encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=destino.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, destino)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return rel


@dataclass(frozen=True)
class Confirmacion:
    """Estado de un patrón o mapa de una pantalla privada.

    Mientras `fecha` sea None el patrón sale de la documentación o del encargo, no de la pantalla
    real del usuario: el verificador no certifica (ni suspende) nada con él; devuelve «no medido».
    Se confirma en un commit posterior a la primera captura real, poniendo la fecha.
    """

    fecha: str | None
    fuente: str

    @property
    def confirmada(self) -> bool:
        return self.fecha is not None


MOTIVO_SIN_CONFIRMAR = "no medido: patrón sin confirmar con tu pantalla real"


def sin_query(url: str) -> str:
    """La URL sin parámetros ni fragmento (pueden llevar identificadores o tokens)."""
    partes = urlsplit(url)
    return urlunsplit((partes.scheme, partes.netloc, partes.path, "", ""))


_MAX_LINEA = 300  # una línea más larga (HTML minificado) no se guarda entera: solo el trozo que casa
_MAX_TROZO = 2000
_SECCION = re.compile(r"^=== pantalla ([A-Za-z0-9_-]+) · (\S*) ===$", re.MULTILINE)


@dataclass(frozen=True)
class PantallaProvisional:
    """Una pantalla capturada sin patrón confirmado: lo que se guarda en config/evidencia/provisional/."""

    nombre: str
    url_final: str
    png: bytes | None
    texto: str | None  # el texto sobre el que corren los patrones (None: no hay nada que guardar)


def extracto(texto: str, patrones, contexto: int = 2) -> str:
    """Solo las líneas que casan con algún patrón y las ±`contexto` de alrededor.

    Si alguna de esas líneas es muy larga (HTML minificado con tokens de sesión) no se guarda: se
    guarda solo el trozo que casa. Nunca devuelve el texto completo.
    """
    lineas = texto.splitlines()
    inicios, pos = [], 0
    for ln in texto.splitlines(keepends=True):
        inicios.append(pos)
        pos += len(ln)

    def linea_de(offset: int) -> int:
        lo, hi = 0, len(inicios) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if inicios[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo

    guardar: set[int] = set()
    trozos: list[str] = []
    for patron in patrones:
        for m in patron.finditer(texto):
            a, b = linea_de(m.start()), linea_de(max(m.end() - 1, m.start()))
            rango = range(max(0, a - contexto), min(len(lineas), b + contexto + 1))
            if all(len(lineas[i]) <= _MAX_LINEA for i in range(a, b + 1)):
                guardar.update(i for i in rango if len(lineas[i]) <= _MAX_LINEA)
            elif len(m.group(0)) <= _MAX_TROZO:
                trozos.append(m.group(0))
    return "\n".join([lineas[i] for i in sorted(guardar)] + trozos)


def escribir_privado(destino: Path, contenido: bytes) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=destino.parent, prefix=".tmp-")  # mkstemp: modo 0600
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, destino)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def documento_de_texto(pantallas: list[PantallaProvisional]) -> str:
    """Texto de varias pantallas en un archivo: cada una bajo `=== pantalla <nombre> · <url sin query> ===`."""
    partes = []
    for p in pantallas:
        if p.texto is not None:
            partes.append(f"=== pantalla {p.nombre} · {sin_query(p.url_final)} ===\n{p.texto.rstrip(chr(10))}\n")
    return "".join(partes)


def leer_texto_provisional(ruta: Path) -> dict[str, str]:
    """{pantalla: texto} de un archivo de texto provisional."""
    contenido = Path(ruta).read_text(encoding="utf-8")
    marcas = list(_SECCION.finditer(contenido))
    salida = {}
    for n, m in enumerate(marcas):
        fin = marcas[n + 1].start() if n + 1 < len(marcas) else len(contenido)
        salida[m.group(1)] = contenido[m.end() + 1: fin]
    return salida


def carpeta_provisional(vault: Path) -> Path:
    return Path(vault) / "config" / "evidencia" / "provisional"


def textos_provisionales(vault: Path, id: str) -> list[Path]:
    """Archivos de texto provisional del paso, del más antiguo al más reciente."""
    if not _SEGURO.match(id):
        raise ValueError("id de evidencia solo admite letras, números, - y _")
    return sorted(f for f in carpeta_provisional(vault).glob(f"{id}-texto-*.txt") if f.is_file() and not f.is_symlink())


def ultimo_texto_provisional(vault: Path, id: str) -> Path | None:
    textos = textos_provisionales(vault, id)
    return textos[-1] if textos else None


def guardar_provisional(
    vault: Path, id: str, pantallas: list[PantallaProvisional], patrones_extracto=None, contexto: int = 2
) -> tuple[list[str], list[str]]:
    """Guarda en config/evidencia/provisional/ las capturas (PNG), las URLs sin query y el texto leído.

    Todo con modo 0600. Con `patrones_extracto` (p. ej. HTML con sesión) solo se guardan los trozos que
    casan, nunca la página entera. Si el texto parece llevar un secreto, no se guarda: solo el PNG.
    Devuelve (rutas relativas al vault, avisos para mostrar).
    """
    from trovify.secretos import RevisionSecretosNoDisponible, buscar_secreto

    if not _SEGURO.match(id) or not all(_SEGURO.match(p.nombre) for p in pantallas):
        raise ValueError("id y pantalla de evidencia solo admiten letras, números, - y _")
    base = carpeta_provisional(vault)
    ahora = datetime.now(ZONA_NEGOCIO)
    fecha = f"{ahora:%Y-%m-%d}"
    varias = len(pantallas) > 1
    rutas: list[str] = []
    avisos: list[str] = []

    def escribir(nombre: str, contenido: bytes) -> None:
        destino = base / nombre
        escribir_privado(destino, contenido)
        rutas.append(destino.relative_to(vault).as_posix())

    for p in pantallas:
        if p.png is not None:
            escribir(f"{id}-captura-{p.nombre}-{fecha}.png" if varias else f"{id}-captura-{fecha}.png", p.png)
    urls = {p.nombre: sin_query(p.url_final) for p in pantallas}
    url_json = {"url_final": urls} if varias else {"url_final": next(iter(urls.values()), "")}
    escribir(f"{id}-url-{fecha}.json", json.dumps(url_json, ensure_ascii=False).encode("utf-8"))

    if patrones_extracto is not None:
        pantallas = [PantallaProvisional(p.nombre, p.url_final, p.png, None if p.texto is None else extracto(p.texto, patrones_extracto, contexto))
                     for p in pantallas]
    documento = documento_de_texto(pantallas)
    if documento:
        try:
            patron = buscar_secreto(documento)
        except RevisionSecretosNoDisponible as exc:
            avisos.append(f"texto no guardado: {exc}")
        else:
            if patron:
                avisos.append(f"texto no guardado: parece llevar un secreto ({patron}); solo se guardó la captura")
            else:
                escribir(f"{id}-texto-{ahora:%Y-%m-%d-%H%M%S%f}.txt", documento.encode("utf-8"))
    return rutas, avisos


def lineas_provisionales(rutas: list[str], avisos: list[str]) -> list[str]:
    return [f"  captura provisional: {r}" for r in rutas] + [f"  aviso: {a}" for a in avisos]


def resultado_provisional(
    vault: Path, id: str, captura, png: bytes | None, *, pantallas: list[PantallaProvisional] | None = None,
    texto: str | None = None, patrones_extracto=None, contexto: int = 2,
) -> ResultadoVerificacion:
    """«No medido» para un patrón sin confirmar: guarda la evidencia provisional y nunca certifica.

    `texto` es lo que leen los patrones (por defecto `captura.texto`); `pantallas`, si hay varias.
    """
    if pantallas is None:
        leido = captura.texto if texto is None else texto
        pantallas = [PantallaProvisional("pagina", captura.url_final, png, leido)]
    rutas, avisos = guardar_provisional(vault, id, pantallas, patrones_extracto, contexto)
    lineas = [f"? {MOTIVO_SIN_CONFIRMAR}", *lineas_provisionales(rutas, avisos)]
    return ResultadoVerificacion(None, [], MOTIVO_SIN_CONFIRMAR, [], {}, lineas)
