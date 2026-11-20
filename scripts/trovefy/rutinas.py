"""Rutinas programadas con timers de systemd de usuario (§3.6 [D-06]; plan 24, Tarea 9).

Cada rutina lanza ``claude -p "/trovefy:<skill> … --rutina"`` con su lista ``--allowedTools``; nunca con
``--dangerously-skip-permissions``. Las rutinas salen de un catálogo de datos (``templates/systemd/rutinas.yaml``) y cada
lista de herramientas se valida antes de escribir nada: subconjunto del ``allowed-tools`` de la skill, solo lectura de
Meta y de Impultienda, nada con ``sudo`` y ningún ``Write`` fuera de ``~/.cache/trovefy/`` (salvo los YAML de la tanda
en la renovación, resolución 25). ``ExecCondition`` evita lanzar Claude si no hay test vivo y ``ExecStopPost`` deja
constancia (y avisa) si una rutina falla.

Cada ejecución deja ``rutinas/log/AAAA-MM-DD/<rutina>.md`` y, si terminó sin parada, ``<rutina>.ok`` (lo mira /vigia).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

from trovefy.vault.escritura import ZONA_NEGOCIO, escribir_atomico

PLANTILLAS = Path(__file__).resolve().parents[2] / "templates" / "systemd"
RAIZ = Path(__file__).resolve().parents[2]
CATALOGO = PLANTILLAS / "rutinas.yaml"
SERVICIO_CAZA = "trovefy-caza.service"
TIMER_CAZA = "trovefy-caza.timer"
CONDICIONES = (None, "test_vivo", "renovacion")
PLAZO_TEST_DIAS = 7  # «Plazo 1 semana» (C1 0:18:10)
ESCRITURA_RENOVACION = ("productos/*/creativos/*/*/brief.yaml", "productos/*/creativos/*/*/escenas.yaml",
                        "productos/*/creativos/*/*/guiones/*.yaml")
OMITIDA = "exec-condition"  # SERVICE_RESULT cuando ExecCondition dijo «no toca» (systemd ≥ 243)


@dataclass(frozen=True)
class Rutina:
    nombre: str
    skill: str
    argumentos: str
    calendario: str
    persistente: bool
    condicion: str | None
    por_pais: bool
    herramientas: tuple[str, ...]
    fin: bool = True
    log: str | None = None
    plantilla: str | None = None


class RutinaInvalida(ValueError):
    """Catálogo, herramientas o datos del país que no permiten instalar (el texto dice por qué)."""


def cargar_catalogo(ruta: Path | None = None) -> dict[str, Rutina]:
    datos = yaml.safe_load(Path(ruta or CATALOGO).read_text(encoding="utf-8")) or {}
    salida: dict[str, Rutina] = {}
    for nombre, d in datos.items():
        if not isinstance(d, dict):
            raise RutinaInvalida(f"rutina {nombre}: no es un mapa")
        try:
            r = Rutina(nombre=str(nombre), skill=str(d["skill"]), argumentos=str(d["argumentos"]),
                       calendario=str(d["calendario"]), persistente=bool(d["persistente"]),
                       condicion=d.get("condicion"), por_pais=bool(d.get("por_pais", False)),
                       herramientas=tuple(str(h) for h in d["herramientas"]), fin=bool(d.get("fin", True)),
                       log=d.get("log"), plantilla=d.get("plantilla"))
        except (KeyError, TypeError) as exc:
            raise RutinaInvalida(f"rutina {nombre}: falta {exc}") from None
        if r.condicion not in CONDICIONES:
            raise RutinaInvalida(f"rutina {nombre}: condición desconocida {r.condicion!r}")
        salida[r.nombre] = r
    return salida


def instancia(r: Rutina, pais: str | None = None) -> str:
    return f"{r.nombre}-{pais.lower()}" if r.por_pais and pais else r.nombre


def nombre_log(r: Rutina, pais: str | None = None) -> str:
    if r.log:
        return r.log.replace("{pais_min}", (pais or "").lower()).replace("{pais}", pais or "")
    return instancia(r, pais)


def _rellenar(texto: str, **valores: str) -> str:
    for clave, valor in valores.items():
        texto = texto.replace("{" + clave + "}", valor)
    return texto


# --- herramientas ------------------------------------------------------------------------------------------------


def allowed_de_skill(skill: str, raiz: Path = RAIZ) -> list[str] | None:
    """``allowed-tools`` del frontmatter de ``skills/<skill>/SKILL.md`` (None si la skill no existe)."""
    ruta = raiz / "skills" / skill / "SKILL.md"
    if not ruta.is_file():
        return None
    partes = ruta.read_text(encoding="utf-8").split("---")
    meta = yaml.safe_load(partes[1]) if len(partes) > 2 else {}
    valor = (meta or {}).get("allowed-tools") or ""
    lista = valor if isinstance(valor, list) else str(valor).split(",")
    return [h.strip() for h in lista if h.strip()]


def catalogo_impultienda(raiz: Path = RAIZ) -> dict:
    import json

    datos = json.loads((raiz / "config" / "impultienda_tools.json").read_text(encoding="utf-8"))
    h = datos["herramientas"]
    return h if isinstance(h, dict) else {x["nombre"]: x for x in h}


def _ruta_de(h: str) -> str:
    return h[h.index("(") + 1:-1] if "(" in h and h.endswith(")") else ""


def validar_herramientas(r: Rutina, allowed_skill: Sequence[str] | None, meta_tools: object,
                         impultienda_tools: dict) -> list[str]:
    """Problemas que impiden instalar la rutina ([] si ninguno). ``meta_tools`` es la lista de herramientas del MCP de
    Meta del vault (``config/meta_tools.json``) o None si no existe."""
    from trovefy.vault.permisos import es_lectura_meta

    problemas: list[str] = []
    if allowed_skill is None:
        return [f"{r.nombre}: la skill /{r.skill} no existe todavía"]
    permitidas = set(allowed_skill)
    nombres_meta = set(meta_tools) if isinstance(meta_tools, (list, tuple, set)) else (
        set(meta_tools) if isinstance(meta_tools, dict) else None)
    for h in r.herramientas:
        if "dangerously" in h:
            problemas.append(f"{r.nombre}: {h}: nunca se saltan los permisos")
            continue
        if h not in permitidas:
            problemas.append(f"{r.nombre}: {h} no está en el allowed-tools de /{r.skill}")
        if h.startswith("mcp__meta-ads__"):
            n = h.removeprefix("mcp__meta-ads__")
            if nombres_meta is None:
                problemas.append(f"{r.nombre}: {h}: falta config/meta_tools.json en el vault (`trovefy meta herramientas "
                                 "importar`)")
            elif n not in nombres_meta or not es_lectura_meta(n):
                problemas.append(f"{r.nombre}: {h} no es de lectura en meta_tools.json (Claude nunca escribe en Meta)")
        elif h.startswith("mcp__impultienda__"):
            n = h.removeprefix("mcp__impultienda__")
            if (impultienda_tools.get(n) or {}).get("clase") != "lectura":
                problemas.append(f"{r.nombre}: {h} no es de lectura en config/impultienda_tools.json")
        elif h.startswith("mcp__"):
            problemas.append(f"{r.nombre}: {h}: servidor MCP no permitido en rutinas")
        elif h.startswith("Bash(") and _ruta_de(h).lstrip().startswith(("sudo", "su ")):
            problemas.append(f"{r.nombre}: {h}: nada con sudo")
        elif h.startswith(("Write(", "Edit(")):
            ruta = _ruta_de(h)
            en_cache = ruta.startswith("~/.cache/trovefy/") and ".." not in ruta
            de_tanda = r.nombre == "renovacion" and h.startswith("Write(") and ruta in ESCRITURA_RENOVACION
            if not (en_cache or de_tanda):
                problemas.append(f"{r.nombre}: {h}: solo se escribe en ~/.cache/trovefy/"
                                 + (" (o los YAML de la tanda)" if r.nombre == "renovacion" else ""))
    if "dangerously" in r.argumentos:
        problemas.append(f"{r.nombre}: los argumentos no pueden saltarse los permisos")
    return problemas


# --- unidades ----------------------------------------------------------------------------------------------------


def _path_por_defecto(claude: str) -> str:
    return ":".join(dict.fromkeys([os.path.dirname(claude) or "/usr/bin", "%h/.local/bin",
                                   "/usr/local/bin", "/usr/bin", "/bin"]))


def _comprobar(*valores: str) -> None:
    for valor in valores:
        if any(ch in valor for ch in '"\\\n'):
            raise ValueError(f"ruta no admitida en una unidad de systemd: {valor!r}")


def unidad_caza(vault: Path, claude: str, path: str | None = None) -> tuple[str, str]:
    """Texto del ``.service`` y del ``.timer`` de la caza diaria (lunes a sábado, 06:30 COT).

    ``path`` es el PATH del servicio; por defecto la carpeta de ``claude``, ``~/.local/bin`` (``%h``
    de systemd: ahí instala ``uv tool`` el comando ``trovefy``) y las rutas del sistema."""
    if path is None:
        path = _path_por_defecto(claude)
    _comprobar(str(vault), claude, path)
    # «%» es un especificador de systemd: en rutas propias se escribe «%%» (el PATH usa %h a propósito).
    servicio = _rellenar((PLANTILLAS / SERVICIO_CAZA).read_text(encoding="utf-8"),
                         vault=str(vault).replace("%", "%%"), claude=claude.replace("%", "%%"), path=path)
    timer = (PLANTILLAS / TIMER_CAZA).read_text(encoding="utf-8")
    if "dangerously" in servicio:  # nunca: §3.6, [D-30]
        raise ValueError("la unidad de la rutina no puede saltarse los permisos")
    return servicio, timer


def unidades(r: Rutina, vault: Path, claude: str, pais: str | None = None, path: str | None = None, *,
             zona: str | None = None, producto: str | None = None, trovefy: str = "%h/.local/bin/trovefy"
             ) -> tuple[str, str]:
    """``.service`` y ``.timer`` de la rutina (de su país, si va por país)."""
    if r.plantilla == "caza":
        return unidad_caza(vault, claude, path)
    if r.por_pais and not pais:
        raise RutinaInvalida(f"{r.nombre} va por país: falta --pais")
    valores = {"pais": pais or "", "pais_min": (pais or "").lower(), "zona": zona or "", "producto": producto or ""}
    argumentos, calendario = _rellenar(r.argumentos, **valores), _rellenar(r.calendario, **valores)
    if "{" in argumentos + calendario:
        raise RutinaInvalida(f"{r.nombre}: falta un dato para {argumentos!r} / {calendario!r} (zona o producto)")
    path = path or _path_por_defecto(claude)
    herramientas = ",".join(r.herramientas)
    _comprobar(str(vault), claude, path, trovefy, argumentos, herramientas)
    sufijo = f" --pais {pais}" if r.por_pais and pais else ""
    tv = trovefy.replace("%", "%%") if not trovefy.startswith("%h/") else trovefy
    servicio = _rellenar(
        (PLANTILLAS / "trovefy-rutina.service.tmpl").read_text(encoding="utf-8"),
        instancia=instancia(r, pais), argumentos=argumentos.replace("%", "%%"),
        vault=str(vault).replace("%", "%%"), path=path, claude=claude.replace("%", "%%"),
        herramientas=herramientas.replace("%", "%%"),
        exec_condition=f"ExecCondition={tv} rutinas condicion {r.nombre}{sufijo}\n" if r.condicion else "",
        exec_stop_post=f"ExecStopPost={tv} rutinas fin {r.nombre}{sufijo}\n" if r.fin else "")
    timer = _rellenar((PLANTILLAS / "trovefy-rutina.timer.tmpl").read_text(encoding="utf-8"),
                      instancia=instancia(r, pais), calendario=calendario,
                      persistente="true" if r.persistente else "false")
    if "dangerously" in servicio:  # nunca: §3.6, [D-30]
        raise ValueError("la unidad de la rutina no puede saltarse los permisos")
    return servicio, timer


def _systemctl(comando: list[str]) -> None:
    subprocess.run(comando, check=True)


def directorio_unidades() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def instalar_caza(vault: Path, claude: str, ejecutar: Callable[[list[str]], None] | None = None) -> list[Path]:
    """Escribe las unidades en ``~/.config/systemd/user/`` y activa el timer."""
    ejecutar = ejecutar or _systemctl
    servicio, timer = unidad_caza(Path(vault), claude)
    carpeta = directorio_unidades()
    rutas = [carpeta / SERVICIO_CAZA, carpeta / TIMER_CAZA]
    for ruta, texto in zip(rutas, (servicio, timer), strict=True):
        escribir_atomico(ruta, texto)
    ejecutar(["systemctl", "--user", "daemon-reload"])
    ejecutar(["systemctl", "--user", "enable", "--now", TIMER_CAZA])
    return rutas


def buscar_claude() -> str | None:
    return shutil.which("claude")


def buscar_trovefy() -> str:
    return shutil.which("trovefy") or "%h/.local/bin/trovefy"


# --- datos del vault -----------------------------------------------------------------------------------------------


def zona_pais(vault: Path, pais: str) -> str | None:
    ruta = Path(vault) / "config" / "mercados.yaml"
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    m = datos.get(pais) if isinstance(datos, dict) else None
    z = m.get("zona") if isinstance(m, dict) else None
    return z if isinstance(z, str) and z else None


def tests_vivos(vault: Path) -> list[tuple[str, str]]:
    """(producto, país) de los tests vivos de ``config/caja.yaml``."""
    from trovefy.caja.config import cargar_caja

    try:
        return [(t.producto, t.pais) for t in cargar_caja(vault).tests if t.estado == "vivo"]
    except Exception:  # noqa: BLE001 - sin caja legible no hay test vivo
        return []


def en_marcha(vault: Path) -> list[tuple[str, str]]:
    """(producto, país) con test vivo en la caja o en ``montado``/``test`` en ``PRODUCTO.md``."""
    from trovefy.vault import frontmatter

    salida = list(tests_vivos(vault))
    for ruta in sorted((Path(vault) / "productos").glob("*/PRODUCTO.md")):
        try:
            meta, _ = frontmatter.leer(ruta)
        except (OSError, ValueError):
            continue
        for pais, b in ((meta or {}).get("paises") or {}).items():
            if isinstance(b, dict) and b.get("estado") in ("montado", "test"):
                salida.append((ruta.parent.name, str(pais)))
    return list(dict.fromkeys(salida))


def _montados_sin_registrar(vault: Path) -> list[tuple[str, str]]:
    """Resolución 12: producto-país en ``montado`` con ``trafico.activar`` y sin la activación registrada."""
    from trovefy.vault import frontmatter

    salida = []
    for ruta in sorted((Path(vault) / "productos").glob("*/PRODUCTO.md")):
        try:
            meta, _ = frontmatter.leer(ruta)
        except (OSError, ValueError):
            continue
        for pais, b in ((meta or {}).get("paises") or {}).items():
            t = (b or {}).get("trafico") if isinstance(b, dict) else None
            if isinstance(t, dict) and b.get("estado") == "montado" and t.get("activar") and not t.get("activado"):
                salida.append((ruta.parent.name, str(pais)))
    return salida


def _t0(vault: Path, producto: str, pais: str) -> datetime | None:
    from trovefy.vault import frontmatter
    from trovefy.vault.producto import ruta_producto

    try:
        meta, _ = frontmatter.leer(ruta_producto(vault, producto))
    except (OSError, ValueError):
        return None
    t = (((meta or {}).get("paises") or {}).get(pais) or {}).get("trafico") or {}
    vals = []
    for k in ("activado", "inicio"):
        try:
            f = datetime.fromisoformat(str(t.get(k)))
        except ValueError:
            continue
        if f.tzinfo:
            vals.append(f)
    return max(vals) if vals else None


def condicion(nombre: str, vault: Path, pais: str | None = None, ahora: datetime | None = None,
              catalogo: dict[str, Rutina] | None = None) -> int:
    """0 = toca lanzar; 1 = no toca (systemd la cuenta como «omitida», no como fallo)."""
    r = (catalogo or cargar_catalogo())[nombre]
    if r.condicion is None:
        return 0
    vivos = tests_vivos(vault)
    del_pais = [x for x in vivos if pais is None or x[1] == pais]
    if r.condicion == "test_vivo":
        pendientes = [x for x in _montados_sin_registrar(vault) if pais is None or x[1] == pais]
        return 0 if del_pais or pendientes else 1
    ahora = (ahora or datetime.now(ZONA_NEGOCIO)).astimezone(ZONA_NEGOCIO)
    for producto, p in del_pais:
        t0 = _t0(vault, producto, p)
        if t0 is None:
            continue
        dias = (ahora.date() - t0.astimezone(ZONA_NEGOCIO).date()).days
        if 1 <= dias < PLAZO_TEST_DIAS and dias % 2 == 1:  # sale a las 00:00 de las 48 h, 96 h, 144 h
            return 0
    return 1


def fin(nombre: str, vault: Path, resultado: str, codigo: str, ahora: datetime | None = None,
        pais: str | None = None, catalogo: dict[str, Rutina] | None = None) -> str | None:
    """Tras la rutina (``ExecStopPost``). Con éxito no hace nada (registra la skill); omitida por su condición lo anota
    sin avisar; con otro resultado lo deja en el log y deposita una alerta ``aviso``. Devuelve la línea anotada."""
    from trovefy.aprobaciones.fuentes import BuzonNoDisponible, depositar

    if resultado == "success":
        return None
    r = (catalogo or cargar_catalogo())[nombre]
    ahora = (ahora or datetime.now(ZONA_NEGOCIO)).astimezone(ZONA_NEGOCIO)
    log = nombre_log(r, pais)
    if resultado == OMITIDA:
        registrar_ejecucion(vault, log, ahora.date(), "omitida: no hay test vivo (o no toca hoy)", ok=True,
                            ahora=ahora, estado="omitida")
        return "omitida"
    texto = f"fallida: {resultado or '—'}/{codigo or '—'}"
    try:
        depositar(vault, {"tipo": "alerta", "origen": "/rutinas", "nivel": "aviso",
                          "titulo": f"Rutina {instancia(r, pais)} falló",
                          "texto": f"La rutina {instancia(r, pais)} falló a las {ahora:%H:%M} ({texto}). Revisa "
                                   f"rutinas/log/{ahora.date().isoformat()}/{log}.md o pregunta a /trovefy:vigia.",
                          "prioridad": "normal"}, lambda: ahora)
    except BuzonNoDisponible as exc:
        texto += f"; sin aviso por Telegram ({exc})"
    registrar_ejecucion(vault, log, ahora.date(), texto, ok=False, ahora=ahora, estado="fallida")
    return texto


def registrar_ejecucion(vault: Path, rutina: str, dia: date, texto: str, ok: bool,
                        ahora: datetime | None = None, estado: str | None = None) -> Path:
    """Añade el resumen a ``rutinas/log/<dia>/<rutina>.md``; deja ``<rutina>.ok`` solo si terminó bien.

    El marcador es **por rutina**: una rutina que falla no borra el «ok» de otra del mismo día.
    ``estado`` es la etiqueta de la entrada (por defecto «ok» o «parada»; p. ej. «interrumpida»)."""
    carpeta = Path(vault) / "rutinas" / "log" / dia.isoformat()
    ruta = carpeta / f"{rutina}.md"
    previo = ruta.read_text(encoding="utf-8") if ruta.exists() else f"# Rutina {rutina} · {dia.isoformat()}\n"
    hora = (ahora or datetime.now(ZONA_NEGOCIO)).astimezone(ZONA_NEGOCIO)
    estado = estado or ("ok" if ok else "parada")
    escribir_atomico(ruta, f"{previo.rstrip()}\n\n## {hora:%H:%M} COT · {estado}\n\n{texto.rstrip()}\n")
    marca = carpeta / f"{rutina}.ok"
    if ok:
        escribir_atomico(marca, f"{hora.isoformat()}\n")
    elif marca.exists():
        marca.unlink()
    return ruta


# --- instalar -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Plan:
    rutina: Rutina
    pais: str | None
    servicio: str
    timer: str

    @property
    def instancia(self) -> str:
        return instancia(self.rutina, self.pais)


def planificar(nombres: Sequence[str], vault: Path, claude: str, paises: Sequence[str] = (), *,
               catalogo: dict[str, Rutina] | None = None, meta_tools: object = "vault",
               trovefy: str | None = None, raiz: Path = RAIZ) -> tuple[list[Plan], list[str]]:
    """Valida todo antes de escribir nada: (unidades a escribir, problemas). Con problemas no se instala nada."""
    from trovefy.vault.permisos import leer_meta_tools

    catalogo = catalogo or cargar_catalogo()
    if meta_tools == "vault":
        try:
            meta_tools = leer_meta_tools(Path(vault))
        except (OSError, ValueError):
            meta_tools = None
    impul = catalogo_impultienda(raiz)
    trovefy = trovefy or buscar_trovefy()
    planes: list[Plan] = []
    problemas: list[str] = []
    vivos = en_marcha(vault)
    for nombre in nombres:
        r = catalogo.get(nombre)
        if r is None:
            problemas.append(f"{nombre}: no está en el catálogo de rutinas")
            continue
        if r.plantilla != "caza":
            problemas += validar_herramientas(r, allowed_de_skill(r.skill, raiz), meta_tools, impul)
        objetivos = list(paises) if r.por_pais else [None]
        if r.por_pais and not paises:
            problemas.append(f"{nombre}: va por país: di cuál con --pais XX")
        for pais in objetivos:
            zona = zona_pais(vault, pais) if pais else None
            producto = next((p for p, x in vivos if x == pais), None)
            if pais and "{zona}" in r.calendario and not zona:
                problemas.append(f"{nombre} {pais}: falta la zona del país en config/mercados.yaml")
                continue
            if pais and "{producto}" in r.argumentos and not producto:
                problemas.append(f"{nombre} {pais}: no hay test vivo en config/caja.yaml para saber el producto")
                continue
            try:
                s, t = unidades(r, Path(vault), claude, pais, zona=zona, producto=producto, trovefy=trovefy)
            except ValueError as exc:
                problemas.append(f"{nombre}: {exc}")
                continue
            planes.append(Plan(r, pais, s, t))
    return planes, list(dict.fromkeys(problemas))


def instalar(nombres: Sequence[str], vault: Path, claude: str, paises: Sequence[str] = (),
             ejecutar: Callable[[list[str]], None] | None = None, **kw) -> list[Path]:
    """Escribe las unidades en ``~/.config/systemd/user/`` y activa los timers. Si algo no valida, no escribe nada
    (``RutinaInvalida`` con todos los problemas)."""
    planes, problemas = planificar(nombres, vault, claude, paises, **kw)
    if problemas:
        raise RutinaInvalida("; ".join(problemas))
    ejecutar = ejecutar or _systemctl
    carpeta = directorio_unidades()
    rutas: list[Path] = []
    for p in planes:
        for sufijo, texto in ((".service", p.servicio), (".timer", p.timer)):
            ruta = carpeta / f"trovefy-{p.instancia}{sufijo}"
            escribir_atomico(ruta, texto)
            rutas.append(ruta)
    ejecutar(["systemctl", "--user", "daemon-reload"])
    for p in planes:
        ejecutar(["systemctl", "--user", "enable", "--now", f"trovefy-{p.instancia}.timer"])
    return rutas


def desinstalar(instancias: Sequence[str], ejecutar: Callable[[list[str]], None] | None = None) -> list[Path]:
    ejecutar = ejecutar or _systemctl
    carpeta = directorio_unidades()
    borradas = []
    for n in instancias:
        timer = carpeta / f"trovefy-{n}.timer"
        if timer.exists():
            ejecutar(["systemctl", "--user", "disable", "--now", timer.name])
        for ruta in (timer, carpeta / f"trovefy-{n}.service"):
            if ruta.exists():
                ruta.unlink()
                borradas.append(ruta)
    ejecutar(["systemctl", "--user", "daemon-reload"])
    return borradas


def instaladas(unidades_dir: Path | None = None) -> list[str]:
    """Instancias con su timer instalado (``caza``, ``cierre``, ``intradia-bg``…)."""
    carpeta = Path(unidades_dir or directorio_unidades())
    if not carpeta.is_dir():
        return []
    return sorted(p.name.removeprefix("trovefy-").removesuffix(".timer") for p in carpeta.glob("trovefy-*.timer"))


def rutina_de_instancia(inst: str, catalogo: dict[str, Rutina]) -> tuple[Rutina, str | None] | None:
    if inst in catalogo:
        return catalogo[inst], None
    base, _, pais = inst.rpartition("-")
    r = catalogo.get(base)
    if r is not None and r.por_pais and len(pais) == 2:
        return r, pais.upper()
    return None
