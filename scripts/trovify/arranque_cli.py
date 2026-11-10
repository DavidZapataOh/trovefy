"""Subcomando `trovify arranque`."""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

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
from trovify.arranque.verificadores.base import (
    LECTORES,
    RUTA_CONFIRMACIONES,
    leer_texto_provisional,
    registrar_confirmacion,
    ultimo_texto_provisional,
)
from trovify.arranque.verificadores.checklist import CHECKLISTS, verificar_checklist
from trovify.cli import registrar
from trovify.dns import normalizar as normalizar_dominio
from trovify.secretos import RevisionSecretosNoDisponible, buscar_secreto
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
    cf = sub.add_parser("confirmar", help="muestra lo leído de tu pantalla real y, con tu sí, confirma el patrón del paso")
    cf.add_argument("id", metavar="ID", help="04, 05, 06, 08, 09, 10 o 10b")
    cf.add_argument("--respuesta", metavar="si|no", help="tu respuesta: ¿coincide con lo que ves en tu pantalla?")
    cf.add_argument("--vault", help=_VAULT_AYUDA)
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
    if "@" in partes.netloc:
        raise ValueError("--dato url: la dirección no puede llevar usuario ni contraseña (`algo@`)")
    host = (partes.hostname or "").lower()
    if partes.scheme != "https" or not (host in ("facebook.com", "fb.com") or host.endswith((".facebook.com", ".fb.com"))):
        raise ValueError("--dato url: debe ser una dirección https de facebook.com o fb.com")
    consulta = ""
    if partes.path.rstrip("/") == "/profile.php":  # las páginas nuevas se identifican solo por ?id=<dígitos>
        ids = [v for v in parse_qs(partes.query).get("id", []) if v.isdigit()]
        consulta = f"id={ids[0]}" if ids else ""
    return urlunsplit((partes.scheme, partes.netloc, partes.path, consulta, ""))


def _parsear_datos(items: list[str]) -> dict[str, str]:
    datos: dict[str, str] = {}
    for item in items:
        clave, sep, valor = item.partition("=")
        if not sep or not _CLAVE_DATO.fullmatch(clave):
            raise ValueError(f"--dato «{clave}» debe ser CLAVE=VALOR con la clave en minúsculas y _")
        if not valor.strip() or "\n" in valor or "\r" in valor:
            raise ValueError(f"--dato {clave}: el valor no puede estar vacío ni tener saltos de línea")
        if buscar_secreto(valor):
            raise ValueError(f"--dato {clave}: el valor parece un secreto; los secretos no se guardan en el vault")
        if clave == "url":
            datos[clave] = _url_limpia(valor)
        elif clave == "dominio":
            try:
                datos[clave] = normalizar_dominio(valor)
            except ValueError as exc:
                raise ValueError(f"--dato dominio: {exc}") from None
        else:
            datos[clave] = valor
    return datos


def _si_no(valor: str) -> bool | None:
    """`si`/`sí`/`no` sin distinguir mayúsculas; None si no es ninguno."""
    v = valor.strip().lower()
    return True if v in ("si", "sí") else False if v == "no" else None


def _parsear_respuestas(items: list[str]) -> dict[str, bool]:
    respuestas: dict[str, bool] = {}
    for item in items:
        clave, _, valor = item.partition("=")
        r = _si_no(valor)
        if r is None:
            raise ValueError(f"--respuesta {clave or item}: responde `si` o `no`")
        respuestas[clave] = r
    return respuestas


def _mostrable(valor: str | None) -> str:
    if valor is None:
        return "(no encontrado)"
    return "(oculto: parece un secreto)" if buscar_secreto(valor) else valor


def _confirmar(vault: Path, id_: str, respuesta: str | None) -> int:
    lector = LECTORES.get(id_)
    if lector is None:
        return _error(f"el paso {id_} no tiene un patrón que confirmar (solo {', '.join(sorted(LECTORES))})")
    si = None if respuesta is None else _si_no(respuesta)
    if respuesta is not None and si is None:
        return _error("--respuesta: responde `si` o `no`")
    archivo = ultimo_texto_provisional(vault, id_)
    if archivo is None:
        return _error(
            f"no hay texto provisional del paso {id_}: ejecuta antes `trovify arranque verificar {id_}` con la sesión iniciada"
        )
    valores = lector.leer(leer_texto_provisional(archivo), vault)
    rel = archivo.relative_to(vault).as_posix()
    print(f"Leído de tu pantalla real ({rel}):")
    for campo, valor in valores.items():
        print(f"  {campo}: {_mostrable(valor)}")
    requeridos = lector.requeridos if lector.requeridos is not None else tuple(valores)
    faltan = [c for c in requeridos if valores.get(c) is None]
    if faltan:
        return _error(
            f"el patrón no casa con tu pantalla real (falta: {', '.join(faltan)}); "
            "hay que ajustar el mapa (cambio en el repo). No se confirma nada."
        )
    if si is None:
        print(f"\n¿Coincide con lo que ves en tu pantalla? Solo con tu «sí»: `trovify arranque confirmar {id_} --respuesta si`.")
        return 0
    if not si:
        print(f"\nNo se guarda nada. Avisa del desajuste del paso {id_} (qué campo no coincide): hay que ajustar el patrón en el repo.")
        return 1
    entrada = registrar_confirmacion(vault, id_, archivo)
    anadir_log(vault, "arranque", f"confirmar {id_}: patrón confirmado por el usuario con su pantalla real", [RUTA_CONFIRMACIONES, rel])
    print(f"\nPatrón del paso {id_} confirmado ({entrada['fecha']}). Ahora: `trovify arranque verificar {id_}`.")
    return 0


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
        if args.accion == "confirmar":
            return _confirmar(destino, args.id, args.respuesta)
        if args.accion == "bloqueado":
            if not args.motivo.strip():
                return _error("--motivo no puede estar vacío")
            p = marcar_bloqueado(destino, args.id, args.motivo)
            print(f"Paso {p.id} ({p.nombre}): {p.estado}.")
            return 0
        pasos = cargar(destino)
    except (PasoDesconocido, ValueError) as exc:
        return _error(str(exc))
    except (ArranqueCorrupto, RevisionSecretosNoDisponible) as exc:
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
