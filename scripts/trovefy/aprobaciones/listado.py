"""Vistas de solo lectura del aprobador: espejo del vault, copia de la auditoría y ``estado/*.json`` del ejecutor.

Fuente del desenlace: ``propuestas/<id>.md`` (lo escribe el ejecutor) y la copia ``ledger/auditoria/AAAA-MM-DD.jsonl``.
``procesadas/`` del buzón nunca es evidencia. Dato ausente = «—» o «no medido: <motivo>».
"""
from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trovefy_ejecutor import auditoria as _aud

from trovefy.aprobaciones.fuentes import leer_estado
from trovefy.vault import frontmatter

ID_PROPUESTA = re.compile(r"^P-\d{8}-\d{3}$")
COT = timezone(timedelta(hours=-5))
VACIO = "—"
SIN_EJECUTOR = "El ejecutor aún no está instalado: se instala con el plan 12 y /arranque."
GRUPOS: dict[str, set[str]] = {
    "pendientes": {"recibida", "enviada", "aceptada", "ejecutando"},
    "ejecutadas": {"ejecutada"},
    "caducadas": {"caducada", "obsoleta"},
    "otras": set(),
}
_CONOCIDOS = set().union(*GRUPOS.values())


@dataclass(frozen=True)
class FilaAprobacion:
    id: str
    tipo: str
    estado: str
    creada: str
    origen: str
    motivo: str


def grupo_de(estado: str) -> str:
    for g, estados in GRUPOS.items():
        if estado in estados:
            return g
    return "otras"


def origen_de(id_: str) -> str:
    n = int(id_[-3:])
    if n < 800:
        return "Claude"
    if n < 900:
        return "ejecutor"
    return "tú, por Telegram"


def _s(v: object) -> str:
    return VACIO if v is None or v == "" else str(v)


def _leer_auditoria(vault: Path) -> tuple[list[dict], list[str]]:
    carpeta = Path(vault) / "ledger" / "auditoria"
    eventos: list[dict] = []
    avisos: list[str] = []
    if not carpeta.is_dir():
        return eventos, avisos
    for ruta in sorted(carpeta.glob("*.jsonl")):
        if ruta.is_symlink() or not ruta.is_file():
            continue
        try:
            texto = ruta.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            avisos.append(f"{ruta.name}: ilegible")
            continue
        for i, linea in enumerate(texto.splitlines(), start=1):
            if not linea.strip():
                continue
            try:
                e = json.loads(linea)
                if not isinstance(e, dict) or not isinstance(e.get("evento"), str) or not isinstance(e.get("datos"), dict):
                    raise TypeError
            except (ValueError, TypeError):
                avisos.append(f"{ruta.name}: línea {i} rota, se salta")
                continue
            eventos.append(e)
    return eventos, avisos


def _leer_espejo(vault: Path, id_: str) -> tuple[dict, str] | None:
    ruta = Path(vault) / "propuestas" / f"{id_}.md"
    if ruta.is_symlink() or not ruta.is_file():
        return None
    try:
        meta, cuerpo = frontmatter.leer(ruta)
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return (meta if isinstance(meta, dict) else {}), cuerpo


def _espejos(vault: Path) -> dict[str, tuple[dict, str]]:
    carpeta = Path(vault) / "propuestas"
    sal: dict[str, tuple[dict, str]] = {}
    if not carpeta.is_dir():
        return sal
    for ruta in sorted(carpeta.glob("P-*.md")):
        if ID_PROPUESTA.match(ruta.stem):
            e = _leer_espejo(vault, ruta.stem)
            if e is not None:
                sal[ruta.stem] = e
    return sal


def listar(vault: Path) -> tuple[list[FilaAprobacion], list[str]]:
    eventos, avisos = _leer_auditoria(vault)
    espejos = _espejos(vault)
    campos: dict[str, dict[str, str]] = {}

    def fila(id_: str) -> dict[str, str]:
        return campos.setdefault(id_, {})

    for id_, (meta, _cuerpo) in espejos.items():
        f = fila(id_)
        f["tipo"] = _s(meta.get("tipo_propuesta"))
        f["estado"] = _s(meta.get("estado"))
        f["creada"] = VACIO
        f["_fecha"] = _s(meta.get("fecha"))
    for e in eventos:
        d, ev = e["datos"], e["evento"]
        id_ = d.get("id")
        if not isinstance(id_, str) or not ID_PROPUESTA.match(id_):
            continue
        f = fila(id_)
        if ev == "recibida":
            f.setdefault("tipo", _s(d.get("tipo")))
            f.setdefault("estado", "recibida")
            f["creada"] = _s(e.get("ts"))
            for k in ("origen", "motivo"):
                if d.get(k):
                    f[k] = str(d[k])
        elif ev == "transicion":
            f["estado"] = _s(d.get("a"))
            if f.get("tipo", VACIO) == VACIO:
                f["tipo"] = _s(d.get("tipo"))
        elif ev == "validacion_rechazada":
            f["estado"] = "rechazada al validar"
            f["motivo"] = _s(d.get("motivo"))
    filas = []
    for id_, f in campos.items():
        creada = f.get("creada", VACIO)
        if creada == VACIO:
            creada = f.get("_fecha", VACIO)
        filas.append(FilaAprobacion(id_, f.get("tipo", VACIO), f.get("estado", VACIO), creada,
                                    f.get("origen") or origen_de(id_), f.get("motivo", VACIO)))
    filas.sort(key=lambda r: (r.creada if r.creada != VACIO else "", r.id), reverse=True)
    return filas, avisos


def explicar(vault: Path, id: str) -> str:
    if not isinstance(id, str) or not ID_PROPUESTA.match(id):
        raise ValueError(f"id inválido (formato P-AAAAMMDD-NNN): {id!r}")
    eventos, _ = _leer_auditoria(vault)
    suyos = [e for e in eventos if e["datos"].get("id") == id]
    espejo = _leer_espejo(vault, id)
    if espejo is None and not suyos:
        return f"No encuentro {id} en propuestas/ ni en la auditoría."
    filas, _ = listar(vault)
    f = next((r for r in filas if r.id == id), None)
    out = [id]
    if f is not None:
        out += [f"Tipo: {f.tipo}", f"Estado: {f.estado}", f"Creada: {f.creada}",
                f"Origen: {f.origen}", f"Motivo: {f.motivo}"]
    if espejo is not None:
        cuerpo = espejo[1].strip().splitlines()
        texto = [x for x in cuerpo if not x.startswith(("Fuente de verdad:", "Detalle:", "- ", "ids_creados:"))]
        evidencia = [x for x in cuerpo if x.startswith(("Detalle:", "- ", "ids_creados:"))]
        if "\n".join(texto).strip():
            out += ["", "Texto final:", "\n".join(texto).strip()]
        if evidencia:
            out += ["", "Evidencia y operaciones (copia del ejecutor):", *evidencia]
    if suyos:
        out += ["", "Línea de tiempo (auditoría):"]
        for e in suyos:
            d, ev, ts = e["datos"], e["evento"], _s(e.get("ts"))
            if ev == "transicion":
                txt = f"transición {_s(d.get('de'))} -> {_s(d.get('a'))}"
            elif ev == "validacion_rechazada":
                txt = f"validación rechazada: {_s(d.get('motivo'))}"
            elif ev == "ejecucion":
                txt = (f"ejecución validate_only={d.get('validate_only')} ok={d.get('ok')}: "
                       f"{_s(d.get('detalle'))}")
            else:
                txt = ev
            out.append(f"- {ts} {txt}")
    return "\n".join(out)


def _verificar_cadena(vault: Path) -> str | None:
    """None si cuadra; texto si no cuadra o no se pudo medir."""
    carpeta = Path(vault) / "ledger" / "auditoria"
    dias = sorted(p for p in carpeta.glob("*.jsonl") if p.is_file() and not p.is_symlink()) if carpeta.is_dir() else []
    if not dias:
        return "Auditoría: no medido: no hay copia en ledger/auditoria/"
    try:
        crudo = b"".join(p.read_bytes() for p in dias)
        primera = crudo.split(b"\n", 1)[0]
        ini = json.loads(primera)
    except (OSError, ValueError):
        return "Auditoría: la copia de la auditoría no cuadra: avisa"
    if not isinstance(ini, dict) or ini.get("n") != 1 or ini.get("hash_prev") != _aud.GENESIS:
        if isinstance(ini, dict) and isinstance(ini.get("n"), int) and ini.get("n") > 1:
            return "Auditoría: no medido: la copia no empieza en el origen de la cadena"
        return "Auditoría: la copia de la auditoría no cuadra: avisa"
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t) / "cadena.jsonl"
        tmp.write_bytes(crudo)
        fallo = _aud._recorrer(tmp)[0]
    if fallo:
        return "Auditoría: la copia de la auditoría no cuadra: avisa"
    return None


def _latido(vault: Path, ahora: datetime, spool: Path | None) -> tuple[list[str], bool]:
    r = leer_estado("latido", spool)
    if r.datos is None:
        if r.motivo and "aún no está instalado" in r.motivo:
            return [SIN_EJECUTOR], True
        return [f"Ejecutor: {r.motivo}"], False
    try:
        f = datetime.fromisoformat(str(r.datos.get("fecha")))
        if f.tzinfo is None:
            raise ValueError
    except ValueError:
        return ["Ejecutor: no medido: latido sin fecha válida"], False
    edad = ahora - f
    if edad > timedelta(minutes=10):
        return [f"Ejecutor: parado desde {f.astimezone(COT):%H:%M}"], False
    return [f"Ejecutor: vivo (hace {max(0, int(edad.total_seconds() // 60))} min)"], False


def _si_no(v: object) -> str:
    return "sí" if v is True else "no" if v is False else "no medido"


def resumen_estado(vault: Path, ahora: datetime, spool: Path | None = None) -> list[str]:
    vault = Path(vault)
    out, sin_ejecutor = _latido(vault, ahora, spool)
    if not sin_ejecutor:
        st = leer_estado("stop", spool)
        if st.datos is None:
            out.append(f"STOP del ejecutor: {st.motivo}")
        else:
            out.append(f"STOP del ejecutor: {'ACTIVO' if st.datos.get('activo') is True else 'no'}")
    out.append(f"STOP del cerebro: {'ACTIVO' if (vault / '.trovefy' / 'STOP').exists() else 'no'}")
    if not sin_ejecutor:
        emp = leer_estado("emparejamiento", spool)
        out.append(f"Telegram emparejado: {_si_no(emp.datos.get('emparejado')) if emp.datos else 'no medido'}")
        cuenta = None
        try:
            from trovefy.caja.config import cargar_caja
            cuenta = cargar_caja(vault).cuenta.id
        except Exception:  # noqa: BLE001 - sin caja.yaml legible la meta cuenta como no medida
            cuenta = None
        meta = leer_estado("meta", spool, cuenta=cuenta) if cuenta else None
        if meta is None or meta.datos is None:
            motivo = "falta config/caja.yaml con la cuenta" if meta is None else (meta.motivo or "")
            out.append(f"Meta: no medido: {motivo.removeprefix('no medido: ')}")
        else:
            d = meta.datos
            out.append(f"Meta: moneda {_s(d.get('currency'))}, offset {_s(d.get('offset'))}, medido {_s(d.get('fecha'))}")
        lim = leer_estado("limites", spool)
        if lim.datos is None:
            out.append(f"Límites vigentes (solo lectura): {lim.motivo}")
        else:
            cuentas = lim.datos.get("cuentas") if isinstance(lim.datos.get("cuentas"), dict) else {}
            for n, (_cid, c) in enumerate(sorted(cuentas.items()), 1):
                if isinstance(c, dict):
                    out.append(f"Límites cuenta {n} (solo lectura): {_s(c.get('moneda'))} "
                               f"tope diario {_s(c.get('tope_gasto_diario_total'))}, "
                               f"máx. conjunto {_s(c.get('max_presupuesto_conjunto'))}")
        lectura = vault / "config" / "limites_ejecutor.lectura.yaml"
        if lectura.is_file() and not lectura.is_symlink():
            try:
                out.append("Copia de lectura config/limites_ejecutor.lectura.yaml:")
                out += [f"  {x}" for x in lectura.read_text(encoding="utf-8").splitlines()[:20]]
            except (OSError, UnicodeDecodeError):
                out.append("  no medido: ilegible")
    eventos, avisos = _leer_auditoria(vault)
    rech = [e for e in eventos if e["evento"] == "validacion_rechazada"][-5:]
    if rech:
        out.append("Rechazadas al validar (últimas):")
        out += [f"  {_s(e['datos'].get('id'))}: {_s(e['datos'].get('motivo'))}" for e in rech]
    camb = [e for e in eventos if e["evento"] == "limite_cambiado"][-5:]
    if camb:
        out.append("Cambios de límites:")
        out += [f"  {_s(e['datos'].get('clave'))}: {_s(e['datos'].get('de'))} -> {_s(e['datos'].get('a'))}"
                for e in camb]
    out += [f"Aviso: {a}" for a in avisos]
    problema = _verificar_cadena(vault)
    out.append(problema or "Auditoría: la copia cuadra")
    return out


def propuesta_noop(ahora: datetime) -> dict:
    return {
        "version": 1,
        "tipo": "noop",
        "origen": "/aprobaciones probar",
        "motivo": "Prueba del circuito: pulsa Aceptar o Rechazar. No cambia nada en Meta.",
    }
