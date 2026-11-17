"""Subcomando `trovefy producto`: el entregable PDF (plan 17, Tarea 13).

Ficha, plan, imágenes de APIMart con tope, gates, maqueta con WeasyPrint, QC con los agentes y cierre.
Claude escribe el texto (D-27); aquí solo se comprueba, se maqueta, se cobra y se registra.

Códigos de salida: 0 bien · 1 una puerta no pasa (estado, señales, gates, no apto, tope, STOP, sin precio,
sin veredicto, sin cierre) · 2 error de uso o de configuración · 3 interrumpido o fallo inesperado. Ninguna
salida lleva la clave de APIMart ni el contenido de ``claude.env``; de un ``task_id`` solo se muestran los
últimos 6 caracteres. Sin ``vista-previa``: su dueño es el plan 18 (resolución 16).
"""

import argparse
import re
import subprocess
import sys
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from trovefy.cli import registrar
from trovefy.secretos import RUTA_CLAUDE_ENV

_SKILL = "producto"
RUTA_ENV = RUTA_CLAUDE_ENV  # los tests la cambian por un env de prueba en tmp_path
_CUATRO = Decimal("0.0001")
_DOS = Decimal("0.01")
_PAGINAS = re.compile(r"\d+(?:,\d+)*")
_SECRETOS: list[str] = []  # la clave leída en esta ejecución: se tacha de toda salida


class _Uso(ValueError):
    """Error de uso de la CLI (argumento mal formado)."""


# --- red y reloj: puntos de inyección de los tests ---------------------------------------------------


def _abrir(req, timeout=None):
    from trovefy.apimart.http import abrir_sin_redireccion

    return abrir_sin_redireccion(req, timeout=timeout)


def _abrir_publico(req, timeout=None):
    from trovefy.apimart.http import abrir_sin_redireccion

    return abrir_sin_redireccion(req, timeout=timeout)


def _dormir(segundos: float) -> None:
    time.sleep(segundos)


def _ahora() -> datetime:
    from trovefy.vault.escritura import ZONA_NEGOCIO

    return datetime.now(ZONA_NEGOCIO)


# --- salida ------------------------------------------------------------------------------------------


def _tachar(texto: object) -> str:
    t = str(texto)
    for s in _SECRETOS:
        if s:
            t = t.replace(s, "***")
    return t


def _decir(texto: object = "") -> None:
    print(_tachar(texto))


def _error(msg: object, codigo: int = 2) -> int:
    print(f"Error: {_tachar(msg)}", file=sys.stderr)
    return codigo


def _usd(valor: Decimal, q: Decimal = _CUATRO) -> str:
    return str(valor.quantize(q))


def _tid(task_id: str) -> str:
    return f"…{task_id[-6:]}" if task_id else "sin task_id"


def _rel(vault: Path, ruta: Path) -> str:
    try:
        return Path(ruta).relative_to(vault).as_posix()
    except ValueError:
        return str(ruta)


def _log(vault: Path, que: str, archivos: list[Path], ahora: datetime) -> None:
    from trovefy.vault.escritura import anadir_log

    anadir_log(vault, _SKILL, que, [_rel(vault, a) for a in archivos], ahora=ahora)


# --- argumentos --------------------------------------------------------------------------------------


def _p_id(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("p_id", metavar="P", help="p-id del producto (productos/<P>/)")


def _pieza(sub: argparse.ArgumentParser, requerida: bool = True) -> None:
    sub.add_argument("--pieza", required=requerida, default=None if requerida else "principal", metavar="X",
                     help="principal, bono-N, bump, u1, u2, u3 o downsell")


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    sub.add_parser("iniciar", help="copia config/producto.yaml de la plantilla (nunca sobrescribe)")

    f = sub.add_parser("ficha", help="paso 1: comprueba estado y señales y escribe entregable/FICHA.md")
    _p_id(f)
    f.add_argument("--pais", required=True, metavar="XX")
    f.add_argument("--exigencia", required=True, choices=("normal", "sanitario", "educativo"))
    f.add_argument("--tipo", required=True, choices=("ebook", "kit"))

    pl = sub.add_parser("plan", help="paso 2: cuenta las palabras de <pieza>/PLAN.md frente al objetivo")
    _p_id(pl)
    _pieza(pl)

    im = sub.add_parser("imagenes", help="paso 5: imágenes de entregable/imagenes.yaml con APIMart, dentro del tope")
    _p_id(im)
    modo = im.add_mutually_exclusive_group()
    modo.add_argument("--simular", action="store_true", help="mide el precio y anota el lote sin enviar nada")
    modo.add_argument("--reanudar", action="store_true", help="sondea las tareas pendientes; nunca reenvía")
    modo.add_argument("--descartar", metavar="IMAGEN",
                      help="marca fallido un envío sin respuesta (su estimado sigue contando) para reenviarlo")
    _pieza(im, requerida=False)

    t = sub.add_parser("tope", help="sube el tope de APIMart del producto con la cita literal del usuario")
    _p_id(t)
    t.add_argument("--usd", required=True, help="tope nuevo en USD (más que el actual)")
    t.add_argument("--cita", required=True, help="las palabras del usuario, literales")

    g = sub.add_parser("gates", help="paso 4: ensambla la pieza y pasa los gates, sin hacer el PDF")
    _p_id(g)
    _pieza(g)

    m = sub.add_parser("maquetar", help="pasos 6-7: PDF con WeasyPrint, QC de gates y maqueta, hoja de contactos")
    _p_id(m)
    _pieza(m)

    q = sub.add_parser("qc", help="paso 8: hoja de contactos de la última versión (o solo --paginas, relectura)")
    _p_id(q)
    _pieza(q)
    q.add_argument("--paginas", metavar="3,7", help="solo estas páginas (las que se tocaron)")

    a = sub.add_parser("anotar-qc", help="pasos 8-9: anota en QC.md la respuesta del agente, leída por stdin")
    _p_id(a)
    _pieza(a)
    a.add_argument("--version", required=True, type=int, metavar="N")
    a.add_argument("--agente", required=True, choices=("revisor", "nativo"))

    e = sub.add_parser("estado", help="piezas, versiones y veredictos; gasto y tope de APIMart")
    _p_id(e)

    c = sub.add_parser("cerrar", help="paso 10: todas las piezas aptas → versiones en PRODUCTO.md y producido")
    _p_id(c)
    c.add_argument("--pais", required=True, metavar="XX")


# --- iniciar, ficha y plan ---------------------------------------------------------------------------


def _iniciar(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.producto.config import iniciar_config

    try:
        ruta = iniciar_config(vault)
    except FileExistsError as e:
        return _error(e)
    _log(vault, "config/producto.yaml copiada de la plantilla", [ruta], _ahora())
    _decir(f"Listo: {_rel(vault, ruta)}. Sus valores los decide el usuario.")
    return 0


def _ficha(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.producto.ficha import crear_ficha, leer_ficha

    ruta = crear_ficha(vault, args.p_id, args.pais.strip().upper(), args.exigencia, args.tipo, _ahora())
    ficha = leer_ficha(vault, args.p_id)
    _decir(f"Ficha: {_rel(vault, ruta)} · {ficha.pais} · {ficha.idioma} · {ficha.exigencia} · {ficha.tipo}")
    for p in ficha.piezas:
        _decir(f"- {p.id} ({p.tipo}): «{p.titulo}» · {p.paginas_objetivo} páginas objetivo")
    return 0


def _pieza_ficha(vault: Path, p_id: str, pieza_id: str):
    from trovefy.producto.ficha import leer_ficha

    ficha = leer_ficha(vault, p_id)
    pf = next((x for x in ficha.piezas if x.id == pieza_id), None)
    if pf is None:
        raise ValueError(f"la pieza {pieza_id} no está en FICHA.md ({', '.join(x.id for x in ficha.piezas)})")
    return ficha, pf


def _plan(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.pdf.plan import comprobar_plan
    from trovefy.producto.config import cargar_config
    from trovefy.producto.rutas import pieza

    _, pf = _pieza_ficha(vault, args.p_id, args.pieza)
    ruta = pieza(vault, args.p_id, args.pieza).raiz / "PLAN.md"
    if not ruta.is_file():
        raise FileNotFoundError(f"falta {_rel(vault, ruta)}: escríbelo (paso 2) y repite")
    c = comprobar_plan(ruta.read_text(encoding="utf-8"), pf.paginas_objetivo, cargar_config(vault))
    _decir(f"Plan de {args.pieza}: {c.palabras} palabras, {c.fichas} fichas, {c.paginas_imagen} páginas de imagen "
           f"→ {c.paginas_estimadas} páginas estimadas (objetivo {c.objetivo})")
    _decir(c.mensaje)
    return 0 if c.paginas_estimadas >= c.objetivo else 1


# --- imágenes y tope ---------------------------------------------------------------------------------


def _gasto_y_tope(vault: Path, p_id: str) -> str:
    from trovefy.apimart.gasto import gastado_usd, leer_costes
    from trovefy.producto.config import ConfigInvalida, cargar_config, tope_de

    try:
        gastado = _usd(gastado_usd(leer_costes(vault, p_id)))
    except ValueError as e:  # CostesCorruptos
        gastado = f"no medido ({e})"
    try:
        tope = f"{_usd(tope_de(vault, p_id, cargar_config(vault)), _DOS)} USD"
    except (ConfigInvalida, FileNotFoundError) as e:
        tope = f"no medido ({e})"
    return f"gastado {gastado} USD de un tope de {tope}"


def _credenciales():
    from trovefy.apimart.http import leer_credenciales

    cred = leer_credenciales(RUTA_ENV)
    _SECRETOS.append(cred.clave)
    return cred


def _precio(vault: Path, base: str, cfg):
    from trovefy.apimart.precios import elegir_modelo, precio_imagen

    hoy = _ahora().date()
    medidos = [precio_imagen(vault, base, m, cfg.resolucion, hoy, abrir=_abrir) for m in cfg.modelos_imagen]
    for m, p in zip(cfg.modelos_imagen, medidos, strict=True):
        _decir(f"- precio de {m} ({cfg.resolucion}): " + (f"{p.usd_por_imagen} USD por imagen ({p.fuente})"
                                                          if p else "no medido"))
    return elegir_modelo(medidos)


def _imagenes(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.apimart import lote
    from trovefy.producto.config import cargar_config
    from trovefy.producto.rutas import validar_p_id

    p_id = validar_p_id(args.p_id)
    if not (vault / "productos" / p_id / "PRODUCTO.md").is_file():
        raise FileNotFoundError(f"no existe productos/{p_id}/PRODUCTO.md")
    if args.descartar:
        n = lote.descartar(vault, p_id, args.pieza, args.descartar, ahora=_ahora)
        _decir(f"{args.pieza}/{args.descartar}: {n} envío(s) sin respuesta descartado(s); su estimado sigue "
               "contando. El próximo lote puede reenviarla.")
        _decir(f"APIMart: {_gasto_y_tope(vault, p_id)}")
        return 0
    cfg = cargar_config(vault)
    cred = _credenciales()
    if args.reanudar:
        r = lote.reanudar(vault, p_id, cred=cred, abrir=_abrir, abrir_publico=_abrir_publico, dormir=_dormir,
                          ahora=_ahora)
    else:
        peticiones = lote.leer_peticiones(vault, p_id)
        _decir(f"Imágenes de {p_id}: {len(peticiones)} en imagenes.yaml" + (" (simulación)" if args.simular else ""))
        precio = _precio(vault, cred.base, cfg)
        if precio is not None:
            _decir(f"- modelo elegido (el más barato medido, P-11): {precio.modelo} · {precio.usd_por_imagen} USD")
        r = lote.generar_imagenes(vault, p_id, peticiones, cred=cred, cfg=cfg, precio=precio, abrir=_abrir,
                                  abrir_publico=_abrir_publico, dormir=_dormir, ahora=_ahora,
                                  simular=args.simular)
    _resultado_lote(r, args.simular)
    _decir(f"APIMart: {_gasto_y_tope(vault, p_id)}")
    if r.detenido:
        _decir(f"Detenido: {r.detenido}")
        if r.alerta_id:
            _decir(f"Alerta en el buzón: {r.alerta_id}. El tope solo lo sube el usuario, con sus palabras.")
        return 1
    return 0


def _resultado_lote(r, simular: bool) -> None:
    def lista(xs):
        return ", ".join(xs) if xs else "ninguna"

    if simular:
        _decir("- simulación: no se envió nada")
    _decir(f"- generadas: {lista(r.generadas)}")
    _decir(f"- omitidas (ya generadas con el mismo prompt): {lista(r.omitidas)}")
    _decir(f"- pendientes: {lista(r.pendientes)}")
    _decir(f"- fallidas: {lista(r.fallidas)}")
    for a in r.avisos:
        _decir(f"  Aviso: {a}")


def _importe(texto: str) -> Decimal:
    try:
        d = Decimal(texto.strip().replace(",", "."))
    except InvalidOperation:
        raise _Uso(f"importe mal escrito: «{texto}» (en USD, p. ej. 3 o 3.50)") from None
    if not d.is_finite() or d <= 0:
        raise _Uso(f"importe mal escrito: «{texto}» (en USD, mayor que 0)")
    return d


def _tope(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.apimart.gasto import subir_tope

    usd = _importe(args.usd)
    ruta = subir_tope(vault, args.p_id, usd, args.cita, _ahora())  # la cita va tal cual, sin recortar
    _decir(f"Tope de APIMart subido con la cita del usuario: {_rel(vault, ruta)}")
    _decir(f"APIMart: {_gasto_y_tope(vault, args.p_id)}")
    return 0


# --- gates, maqueta y QC -----------------------------------------------------------------------------


def _hallazgos(informe) -> None:
    for h in informe.hallazgos:
        _decir(f"  {h.gate} · {h.severidad} · {h.donde} · {h.texto}")


def _gates(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.pdf.gates import evaluar
    from trovefy.pdf.render import ensamblar_pieza
    from trovefy.producto.config import cargar_config

    e = ensamblar_pieza(vault, args.p_id, args.pieza)
    inf = evaluar(e.html, raiz=e.pieza.raiz, idioma=e.ficha.idioma, exigencia=e.ficha.exigencia,
                  tipo_pieza=e.pieza_ficha.tipo, paginas_objetivo=e.pieza_ficha.paginas_objetivo,
                  cfg=cargar_config(vault), vault=vault)
    _decir(f"Gates de {args.pieza}: puntuación {inf.puntuacion} · {inf.palabras} palabras · "
           f"{inf.paginas_estimadas} páginas estimadas (objetivo {e.pieza_ficha.paginas_objetivo}) · "
           + ("pasa" if inf.pasa else "no pasa"))
    _hallazgos(inf)
    return 0 if inf.pasa else 1


def _contactos(vault: Path, raiz: Path, pdf: Path, version: int, paginas: list[int] | None) -> Path | None:
    from trovefy.pdf.qc import QcNoDisponible, hoja_de_contactos, ruta_contactos

    destino = ruta_contactos(raiz, version, relectura=paginas is not None)
    try:
        return hoja_de_contactos(pdf, destino, paginas, base=vault)
    except QcNoDisponible as e:
        _decir(f"Hoja de contactos: {e}")
        return None


def _maquetar(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.pdf.render import producir_pdf
    from trovefy.producto.config import cargar_config
    from trovefy.producto.qc_registro import anotar_producido

    ahora = _ahora()
    r = producir_pdf(vault, args.p_id, args.pieza, cargar_config(vault), subprocess.run, ahora=ahora)
    raiz = r.html.parent.parent
    qc = anotar_producido(raiz, r, ahora)  # gates y maqueta, con el sha256 del PDF
    hoja = _contactos(vault, raiz, r.pdf, r.version, None) if r.pdf is not None else None
    _log(vault, f"{args.p_id} {args.pieza} v{r.version}: QC de gates y maqueta"
         + (f"; hoja de contactos {hoja.name}" if hoja else ""), [qc, *([hoja] if hoja else [])], ahora)

    _decir(f"{args.pieza} v{r.version}: gates {r.informe.puntuacion} ({'pasa' if r.informe.pasa else 'no pasa'})")
    _hallazgos(r.informe)
    if r.pdf is None:
        _decir("Sin PDF: " + ("no pasa los gates" if not r.informe.pasa else "problemas de fuentes"))
    else:
        en_pdfinfo = r.paginas_pdfinfo if r.paginas_pdfinfo is not None else "no medido"
        _decir(f"- PDF: {_rel(vault, r.pdf)} · {r.paginas} páginas (pdfinfo: {en_pdfinfo})")
    for d in r.desbordes:
        _decir(f"- desborda: {d} (página fija; nunca se recorta: acorta el texto o pártela)")
    for p in r.problemas:
        _decir(f"- {p}")
    if hoja:
        _decir(f"- hoja de contactos: {_rel(vault, hoja)} (para el agente revisor)")
    _decir(f"- QC: {_rel(vault, qc)}")
    _decir("Apto." if r.apto else "No apto.")
    return 0 if r.apto and hoja is not None else 1


def _ultima(vault: Path, p_id: str, pieza_id: str):
    from trovefy.producto.cierre import revisar

    e = next((x for x in revisar(vault, p_id) if x.id == pieza_id), None)
    if e is None:
        raise ValueError(f"la pieza {pieza_id} no está en FICHA.md")
    if e.version is None or e.pdf is None:
        raise FileNotFoundError(f"{pieza_id} aún no tiene PDF: `trovefy producto maquetar`")
    return e


def _paginas(texto: str | None) -> list[int] | None:
    if texto is None:
        return None
    limpio = texto.replace(" ", "")
    if not _PAGINAS.fullmatch(limpio) or any(int(n) < 1 for n in limpio.split(",")):
        raise _Uso(f"--paginas mal escrito: «{texto}» (números desde 1 separados por comas, p. ej. 3,7)")
    return [int(n) for n in limpio.split(",")]


def _qc(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.producto.rutas import pieza

    paginas = _paginas(args.paginas)
    e = _ultima(vault, args.p_id, args.pieza)
    raiz = pieza(vault, args.p_id, args.pieza).raiz
    pdf = vault / "productos" / args.p_id / e.pdf
    hoja = _contactos(vault, raiz, pdf, e.version, paginas)
    if hoja is None:
        return 1
    _log(vault, f"{args.p_id} {args.pieza} v{e.version}: hoja de contactos {hoja.name}"
         + (f" (relectura de las páginas {args.paginas})" if paginas else ""), [hoja], _ahora())
    _decir(f"{args.pieza} v{e.version}: {_rel(vault, hoja)}"
           + (" · relee solo estas páginas" if paginas else ""))
    return 0


def _anotar_qc(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.producto.qc_registro import NO_MEDIDO, anotar_qc, parsear_veredicto
    from trovefy.producto.rutas import pieza

    texto = sys.stdin.read()
    veredicto = parsear_veredicto(texto)
    raiz = pieza(vault, args.p_id, args.pieza).raiz
    ahora = _ahora()
    ruta = anotar_qc(raiz, args.version, args.agente, veredicto, texto, ahora)
    _log(vault, f"{args.p_id} {args.pieza} v{args.version}: {args.agente} · {veredicto or 'no medido'}", [ruta], ahora)
    if veredicto is None:
        _decir(f"{args.agente} v{args.version}: {NO_MEDIDO} (anotado así en {_rel(vault, ruta)}). La respuesta "
               "debe terminar en una sola línea «VEREDICTO: ok» o «VEREDICTO: corregir»: pídesela de nuevo.")
        return 1
    _decir(f"{args.agente} v{args.version}: {veredicto} → {_rel(vault, ruta)}")
    return 0


# --- estado y cierre ---------------------------------------------------------------------------------


def _estado(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.apimart.gasto import leer_costes
    from trovefy.producto.cierre import revisar
    from trovefy.producto.rutas import validar_p_id

    p_id = validar_p_id(args.p_id)
    if not (vault / "productos" / p_id / "PRODUCTO.md").is_file():
        raise FileNotFoundError(f"no existe productos/{p_id}/PRODUCTO.md")
    _decir(f"Entregable de {p_id}")
    try:
        estados = revisar(vault, p_id)
    except (FileNotFoundError, ValueError) as e:
        _decir(f"- ficha: {e}")
        estados = []
    for e in estados:
        if e.version is None:
            _decir(f"- {e.id}: sin PDF")
            continue
        _decir(f"- {e.id} v{e.version}: {e.pdf} · {e.paginas if e.paginas is not None else 'no medido'} págs · "
               f"gates {e.gates or 'no medido'} · maqueta {e.maqueta or 'no medido'} · revisor "
               f"{e.revisor or 'no medido'} · nativo {e.nativo or 'no medido'} · "
               + ("apta" if e.apta else "no apta"))
    _decir(f"APIMart: {_gasto_y_tope(vault, p_id)}")
    try:
        ultimas: dict = {}
        for f in leer_costes(vault, p_id):
            ultimas[f.intento] = f
        for f in ultimas.values():
            if f.estado in ("enviando", "enviada", "pendiente"):
                _decir(f"- {f.pieza}/{f.imagen}: {f.estado} (tarea {_tid(f.task_id)})")
    except ValueError:
        pass  # ya se dijo «no medido» en el gasto
    return 0


def _cerrar(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.producto.cierre import cerrar

    ok, mensajes = cerrar(vault, args.p_id, args.pais, _ahora())
    if ok:
        for m in mensajes:
            _decir(m)
        return 0
    _decir("No se cierra:")
    for m in mensajes:
        _decir(f"- {m}")
    return 1


_ACCIONES = {
    "iniciar": _iniciar, "ficha": _ficha, "plan": _plan, "imagenes": _imagenes, "tope": _tope, "gates": _gates,
    "maquetar": _maquetar, "qc": _qc, "anotar-qc": _anotar_qc, "estado": _estado, "cerrar": _cerrar,
}


def _ejecutar(args: argparse.Namespace) -> int:
    from trovefy.apimart.http import SinClave
    from trovefy.pdf.render import PdfNoDisponible
    from trovefy.producto.ficha import EstadoNoValido, OfertaNoAprobada, SinTresSenales
    from trovefy.secretos import RevisionSecretosNoDisponible
    from trovefy.vault.rutas import vault_root

    _SECRETOS.clear()
    try:
        return _ACCIONES[args.accion](args, vault_root())
    except (EstadoNoValido, SinTresSenales, OfertaNoAprobada) as e:  # puertas de /producto (contrato 3, §4.1)
        return _error(e, 1)
    except SinClave as e:
        arreglos = "".join(f"\n- {a}" for a in e.arreglos)
        return _error(f"APIMart sin credenciales: {e.motivo}{arreglos}")
    except PdfNoDisponible as e:
        return _error(e)
    except RevisionSecretosNoDisponible as e:
        return _error(e)
    except (ValueError, FileNotFoundError, FileExistsError) as e:  # _Uso, ConfigInvalida…
        return _error(e)
    except KeyboardInterrupt:
        print("INTERRUMPIDA: cancelado por el usuario (Ctrl-C).", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001 - la CLI nunca muestra un traceback
        return _error(f"fallo inesperado ({type(e).__name__})", 3)
    finally:
        _SECRETOS.clear()


registrar("producto", _configurar, _ejecutar,
          ayuda="entregable PDF: ficha, imágenes con tope, maquetación, gates, QC y cierre")
