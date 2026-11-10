"""Subcomando `trovify arranque`."""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from trovify.arranque.estado import (
    ArranqueCorrupto,
    PasoDesconocido,
    ResultadoVerificacion,
    aplicar_verificacion,
    cargar,
    marcar_bloqueado,
    marcar_hecho,
    porcentaje_fase,
    siguiente,
)
from trovify.arranque.verificadores import REGISTRO
from trovify.arranque.verificadores.checklist import CHECKLISTS, verificar_checklist
from trovify.cerebro.ingesta import _buscar_secreto
from trovify.cli import registrar
from trovify.vault.escritura import anadir_log
from trovify.vault.rutas import vault_root

_VAULT_AYUDA = "ruta del vault (por defecto, TROVIFY_VAULT o ~/trovify-cerebro)"


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    sub.add_parser("estado", help="tabla de pasos y avance de la fase 0").add_argument("--vault", help=_VAULT_AYUDA)
    sub.add_parser("siguiente", help="el próximo paso de la fase 0").add_argument("--vault", help=_VAULT_AYUDA)
    h = sub.add_parser("hecho", help="marca un paso como hecho (no verificado)")
    h.add_argument("id", metavar="ID")
    h.add_argument("--nota", help="nota breve")
    h.add_argument("--dato", action="append", default=[], metavar="CLAVE=VALOR",
                   help="dato del paso (repetible), p. ej. url=https://www.facebook.com/tu-pagina; nunca un secreto")
    h.add_argument("--vault", help=_VAULT_AYUDA)
    v = sub.add_parser("verificar", help="ejecuta el verificador de un paso")
    v.add_argument("id", metavar="ID")
    v.add_argument("--vault", help=_VAULT_AYUDA)
    c = sub.add_parser("checklist", help="verifica un paso con una lista de comprobaciones (paso 03)")
    c.add_argument("id", metavar="ID")
    c.add_argument("--respuesta", action="append", default=[], metavar="CLAVE=si|no", help="respuesta a una comprobación (repetible)")
    c.add_argument("--vault", help=_VAULT_AYUDA)
    b = sub.add_parser("bloqueado", help="marca un paso como bloqueado")
    b.add_argument("id", metavar="ID")
    b.add_argument("--motivo", required=True, help="por qué está bloqueado")
    b.add_argument("--vault", help=_VAULT_AYUDA)


def _error(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return 2


_CLAVE_DATO = re.compile(r"[a-z_]+")


_PROHIBIDO_EN_URL = ("access_token=", "token=", "code=", "sig=", "fb_dtsg")


def _url_limpia(valor: str) -> str:
    """https y dominio de Facebook; sin parámetros ni fragmento (pueden llevar tokens)."""
    if any(x in valor.lower() for x in _PROHIBIDO_EN_URL):
        raise ValueError("--dato url: la dirección lleva un token o código; copia solo la dirección de la página")
    partes = urlsplit(valor)
    host = (partes.hostname or "").lower()
    if partes.scheme != "https" or not (host in ("facebook.com", "fb.com") or host.endswith((".facebook.com", ".fb.com"))):
        raise ValueError("--dato url: debe ser una dirección https de facebook.com o fb.com")
    return urlunsplit((partes.scheme, partes.netloc, partes.path, "", ""))


def _parsear_datos(items: list[str]) -> dict[str, str]:
    datos: dict[str, str] = {}
    for item in items:
        clave, sep, valor = item.partition("=")
        if not sep or not _CLAVE_DATO.fullmatch(clave):
            raise ValueError(f"--dato «{clave}» debe ser CLAVE=VALOR con la clave en minúsculas y _")
        if not valor.strip() or "\n" in valor or "\r" in valor:
            raise ValueError(f"--dato {clave}: el valor no puede estar vacío ni tener saltos de línea")
        if _buscar_secreto(valor):
            raise ValueError(f"--dato {clave}: el valor parece un secreto; los secretos no se guardan en el vault")
        datos[clave] = _url_limpia(valor) if clave == "url" else valor
    return datos


def _parsear_respuestas(items: list[str]) -> dict[str, bool]:
    respuestas: dict[str, bool] = {}
    for item in items:
        clave, _, valor = item.partition("=")
        if valor not in ("si", "no"):
            raise ValueError(f"--respuesta {clave or item}: responde `si` o `no`")
        respuestas[clave] = valor == "si"
    return respuestas


def _checklist(vault: Path, id_: str, items: list[str]) -> int:
    if id_ not in CHECKLISTS:
        raise ValueError(f"el paso {id_} no tiene lista de comprobaciones")
    cargado = next((p for p in cargar(vault) if p.id == id_), None)
    if cargado is None:
        raise PasoDesconocido(id_)
    r = verificar_checklist(vault, id_, _parsear_respuestas(items))
    p = aplicar_verificacion(vault, id_, r)
    for linea in r.lineas:
        print(linea)
    texto, codigo = _RESULTADO[r.ok]
    print(f"\nPaso {p.id} ({p.nombre}): {texto} — {r.motivo}. Estado: {p.estado}.")
    for a in r.arreglos:
        print(f"  - {a}")
    return codigo


_RESULTADO = {True: ("ok", 0), False: ("falló", 1), None: ("no medido", 3)}


def _verificar(vault: Path, id_: str) -> int:
    cargar_ = next((p for p in cargar(vault) if p.id == id_), None)
    if cargar_ is None:
        raise PasoDesconocido(id_)
    funcion = REGISTRO.get(id_)
    if funcion is None:
        return _error(f"el paso {id_} ({cargar_.nombre}) no tiene verificador todavía")
    try:
        r = funcion(vault)
    except Exception as exc:  # noqa: BLE001  nunca el texto de la excepción: podría llevar un secreto
        motivo = f"no medido: error del verificador ({type(exc).__name__})"
        r = ResultadoVerificacion(None, [], motivo, [], {}, [f"? {motivo}"])
    antes = cargar_.estado
    p = aplicar_verificacion(vault, id_, r)
    for linea in r.lineas:
        print(linea)
    texto, codigo = _RESULTADO[r.ok]
    print(f"\nPaso {p.id} ({p.nombre}): {texto} — {r.motivo}. Estado: {p.estado}.")
    if r.arreglos:
        print("Para arreglarlo (los comandos de sistema van en una terminal de Ubuntu (WSL) aparte):")
        for a in r.arreglos:
            print(f"  - {a}")
    if p.estado == antes:  # si cambió de estado, aplicar_verificacion ya escribió la línea del log
        anadir_log(vault, "arranque", f"verificar {id_}: {texto} — {r.motivo}", r.evidencia or ["config/arranque.yaml"])
    return codigo


def _ejecutar(args: argparse.Namespace) -> int:
    destino = Path(args.vault).expanduser() if args.vault else vault_root()
    try:
        if args.accion == "hecho":
            p = marcar_hecho(destino, args.id, args.nota, _parsear_datos(args.dato))
            print(f"Paso {p.id} ({p.nombre}): {p.estado}.")
            return 0
        if args.accion == "verificar":
            return _verificar(destino, args.id)
        if args.accion == "checklist":
            return _checklist(destino, args.id, args.respuesta)
        if args.accion == "bloqueado":
            if not args.motivo.strip():
                return _error("--motivo no puede estar vacío")
            p = marcar_bloqueado(destino, args.id, args.motivo)
            print(f"Paso {p.id} ({p.nombre}): {p.estado}.")
            return 0
        pasos = cargar(destino)
    except (PasoDesconocido, ValueError) as exc:
        return _error(str(exc))
    except ArranqueCorrupto as exc:
        return _error(str(exc))
    except OSError as exc:
        return _error(f"no se pudo escribir en el vault: {exc.strerror or exc}")
    if args.accion == "siguiente":
        s = siguiente(pasos)
        if s is not None:
            print(f"Siguiente: {s.id} · {s.nombre} ({s.estado})")
            return 0
        pendientes = [p for p in pasos if p.fase == 0 and p.estado in ("bloqueado", "hecho")]
        if not pendientes:
            print("Fase 0 completa: todos los pasos están verificados.")
        else:
            print("No hay un paso siguiente: lo que falta de la fase 0 está bloqueado o esperando verificación.")
            for p in pendientes:
                print(f"  {p.id} · {p.nombre} ({p.estado}): {p.nota or 'sin motivo'}")
        return 0
    print(f"{'ID':<4} {'Paso':<40} {'Estado':<11} {'Fecha':<10} Nota")
    for p in pasos:
        nota = (p.nota or "").replace("\n", " ")
        nota = nota if len(nota) <= 80 else nota[:79] + "…"
        print(f"{p.id:<4} {p.nombre:<40} {p.estado:<11} {p.fecha or '—':<10} {nota}".rstrip())
    frac = porcentaje_fase(pasos, 0)
    print(f"\nFase 0: {round(frac * 12)}/12 verificados ({frac * 100:.0f} %)")
    return 0


registrar("arranque", _configurar, _ejecutar)
