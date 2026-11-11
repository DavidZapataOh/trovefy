"""Utilidades comunes de los verificadores: ejecutar comandos sin colgarse y guardar evidencia."""

import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yaml

from trovefy.arranque.estado import ResultadoVerificacion
from trovefy.vault.escritura import ZONA_NEGOCIO

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


def guardar_evidencia(vault: Path, id: str, nombre: str, datos: dict | bytes, provisional: bool = False) -> str:
    """Escribe la evidencia en config/evidencia/ y devuelve su ruta relativa al vault.

    `provisional=True`: una medida que no certifica nada va a config/evidencia/provisional/.
    """
    if not _SEGURO.match(id) or not _SEGURO.match(nombre):
        raise ValueError("id y nombre de evidencia solo admiten letras, números, - y _")
    ext = "png" if isinstance(datos, bytes) else "json"
    carpeta = "config/evidencia/provisional" if provisional else "config/evidencia"
    rel = f"{carpeta}/{id}-{nombre}-{datetime.now(ZONA_NEGOCIO):%Y-%m-%d}.{ext}"
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
    Se confirma en un commit posterior a la primera captura real, poniendo la fecha, o con la confirmación
    del usuario en el vault (`trovefy arranque confirmar`, ver `confirmacion_de`).
    """

    fecha: str | None
    fuente: str
    aviso: str | None = None  # p. ej. «patrón cambiado; vuelve a confirmar»

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
    from trovefy.secretos import RevisionSecretosNoDisponible, buscar_secreto

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
    texto: str | None = None, patrones_extracto=None, contexto: int = 2, motivo: str | None = None,
) -> ResultadoVerificacion:
    """«No medido» para un patrón sin confirmar: guarda la evidencia provisional y nunca certifica.

    `texto` es lo que leen los patrones (por defecto `captura.texto`); `pantallas`, si hay varias.
    """
    if pantallas is None:
        leido = captura.texto if texto is None else texto
        pantallas = [PantallaProvisional("pagina", captura.url_final, png, leido)]
    rutas, avisos = guardar_provisional(vault, id, pantallas, patrones_extracto, contexto)
    motivo = motivo or MOTIVO_SIN_CONFIRMAR
    lineas = [f"? {motivo}", *lineas_provisionales(rutas, avisos)]
    return ResultadoVerificacion(None, [], motivo, [], {}, lineas)


# --- Confirmación del patrón por el usuario (config/confirmaciones.yaml en el vault) ---------------
#
# Dos mecanismos equivalentes: la fecha en el código (`Confirmacion.fecha`, mapa `capturado`) o una
# confirmación del usuario en el vault, hecha con `trovefy arranque confirmar <paso> --respuesta si`
# sobre el texto provisional de su pantalla real. La del vault solo vale si su `texto_sha256` coincide
# con un texto provisional que existe: una edición a mano del yaml no certifica nada.

RUTA_CONFIRMACIONES = "config/confirmaciones.yaml"
_SHA = re.compile(r"[0-9a-f]{64}")
_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")


class ConfirmacionesIlegibles(ValueError):
    """config/confirmaciones.yaml no se puede leer; nunca se sobrescribe."""


@dataclass(frozen=True)
class Lector:
    """Cómo lee un paso su texto provisional: {pantalla: texto} → {campo: valor | None}."""

    leer: Callable[[dict[str, str], Path], dict[str, str | None]]
    requeridos: tuple[str, ...] | None  # None: todos los campos que devuelve `leer`
    aceptar: Callable[[dict[str, str | None]], str | None] | None = None  # motivo para no confirmar, o None
    huella: str | Callable[[], str] = ""  # sha256 de los patrones (código) o del mapa actuales

    def huella_actual(self) -> str:
        return self.huella() if callable(self.huella) else self.huella


LECTORES: dict[str, Lector] = {}


def registrar_lector(
    id_: str,
    leer: Callable[[dict[str, str], Path], dict[str, str | None]],
    requeridos: tuple[str, ...] | None = None,
    aceptar: Callable[[dict[str, str | None]], str | None] | None = None,
    huella: str | Callable[[], str] = "",
) -> None:
    LECTORES[id_] = Lector(leer, requeridos, aceptar, huella)


def huella_de(*partes) -> str:
    """sha256 de los patrones de código de un paso (regex o textos): si cambian, cambia la huella."""
    texto = "\n".join(p.pattern if isinstance(p, re.Pattern) else str(p) for p in partes)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def huella_mapa(mapa: dict) -> str:
    """sha256 de las pantallas de un mapa (URL, firma y patrones), sin `capturado` ni `fuente`."""
    return hashlib.sha256(json.dumps(mapa["pantallas"], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def lector_para(paso: str, mapa: dict | None = None) -> Lector | None:
    """El lector del paso; con `mapa`, el de ese mapa concreto (el que está usando el verificador)."""
    base = LECTORES.get(paso)
    if base is None or mapa is None:
        return base
    return Lector(lector_de_mapa(lambda: mapa), base.requeridos, base.aceptar, huella_mapa(mapa))


def rechazo(lector: Lector, valores: dict[str, str | None]) -> str | None:
    """Por qué no se puede confirmar lo leído (None: se puede)."""
    requeridos = lector.requeridos if lector.requeridos is not None else tuple(valores)
    faltan = [c for c in requeridos if valores.get(c) is None]
    if faltan:
        return (
            f"el patrón no casa con tu pantalla real (falta: {', '.join(faltan)}); "
            "hay que ajustar el mapa (cambio en el repo). No se confirma nada."
        )
    return lector.aceptar(valores) if lector.aceptar else None


def lector_de_mapa(mapa: Callable[[], dict]) -> Callable[[dict[str, str], Path], dict]:
    """Lector para un mapa.yaml: «<pantalla>.firma» y «<pantalla>.<campo>» de cada pantalla."""
    from trovefy.mapa import FirmaAusente, leer_pantalla

    def leer(textos: dict[str, str], _vault: Path) -> dict[str, str | None]:
        m = mapa()
        salida: dict[str, str | None] = {}
        for nombre, pantalla in m["pantallas"].items():
            texto = textos.get(nombre)
            try:
                campos = leer_pantalla(pantalla, texto) if texto is not None else None
            except FirmaAusente:
                campos = None
            salida[f"{nombre}.firma"] = None if campos is None else "presente"
            for campo in pantalla.get("campos", {}):
                salida[f"{nombre}.{campo}"] = None if campos is None else campos.get(campo)
        return salida

    return leer


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def _leer_confirmaciones(vault: Path) -> dict:
    """Contenido de config/confirmaciones.yaml; lanza ConfirmacionesIlegibles si no se puede leer (nunca se pisa)."""
    ruta = Path(vault) / RUTA_CONFIRMACIONES
    if not ruta.exists():
        return {}
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ConfirmacionesIlegibles(f"{ruta} no se puede leer ({type(exc).__name__}); no se sobrescribe") from exc
    if datos is None:
        return {}
    if not isinstance(datos, dict):
        raise ConfirmacionesIlegibles(f"{ruta} no es un mapa; no se sobrescribe")
    return datos


def motivo_patron_cambiado(paso: str) -> str:
    return f"no medido: patrón cambiado; vuelve a confirmar con `trovefy arranque confirmar {paso}`"


def estado_confirmacion(vault: Path, paso: str, mapa: dict | None = None) -> tuple[str | None, str | None]:
    """(fecha, aviso) de la confirmación del usuario en el vault.

    Vale solo si (1) su sha256 coincide con un texto provisional existente, (2) su huella es la de los
    patrones o el mapa actuales y (3) el lector actual, sobre ese texto, sigue leyendo todo lo requerido
    y lo acepta. Con (1) pero sin (2) o (3): (None, «patrón cambiado; vuelve a confirmar»).
    """
    try:
        entrada = _leer_confirmaciones(vault).get(paso)
    except (ValueError, OSError):
        return None, None
    if not isinstance(entrada, dict):
        return None, None
    fecha, sha = entrada.get("fecha"), entrada.get("texto_sha256")
    fecha = fecha.isoformat() if isinstance(fecha, date) else fecha
    if not isinstance(fecha, str) or not _FECHA.fullmatch(fecha) or not isinstance(sha, str) or not _SHA.fullmatch(sha):
        return None, None
    try:
        archivo = next((f for f in textos_provisionales(vault, paso) if _sha256(f) == sha), None)
    except OSError:
        return None, None
    if archivo is None:
        return None, None
    lector = lector_para(paso, mapa)
    if lector is None:
        return None, None
    cambiado = motivo_patron_cambiado(paso)
    try:
        if entrada.get("huella") != lector.huella_actual():
            return None, cambiado
        if rechazo(lector, lector.leer(leer_texto_provisional(archivo), vault)):
            return None, cambiado
    except (OSError, ValueError, KeyError):
        return None, cambiado
    return fecha, None


def fecha_confirmada(vault: Path, paso: str, mapa: dict | None = None) -> str | None:
    return estado_confirmacion(vault, paso, mapa)[0]


def aviso_confirmacion(vault: Path, paso: str, mapa: dict | None = None) -> str | None:
    return estado_confirmacion(vault, paso, mapa)[1]


def confirmacion_de(vault: Path, paso: str, codigo: Confirmacion) -> Confirmacion:
    """La confirmación del código o, si no la hay, la del usuario en el vault (misma regla para todos)."""
    if codigo.confirmada:
        return codigo
    fecha, aviso = estado_confirmacion(vault, paso)
    if fecha is None:
        return Confirmacion(codigo.fecha, codigo.fuente, aviso)
    return Confirmacion(fecha=fecha, fuente=f"confirmado por el usuario con su pantalla real ({RUTA_CONFIRMACIONES})")


def mapa_confirmado(vault: Path, paso: str, mapa: dict) -> dict:
    """El mapa con `capturado` puesto si el usuario confirmó el paso en el vault con este mismo mapa."""
    if mapa.get("capturado") is not None:
        return mapa
    fecha = fecha_confirmada(vault, paso, mapa)
    return mapa if fecha is None else {**mapa, "capturado": fecha}


def registrar_confirmacion(vault: Path, paso: str, archivo: Path, huella: str) -> dict:
    """Escribe (atómico) la confirmación del paso en config/confirmaciones.yaml del vault."""
    from trovefy.vault.escritura import escribir_atomico

    datos = _leer_confirmaciones(vault)
    entrada = {
        "fecha": f"{datetime.now(ZONA_NEGOCIO):%Y-%m-%d}",
        "texto_sha256": _sha256(archivo),
        "archivo": Path(archivo).relative_to(vault).as_posix(),
        "huella": huella,
    }
    datos[paso] = entrada
    escribir_atomico(Path(vault) / RUTA_CONFIRMACIONES, yaml.safe_dump(datos, allow_unicode=True, sort_keys=True))
    return entrada
