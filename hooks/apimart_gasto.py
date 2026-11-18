"""Hook PreToolUse: APIMart solo se llama con ``trovefy producto`` (tiene tope de gasto, contrato 7).

Rutas protegidas, comparadas **resueltas** (``..``, ``//``, enlaces, ``cd``, ``git -C``, ``~``/``$HOME``,
las grafías del vault y los globs, expandidos y como patrón), al modo de ``raw_inmutable``:

- ``productos/*/decisiones/*-tope-apimart.md``: solo las crea ``trovefy producto`` (Write/Edit y Bash).
- ``productos/*/PRODUCTO.md``: Write/Edit/MultiEdit no pueden cambiar ``apimart_tope_usd``; se compara el
  valor **parseado** antes y después (YAML del frontmatter con PyYAML si está; sin PyYAML, un lector
  conservador que da «ilegible» —y deniega— ante claves entre comillas con escapes, mapas de flujo,
  ``?``, ``<<``, anclas, claves repetidas o valores de varias líneas). El mismo valor con otras comillas
  pasa. Bash: se deniega reescribirlo (``>``, ``cp``, ``mv``, ``tee``, intérpretes…), añadirle algo que
  mencione el tope y ``sed -i`` que mencione el tope, use escapes o no muestre ninguna clave.
- ``config/producto.yaml``: no se escribe (lo decide el usuario).
- ``config/pantallas-confirmadas.yaml`` (I-1 del plan 18; la copia antigua, que ya no se lee): ni
  Write/Edit/MultiEdit ni Bash (``>``, ``cp``, ``mv``, ``tee``, ``sed -i``, intérpretes…), tampoco en bloque
  sobre ``config/``. Leerlo sí.
- ``config/evidencia/p05-*`` (F1-4 del plan 18): la evidencia de la sonda (``p05-impultienda-<fecha>.json``,
  de la que sale el hosting) y las capturas de las pantallas confirmadas; solo las escribe ``trovefy landing
  sonda|capturar``. Ni Write/Edit/MultiEdit ni Bash. Leerlas sí.
- La confirmación de pantallas (F1-1 del plan 18) vive en ``~/.config/trovefy/pantallas-confirmadas.yaml``
  (abajo) y la escribe solo el usuario, en su terminal: se deniega cualquier Bash que mencione
  ``landing capturar``, ``tienda.confirmacion``, ``confirmar_pantalla`` o ``capturar_pantalla`` (salvo un
  segmento de solo lectura/desarrollo: ``rg``, ``grep``, ``uv run pytest``, ``git log|diff|show|commit``…),
  y ``TROVEFY_VAULT=``/``env … TROVEFY_VAULT`` junto a ``trovefy landing sonda|publicar`` (un segundo vault).
- El libro de gasto: ``productos/*/entregable/costes.csv`` (también en subcarpetas),
  ``.apimart-intentos.jsonl`` y ``.apimart.lock``; sus carpetas (``entregable/``, el producto,
  ``productos/``, el vault) no se borran, mueven ni sobrescriben en bloque (``rm -r``, ``mv``, ``cp -r``,
  ``rsync``, intérpretes…). Por nombre, además, cualquier escritura que mencione esos archivos.
- ``productos/*/entregable/**/QC.md``, ``.QC.md.lock`` y ``entregable/**/*.pdf`` (M3 de las Tareas 11–12):
  solo los escribe ``trovefy producto``; ni Write/Edit/MultiEdit ni Bash (``>``, ``cp``, ``mv``, ``rm``,
  ``sed -i``, intérpretes…), tampoco en bloque sobre una carpeta que los contenga. Leerlos sí.
- El registro de los mensajes del usuario (``~/.config/trovefy/mensajes-usuario.json``, plan 19, Tarea 11), que
  prueba que una aprobación de `trovefy checkout aprobar` es suya: solo lo escribe el hook ``UserPromptSubmit``. Se
  deniega cualquier Bash que importe ``trovefy.checkout.mensajes``, llame a ``registrar_mensaje``, nombre el
  archivo o lance ``hooks/mensaje_usuario.py`` (salvo un segmento de solo lectura/desarrollo, como arriba).
- El checkout por el MCP (C1 de la revisión de la Tarea 11 del 19): ``productos/*/checkout/*/{APROBACION.md,
  PLAN-MCP.json,PLAN-MCP.md,MCP-ESTADO.json,COMPROBACION.md,CHECKOUT.md}`` y ``checkout/*/mcp/**`` (el historial de
  etapas y las citas usadas) solo los escribe ``trovefy checkout …``: ni Write/Edit/MultiEdit/NotebookEdit ni Bash,
  tampoco en bloque. Leerlos sí. Y ``trovefy checkout aprobar`` (H2) lo ejecuta solo el usuario en su terminal: se
  deniega cualquier Bash que lo lance (``uv run``, ``python -m``, ``script``, ``unbuffer``, ``expect``, ``pty``,
  ``cli.main([...])``) o importe ``checkout.mcp_cli``/``hay_terminal`` (salvo un segmento de solo lectura/desarrollo).
- ``.trovefy/STOP``: crearlo sí; borrarlo o moverlo no (lo quita el usuario).
- ``git checkout|restore|stash|reset|clean|switch…`` con el vault como directorio (cwd, ``cd``, ``-C``) o
  sobre una ruta del vault cuentan como escritura y se deniegan.
- ``~/.config/trovefy`` y lo que cuelga de él: ni Read, ni Grep (``path`` y ``glob``), ni Write/Edit/
  MultiEdit/NotebookEdit, ni Bash (``cat``, ``grep``, ``head``, globs, ``grep -r`` sobre ``~/.config``…),
  salvo un segmento que empieza por ``trovefy …`` (o ``uv run trovefy …``) y no redirige hacia allí.

Escrituras por Bash que se reconocen (F1-2): ``>``, ``>>``, ``>|``, ``tee``, ``sed -i``, ``cp``/``mv``/
``install``/``ln`` (también ``-t DIR``/``--target-directory``: ``DIR/<nombre del origen>``), ``curl -o|-O``,
``wget`` (``-O``, o el nombre de la URL), ``awk`` con ``print >``/``|``/``system``, ``rm``, ``tar``…; y una
palabra con llaves ``{a,b}`` cuenta con todas sus expansiones.

Bash que menciona APIMart (``apimart.ai``, ``APIMART…``, ``trovefy.apimart``, ``claude.env`` o
``apimart_tope_usd``; el comando se normaliza: sin comillas ni barras invertidas, y decodificado ``%xx``):
se deniega con ``$(…)``, comillas invertidas, ``<(…)``, ``>(…)``, ``&`` suelto o un intérprete. Cada
segmento que lo menciona debe empezar por ``trovefy producto`` o ser de solo lectura/desarrollo
(``uv run pytest``, ``ruff``, ``rg``, ``grep``, ``git log|diff|show|commit`` sin ``--pre``/``--output``…);
eso se mira **antes** que la regla de ``claude.env`` (``git commit -m "…claude.env…"`` y
``rg claude.env`` pasan; ``cat`` sobre ``claude.env`` no, y la clave real ya la cubre la regla de ruta).
El cuerpo del heredoc de ``trovefy producto anotar-qc … <<'FIN'`` (delimitador entrecomillado: bash no
expande nada) es la respuesta del agente: se analiza solo la primera línea y lo que siga a la de cierre.

WebFetch: deniega ``apimart.ai`` y sus subdominios salvo ``docs.apimart.ai`` (ruling R-D). Solo biblioteca
estándar (PyYAML opcional); falla cerrado. Idea tomada del ``guard.mjs`` de LordVayron/video-factory
(MIT, commit 8afd1b2e). Los rodeos deliberados (cadenas construidas, importlib) quedan fuera (ruling): la
defensa real está en el código (``tope_de``, ``leer_costes``, STOP).
"""
from __future__ import annotations

import fnmatch
import os
import pathlib
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote, urlsplit

from _comun import (
    _SEGMENTOS,
    SEPARADORES_RUTA,
    bases_vault,
    bash_destructivo,
    coincide_patron,
    directorios_recorridos,
    ejecutar_guardia,
    es_ancestro_de_patron,
    herramienta,
    parte_coincide,
    resolver,
    rutas_de_ficha,
    tiene_glob,
    vault_root,
)

try:  # el python3 del sistema puede no tenerlo: entonces, el lector conservador
    import yaml
except ImportError:  # pragma: no cover - depende del intérprete
    yaml = None

MOTIVO = "APIMart solo se llama con `trovefy producto`: tiene tope de gasto"
MOTIVO_CLAVE = "claude.env guarda la clave de APIMart: solo la lee `trovefy producto`"
MOTIVO_CONF = "~/.config/trovefy guarda las claves: solo lo lee `trovefy …`; ni Read, ni Grep, ni cat"
MOTIVO_TOPE = "el tope de APIMart solo lo sube `trovefy producto` con la cita literal del usuario"
MOTIVO_CONFIG = "config/producto.yaml no se edita desde Claude: sus valores los decide el usuario"
MOTIVO_PANTALLAS = ("las confirmaciones de pantalla las escribe solo `trovefy landing capturar`, lanzado por el "
                    "usuario en su terminal con la pantalla delante: no se crean, editan, mueven ni borran a mano")
MOTIVO_CAPTURAR = ("`trovefy landing capturar` (la confirmación de la pantalla) lo ejecuta el usuario en su "
                   "terminal, no Claude: dale la orden y espera a que te diga que terminó")
MOTIVO_MENSAJES = ("el registro de tus mensajes (la prueba de que una aprobación es tuya) solo lo escribe el hook al "
                   "enviar tú un mensaje: Claude no lo escribe ni lanza ese hook a mano")
MOTIVO_OTRO_VAULT = ("`trovefy landing sonda|publicar` se lanza con el vault de siempre, sin cambiar TROVEFY_VAULT: "
                     "lo ejecuta el usuario en su terminal")
MOTIVO_EVIDENCIA = ("config/evidencia/p05-* (la evidencia de la sonda y las capturas de las pantallas confirmadas) "
                    "solo la escriben `trovefy landing sonda|capturar`: no se crea, edita, mueve ni borra a mano")
MOTIVO_GASTO = ("costes.csv, .apimart-intentos.jsonl y .apimart.lock (y su carpeta entregable/) son el registro del "
                "gasto: solo los escribe `trovefy producto`; no se editan, mueven ni borran (si algo falla, pide ayuda)")
MOTIVO_STOP = ".trovefy/STOP lo quita el usuario: Claude no lo borra ni lo mueve"
MOTIVO_QC = ("QC.md, su cerrojo y los PDF del entregable solo los escribe `trovefy producto` (maquetar, qc, "
             "anotar-qc): no se editan, crean, mueven ni borran a mano")
MOTIVO_GIT = ("git checkout/restore/stash/reset/clean sobre el vault puede reescribir el registro del gasto, el tope "
              "o STOP: si hace falta, que lo haga el usuario")
MOTIVO_CHECKOUT = ("el plan del MCP, su aprobación, el estado, la comprobación, CHECKOUT.md y el historial "
                   "checkout/<PAIS>/mcp/ solo los escribe `trovefy checkout …`: no se crean, editan, mueven ni borran "
                   "a mano")
MOTIVO_APROBAR = ("`trovefy checkout aprobar` (tu «sí» al plan del MCP) lo ejecutas tú en tu terminal, fuera de "
                  "Claude, con la frase del resumen: Claude no lo ejecuta (ni con script, unbuffer, expect o pty)")

_MENCION = re.compile(
    r"(?i:apimart\.ai|trovefy\.apimart|from\s+trovefy\s+import\s+apimart|claude\.env|apimart_tope_usd)|APIMART")
_CLAUDE_ENV = re.compile(r"claude\.env", re.IGNORECASE)
_TOPE = re.compile(r"apimart_tope_usd", re.IGNORECASE)
_TOPE_SUELTO = re.compile(r"tope", re.IGNORECASE)
_TROVEFY = re.compile(r"(?:uv\s+run\s+)?trovefy\s+producto(?:\s|$)")
_TROVEFY_CUALQUIERA = re.compile(r"(?:uv\s+run\s+)?trovefy(?:\s|$)")
_LECTURA = re.compile(r"(?:uv\s+run\s+(?:pytest|ruff)|ruff|rg|grep|git\s+(?:log|diff|show|commit))(?:\s|$)")
_OPCION_PELIGROSA = re.compile(r"--(?:pre|pre-glob|output|ext-diff|textconv|exec)\b")
_SUBCOMANDO = re.compile(r"\$\(|`|<\(|>\(")
_REDIRECCION_FD = re.compile(r"\d*>&\d*-?|&>>?|\d?>\s*/dev/null")
_INTERPRETE = re.compile(
    r"(?:sudo\s+)?(?:sh|bash|zsh|dash|ksh|fish|python[\d.]*|perl|ruby|node|deno|bun|php|xargs|eval|source|\.|exec"
    r"|env|printenv|nohup|timeout|parallel|busybox|uv\s+run\s+python[\d.]*)(?:\s|$)")
_GASTO = re.compile(r"costes\.csv|\.apimart-intentos\.jsonl|\.apimart\.lock", re.IGNORECASE)
_CAPTURAR = re.compile(r"landing\w*\s+capturar|tienda\.confirmacion|tienda\s+import\s+confirmacion"
                       r"|confirmar_pantalla|capturar_pantalla")
# El registro de los mensajes del usuario (plan 19, Tarea 11): solo lo escribe el hook UserPromptSubmit.
_MENSAJES = re.compile(r"checkout\.mensajes|checkout\s+import\s+mensajes|registrar_mensaje|mensajes-usuario"
                       r"|mensaje_usuario\.py")
# H2 de la revisión de la Tarea 11 del 19: `trovefy checkout aprobar` solo lo ejecuta el usuario, en su terminal.
# Cualquier forma: `uv run`, `python -m`, `script`, `unbuffer`, `expect`, `pty`, `cli.main([...])`, importar mcp_cli.
_APROBAR = re.compile(r"\bcheckout\w*\b.*\baprobar\b|checkout\.mcp_cli\b|\bimport\s+mcp_cli\b|\bhay_terminal\b")
_OTRO_VAULT = re.compile(r"\bTROVEFY_VAULT\s*=|\benv\b[^;&|\n]*\bTROVEFY_VAULT\b")
_SONDA_PUBLICAR = re.compile(r"landing\w*\s+(?:sonda|publicar)\b")
_ARCHIVOS_GASTO = (".apimart-intentos.jsonl", ".apimart.lock")

# Patrones relativos al vault (componentes; ``*`` es un componente cualquiera, ``**`` cero o más).
_LIBRO = (("productos", "*", "entregable", "costes.csv"),
          ("productos", "*", "entregable", ".apimart-intentos.jsonl"),
          ("productos", "*", "entregable", ".apimart.lock"),
          ("productos", "*", "entregable", "**", "costes.csv"))
_DECISION = (("productos", "*", "decisiones", "*-tope-apimart.md"),)
_CONFIG = (("config", "producto.yaml"),)
_PANTALLAS = (("config", "pantallas-confirmadas.yaml"),)  # I-1 del plan 18: la confirmación exige un humano
_EVIDENCIA = (("config", "evidencia", "p05-*"),)  # F1-4 del plan 18: la sonda y las capturas confirmadas
_STOP = ((".trovefy", "STOP"),)
_PRODUCTO = (("productos", "*", "PRODUCTO.md"),)
# M3 (Tareas 11–12): el registro de QC y los PDF que el cierre da por buenos. Solo `trovefy producto`.
_QC = (("productos", "*", "entregable", "**", "QC.md"),
       ("productos", "*", "entregable", "**", ".QC.md.lock"),
       ("productos", "*", "entregable", "**", "*.[pP][dD][fF]"))
_QC_NOMBRE = re.compile(r"(?:QC\.md|\.QC\.md\.lock|.*\.pdf)", re.IGNORECASE)
# C1 (revisión de la Tarea 11 del 19): el plan del MCP, su aprobación y lo que resulta de aplicarlo. Solo
# `trovefy checkout …`.
_CHECKOUT_MCP = tuple(("productos", "*", "checkout", "*", nombre) for nombre in (
    "APROBACION.md", "PLAN-MCP.json", "PLAN-MCP.md", "MCP-ESTADO.json", "COMPROBACION.md", "CHECKOUT.md")) + (
    ("productos", "*", "checkout", "*", "mcp", "**"),)
_QC_MAX_RECORRIDO = 5000

# Clases de escritura de cada ruta alcanzada por un comando.
_EN_BLOQUE = frozenset({"borra", "mueve", "copia_r", "rsync", "git", "interprete", "bloque"})
_QUITA = frozenset({"borra", "mueve", "rsync", "git", "interprete"})
_GIT_ESCRIBE = frozenset({"checkout", "restore", "stash", "reset", "clean", "switch", "rm", "mv", "pull", "merge",
                          "rebase", "cherry-pick", "revert", "apply", "am", "read-tree", "checkout-index",
                          "filter-branch", "filter-repo"})
_GIT_OPCION_CON_VALOR = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"})
_REDIRECCION = re.compile(r"(?:\d*|&)(>>|>\|?)\s*([^\s;&|()<>]+)")
_ESCAPES = re.compile(r"\\|\$'|\bprintf\b|\becho\s+-\w*e")
_CLAVE_VISIBLE = re.compile(r"[A-Za-z_][\w-]*\s*:")


def _normalizar(comando: str) -> str:
    """Sin comillas ni barras invertidas, y ``>|`` como ``>`` (antes de partir por ``|``)."""
    return re.sub(r">\s*\|", ">", re.sub(r"[\"'\\]", "", comando))


def _host(url: str) -> str:
    try:
        return (urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _fondo(comando: str) -> bool:
    """¿Hay un ``&`` suelto (segundo plano), sin contar ``&&`` ni las redirecciones ``2>&1``/``&>``?"""
    return "&" in _REDIRECCION_FD.sub(" ", comando).replace("&&", " ")


def _escribe(comando: str) -> bool:
    limpio = re.sub(r"\d?>\s*/dev/null", " ", comando)
    return bash_destructivo(limpio) or ">>" in limpio or bool(re.search(r"\bdd\b|\bshred\b|\bunlink\b", limpio))


def _segmentos(comando: str) -> list[str]:
    return [s.strip() for s in _SEGMENTOS.split(comando) if s.strip()]


# --- Qué rutas escribe cada segmento ---------------------------------------------------------------------

def _palabras(segmento: str) -> list[str]:
    """Palabras del segmento sin ``sudo``/``command``/``time`` ni asignaciones ``VAR=x`` iniciales."""
    palabras = segmento.split()
    while palabras and (palabras[0] in ("sudo", "command", "builtin", "time")
                        or re.fullmatch(r"[A-Za-z_]\w*=\S*", palabras[0])):
        palabras.pop(0)
    return palabras


def _subcomando_git(palabras: list[str]) -> str | None:
    i = 1
    while i < len(palabras):
        p = palabras[i]
        if p in _GIT_OPCION_CON_VALOR:
            i += 2
            continue
        if p.startswith("-"):
            i += 1
            continue
        return p
    return None


def _fichas(texto: str) -> list[str]:
    return [f for f in SEPARADORES_RUTA.split(texto) if f and not f.startswith("-")]


_LLAVES = re.compile(r"\{([^{}]*,[^{}]*)\}")
_MAX_LLAVES = 64


def _expandir_llaves(palabra: str) -> list[str]:
    """Las expansiones de ``{a,b}`` de una palabra (como bash, hasta ``_MAX_LLAVES``); ``[]`` si no tiene."""
    if not _LLAVES.search(palabra):
        return []
    pendientes, hechas = [palabra], []
    while pendientes and len(hechas) + len(pendientes) <= _MAX_LLAVES:
        p = pendientes.pop()
        m = _LLAVES.search(p)
        if m is None:
            hechas.append(p)
            continue
        pendientes += [p[:m.start()] + alt + p[m.end():] for alt in m.group(1).split(",")]
    return hechas + pendientes


def _fichas_con_llaves(texto: str) -> list[str]:
    """``_fichas`` más las de cada expansión de llaves (``cp x ~/.config/{trovefy,y}/z``)."""
    salida = _fichas(texto)
    for palabra in texto.split():
        for exp in _expandir_llaves(palabra):
            salida += _fichas(exp)
    return salida


def _dir_destino(palabras: list[str]) -> str | None:
    """El ``DIR`` de ``-t DIR``, ``-tDIR`` o ``--target-directory[=]DIR`` (cp, mv, install, ln)."""
    for i, w in enumerate(palabras):
        if w in ("-t", "--target-directory") and i + 1 < len(palabras):
            return palabras[i + 1]
        if w.startswith("--target-directory="):
            return w.split("=", 1)[1]
        if re.fullmatch(r"-[a-zA-Z]*t\S+", w) and not w.startswith("--"):
            return w[w.index("t", 1) + 1:]
    return None


def _nombre_url(url: str) -> str | None:
    if "://" not in url:
        return None
    nombre = url.split("?", 1)[0].split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return nombre or None


def _valor_corto(palabras: list[str], letra: str, largas: tuple[str, ...]) -> list[str]:
    """Valores de una opción con argumento: ``-o X``, ``-oX``, ``-so X`` (agrupada), ``--output X``,
    ``--output=X``."""
    valores = []
    for i, w in enumerate(palabras):
        siguiente = palabras[i + 1] if i + 1 < len(palabras) else None
        if w in largas and siguiente:
            valores.append(siguiente)
        elif any(w.startswith(f"{larga}=") for larga in largas):
            valores.append(w.split("=", 1)[1])
        elif re.fullmatch(r"-[a-zA-Z]+\S*", w) and not w.startswith("--") and letra in w[1:]:
            j = w.index(letra, 1)
            if not w[1:j].isalpha():
                continue
            resto = w[j + 1:]
            if resto:
                valores.append(resto)
            elif siguiente:
                valores.append(siguiente)
    return valores


def _descargas(orden: str, palabras: list[str]) -> list[str]:
    """Archivos que escriben ``curl``/``wget``."""
    urls = [w for w in palabras[1:] if "://" in w]
    if orden == "curl":
        destinos = _valor_corto(palabras, "o", ("--output",))
        remoto = any(w in ("--remote-name", "--remote-name-all") or
                     (re.fullmatch(r"-[a-zA-Z]+", w) and "O" in w) for w in palabras[1:])
        carpeta = (_valor_corto(palabras, "\0", ("--output-dir",)) or [None])[0]
    else:
        destinos = (_valor_corto(palabras, "O", ("--output-document",))
                    + _valor_corto(palabras, "o", ("--output-file",))
                    + _valor_corto(palabras, "a", ("--append-output",)))
        remoto = not _valor_corto(palabras, "O", ("--output-document",))
        carpeta = (_valor_corto(palabras, "P", ("--directory-prefix",)) or [None])[0]
    if remoto:
        for u in urls:
            if (nombre := _nombre_url(u)) is not None:
                destinos.append(f"{carpeta}/{nombre}" if carpeta else nombre)
    return destinos


def _objetivos(c: str) -> tuple[list[tuple[str, str, str]], bool]:
    """``([(ficha, clase, segmento)], hay_git_que_escribe)`` de un comando ya normalizado.

    Clases: ``redir`` (``>``), ``anade`` (``>>``, ``tee -a``), ``tee``, ``sed``, ``borra``, ``mueve``,
    ``copia``, ``copia_r``, ``rsync``, ``git``, ``interprete``, ``escribe`` y ``bloque`` (tar/unzip).
    """
    objetivos: list[tuple[str, str, str]] = []
    git = False
    segmentos = _segmentos(c)
    if any(_INTERPRETE.match(s) for s in segmentos):  # un intérprete puede escribir cualquier ruta del comando
        objetivos += [(f, "interprete", c) for f in _fichas_con_llaves(c)]
    for seg in segmentos:
        antes = len(objetivos)
        for m in _REDIRECCION.finditer(seg):
            destino = m.group(2).rstrip("})")
            if destino.startswith("&") or destino == "/dev/null":
                continue
            objetivos.append((destino, "anade" if m.group(1) == ">>" else "redir", seg))
        sin_redir = _REDIRECCION.sub(" ", seg)
        palabras = _palabras(sin_redir)
        if not palabras:
            continue
        orden = os.path.basename(palabras[0])
        args = _fichas(" ".join(palabras[1:]))
        opciones = [p for p in palabras[1:] if p.startswith("-")]
        if orden in ("rm", "rmdir", "unlink", "shred"):
            objetivos += [(a, "borra", seg) for a in args]
        elif orden == "mv":
            objetivos += [(a, "mueve", seg) for a in args]
            objetivos += [(f"{d}/{os.path.basename(a)}", "mueve", seg) for d in args for a in args if a != d]
        elif orden in ("curl", "wget"):
            objetivos += [(a, "escribe", seg) for a in _descargas(orden, palabras)]
        elif orden in ("awk", "gawk", "mawk", "nawk") and re.search(r">|\||\bsystem\b", seg):
            objetivos += [(f, "interprete", seg) for f in re.split(r"[\s;&|()<>`=,{}]+", seg) if f
                          and not f.startswith("-")]
        elif orden in ("cp", "install", "ln", "rsync"):
            recursivo = orden == "rsync" or any(re.fullmatch(r"-[a-zA-Z]*[rRa][a-zA-Z]*|--recursive|--archive", o)
                                                for o in opciones)
            clase = "rsync" if orden == "rsync" else ("copia_r" if recursivo else "copia")
            dir_t = _dir_destino(palabras[1:]) if orden != "rsync" else None
            if dir_t is not None:  # -t DIR: DIR/<nombre de cada origen>
                origenes = [a for a in args if a != dir_t]
                objetivos.append((dir_t, clase, seg))
                objetivos += [(f"{dir_t}/{os.path.basename(a.rstrip('/'))}", clase, seg) for a in origenes]
            elif args:
                destino = args[-1]
                objetivos.append((destino, clase, seg))
                objetivos += [(f"{destino}/{os.path.basename(a)}", clase, seg) for a in args[:-1]]
            if orden == "rsync" and "--remove-source-files" in palabras:
                objetivos += [(a, clase, seg) for a in args]
        elif orden in ("truncate", "touch", "dd", "chmod", "chown", "patch"):
            objetivos += [(a, "escribe", seg) for a in args]
        elif orden in ("tar", "unzip", "cpio"):
            objetivos += [(a, "bloque", seg) for a in args]
        elif orden == "tee":
            anade = any(re.fullmatch(r"-[a-zA-Z]*a[a-zA-Z]*|--append", o) for o in opciones)
            objetivos += [(a, "anade" if anade else "tee", seg) for a in args]
        elif orden == "sed" and any(re.fullmatch(r"-[a-zA-Z]*i\S*|--in-place\S*", o) for o in opciones):
            objetivos += [(a, "sed", seg) for a in args]
        elif orden == "find" and re.search(r"\s-(?:delete|exec|execdir|ok|okdir)\b", seg):
            objetivos += [(a, "borra", seg) for a in args]
        elif orden == "git" and _subcomando_git(palabras) in _GIT_ESCRIBE:
            git = True
            objetivos += [(a, "git", seg) for a in args]
        if len(objetivos) > antes:  # un segmento que escribe: cada expansión de llaves cuenta (F1-2)
            objetivos += [(f, "bloque", seg) for palabra in seg.split() for exp in _expandir_llaves(palabra)
                          for f in _fichas(exp)]
    return objetivos, git


def _partes_en_vault(ruta: pathlib.Path, vault_res: pathlib.Path) -> tuple[str, ...] | None:
    """Componentes relativos al vault; ``()`` si es el vault o un antecesor suyo; ``None`` si está fuera."""
    try:
        return ruta.relative_to(vault_res).parts
    except ValueError:
        pass
    try:
        vault_res.relative_to(ruta)
    except ValueError:
        return None
    return ()


def _toca(partes: tuple[str, ...], patrones: tuple[tuple[str, ...], ...], en_bloque: bool) -> bool:
    if any(coincide_patron(partes, p) for p in patrones):
        return True
    return en_bloque and any(es_ancestro_de_patron(partes, p) for p in patrones)


def _contiene_qc(ruta: pathlib.Path, partes: tuple[str, ...]) -> bool:
    """¿Una operación en bloque sobre ``ruta`` (``rm -r``, ``mv``, ``cp -r``…) alcanza QC.md o un PDF?

    Solo dentro de ``productos/``; se mira en disco (como mucho ``_QC_MAX_RECORRIDO`` entradas; si hay
    más, se da por alcanzado: falla cerrado)."""
    if len(partes) < 2 or partes[0] != "productos" or not ruta.is_dir():
        return False
    vistos = 0
    for _raiz, _dirs, archivos in os.walk(ruta):
        vistos += len(archivos) + len(_dirs)
        if any(_QC_NOMBRE.fullmatch(a) for a in archivos) or vistos > _QC_MAX_RECORRIDO:
            return True
    return False


def _sed_cambia_tope(original: str, segmento: str) -> bool:
    """¿Este ``sed -i`` puede cambiar el tope? Sí si lo menciona, usa escapes o no muestra ninguna clave."""
    if _TOPE_SUELTO.search(original) or "\\" in original:
        return True
    return not _CLAVE_VISIBLE.search(segmento)


def _bash_rutas(original: str, c: str, cwd: str | None) -> str | None:
    """Motivo de denegación si el comando escribe una ruta protegida del vault; ``None`` si no."""
    vault = vault_root()
    vault_res = vault.resolve(strict=False)
    bases = bases_vault(vault, vault_res)
    objetivos, git = _objetivos(c)
    dirs = directorios_recorridos(c, bases, vault_res, cwd)
    if git and any(_partes_en_vault(d, vault_res) is not None for d in dirs):
        return MOTIVO_GIT
    for ficha, clase, seg in objetivos:
        en_bloque = clase in _EN_BLOQUE
        for ruta in rutas_de_ficha(ficha, dirs, bases, vault_res):
            partes = _partes_en_vault(ruta, vault_res)
            if partes is None:
                continue
            if clase == "git":
                return MOTIVO_GIT
            if _toca(partes, _LIBRO, en_bloque):
                return MOTIVO_GASTO
            if _toca(partes, _DECISION, en_bloque):
                return MOTIVO_TOPE
            if _toca(partes, _CONFIG, en_bloque):
                return MOTIVO_CONFIG
            if _toca(partes, _PANTALLAS, en_bloque):
                return MOTIVO_PANTALLAS
            if _toca(partes, _EVIDENCIA, en_bloque):
                return MOTIVO_EVIDENCIA
            if _toca(partes, _QC, False) or (en_bloque and _contiene_qc(ruta, partes)):
                return MOTIVO_QC
            if _toca(partes, _CHECKOUT_MCP, en_bloque):
                return MOTIVO_CHECKOUT
            if clase in _QUITA and _toca(partes, _STOP, True):
                return MOTIVO_STOP
            if any(coincide_patron(partes, p) for p in _PRODUCTO):
                if clase == "anade" and not (_TOPE_SUELTO.search(original) or _ESCAPES.search(original)):
                    continue
                if clase == "sed" and not _sed_cambia_tope(original, seg):
                    continue
                return MOTIVO_TOPE
    return None


# --- ~/.config/trovefy -----------------------------------------------------------------------------------

def _conf() -> pathlib.Path:
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return resolver(os.path.join(home, ".config", "trovefy"), None)


def _relacion_conf(ruta: pathlib.Path) -> str | None:
    """``"dentro"`` si ``ruta`` (quizá con glob) está en ``~/.config/trovefy``; ``"ancestro"``; o ``None``."""
    conf = _conf().parts
    partes = ruta.parts
    n = min(len(partes), len(conf))
    if not all(parte_coincide(a, b) for a, b in zip(partes[:n], conf[:n], strict=True)):
        return None
    return "dentro" if len(partes) >= len(conf) else "ancestro"


_RECURSIVO = re.compile(r"(?:^|\s)(?:-[a-zA-Z]*[rRa][a-zA-Z]*|--recursive|--archive)(?=\s|$)")
_RECORRE = frozenset({"rg", "find", "tar", "zip", "rsync", "tree", "du", "fd", "ag", "ack"})


def _bash_conf(c: str, cwd: str | None) -> bool:
    """¿Algún segmento (que no sea ``trovefy …``) alcanza ``~/.config/trovefy``?"""
    vault = vault_root()
    vault_res = vault.resolve(strict=False)
    bases = bases_vault(vault, vault_res)
    dirs = directorios_recorridos(c, bases, vault_res, cwd)
    for seg in _segmentos(c):
        if _TROVEFY_CUALQUIERA.match(seg):  # `trovefy …` lee su config, pero no se le redirige la salida allí
            fichas = [m.group(2).rstrip("})") for m in _REDIRECCION.finditer(seg)]
            if any(_relacion_conf(r) for f in fichas for r in rutas_de_ficha(f, dirs, bases, vault_res)):
                return True
            continue
        palabras = _palabras(seg)
        recorre = bool(palabras) and (os.path.basename(palabras[0]) in _RECORRE or bool(_RECURSIVO.search(seg)))
        for ficha in _fichas_con_llaves(seg):
            for ruta in rutas_de_ficha(ficha, dirs, bases, vault_res):
                relacion = _relacion_conf(ruta)
                if relacion == "dentro" or (relacion == "ancestro" and recorre and len(ruta.parts) > 1):
                    return True
    return False


def _grep_conf(datos: dict, cwd: str | None) -> bool:
    ruta = datos.get("path")
    destino = resolver(ruta if isinstance(ruta, str) and ruta else (cwd or os.getcwd()), cwd)
    relacion = _relacion_conf(destino)
    if relacion == "dentro":
        return True
    if relacion is None:
        return False
    patron = datos.get("glob")
    if not isinstance(patron, str) or not patron.strip():
        return True
    conf = _conf()
    nombres = ["claude.env", "x.env"]
    try:
        nombres += [p.name for p in conf.iterdir()]
    except OSError:
        pass
    for nombre in nombres:
        completo = os.path.relpath(conf / nombre, destino)
        if fnmatch.fnmatchcase(nombre, patron) or fnmatch.fnmatchcase(completo, patron):
            return True
    return bool(re.search(r"trovefy|\.config|env", patron, re.IGNORECASE)) or tiene_glob(patron) and "**" in patron


# --- Bash -----------------------------------------------------------------------------------------------

_ANOTAR_QC_HEREDOC = re.compile(
    r"(?:^|&&|\|\||[;|(])\s*(?:uv\s+run\s+)?trovefy\s+producto\s+anotar-qc\s[^;&|<>\n]*<<(-?)\s*(['\"])(\w+)\2")


def _sin_cuerpo_qc(comando: str) -> str:
    """Quita el cuerpo del heredoc de ``trovefy producto anotar-qc … <<'FIN'`` (ruling de la revisión final).

    Con el delimitador entrecomillado bash no expande nada en el cuerpo: es la respuesta del agente, datos.
    Queda la primera línea entera y lo que siga a la línea de cierre. Solo si la primera línea tiene un
    único ``<<``; con el delimitador sin comillas (o cualquier otra forma) el comando se analiza entero.
    """
    primera, salto, resto = comando.partition("\n")
    if not salto or primera.count("<<") != 1:
        return comando
    m = _ANOTAR_QC_HEREDOC.search(primera)
    if not m:
        return comando
    tabs, delim = m.group(1) == "-", m.group(3)
    lineas = resto.split("\n")
    for i, linea in enumerate(lineas):
        if (linea.lstrip("\t") if tabs else linea) == delim:
            return "\n".join([primera, *lineas[i + 1:]])
    return primera  # sin línea de cierre, bash lee el cuerpo hasta el final


def _capturar(c: str, segmentos: list[str], patron: re.Pattern[str] = _CAPTURAR) -> bool:
    """¿El comando lanza (o importa) la confirmación de pantallas? Solo la lanza el usuario (F1-1). Con
    ``patron=_MENSAJES``: ¿toca el registro de los mensajes del usuario? Solo lo escribe su hook (Tarea 11 del 19)."""
    if not patron.search(c):
        return False
    if _SUBCOMANDO.search(c) or _fondo(c):
        return True
    for seg in segmentos:
        if _INTERPRETE.match(seg) or patron.search(seg) and not (
                _LECTURA.match(seg) and not _OPCION_PELIGROSA.search(seg) and not _escribe(seg)):
            return True
    return False


def _bash(comando: str, cwd: str | None = None) -> tuple[str, str]:
    comando = _sin_cuerpo_qc(comando)
    for variante in dict.fromkeys((comando, unquote(comando))):
        c = _normalizar(variante)
        segmentos = _segmentos(c)
        if _capturar(c, segmentos):
            return "deny", MOTIVO_CAPTURAR
        if _capturar(c, segmentos, _MENSAJES):
            return "deny", MOTIVO_MENSAJES
        if _capturar(c, segmentos, _APROBAR):
            return "deny", MOTIVO_APROBAR
        if _OTRO_VAULT.search(c) and _SONDA_PUBLICAR.search(c):
            return "deny", MOTIVO_OTRO_VAULT
        motivo = _bash_rutas(variante, c, cwd)
        if motivo:
            return "deny", motivo
        if _bash_conf(c, cwd):
            return "deny", MOTIVO_CONF
        if _GASTO.search(c) and (_escribe(c) or any(_INTERPRETE.match(s) for s in segmentos)):
            return "deny", MOTIVO_GASTO
        if not _MENCION.search(c):
            continue
        if _SUBCOMANDO.search(c) or _fondo(c):
            return "deny", MOTIVO
        for seg in segmentos:
            if not _MENCION.search(seg):
                if _INTERPRETE.match(seg):  # p. ej. `rg -o 'curl …apimart.ai…' x | sh`
                    return "deny", MOTIVO
                continue
            if _TROVEFY.match(seg):
                continue
            if _LECTURA.match(seg) and not _OPCION_PELIGROSA.search(seg) and not _escribe(seg):
                continue  # la clave real ya la cubre _bash_conf (por ruta)
            if _CLAUDE_ENV.search(seg):
                return "deny", MOTIVO_CLAVE
            return "deny", MOTIVO_TOPE if _TOPE.search(seg) else MOTIVO
    return "allow", ""


# --- El tope de PRODUCTO.md, parseado ---------------------------------------------------------------------

_ILEGIBLE = object()
_APERTURA = re.compile(r"---\r?\n")  # los mismos delimitadores que trovefy.vault.frontmatter.leer
_CIERRE = re.compile(r"\r?\n---\r?\n")
_NULOS = ("", "~", "null", "Null", "NULL")


def _frontmatter(texto: str) -> str | None:
    abre = _APERTURA.match(texto)
    if not abre:
        return None
    resto = texto[abre.end():]
    if _APERTURA.match(resto):
        return None
    cierre = _CIERRE.search(resto)
    return None if cierre is None else resto[: cierre.start()]


def _canonico(valor: object) -> object:
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        return ("crudo", repr(valor))
    try:
        d = Decimal(str(valor).strip())
    except InvalidOperation:
        return ("crudo", str(valor))
    return d if d.is_finite() else ("crudo", str(valor))


if yaml is not None:
    class _Cargador(yaml.SafeLoader):
        """SafeLoader (como ``frontmatter.leer``) que no admite claves repetidas en un mapa."""

        def construct_mapping(self, node, deep=False):
            vistas = set()
            for clave, _ in node.value:
                if isinstance(clave, yaml.ScalarNode):
                    if clave.value in vistas:
                        raise yaml.constructor.ConstructorError(None, None, "clave repetida", clave.start_mark)
                    vistas.add(clave.value)
            return super().construct_mapping(node, deep)


def _tope_con_yaml(fm: str) -> object:
    try:
        datos = yaml.load(fm, Loader=_Cargador)
    except yaml.YAMLError:
        return _ILEGIBLE
    if datos is None:
        return None
    if not isinstance(datos, dict):
        return _ILEGIBLE
    return _canonico(datos.get("apimart_tope_usd"))


_LINEA_CLAVE = re.compile(r"""("[^"\\]*"|'(?:[^']|'')*'|[^\s:#'"][^:#]*?)\s*:(?:[ \t]+(.*))?$""")


def _escalar_sin_yaml(texto: str, sigue: bool) -> object:
    v = texto.strip()
    if v.startswith("'"):
        m = re.fullmatch(r"'((?:[^']|'')*)'\s*(?:#.*)?", v)
        return _canonico(m.group(1).replace("''", "'")) if m else _ILEGIBLE
    if v.startswith('"'):
        m = re.fullmatch(r'"([^"\\]*)"\s*(?:#.*)?', v)
        return _canonico(m.group(1)) if m else _ILEGIBLE
    v = re.sub(r"\s+#.*$", "", v)
    if v[:1] in tuple("{[&*!|>%@`") or sigue:
        return _ILEGIBLE
    return None if v in _NULOS else _canonico(v)


def _tope_sin_yaml(fm: str) -> object:
    """Lector conservador del nivel superior: ante cualquier forma rara de YAML, ``_ILEGIBLE``."""
    lineas = fm.replace("\r\n", "\n").split("\n")
    valores = []
    for i, linea in enumerate(lineas):
        if not linea.strip() or linea.lstrip().startswith("#") or linea[0] in " \t" or linea.startswith("- ") \
                or linea == "-":
            continue
        if linea[0] in "?{[&*!%|>@`" or linea.startswith(("<<", "...", "---")):
            return _ILEGIBLE
        m = _LINEA_CLAVE.match(linea)
        if m is None:
            return _ILEGIBLE
        clave = m.group(1)
        if clave[:1] == "'":
            clave = clave[1:-1].replace("''", "'")
        elif clave[:1] == '"':
            clave = clave[1:-1]
        valor = m.group(2) or ""
        if clave != "apimart_tope_usd":
            if re.match(r"\s*[\[{]", valor) and valor.count("[") + valor.count("{") != \
                    valor.count("]") + valor.count("}"):
                return _ILEGIBLE  # un flujo que sigue en otras líneas
            continue
        sigue = i + 1 < len(lineas) and lineas[i + 1][:1] in (" ", "\t") and bool(lineas[i + 1].strip())
        valores.append(_escalar_sin_yaml(valor, sigue))
    if len(valores) > 1:
        return _ILEGIBLE
    return valores[0] if valores else None


def _tope_parseado(texto: str) -> object:
    fm = _frontmatter(texto)
    if fm is None or not fm.strip():
        return None
    return _tope_con_yaml(fm) if yaml is not None else _tope_sin_yaml(fm)


def _tope_distinto(actual: str, nuevo: str) -> bool:
    if _frontmatter(actual) == _frontmatter(nuevo):
        return False
    antes, despues = _tope_parseado(actual), _tope_parseado(nuevo)
    if antes is _ILEGIBLE or despues is _ILEGIBLE:
        return True
    return antes != despues


# --- Write/Edit/MultiEdit/NotebookEdit -------------------------------------------------------------------

def _relativa(ruta: str, cwd: str | None) -> tuple[str, ...] | None:
    """Partes de ``ruta`` (resuelta, enlaces incluidos) relativas al vault; ``None`` si está fuera."""
    try:
        destino = resolver(ruta, cwd)
        return destino.relative_to(vault_root().resolve(strict=False)).parts
    except (ValueError, OSError):
        return None


def _tras_editar(actual: str, ediciones: object) -> str | None:
    if not isinstance(ediciones, list) or not ediciones:
        return None
    for e in ediciones:
        if not isinstance(e, dict):
            return None
        viejo, nuevo = e.get("old_string"), e.get("new_string")
        if not isinstance(viejo, str) or not isinstance(nuevo, str) or not viejo or viejo not in actual:
            return None
        actual = actual.replace(viejo, nuevo) if e.get("replace_all") else actual.replace(viejo, nuevo, 1)
    return actual


def _cambia_tope(nombre: str, datos: dict, destino: pathlib.Path) -> bool:
    try:
        actual = destino.read_text(encoding="utf-8") if destino.is_file() else ""
    except (OSError, UnicodeDecodeError):
        return True
    if nombre == "write":
        nuevo = datos.get("content")
        return not isinstance(nuevo, str) or _tope_distinto(actual, nuevo)
    ediciones = [datos] if nombre == "edit" else datos.get("edits")
    nuevo = _tras_editar(actual, ediciones)
    if nuevo is None:  # no se sabe cómo queda: se deniega si la edición nombra el tope
        return any(isinstance(e, dict) and _TOPE_SUELTO.search(f"{e.get('old_string')}{e.get('new_string')}")
                   for e in (ediciones if isinstance(ediciones, list) else [datos]))
    return _tope_distinto(actual, nuevo)


def _escritura(nombre: str, datos: dict, cwd: str | None) -> tuple[str, str]:
    ruta = datos.get("notebook_path" if nombre == "notebookedit" else "file_path")
    if not isinstance(ruta, str) or not ruta:
        return "allow", ""
    if _relacion_conf(resolver(ruta, cwd)) == "dentro":
        return "deny", MOTIVO_CONF
    partes = _relativa(ruta, cwd)
    if partes is None:
        return "allow", ""
    if partes == ("config", "producto.yaml"):
        return "deny", MOTIVO_CONFIG
    if any(coincide_patron(partes, p) for p in _PANTALLAS):
        return "deny", MOTIVO_PANTALLAS
    if any(coincide_patron(partes, p) for p in _EVIDENCIA):
        return "deny", MOTIVO_EVIDENCIA
    if any(coincide_patron(partes, p) for p in _CHECKOUT_MCP):
        return "deny", MOTIVO_CHECKOUT
    if len(partes) < 3 or partes[0] != "productos":
        return "allow", ""
    if partes[2] == "entregable" and (partes[-1] == "costes.csv" or partes[-1] in _ARCHIVOS_GASTO):
        return "deny", MOTIVO_GASTO
    if any(coincide_patron(partes, p) for p in _DECISION):
        return "deny", MOTIVO_TOPE
    if any(coincide_patron(partes, p) for p in _QC):
        return "deny", MOTIVO_QC
    if len(partes) == 3 and partes[2] == "PRODUCTO.md" and (
            nombre == "notebookedit" or _cambia_tope(nombre, datos, resolver(ruta, cwd))):
        return "deny", MOTIVO_TOPE
    return "allow", ""


def decidir(entrada: dict) -> tuple[str, str]:
    nombre, datos = herramienta(entrada)
    nombre = nombre.lower()
    cwd = entrada.get("cwd") if isinstance(entrada.get("cwd"), str) else None
    if nombre == "bash":
        comando = datos.get("command", "")
        if not isinstance(comando, str):
            return "deny", MOTIVO
        return _bash(comando, cwd)
    if nombre == "webfetch":
        url = str(datos.get("url", ""))
        hosts = {_host(url), _host(unquote(url))}
        if any(h == "apimart.ai" or (h.endswith(".apimart.ai") and h != "docs.apimart.ai") for h in hosts):
            return "deny", MOTIVO
        return "allow", ""
    if nombre in ("read", "grep"):
        ruta = datos.get("file_path" if nombre == "read" else "path")
        if isinstance(ruta, str) and _CLAUDE_ENV.search(_normalizar(unquote(ruta))):
            return "deny", MOTIVO_CLAVE
        if nombre == "read" and isinstance(ruta, str) and ruta and _relacion_conf(resolver(ruta, cwd)) == "dentro":
            return "deny", MOTIVO_CONF
        if nombre == "grep" and _grep_conf(datos, cwd):
            return "deny", MOTIVO_CONF
        return "allow", ""
    if nombre in ("write", "edit", "multiedit", "notebookedit"):
        return _escritura(nombre, datos, cwd)
    return "allow", ""


if __name__ == "__main__":
    ejecutar_guardia(decidir)
