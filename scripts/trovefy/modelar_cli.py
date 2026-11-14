"""Subcomando `trovefy modelar`: oferta propia (autopsia, escalera, brandbook y comparativa) y su aprobación."""

import argparse
import re
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from trovefy.cli import registrar

EJEMPLO = Path("skills") / "modelar" / "references" / "modelar-ejemplo.yaml"
_RAIZ = Path(__file__).resolve().parents[2]
_PRECIO_FRONT = re.compile(r"^([A-Za-z]{2}):(.+)$")
_ID_OFERTA = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SENAL = {True: "sí", False: "no", None: "no medida"}
CIERRE = "Si no la rechazas en esta sesión, queda aprobada."


class _Uso(ValueError):
    """Error de uso de la CLI (argumento mal formado)."""


def _producto(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--producto", required=True, metavar="P", help="p-id del producto (productos/<P>/)")


def _cita(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--cita", required=True, help="las palabras del usuario, literales")


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    _producto(sub.add_parser("preparar", help="comprueba lo que hace falta para modelar, sin escribir nada"))
    e = sub.add_parser("escribir", help="valida productos/<P>/modelar.yaml y escribe OFERTA, ESCALERA, BRANDBOOK "
                                        "y comparativa")
    _producto(e)
    e.add_argument("--precio-front", action="append", default=[], dest="precio_front", metavar="XX:importe",
                   help="precio del front que da el usuario para un país, en su moneda (se repite)")
    a = sub.add_parser("aprobar", help="la oferta queda aprobada con las palabras del usuario")
    _producto(a)
    _cita(a)
    r = sub.add_parser("rechazar", help="la oferta queda rechazada con las palabras del usuario")
    _producto(r)
    _cita(r)
    _producto(sub.add_parser("cerrar", help="aprobación tácita: lo presentado y no rechazado queda aprobado"))
    x = sub.add_parser("excepcion", help="registra la excepción de R16 con las palabras del usuario")
    _producto(x)
    x.add_argument("--pais", required=True, metavar="XX", help="país elegido")
    _cita(x)
    _producto(sub.add_parser("ver", help="resumen de OFERTA.md, ESCALERA.md y estado"))
    _producto(sub.add_parser("recalcular", help="rehace solo la economía de ESCALERA.md (estado modelado o más)"))


def _error(msg: str, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _ahora() -> datetime:
    from trovefy.vault.escritura import ZONA_NEGOCIO

    return datetime.now(ZONA_NEGOCIO)


def _hoy() -> date:
    return _ahora().date()


def _coma(x: object) -> str:
    return str(x).replace(".", ",")


def _rel(vault: Path, ruta: Path) -> str:
    try:
        return ruta.relative_to(vault).as_posix()
    except ValueError:
        return str(ruta)


def precios_front(valores: list[str]) -> dict[str, Decimal]:
    """``["XR:65", "XE:13,90"]`` → ``{"XR": Decimal("65"), "XE": Decimal("13.90")}``; mal formado → ``_Uso``."""
    out: dict[str, Decimal] = {}
    for v in valores:
        m = _PRECIO_FRONT.match(v.strip())
        importe = None
        if m:
            try:
                importe = Decimal(m.group(2).strip().replace(",", "."))
            except InvalidOperation:
                importe = None
        if importe is None or not importe.is_finite() or importe <= 0:
            raise _Uso(f"--precio-front mal formado: «{v}»; usa XX:importe en la moneda del país (p. ej. XR:65)")
        pais = m.group(1).upper()
        if pais in out:
            raise _Uso(f"--precio-front repetido para {pais}")
        out[pais] = importe
    return out


# --- preparar --------------------------------------------------------------------------------------


def _ficha_original(vault: Path, p_id: str) -> dict | None:
    from trovefy.vault import frontmatter
    from trovefy.vault.producto import ruta_producto

    meta = frontmatter.leer(ruta_producto(vault, p_id))[0] or {}
    oferta_id = meta.get("oferta_id")
    if not isinstance(oferta_id, str) or not _ID_OFERTA.fullmatch(oferta_id) or ".." in oferta_id:
        return None
    ficha = vault / "wiki" / "ofertas" / f"{oferta_id}.md"
    return (frontmatter.leer(ficha)[0] or {}) if ficha.is_file() else None


def _precio_original(ficha: dict | None) -> str:
    if ficha is None or ficha.get("precio") in (None, ""):
        return "no medido (sin ficha de la oferta o sin precio)"
    try:
        precio = Decimal(str(ficha["precio"]).strip().replace(",", "."))
    except InvalidOperation:
        return "no medido (precio de la ficha no legible)"
    if not precio.is_finite():
        return "no medido (precio de la ficha no legible)"
    moneda = ficha.get("moneda")
    texto = _coma(precio.quantize(Decimal("0.01")))
    if isinstance(moneda, str) and moneda.strip():
        return f"{texto} {moneda.strip().upper()}"
    return f"{texto}, moneda no medida"


def _landing_original(ficha: dict | None) -> str:
    dominio = (ficha or {}).get("dominio")
    if isinstance(dominio, str) and dominio.strip():
        return f"https://{dominio.strip().strip('/')}/"
    return "no medida (la ficha de la oferta no trae dominio)"


def _preparar(args: argparse.Namespace) -> int:
    from trovefy.config import mercados as mercados_cfg
    from trovefy.economia.config import cargar_economia, costes_de
    from trovefy.modelar.salida import ESTADOS_PERMITIDOS
    from trovefy.vault import frontmatter
    from trovefy.vault.producto import estado_pais, pais_elegido, ruta_producto
    from trovefy.vault.rutas import vault_root

    vault = vault_root()
    p_id = args.producto
    carpeta = ruta_producto(vault, p_id).parent  # ValueError si el p-id no vale
    faltan: list[str] = []
    avisos: list[str] = []
    print(f"Preparar /modelar · {p_id}")
    if not (carpeta / "PRODUCTO.md").is_file():
        return _cierre_preparar([f"falta productos/{p_id}/PRODUCTO.md: el producto sale de /auditar"], [])

    pais = None
    try:
        pais, reserva, _ = pais_elegido(vault, p_id)
        print(f"- país elegido: {pais}" + (f" (reserva {reserva})" if reserva else " (sin reserva)"))
    except FileNotFoundError as e:
        faltan.append(str(e))
    if pais:
        estado = estado_pais(vault, p_id, pais)
        print(f"- estado de {pais}: {estado or 'sin estado'}")
        if estado not in ESTADOS_PERMITIDOS:
            faltan.append(f"{pais} está en {estado or 'sin estado'}: /modelar solo trabaja en aprobado "
                          "(o en modelado, para rehacer)")
        ruta_mercados = vault / "config" / "mercados.yaml"
        mercado = mercados_cfg.cargar(ruta_mercados).get(pais) if ruta_mercados.is_file() else None
        if mercado is None:
            faltan.append(f"falta {pais} en config/mercados.yaml")
        else:
            bajo, alto = (Decimal(str(x)).quantize(Decimal("0.01")) for x in mercado.banda_eur)
            print(f"- {pais}: idioma {mercado.idioma} · moneda {mercado.moneda} · banda {_coma(bajo)}–{_coma(alto)} €")

    auditoria = carpeta / "AUDITORIA.md"
    if auditoria.is_file():
        print("- AUDITORIA.md: está")
        if (frontmatter.leer(auditoria)[0] or {}).get("teardown"):
            print("- teardown: lo trae AUDITORIA.md; reutilízalo")
        else:
            print("- teardown: el teardown lo haces tú en este paso")
    else:
        faltan.append(f"falta productos/{p_id}/AUDITORIA.md: /auditar")

    ficha = _ficha_original(vault, p_id)
    print(f"- landing del original: {_landing_original(ficha)}")
    print(f"- precio del original: {_precio_original(ficha)}")

    if not (carpeta / "referencia" / "anuncios.md").is_file():
        avisos.append("falta referencia/anuncios.md: ejecuta antes /ver-anuncios (plan 15)")
    try:
        costes = costes_de(cargar_economia(vault))
        print("- config/economia.yaml: está")
        if getattr(costes, "motivo", None):
            avisos.append(f"comisiones de la ruta activa: {costes.motivo}")
    except (FileNotFoundError, ValueError) as e:  # EconomiaInvalida es un ValueError
        faltan.append(str(e))
    ejemplo = _RAIZ / EJEMPLO
    print(f"- ejemplo de modelar.yaml: {ejemplo if ejemplo.is_file() else EJEMPLO.as_posix()}")
    return _cierre_preparar(faltan, avisos)


def _cierre_preparar(faltan: list[str], avisos: list[str]) -> int:
    for a in avisos:
        print(f"Aviso: {a}")
    if faltan:
        print("Falta, y sin esto no se modela:")
        for f in faltan:
            print(f"- {f}")
        return 1
    print("Listo: escribe productos/<P>/modelar.yaml y ejecuta `trovefy modelar escribir`.")
    return 0


# --- escribir, ver y recalcular ----------------------------------------------------------------------


def _cifra(bloque: dict, campo: str, unidad: str = " USD") -> str:
    valor = bloque.get(campo)
    if valor is None:
        return bloque.get(f"{campo}_motivo") or "no medido"
    return f"{_coma(valor)}{unidad}"


def _resumen_escalera(paises: dict) -> None:
    for pais, b in paises.items():
        pasos = b.get("pasos")
        if not pasos:
            print(f"{pais}: escalera {b.get('pasos_motivo') or 'no medida'}")
        else:
            front = pasos["front"]
            print(f"{pais}: front {_coma(front['precio'])} {b.get('moneda')} ({b.get('fuente_precio')})")

        print(f"  BE {_cifra(b, 'be_usd')} · CPA test {_cifra(b, 'cpa_test_usd')} · CPA escala "
              f"{_cifra(b, 'cpa_escala_usd')} · ROAS de equilibrio {_cifra(b, 'roas_be', '')}")
        for a in b.get("avisos") or ():
            print(f"  Aviso: {a}")


def _escribir(args: argparse.Namespace) -> int:
    from trovefy import fx
    from trovefy.config import mercados as mercados_cfg
    from trovefy.economia.config import cargar_economia
    from trovefy.modelar.esquema import ModeladoInvalido, cargar_modelado
    from trovefy.modelar.salida import cargar_escalera, cargar_oferta, escribir_modelado
    from trovefy.vault.producto import pais_elegido, ruta_producto
    from trovefy.vault.rutas import vault_root

    vault = vault_root()
    p_id = args.producto
    precios = precios_front(args.precio_front)
    carpeta = ruta_producto(vault, p_id).parent
    fuente = carpeta / "modelar.yaml"
    if not fuente.is_file():
        raise FileNotFoundError(f"falta productos/{p_id}/modelar.yaml: escríbelo siguiendo {EJEMPLO.as_posix()}")
    pais, _, _ = pais_elegido(vault, p_id)
    ruta_mercados = vault / "config" / "mercados.yaml"
    if not ruta_mercados.is_file():
        raise FileNotFoundError("falta config/mercados.yaml")
    mercado = mercados_cfg.cargar(ruta_mercados).get(pais)
    if mercado is None:
        raise ValueError(f"falta {pais} en config/mercados.yaml")
    config = cargar_economia(vault)
    try:
        m = cargar_modelado(fuente, p_id, pais, mercado.idioma)
    except ModeladoInvalido as e:
        print("modelar.yaml no es válido; corrige esto y repite:", file=sys.stderr)
        for err in e.errores:
            print(f"- {err}", file=sys.stderr)
        return 2
    hoy = _hoy()
    cambio = fx.cambio_del_dia(vault, hoy)
    rutas = escribir_modelado(vault, p_id, m, config, cambio, precios, hoy, _ahora())
    print(f"Oferta presentada: {p_id} · {pais}")
    for r in rutas:
        print(f"- {_rel(vault, r)}")
    if cambio is None:
        print("Cambio del BCE: no medido hoy; lo que depende de él sale «no medido».")
    oferta = cargar_oferta(vault, p_id)
    valor = oferta.get("se_puede_mejorar")
    print(f"Tercera señal (se puede mejorar: {_SENAL.get(valor, 'no medida')}): "
          f"{oferta.get('se_puede_mejorar_motivo') or 'sin motivo'}")
    _resumen_escalera(cargar_escalera(vault, p_id))
    print(CIERRE)
    return 0


def _ver(args: argparse.Namespace) -> int:
    from trovefy.modelar.salida import cargar_escalera, cargar_oferta
    from trovefy.vault.producto import estado_pais, pais_elegido
    from trovefy.vault.rutas import vault_root

    vault = vault_root()
    p_id = args.producto
    oferta = cargar_oferta(vault, p_id)
    paises = cargar_escalera(vault, p_id)
    pais, _, _ = pais_elegido(vault, p_id)
    print(f"Oferta de {p_id} · {oferta.get('pais')} · {oferta.get('fecha')}")
    print(f"- aprobación: {oferta.get('aprobacion') or 'no medida'}")
    nota = (oferta.get("autopsia") or {})
    print(f"- autopsia: original {_coma((nota.get('original') or {}).get('nota'))} · nuestra "
          f"{_coma((nota.get('nuestra') or {}).get('nota'))}")
    valor = oferta.get("se_puede_mejorar")
    print(f"- se puede mejorar: {_SENAL.get(valor, 'no medida')} ({oferta.get('se_puede_mejorar_motivo') or 'sin motivo'})")
    print(f"- estado de {pais}: {estado_pais(vault, p_id, pais) or 'sin estado'}")
    _resumen_escalera(paises)
    return 0


def _recalcular(args: argparse.Namespace) -> int:
    from trovefy import fx
    from trovefy.economia.config import cargar_economia
    from trovefy.modelar.recalculo import recalcular
    from trovefy.modelar.salida import cargar_escalera
    from trovefy.vault.rutas import vault_root

    vault = vault_root()
    config = cargar_economia(vault)
    hoy = _hoy()
    cambio = fx.cambio_del_dia(vault, hoy)
    if cambio is None:
        print("No se recalcula: hoy no hay cambio del BCE y la economía en USD saldría «no medido». "
              "Vuelve a intentarlo más tarde.", file=sys.stderr)
        return 1
    ruta, version = recalcular(vault, args.producto, config, cambio, hoy, _ahora())
    print(f"Economía recalculada: {_rel(vault, ruta)} (la anterior en {_rel(vault, version)})")
    print("Precios, pasos activos, OFERTA.md, aprobación y estado: sin cambios.")
    _resumen_escalera(cargar_escalera(vault, args.producto))
    return 0


# --- aprobación ----------------------------------------------------------------------------------


def _aprobar(args: argparse.Namespace) -> int:
    from trovefy.modelar.aprobacion import MOTIVO_RECHAZADA, aprobar
    from trovefy.vault.rutas import vault_root

    try:
        print(aprobar(vault_root(), args.producto, args.cita, _ahora()))
    except ValueError as e:
        if str(e) == MOTIVO_RECHAZADA:  # gate: la oferta rechazada no se aprueba
            return _error(str(e), 1)
        raise
    return 0


def _rechazar(args: argparse.Namespace) -> int:
    from trovefy.modelar.aprobacion import rechazar
    from trovefy.vault.rutas import vault_root

    vault = vault_root()
    ruta = rechazar(vault, args.producto, args.cita, _ahora())
    print(f"Oferta de {args.producto}: rechazada. Tu cita queda en {_rel(vault, ruta)}. Vuelve a /modelar.")
    return 0


def _cerrar(args: argparse.Namespace) -> int:
    from trovefy.modelar.aprobacion import cerrar
    from trovefy.vault.rutas import vault_root

    c = cerrar(vault_root(), args.producto, _ahora())
    print(c)
    return 1 if c.bloqueado else 0


def _excepcion(args: argparse.Namespace) -> int:
    from trovefy.modelar.aprobacion import cerrar, registrar_excepcion
    from trovefy.vault.rutas import vault_root

    vault = vault_root()
    ahora = _ahora()
    try:
        ruta = registrar_excepcion(vault, args.producto, args.pais, args.cita, ahora)
    except ValueError as e:  # gate no pasado (oferta rechazada, país que no es el elegido…): nada escrito
        return _error(str(e), 1)
    print(f"Excepción de R16 registrada con tu cita: {_rel(vault, ruta)}")
    c = cerrar(vault, args.producto, ahora)  # idempotente: dice si el país pasa a modelado
    print(c)
    return 1 if c.bloqueado else 0


_ACCIONES = {
    "preparar": _preparar, "escribir": _escribir, "aprobar": _aprobar, "rechazar": _rechazar,
    "cerrar": _cerrar, "excepcion": _excepcion, "ver": _ver, "recalcular": _recalcular,
}


def _ejecutar(args: argparse.Namespace) -> int:
    from trovefy.secretos import RevisionSecretosNoDisponible

    try:
        return _ACCIONES[args.accion](args)
    except RevisionSecretosNoDisponible as e:
        return _error(str(e))
    except (ValueError, FileNotFoundError) as e:  # EstadoInesperado, EconomiaInvalida, PrecioInvalido, _Uso
        return _error(str(e))
    except KeyboardInterrupt:
        print("INTERRUMPIDA: cancelado por el usuario (Ctrl-C).", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001 - la CLI nunca muestra un traceback
        return _error(f"fallo inesperado ({type(e).__name__})", 3)


registrar("modelar", _configurar, _ejecutar, ayuda="oferta propia: autopsia, escalera, brandbook y comparativa")
