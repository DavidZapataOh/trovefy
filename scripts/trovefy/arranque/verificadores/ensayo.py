"""Paso 18: ensayo general. Se comprueba en la copia de la auditoría del vault y en el registro del ensayo.

Ok solo con las tres cosas: un noop depositado por Claude, aceptado y ejecutado; un montaje validado con
validate_only; una compra de prueba con su reembolso. Evidencia parcial o ilegible nunca verifica.
En los motivos solo se copian ids, tipos y estados.
"""

import re
from pathlib import Path

from trovefy.aprobaciones.listado import NO_CUADRA, tramos_de_auditoria
from trovefy.arranque.ensayo import RUTA_ENSAYO, leer_ensayo
from trovefy.arranque.estado import ResultadoVerificacion
from trovefy.arranque.verificadores import verificador

NOOP_ACEPTADO = ("transicion", {"tipo": "noop", "a": "aceptada"})
NOOP_EJECUTADO = ("transicion", {"tipo": "noop", "a": "ejecutada"})
MONTAJE_VALIDADO = ("ejecucion", {"tipo": "crear_estructura_pausada", "validate_only": True, "ok": True})
ID_CLAUDE = re.compile(r"^P-\d{8}-(00[1-9]|0[1-9]\d|[1-7]\d\d)$")
CARPETA = "ledger/auditoria"


def _casa(e: dict, patron: tuple[str, dict]) -> bool:
    evento, campos = patron
    d = e.get("datos")
    return e.get("evento") == evento and isinstance(d, dict) and all(k in d and d[k] == v and type(d[k]) is type(v) for k, v in campos.items())


def _noops_completos(eventos: list[dict]) -> bool:
    aceptados: set[str] = set()
    for e in eventos:  # en orden de cadena: aceptada y luego ejecutada
        id_ = e["datos"].get("id")
        if not isinstance(id_, str) or not ID_CLAUDE.match(id_):
            continue
        if _casa(e, NOOP_ACEPTADO):
            aceptados.add(id_)
        elif _casa(e, NOOP_EJECUTADO) and id_ in aceptados:
            return True
    return False


def _no_medido(motivo: str, evidencia: list[str]) -> ResultadoVerificacion:
    m = f"no medido: {motivo}"
    return ResultadoVerificacion(None, evidencia, m, ["avisa para revisar la copia de la auditoría con el ejecutor"], {}, [f"? {m}"])


@verificador("18")
def verificar_ensayo(vault: Path) -> ResultadoVerificacion:
    vault = Path(vault)
    carpeta = vault / CARPETA
    dias = sorted(p for p in carpeta.glob("*.jsonl") if p.is_file() and not p.is_symlink()) if carpeta.is_dir() else []
    evidencia = [f"{CARPETA}/{p.name}" for p in dias] + [RUTA_ENSAYO]
    faltas: list[tuple[str, str]] = []  # (qué falta, arreglo)
    tramos, error = tramos_de_auditoria(vault)
    if error == NO_CUADRA or not all(t.cuadra for t in tramos):
        m = "la copia de la auditoría no cuadra"
        return ResultadoVerificacion(False, [], m, ["avisa: la cadena de la copia de la auditoría está rota y hay que revisarla"],
                                     {}, [f"✗ {m}"])
    if error:
        faltas.append(("no hay copia de la auditoría en el vault", "el ejecutor copia la auditoría al vault (plan 12)"))
    else:
        # Solo cuentan eventos de tramos que verifican por dentro (aquí, todos); huecos, reanudaciones o una copia
        # que no empieza en el origen no invalidan esos eventos.
        eventos = [e for t in tramos for e in t.lineas if isinstance(e.get("datos"), dict)]
        if not _noops_completos(eventos):
            faltas.append(("falta un noop aceptado por Telegram y ejecutado",
                           "deposita un noop con `trovefy aprobaciones probar` y acéptalo en Telegram"))
        if not any(_casa(e, MONTAJE_VALIDADO) for e in eventos):
            faltas.append(("falta el montaje en validate_only",
                           "`trovefy arranque ensayo montaje`, luego `trovefy buzon depositar <ruta>` y acéptalo en Telegram"))
    try:
        reg = leer_ensayo(vault)
    except ValueError:
        return _no_medido(f"{RUTA_ENSAYO} no se puede leer", evidencia)
    compras = [c.get("pedido") for c in reg.get("compras", []) if isinstance(c.get("pedido"), str)]
    reembolsados = {r.get("pedido") for r in reg.get("reembolsos", [])}
    if not compras:
        faltas.append(("falta la compra de prueba",
                       "trovefy arranque ensayo compra --pedido ID --importe 2.00 --moneda USD --pasarela whop"))
    for pedido in compras:
        if pedido not in reembolsados:
            faltas.append((f"falta el reembolso de la compra de prueba {pedido}",
                           f"trovefy arranque ensayo reembolso --pedido {pedido}"))
    if faltas:
        motivo = "; ".join(f for f, _ in faltas)
        return ResultadoVerificacion(False, [], motivo, [a for _, a in faltas], {}, [f"✗ {f}" for f, _ in faltas])
    motivo = "noop aceptado y ejecutado, montaje en validate_only y compra de prueba con su reembolso"
    return ResultadoVerificacion(True, evidencia, motivo, [], {}, [f"✓ {motivo}"])
