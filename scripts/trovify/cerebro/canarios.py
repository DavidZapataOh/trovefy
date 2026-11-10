"""Canarios del cerebro: preguntas con respuesta conocida que se hacen a `/consultar`."""

import hashlib
import json
import re
import subprocess
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml

from trovify.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico

MAX_RESPUESTA = 2000
TIMEOUT_S = 300


@dataclass
class Canario:
    id: str
    pregunta: str
    debe_contener: list[list[str]]
    no_debe_contener: list[str]


@dataclass
class Resultado:
    id: str
    estado: Literal["ok", "falla", "error"]
    faltan: list[str]
    respuesta: str


def ruta_por_defecto() -> Path:
    """tests/canarios.yaml del repo, buscado hacia arriba desde este paquete."""
    for padre in Path(__file__).resolve().parents:
        candidata = padre / "tests" / "canarios.yaml"
        if candidata.is_file():
            return candidata
    raise FileNotFoundError(
        "No encuentro tests/canarios.yaml junto al código de Trovify; indica la ruta con --canarios."
    )


def cargar(ruta: Path | None = None) -> list[Canario]:
    ruta = Path(ruta) if ruta else ruta_por_defecto()
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, list):
        raise TypeError(f"{ruta}: se esperaba una lista de canarios")
    salida = []
    for d in datos:
        try:
            salida.append(Canario(
                id=str(d["id"]),
                pregunta=str(d["pregunta"]),
                debe_contener=[[str(a) for a in g] for g in d["debe_contener"]],
                no_debe_contener=[str(a) for a in d.get("no_debe_contener") or []],
            ))
        except (KeyError, TypeError) as exc:
            raise ValueError(f"{ruta}: canario mal formado ({exc!r})") from exc
    return salida


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes, coma decimal a punto y espacios colapsados."""
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    return re.sub(r"\s+", " ", t).strip()


def _aparece(alternativa: str, texto: str) -> bool:
    alt = normalizar(alternativa)
    return bool(alt) and re.search(rf"(?<!\w){re.escape(alt)}(?!\w)", texto) is not None


def evaluar(respuesta: str, c: Canario) -> Resultado:
    texto = normalizar(respuesta)
    faltan = [g[0] for g in c.debe_contener if not any(_aparece(a, texto) for a in g)]
    prohibido = any(_aparece(a, texto) for a in c.no_debe_contener)
    estado = "ok" if not faltan and not prohibido else "falla"
    return Resultado(c.id, estado, faltan, respuesta)


def preguntar_a_claude(vault: Path, pregunta: str) -> str:
    try:
        p = subprocess.run(
            ["claude", "-p", f"/trovify:consultar {pregunta}", "--allowedTools", "Read,Grep,Glob"],
            cwd=vault, capture_output=True, text=True, timeout=TIMEOUT_S, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"claude no respondió en {TIMEOUT_S} s") from exc
    if p.returncode != 0:
        raise RuntimeError(f"claude terminó con código {p.returncode}: {(p.stderr or '').strip()[:300]}")
    return p.stdout


def correr(
    vault: Path,
    canarios: list[Canario],
    preguntar: Callable[[Path, str], str] = preguntar_a_claude,
    actualizar_ultimo: bool = True,
    canarios_sha256: str | None = None,
) -> list[Resultado]:
    vault = Path(vault)
    resultados = []
    for c in canarios:
        try:
            r = evaluar(preguntar(vault, c.pregunta), c)
        except Exception as exc:  # noqa: BLE001 # cualquier fallo de ejecución cuenta como error, nunca como ok
            r = Resultado(c.id, "error", [], f"{type(exc).__name__}: {exc}")
        r.respuesta = r.respuesta[:MAX_RESPUESTA]
        resultados.append(r)
    ahora = datetime.now(ZONA_NEGOCIO)
    todos_ok = bool(resultados) and all(r.estado == "ok" for r in resultados)
    cuerpo = json.dumps(
        {"fecha": f"{ahora:%Y-%m-%d}", "todos_ok": todos_ok, "ids": [c.id for c in canarios],
         "canarios_sha256": canarios_sha256 or _sha_por_defecto(),
         "resultados": [asdict(r) for r in resultados]},
        ensure_ascii=False, indent=2,
    ) + "\n"
    carpeta = vault / "data" / "canarios"
    base = f"{ahora:%Y-%m-%d-%H%M}"
    nombre, n = f"{base}.json", 1
    while (carpeta / nombre).exists():
        n += 1
        nombre = f"{base}-{n}.json"
    escribir_atomico(carpeta / nombre, cuerpo)
    escribir_atomico(carpeta / ("ultimo.json" if actualizar_ultimo else "parcial.json"), cuerpo)
    ok = sum(r.estado == "ok" for r in resultados)
    anadir_log(vault, "canarios", f"{ok}/{len(resultados)} canarios ok",
               [f"data/canarios/{nombre}"])
    return resultados


def sha256_de(ruta: Path | None = None) -> str:
    ruta = Path(ruta) if ruta else ruta_por_defecto()
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _sha_por_defecto() -> str:
    try:
        return sha256_de()
    except OSError:
        return "—"
