"""Subcomando ``trovefy creativos``: la tanda de creativos (plan 21).

Claude escribe los textos (D-27): ``brief.yaml``, ``escenas.yaml`` y ``guiones/ADnn.yaml``. Aquí solo se valida,
se genera (APIMart y, si hace falta, ElevenLabs, siempre con el coste aprobado por el usuario y dentro del tope),
se compone, se renderiza, se mide y se registra. Nada se escribe en Meta.

Códigos de salida: 0 bien · 1 una puerta no pasa (estado, brief, tope, sin aprobar, STOP, sin precio, QA, Whisper,
sin cierre) · 2 error de uso o de configuración · 3 interrumpido o fallo inesperado. Ninguna salida lleva claves.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from trovefy.cli import registrar
from trovefy.secretos import RUTA_CLAUDE_ENV

_SKILL = "/creativos"
RUTA_ENV = RUTA_CLAUDE_ENV  # los tests la cambian
_SECRETOS: list[str] = []


class _Uso(ValueError):
    pass


class _Puerta(ValueError):
    """Una puerta del método no pasa (salida 1)."""


# --- red y reloj (puntos de inyección de los tests) ---------------------------------------------------------------


def _abrir(req, timeout=None):
    from trovefy.apimart.http import abrir_sin_redireccion

    return abrir_sin_redireccion(req, timeout=timeout)


def _abrir_publico(req, timeout=None):
    from trovefy.apimart.http import abrir_sin_redireccion

    return abrir_sin_redireccion(req, timeout=timeout)


def _abrir_elevenlabs(req, timeout=None):
    import urllib.request

    return urllib.request.urlopen(req, timeout=timeout)


def _dormir(segundos: float) -> None:
    time.sleep(segundos)


def _ahora() -> datetime:
    from trovefy.vault.escritura import ZONA_NEGOCIO

    return datetime.now(ZONA_NEGOCIO)


def _decir(texto: object = "") -> None:
    t = str(texto)
    for s in _SECRETOS:
        if s:
            t = t.replace(s, "***")
    print(t)


def _error(msg: object, codigo: int = 2) -> int:
    t = str(msg)
    for s in _SECRETOS:
        if s:
            t = t.replace(s, "***")
    print(f"Error: {t}", file=sys.stderr)
    return codigo


def _rel(vault: Path, ruta: Path) -> str:
    try:
        return Path(ruta).relative_to(vault).as_posix()
    except ValueError:
        return str(ruta)


# --- argumentos ---------------------------------------------------------------------------------------------------


def _base(sub: argparse.ArgumentParser, tanda: bool = True, ad: bool = False) -> None:
    sub.add_argument("--producto", required=True, metavar="P", help="p-id del producto")
    sub.add_argument("--pais", required=True, metavar="XX", help="código del país (dos letras)")
    if tanda:
        sub.add_argument("--tanda", required=True, metavar="tN", help="t1, t2…")
    if ad:
        sub.add_argument("--ad", metavar="ADnn", help="solo este anuncio")


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    sub.add_parser("iniciar", help="copia config/creativos.yaml de la plantilla (nunca sobrescribe)")
    c = sub.add_parser("contexto", help="lo que la tanda necesita del vault, en YAML (para que Claude lo lea)")
    _base(c, tanda=False)
    c.add_argument("--renovar", action="store_true")
    n = sub.add_parser("nueva", help="abre la siguiente tanda de test (t1, t2…) y dice su carpeta")
    _base(n, tanda=False)
    b = sub.add_parser("brief", help="paso 1: valida brief.yaml (20 candidatos, 10 elegidos) y escribe TANDA.md")
    _base(b)
    k = sub.add_parser("coste", help="estimación del coste de la tanda tal como está escrita (no envía nada)")
    _base(k)
    k.add_argument("--proveedor-voz", choices=("apimart", "elevenlabs"))
    a = sub.add_parser("aprobar-coste", help="guarda la estimación vigente con las palabras literales del usuario")
    _base(a)
    a.add_argument("--cita", required=True)
    a.add_argument("--proveedor-voz", choices=("apimart", "elevenlabs"))
    t = sub.add_parser("tope", help="fija el tope de la tanda (o de todas las renovaciones) con la cita del usuario")
    _base(t, tanda=False)
    t.add_argument("--tanda", required=True, metavar="tN|renovacion")
    t.add_argument("--usd", required=True)
    t.add_argument("--cita", required=True)
    e = sub.add_parser("escenas", help="imágenes de escenas.yaml con APIMart, dentro del tope y con coste aprobado")
    _base(e)
    modo = e.add_mutually_exclusive_group()
    modo.add_argument("--simular", action="store_true")
    modo.add_argument("--reanudar", action="store_true")
    modo.add_argument("--descartar", metavar="ESCENA")
    s = sub.add_parser("estaticos", help="compone los estáticos 1080×1350 con la marca y medios propios")
    _base(s, ad=True)
    v = sub.add_parser("voz", help="voz por partes de cada vídeo (APIMart o ElevenLabs)")
    _base(v, ad=True)
    v.add_argument("--solo-gancho", action="store_true")
    v.add_argument("--simular", action="store_true")
    v.add_argument("--proveedor", choices=("apimart", "elevenlabs"))
    v.add_argument("--voz", help="voz de APIMart (alloy, echo, fable, onyx, nova, shimmer)")
    cl = sub.add_parser("clips", help="clips de APIMart de cada vídeo (gancho, B-roll, UGC, claymation, 3D)")
    _base(cl, ad=True)
    cl.add_argument("--solo-gancho", action="store_true")
    modo = cl.add_mutually_exclusive_group()
    modo.add_argument("--simular", action="store_true")
    modo.add_argument("--reanudar", action="store_true")
    m = sub.add_parser("musica", help="la pista de la tanda: APIMart con licencia, la del usuario o la de otra tanda")
    _base(m)
    fuente = m.add_mutually_exclusive_group(required=True)
    fuente.add_argument("--prompt", help="descripción de la música (APIMart/Suno, instrumental)")
    fuente.add_argument("--propia", metavar="ARCHIVO", help="ruta en config/creativos/musica/ (con su licencia)")
    fuente.add_argument("--reutilizar", metavar="tN", help="la música guardada de otra tanda")
    m.add_argument("--simular", action="store_true")
    vi = sub.add_parser("video", help="monta un vídeo con ffmpeg (o solo la prueba del gancho)")
    _base(vi)
    vi.add_argument("--ad", required=True, metavar="ADnn")
    vi.add_argument("--solo-gancho", action="store_true")
    q = sub.add_parser("qa", help="QA automática de la tanda")
    _base(q)
    w = sub.add_parser("whisper", help="re-transcribe la voz con WhisperX local y mide la similitud")
    _base(w, ad=True)
    h = sub.add_parser("contactos", help="hoja de contactos (revisor) y textos (nativo)")
    _base(h)
    an = sub.add_parser("anotar", help="anota en QA.md la respuesta del agente, leída por stdin")
    _base(an)
    an.add_argument("--agente", required=True, choices=("revisor", "nativo"))
    an.add_argument("--version", required=True, help="la hoja o el HTML revisado (qc/…)")
    ce = sub.add_parser("cerrar", help="manifest.csv, PRODUCTO.md y aviso por Telegram")
    _base(ce)
    r = sub.add_parser("rehacer", help="reabre la tanda tras un veto, con el motivo literal del usuario")
    _base(r)
    r.add_argument("--ad", action="append", required=True)
    r.add_argument("--motivo", required=True)
    rn = sub.add_parser("renovar", help="abre la tanda de renovación sobre el ángulo ganador (lectura de /leer)")
    _base(rn, tanda=False)
    es = sub.add_parser("estado", help="la tanda: piezas, QA, gasto, tope y aprobación")
    _base(es)


# --- ayudas -------------------------------------------------------------------------------------------------------


def _cargar(args, vault: Path, *, renovar: bool = False, rehacer: bool = False):
    from trovefy.creativos.config import cargar_config
    from trovefy.creativos.contexto import cargar_contexto

    cfg = cargar_config(vault)
    ctx = cargar_contexto(vault, args.producto, args.pais.strip().upper(), cfg, renovar=renovar, rehacer=rehacer)
    return ctx, cfg


def _carpeta(vault: Path, ctx, tanda: str) -> Path:
    from trovefy.creativos.contexto import ruta_tanda

    carpeta = ruta_tanda(vault, ctx.producto, ctx.pais, tanda)
    if not carpeta.is_dir():
        raise FileNotFoundError(f"no existe la tanda {tanda}: `trovefy creativos nueva` o `renovar`")
    return carpeta


def _modo(vault: Path, args) -> tuple[bool, bool]:
    """(renovación, rehacer): una tanda de renovación trabaja con el test vivo; una tanda reabierta tras un veto,
    también con el país en ``montado`` (resolución 7)."""
    from trovefy.creativos import tanda as tanda_md
    from trovefy.creativos.contexto import ruta_tanda

    carpeta = ruta_tanda(vault, args.producto, args.pais.strip().upper(), args.tanda)
    if not carpeta.is_dir():
        return False, False
    meta, _, _ = tanda_md.leer(carpeta)
    return meta.get("tipo") == "renovacion", bool(meta.get("rehacer")) and not meta.get("cerrada")


def _contexto_tanda(args, vault: Path):
    """(ctx, cfg, carpeta, ficha, plan de renovación) con la ficha validada."""
    from trovefy.creativos.brief import cargar_ficha
    from trovefy.creativos.renovar import plan_de

    renovacion, rehacer = _modo(vault, args)
    ctx, cfg = _cargar(args, vault, renovar=renovacion, rehacer=rehacer)
    carpeta = _carpeta(vault, ctx, args.tanda)
    plan = plan_de(carpeta)
    return ctx, cfg, carpeta, cargar_ficha(carpeta, ctx, cfg, plan), plan


def _cred(*, simular: bool = False):
    from trovefy.apimart.http import SinClave, credenciales_publicas, leer_credenciales

    try:
        cred = leer_credenciales(RUTA_ENV)
    except SinClave:
        if not simular:
            raise
        return credenciales_publicas(RUTA_ENV)
    _SECRETOS.append(cred.clave)
    return cred


def _precio_imagen(vault: Path, base: str, cfg):
    from trovefy.apimart.precios import elegir_modelo, precio_imagen

    hoy = _ahora().date()
    return elegir_modelo([precio_imagen(vault, base, m, cfg.resolucion, hoy, abrir=_abrir) for m in cfg.modelos_imagen])


def _importe(texto: str) -> Decimal:
    try:
        d = Decimal(texto.strip().replace(",", "."))
    except InvalidOperation:
        raise _Uso(f"importe mal escrito: «{texto}» (en USD, p. ej. 6 o 6.00)") from None
    if not d.is_finite() or d <= 0:
        raise _Uso(f"importe mal escrito: «{texto}»")
    return d


def _elegidos(ficha, ad: str | None, tipo: str) -> list:
    salida = [e for e in ficha.elegidos if ficha.brief(e.ad).tipo == tipo and (ad is None or e.ad == ad)]
    if ad is not None and not salida:
        raise _Uso(f"{ad} no es un {tipo} de la tanda")
    return salida


def _envios(envios) -> int:
    codigo = 0
    for e in envios:
        linea = f"- {e.id}: {e.estado}"
        if e.coste_usd is not None:
            linea += f" · {e.coste_usd} USD"
        if e.motivo:
            linea += f" · {e.motivo}"
        _decir(linea)
        if e.estado in ("detenido", "fallida", "pendiente"):
            codigo = 1
    return codigo


def _gasto(vault: Path, ctx, cfg, tanda: str, carpeta: Path) -> str:
    from trovefy.apimart.gasto import gastado_usd, leer_costes
    from trovefy.creativos import coste

    try:
        gastado = gastado_usd(leer_costes(vault, ctx.producto, carpeta))
    except ValueError as e:
        return f"gasto no medido ({e})"
    tope, motivo = coste.limite(vault, ctx.producto, ctx.pais, tanda, cfg)
    return (f"gastado {gastado} USD; límite {tope} USD"
            + (" (sin aprobar: no se envía nada)" if motivo else " (aprobado por el usuario)"))


# --- acciones -----------------------------------------------------------------------------------------------------


def _iniciar(args, vault: Path) -> int:
    from trovefy.creativos.config import iniciar_config
    from trovefy.vault.escritura import anadir_log

    ruta = iniciar_config(vault)
    anadir_log(vault, _SKILL, "config/creativos.yaml copiada de la plantilla", [_rel(vault, ruta)], ahora=_ahora())
    _decir(f"Listo: {_rel(vault, ruta)}. Sus topes y precios los decide el usuario.")
    return 0


def _contexto(args, vault: Path) -> int:
    import yaml

    from trovefy.creativos.contexto import resumen

    ctx, _ = _cargar(args, vault, renovar=args.renovar)
    _decir(yaml.safe_dump(resumen(ctx), allow_unicode=True, sort_keys=False).rstrip())
    return 0


def _nueva(args, vault: Path) -> int:
    from trovefy.creativos import tanda as tanda_md
    from trovefy.creativos.contexto import ruta_tanda, siguiente_tanda

    ctx, _ = _cargar(args, vault)
    tanda, n = siguiente_tanda(vault, ctx.producto, ctx.pais)
    carpeta = ruta_tanda(vault, ctx.producto, ctx.pais, tanda)
    carpeta.mkdir(parents=True)
    tanda_md.actualizar(carpeta, {"tipo": "test", "producto": ctx.producto, "pais": ctx.pais, "tanda": tanda,
                                  "grupo": f"G{n}"}, "tanda abierta", _ahora())
    _decir(f"Tanda {tanda} (grupo G{n}): {_rel(vault, carpeta)}/ — escribe ahí brief.yaml, escenas.yaml y guiones/")
    return 0


def _brief(args, vault: Path) -> int:
    from trovefy.creativos.brief import BriefInvalido, cargar_ficha, escribir_ficha
    from trovefy.creativos.renovar import plan_de

    renovacion, rehacer = _modo(vault, args)
    ctx, cfg = _cargar(args, vault, renovar=renovacion, rehacer=rehacer)
    carpeta = _carpeta(vault, ctx, args.tanda)
    try:
        ficha = cargar_ficha(carpeta, ctx, cfg, plan_de(carpeta))
    except BriefInvalido as e:
        _decir(str(e))
        return 1
    ruta = escribir_ficha(vault, ctx, ficha, _ahora(), carpeta, "renovacion" if renovacion else "test")
    _decir(f"brief.yaml vale: {len(ficha.candidatos)} candidatos, {len(ficha.elegidos)} elegidos → {_rel(vault, ruta)}")
    for e in ficha.elegidos:
        b = ficha.brief(e.ad)
        _decir(f"- {ficha.nombre(e.ad)} · {e.uso} · {b.tipo} · {b.formato}")
    for m in ctx.motivos:
        _decir(f"  {m}")
    return 0


def _estimacion(args, vault: Path, ctx, cfg, carpeta, ficha):
    from trovefy.creativos.estimacion import estimar
    from trovefy.creativos.guion import cargar_escenas

    precio = None
    if cargar_escenas(carpeta):
        precio = _precio_imagen(vault, _cred(simular=True).base, cfg)
    return estimar(vault, cfg, carpeta, ficha, precio, forzar_voz=getattr(args, "proveedor_voz", None))


def _coste(args, vault: Path) -> int:
    from trovefy.creativos import coste

    ctx, cfg, carpeta, ficha, _ = _contexto_tanda(args, vault)
    est = _estimacion(args, vault, ctx, cfg, carpeta, ficha)
    tope = coste.tope_vigente(vault, ctx.producto, ctx.pais, args.tanda, cfg)
    _decir(f"Coste estimado de la tanda {args.tanda} (no se envió nada):")
    for linea in est.lineas() or ["nada que pagar: todo está hecho o no lleva APIMart"]:
        _decir(f"- {linea}")
    _decir(f"Total: {est.total} USD" + (" + lo no medido" if est.no_medido else "") + f" · tope {tope} USD")
    for m in est.no_medido:
        _decir(f"  {m}")
    if est.usa_elevenlabs and cfg.elevenlabs.coste_mensual_usd is not None:
        _decir(f"  ElevenLabs: además, el plan {cfg.elevenlabs.plan} cuesta {cfg.elevenlabs.coste_mensual_usd} USD al mes "
               "(lo contrata el usuario)")
    _decir(f"APIMart: {_gasto(vault, ctx, cfg, args.tanda, carpeta)}")
    return 1 if est.no_medido or est.total > tope else 0


def _aprobar_coste(args, vault: Path) -> int:
    from trovefy.creativos import coste

    ctx, cfg, carpeta, ficha, _ = _contexto_tanda(args, vault)
    est = _estimacion(args, vault, ctx, cfg, carpeta, ficha)
    tope = coste.tope_vigente(vault, ctx.producto, ctx.pais, args.tanda, cfg)
    ruta = coste.aprobar(vault, ctx.producto, ctx.pais, args.tanda, est, tope, args.cita, _ahora())
    _decir(f"Coste aprobado con las palabras del usuario: {est.total} USD (tope {tope} USD) → {_rel(vault, ruta)}")
    return 0


def _tope(args, vault: Path) -> int:
    from trovefy.creativos import coste

    pais = args.pais.strip().upper()
    ruta = coste.fijar_tope(vault, args.producto, pais, args.tanda, _importe(args.usd), args.cita, _ahora())
    _decir(f"Tope de creativos fijado con la cita del usuario: {_rel(vault, ruta)}")
    return 0


def _escenas(args, vault: Path) -> int:
    from trovefy.apimart import lote
    from trovefy.creativos import escenas
    from trovefy.creativos.guion import cargar_escenas

    ctx, cfg, carpeta, _, _ = _contexto_tanda(args, vault)
    d = escenas.destino(vault, ctx, cfg, args.tanda)
    if args.descartar:
        n = lote.descartar(vault, ctx.producto, "escena", args.descartar, ahora=_ahora, destino=d)
        _decir(f"{args.descartar}: {n} envío(s) sin respuesta descartado(s); su estimado sigue contando")
        return 0
    cred = _cred(simular=args.simular)
    if args.reanudar:
        r = lote.reanudar(vault, ctx.producto, cred=cred, abrir=_abrir, abrir_publico=_abrir_publico, dormir=_dormir,
                          ahora=_ahora, destino=d)
    else:
        lista = cargar_escenas(carpeta)
        precio = _precio_imagen(vault, cred.base, cfg)
        _decir(f"Escenas: {len(lista)} · precio " + (f"{precio.usd_por_imagen} USD/imagen ({precio.modelo})" if precio
                                                     else "no medido"))
        r = escenas.generar(vault, ctx, cfg, args.tanda, lista, cred=cred, precio=precio, abrir=_abrir,
                            abrir_publico=_abrir_publico, ahora=_ahora, simular=args.simular, dormir=_dormir)
    if args.simular:
        _decir("- simulación: no se envió nada")
    _decir(f"- generadas: {', '.join(r.generadas) or 'ninguna'} · omitidas: {', '.join(r.omitidas) or 'ninguna'} · "
           f"pendientes: {', '.join(r.pendientes) or 'ninguna'} · fallidas: {', '.join(r.fallidas) or 'ninguna'}")
    for a in r.avisos:
        _decir(f"  Aviso: {a}")
    _decir(f"APIMart: {_gasto(vault, ctx, cfg, args.tanda, carpeta)}")
    if r.detenido:
        _decir(f"Detenido: {r.detenido}")
        return 1
    return 0


def _fuentes(ctx) -> dict[str, Path]:
    from trovefy.pdf.fuentes import ruta_fuente

    salida = {}
    for uso in ("titulos", "texto"):
        familia = ctx.tipografias.get(uso) or ctx.tipografias.get("texto") or "Noto Sans"
        ruta = ruta_fuente(familia)
        if ruta is None:
            raise _Puerta(f"no medido: la tipografía «{familia}» del brandbook no está en la máquina "
                          "(trovefy producto lo explica: sudo apt install, lo hace el usuario)")
        salida[uso] = ruta
    return salida


def _estaticos(args, vault: Path) -> int:
    from trovefy.creativos import estaticos
    from trovefy.creativos.clips import medios_disponibles
    from trovefy.creativos.guion import cargar_guion

    ctx, cfg, carpeta, ficha, _ = _contexto_tanda(args, vault)
    fuentes = _fuentes(ctx)
    medios = medios_disponibles(carpeta, ctx.medios_propios)
    for e in _elegidos(ficha, args.ad, "imagen"):
        g = cargar_guion(carpeta, e.ad, "imagen", cfg)
        img = estaticos.componer(cfg, ctx.paleta, g, medios, fuentes)
        ruta, sha = estaticos.escribir_estatico(vault, carpeta, e.ad, img)
        _decir(f"- {e.ad}: {_rel(vault, ruta)} · sha256 {sha[:12]}")
    from trovefy.vault.escritura import anadir_log

    anadir_log(vault, _SKILL, f"{ctx.producto} {ctx.pais} {args.tanda}: estáticos compuestos",
               [_rel(vault, carpeta / "medios.json")], ahora=_ahora())
    return 0


def _voz(args, vault: Path) -> int:
    from trovefy.creativos import escenas, voz
    from trovefy.creativos.guion import cargar_guion

    ctx, cfg, carpeta, ficha, _ = _contexto_tanda(args, vault)
    precio, motivo = voz.elegir_proveedor(vault, cfg, carpeta, args.proveedor)
    if precio is None:
        _decir(f"Detenido: {motivo}")
        return 1
    d = escenas.destino(vault, ctx, cfg, args.tanda)
    llamar_a = llamar_e = None
    if not args.simular:
        if precio.proveedor == "apimart":
            llamar_a = voz.apimart_real(_cred(), _abrir)
        else:
            from trovefy.voz import elevenlabs

            cred_el = elevenlabs.leer_credenciales()
            _SECRETOS.append(cred_el.clave)
            llamar_e = voz.elevenlabs_real(cred_el, _abrir_elevenlabs)
    nombre_voz = args.voz or (cfg.voz_tts if precio.proveedor == "apimart" else cfg.elevenlabs.voz_id) or "nova"
    codigo = 0
    _decir(f"Voz: {precio.proveedor} · {precio.modelo} · {nombre_voz} · {precio.usd_por_caracter} USD/carácter")
    for e in _elegidos(ficha, args.ad, "video"):
        g = cargar_guion(carpeta, e.ad, "video", cfg)
        r = voz.generar(vault, ctx.producto, d, carpeta, g, precio=precio, voz=nombre_voz, llamar_apimart=llamar_a,
                        llamar_elevenlabs=llamar_e, ahora=_ahora, solo_gancho=args.solo_gancho, simular=args.simular)
        _decir(f"{e.ad}:")
        codigo = max(codigo, _envios(r))
    _decir(f"Gasto: {_gasto(vault, ctx, cfg, args.tanda, carpeta)}")
    return codigo


def _api_real(cred):
    from trovefy.apimart import cliente
    from trovefy.apimart.musica import RUTA_TAREA, enviar_musica, leer_tarea_musica
    from trovefy.apimart.subidas import subir
    from trovefy.apimart.video import descargar_binario, enviar_video, leer_tarea_video
    from trovefy.apimart.voz import subir_audio
    from trovefy.creativos.clips import Apimart
    from trovefy.vault.rutas import vault_root

    vault = vault_root()
    return Apimart(
        enviar_video=lambda c: enviar_video(cred, c, _abrir),
        enviar_musica=lambda c: enviar_musica(cred, c, _abrir),
        esperar_video=lambda t: cliente.esperar(cred, t, _abrir, _dormir, leer=leer_tarea_video),
        esperar_musica=lambda t: cliente.esperar(cred, t, _abrir, _dormir, ruta=RUTA_TAREA, leer=leer_tarea_musica),
        descargar_video=lambda u: descargar_binario(u, _abrir_publico),
        descargar_audio=lambda u: descargar_binario(u, _abrir_publico, tipo="audio"),
        subir_imagen=lambda r: subir(cred, r, vault, _abrir, _ahora()),
        subir_audio=lambda n, datos: subir_audio(cred, n, datos, _abrir))


def _clips(args, vault: Path) -> int:
    from trovefy.creativos import clips, escenas, pago
    from trovefy.creativos.guion import cargar_guion

    ctx, cfg, carpeta, ficha, _ = _contexto_tanda(args, vault)
    d = escenas.destino(vault, ctx, cfg, args.tanda)
    cred = _cred(simular=args.simular)
    api = _api_real(cred)
    if args.reanudar:
        from trovefy.producto.medios import CARPETA, escribir_medio, registrar_medio

        fuente = escenas.raiz_fuente(carpeta)

        def guardar_de(id_):
            def guardar(datos, estado):
                sha = escribir_medio(fuente / CARPETA / f"{id_}.mp4", datos, base=vault)
                registrar_medio(fuente, id_, f"{id_}.mp4", sha, "apimart", base=vault,
                                task_id=getattr(estado, "task_id", ""))
                return fuente / CARPETA / f"{id_}.mp4"
            return guardar

        return _envios(pago.reanudar(vault, ctx.producto, d, clips.PIEZA_CLIP, esperar=api.esperar_video,
                                     descargar=api.descargar_video, guardar_de=guardar_de, ahora=_ahora))
    codigo = 0
    for e in _elegidos(ficha, args.ad, "video"):
        g = cargar_guion(carpeta, e.ad, "video", cfg)
        r = clips.generar_clips(vault, ctx.producto, d, carpeta, g, cfg, propios=ctx.medios_propios, api=api,
                                ahora=_ahora, solo_gancho=args.solo_gancho, simular=args.simular)
        _decir(f"{e.ad} ({g.plantilla}):")
        codigo = max(codigo, _envios(r))
    _decir(f"APIMart: {_gasto(vault, ctx, cfg, args.tanda, carpeta)}")
    return codigo


def _musica(args, vault: Path) -> int:
    from trovefy.creativos import clips, escenas
    from trovefy.creativos.config import fuente_de
    from trovefy.creativos.contexto import ruta_tanda

    ctx, cfg, carpeta, _, _ = _contexto_tanda(args, vault)
    if args.propia:
        ruta = clips.musica_propia(vault, carpeta, Path(args.propia))
        _decir(f"Música propia con su licencia: {_rel(vault, ruta)}")
        return 0
    if args.reutilizar:
        ruta = clips.reutilizar_musica(vault, ruta_tanda(vault, ctx.producto, ctx.pais, args.reutilizar), carpeta)
        _decir(f"Música reutilizada de {args.reutilizar}: {_rel(vault, ruta)}")
        return 0
    e = clips.generar_musica(vault, ctx.producto, escenas.destino(vault, ctx, cfg, args.tanda), carpeta, cfg,
                             args.prompt, api=_api_real(_cred(simular=args.simular)), ahora=_ahora,
                             simular=args.simular,
                             fuente_licencia=fuente_de(vault, "apimart.licencia_musica_comercial") or "")
    return _envios([e])


def _video(args, vault: Path) -> int:
    from trovefy.creativos import clips, voz
    from trovefy.creativos import video as v
    from trovefy.creativos.estaticos import escribir_pieza
    from trovefy.creativos.guion import cargar_guion
    from trovefy.producto.medios import escribir_medio

    ctx, cfg, carpeta, ficha, _ = _contexto_tanda(args, vault)
    _elegidos(ficha, args.ad, "video")
    g = cargar_guion(carpeta, args.ad, "video", cfg)
    qc = carpeta / "qc"
    qc.mkdir(parents=True, exist_ok=True)
    tiras = {}
    for s in g.segmentos:
        if s.paginas:
            if ctx.pdf_vigente is None:
                raise _Puerta("no medido: PDF vigente del entregable (scroll_pdf)")
            tiras[s.clave] = v.tira_pdf(ctx.pdf_vigente, s.paginas, qc / ".tiras" / f"{args.ad}-{s.clave}.png",
                                        int(cfg.video_ancho * 0.8))
    voces = voz.pistas(carpeta, g)
    duraciones = {k: v.duracion_audio(r) for k, r in voces.items()}
    from trovefy.creativos.estaticos import colores

    color = "#{:02X}{:02X}{:02X}".format(*colores(ctx.paleta)[1])
    guion = v.guion_prueba(g, cfg) if args.solo_gancho else g
    entradas = v.Entradas(v.tramos(guion, clips.clips_descargados(carpeta, g),
                                   clips.medios_disponibles(carpeta, ctx.medios_propios), tiras, cfg),
                          voces, duraciones, clips.ruta_musica(carpeta), color)
    ass = qc / f"{args.ad}.ass"
    ass.write_text(v.subtitulos_ass(guion, cfg, ctx.tipografias, duraciones), encoding="utf-8")
    if args.solo_gancho:
        salida = qc / f"gancho-{args.ad}.mp4"
        v.renderizar(v.orden_plantilla(guion, entradas, cfg, ass, salida, hasta_s=cfg.prueba_gancho_s))
        fotos = v.fotogramas(salida, v.segundos_prueba(cfg), qc, f"gancho-{args.ad}")
        _decir(f"Prueba del gancho: {_rel(vault, salida)}. Mira estos fotogramas con Read antes del vídeo entero:")
        for f in fotos:
            _decir(f"- {_rel(vault, f)}")
        return 0
    tmp = qc / f".render-{args.ad}.mp4"
    v.renderizar(v.orden_plantilla(g, entradas, cfg, ass, tmp))
    datos = tmp.read_bytes()
    tmp.unlink()
    ruta, sha = escribir_pieza(vault, carpeta, args.ad, datos, "mp4", tipo="video", plantilla=g.plantilla)
    foto = v.fotogramas(ruta, [1.0], qc / ".fotogramas", f"miniatura-{args.ad}")[0]
    escribir_medio(carpeta / "miniaturas" / f"{args.ad}.jpg", foto.read_bytes(), base=vault)
    info = v.sondear(ruta)
    _decir(f"{args.ad}: {_rel(vault, ruta)} · {info['ancho']}×{info['alto']} · {info['duracion']:.1f} s · "
           f"{info['bytes'] // 1024} KB · sha256 {sha[:12]}")
    return 0


def _piezas(ficha) -> list[tuple[str, str]]:
    return [(e.ad, ficha.brief(e.ad).tipo) for e in ficha.elegidos]


def _qa(args, vault: Path) -> int:
    from trovefy.creativos import qa
    from trovefy.creativos.brief import leer_brief

    ctx, cfg, carpeta, ficha, plan = _contexto_tanda(args, vault)
    h = qa.revisar_tanda(vault, ctx, cfg, ficha, carpeta, renovacion=plan, datos_brief=leer_brief(carpeta))
    ruta = qa.escribir_qa_auto(carpeta, _piezas(ficha), h, _ahora())
    for x in h:
        _decir(f"{'✗' if x.bloquea else '·'} {x.ad or 'tanda'} · {x.regla} · {x.texto}")
    bloquean = [x for x in h if x.bloquea]
    _decir(f"QA automática: {'bloquea' if bloquean else 'ok'} → {_rel(vault, ruta)}")
    return 1 if bloquean else 0


def _whisper(args, vault: Path) -> int:
    from trovefy.creativos import whisper
    from trovefy.creativos.guion import cargar_guion
    from trovefy.creativos.manifest import _proveedor_voz

    ctx, cfg, carpeta, ficha, _ = _contexto_tanda(args, vault)
    codigo = 0
    for e in _elegidos(ficha, args.ad, "video"):
        g = cargar_guion(carpeta, e.ad, "video", cfg)
        trabajo = Path.home() / ".cache" / "trovefy" / "creativos" / ctx.producto / args.tanda / e.ad
        r = whisper.revisar_voz(g, carpeta / f"{e.ad}.mp4", ctx.idioma, cfg, trabajo)
        whisper.anotar(carpeta, r, cfg, _proveedor_voz(carpeta, e.ad) or "apimart", _ahora())
        _decir(f"- {e.ad}: {r.estado} · similitud {r.similitud if r.similitud is not None else 'no medido'} "
               f"(umbral {cfg.whisper_similitud_min})" + (f" · {r.motivo}" if r.motivo else ""))
        if r.estado != "ok":
            codigo = 1
            paso = whisper.siguiente_paso(carpeta, e.ad)
            consejo = {"revozar": "ajusta el texto (el precio en palabras) y re-voza una vez: `trovefy creativos voz`",
                       "elevenlabs": "pasa la voz a ElevenLabs (con su coste aprobado): `--proveedor elevenlabs`",
                       "parar": "ni así llega: para y díselo al usuario"}.get(paso)
            if consejo:
                _decir(f"  Siguiente: {consejo}")
    return codigo


def _contactos(args, vault: Path) -> int:
    from trovefy.creativos import contactos

    ctx, cfg, carpeta, ficha, _ = _contexto_tanda(args, vault)
    hoja = contactos.hoja_contactos(vault, carpeta, ficha)
    html = contactos.textos_html(vault, ctx, carpeta, ficha, cfg)
    _decir(f"Hoja de contactos para el revisor: {_rel(vault, hoja)}")
    _decir(f"Textos para el nativo: {_rel(vault, html)}")
    return 0


def _anotar(args, vault: Path) -> int:
    from trovefy.creativos import contactos

    _ctx, _cfg, carpeta, ficha, _ = _contexto_tanda(args, vault)
    texto = sys.stdin.read()
    try:
        v = contactos.anotar_agente(carpeta, _piezas(ficha), args.agente, texto, args.version, _ahora())
    except ValueError as e:
        _decir(str(e))
        return 1
    _decir(f"{args.agente}: {v} → {_rel(vault, carpeta / 'QA.md')}")
    return 0 if v == "ok" else 1


def _cerrar(args, vault: Path) -> int:
    from trovefy.creativos import manifest

    ctx, cfg, _carpeta, ficha, _ = _contexto_tanda(args, vault)
    try:
        ruta, aviso = manifest.cerrar_tanda(vault, ctx, ficha, cfg, _ahora())
    except manifest.TandaNoCierra as e:
        _decir(str(e))
        return 1
    _decir(f"Tanda {args.tanda} cerrada: {_rel(vault, ruta)}")
    _decir(aviso)
    return 0


def _rehacer(args, vault: Path) -> int:
    from trovefy.creativos import manifest

    ctx, _ = _cargar(args, vault, rehacer=True)
    ruta = manifest.rehacer(vault, ctx.producto, ctx.pais, args.tanda, args.ad, args.motivo, _ahora())
    _decir(f"Tanda {args.tanda} reabierta para {', '.join(args.ad)} con el motivo del usuario → {_rel(vault, ruta)}")
    return 0


def _renovar(args, vault: Path) -> int:
    from trovefy.creativos.renovar import abrir_renovacion

    ctx, cfg = _cargar(args, vault, renovar=True)
    try:
        tanda, plan = abrir_renovacion(vault, ctx.producto, ctx.pais, cfg.formatos_video, _ahora())
    except ValueError as e:
        _decir(str(e))
        return 1
    _decir(f"Renovación {tanda} sobre «{plan.ganador.angulo}» ({plan.ganador.anuncio}): reservas "
           f"{', '.join(plan.reservas) or 'ninguna'}; nuevas {plan.nuevas_sobre_ganador} sobre el ganador y "
           f"{plan.nuevas_angulo_nuevo} de ángulo nuevo; formatos {', '.join(plan.formatos) or 'no medido'}")
    return 0


def _estado(args, vault: Path) -> int:
    from trovefy.creativos import coste, registro

    ctx, cfg, carpeta, ficha, _ = _contexto_tanda(args, vault)
    est = registro.estado(carpeta, _piezas(ficha))
    _decir(f"Tanda {args.tanda} de {ctx.producto} {ctx.pais}")
    for e in ficha.elegidos:
        tipo = ficha.brief(e.ad).tipo
        hay = registro.archivo_pieza(carpeta, e.ad, tipo).is_file()
        w = est.whisper.get(e.ad) if tipo == "video" else "—"
        _decir(f"- {ficha.nombre(e.ad)} · {e.uso} · {tipo} · {'hecho' if hay else 'falta'} · Whisper {w or 'no medido'}")
    _decir(f"QA: automática {est.automatica or 'no medido'} · revisor {est.revisor or 'no medido'} · nativo "
           f"{est.nativo or 'no medido'}")
    a = coste.aprobacion(carpeta)
    _decir("Coste aprobado: " + (f"{a['total_usd']} USD («{a['cita']}»)" if a else "no"))
    _decir(f"APIMart: {_gasto(vault, ctx, cfg, args.tanda, carpeta)}")
    return 0


_ACCIONES = {
    "iniciar": _iniciar, "contexto": _contexto, "nueva": _nueva, "brief": _brief, "coste": _coste,
    "aprobar-coste": _aprobar_coste, "tope": _tope, "escenas": _escenas, "estaticos": _estaticos, "voz": _voz,
    "clips": _clips, "musica": _musica, "video": _video, "qa": _qa, "whisper": _whisper, "contactos": _contactos,
    "anotar": _anotar, "cerrar": _cerrar, "rehacer": _rehacer, "renovar": _renovar, "estado": _estado,
}


def _ejecutar(args: argparse.Namespace) -> int:
    from trovefy.apimart.http import SinClave
    from trovefy.creativos.contexto import EstadoNoPermite
    from trovefy.creativos.video import VideoInvalido
    from trovefy.secretos import RevisionSecretosNoDisponible
    from trovefy.vault.rutas import vault_root
    from trovefy.voz.elevenlabs import ErrorElevenLabs

    _SECRETOS.clear()
    try:
        return _ACCIONES[args.accion](args, vault_root())
    except (EstadoNoPermite, _Puerta, VideoInvalido) as e:
        return _error(e, 1)
    except SinClave as e:
        return _error(f"APIMart sin credenciales: {e.motivo}" + "".join(f"\n- {a}" for a in e.arreglos))
    except ErrorElevenLabs as e:
        return _error(f"ElevenLabs: {e}")
    except RevisionSecretosNoDisponible as e:
        return _error(e)
    except (ValueError, FileNotFoundError, FileExistsError) as e:
        return _error(e)
    except KeyboardInterrupt:
        print("INTERRUMPIDA: cancelado por el usuario (Ctrl-C).", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001 - la CLI nunca muestra un traceback
        return _error(f"fallo inesperado ({type(e).__name__})", 3)
    finally:
        _SECRETOS.clear()


registrar("creativos", _configurar, _ejecutar,
          ayuda="tanda de creativos: brief, coste aprobado, imágenes, voz, clips, música, vídeos, QA, revisión y cierre")
