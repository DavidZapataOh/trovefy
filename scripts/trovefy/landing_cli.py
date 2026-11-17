"""Subcomando `trovefy landing`: landing propia por país (plan 18).

Claude escribe el texto y el diseño en un borrador fuera del vault; aquí solo lo determinista: entrada,
medios, esqueleto, comprobación, QA y publicación.

Códigos de salida: 0 bien · 1 una puerta no pasa (estado, validación) · 2 error de uso o de entrada ·
3 fallo inesperado.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from trovefy.cli import registrar

_ejecutar_orden = None  # punto de inyección de los tests (pdftoppm, ffmpeg, pdfinfo); None → subprocess.run


def _orden():
    """La función que corre las órdenes externas, resuelta en cada llamada."""
    return _ejecutar_orden or subprocess.run


def _cache() -> Path:
    """Raíz de la caché de trabajo (fuera del vault); los tests la cambian."""
    return Path.home() / ".cache" / "trovefy"


def _borrador(p_id: str, pais: str) -> Path:
    return _cache() / "landing" / p_id / pais.upper()


def _error(msg: object, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _comunes(p: argparse.ArgumentParser) -> None:
    p.add_argument("--producto", required=True, help="p-id del producto (p-0001-…)")
    p.add_argument("--pais", required=True, help="código del país (BG, RO…)")


def _configurar_impultienda(sub) -> None:
    """Subcomandos de hosting y publicación (Tareas 8–9)."""
    s = sub.add_parser("sonda", help="mide qué admite Impultienda: pega una prueba, mira la tienda y restaura "
                                     "tu contenido")
    _comunes(s)
    s.add_argument("--tienda", required=True, help="URL pública de tu tienda (https://…); se guarda en mercados.yaml")
    s.add_argument("--dominio-propio", choices=("si", "no"), default=None,
                   help="tu respuesta: ¿Impultienda te deja conectar tu dominio en tu plan?")
    s.add_argument("--url", default=None, help="URL de «Diseño de tienda → Contenido» si no es la del mapa")
    s.add_argument("--campo-vacio", action="store_true",
                   help="el campo «HTML completo de la tienda» está vacío de verdad (lo has mirado tú): sin esto, un campo leído vacío para sin tocar nada")
    c = sub.add_parser("capturar", help="confirma tú la pantalla «Diseño de tienda → Contenido» (sin clics)")
    c.add_argument("--url", default=None, help="dónde abrir la ventana (de app.impultienda.ar)")
    pu = sub.add_parser("publicar", help="publica (Impultienda) o verifica la subida (Cloudflare), QA publicada y "
                                         "estado con_landing")
    _comunes(pu)
    pu.add_argument("--url", default=None, help="ruta Cloudflare: la URL https donde subiste la landing")
    pu.add_argument("--campo-vacio", action="store_true",
                    help="el campo «HTML completo de la tienda» está vacío de verdad (lo has mirado tú): sin esto, un campo leído vacío para sin tocar nada")


def _configurar(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="accion", metavar="<acción>", required=True)
    _comunes(sub.add_parser("estado", help="estado del país, PDF vigente y lo que falta"))
    _configurar_impultienda(sub)
    m = sub.add_parser("medios", help="vistas previas reales del PDF e imágenes propias a assets/")
    _comunes(m)
    m.add_argument("--paginas", default="1,2,3", help="páginas del PDF para la vista previa (1,4,7)")
    pr = sub.add_parser("preparar", help="borrador con el esqueleto propio, wireframe.yaml y landing.yaml")
    _comunes(pr)
    pr.add_argument("--hosting", choices=("impultienda", "cloudflare"), default=None,
                    help="dónde se publica (por defecto, el que mida la sonda)")
    pr.add_argument("--rehacer", action="store_true", help="vuelve a escribir el index.html del borrador")
    _comunes(sub.add_parser("guardar", help="copia el borrador al vault (sin secretos) y fija la versión"))
    _comunes(sub.add_parser("validar", help="comprobación estática de la landing guardada"))
    q = sub.add_parser("qa", help="QA en Chromium (390/1280, peso, LCP 4G, hitos, clic con UTM): QA.md, o "
                                  "QA-publicada.md con --publicada")
    _comunes(q)
    q.add_argument("--publicada", action="store_true", help="mide la URL publicada (landing.yaml → url)")
    _comunes(sub.add_parser("texto", help="texto visible de la landing guardada, para el agente nativo"))
    n = sub.add_parser("nativo", help="registra el veredicto del agente nativo (ok|corregir) ligado a la versión")
    _comunes(n)
    n.add_argument("--veredicto", choices=("ok", "corregir"), default=None,
                   help="el que dio el agente; si falta, se lee de su respuesta (VEREDICTO: …)")
    n.add_argument("--notas-archivo", required=True, help="archivo con la respuesta del agente, tal cual")
    n.add_argument("--version", required=True,
                   help="la «Versión:» que imprimió trovefy landing texto (la que leyó el agente)")
    n.add_argument("--texto-sha256", default=None,
                   help="el «Texto-sha256:» que imprimió trovefy landing texto; si se da, tiene que ser el actual")
    r = sub.add_parser("resena", help="añade una reseña real (con su pedido o email de origen)")
    _comunes(r)
    r.add_argument("--texto", required=True, help="texto literal de la reseña")
    r.add_argument("--fecha", required=True, help="fecha de la reseña (AAAA-MM-DD)")
    r.add_argument("--fuente", required=True, help="pedido o email de origen")


# --- acciones ------------------------------------------------------------------------------------


def _con_paradas(accion):
    """Las paradas del navegador salen con su motivo: 1 si es «no medido» o una parada del conductor (no se tocó
    nada más), 2 si el navegador falló."""

    def envuelta(args: argparse.Namespace, vault: Path) -> int:
        from trovefy.landing.hosting import CapacidadNoMedida
        from trovefy.landing.publicar import NoPublicable
        from trovefy.navegador import NavegadorError
        from trovefy.tienda.conductor import Parada

        try:
            return accion(args, vault)
        except Parada as e:
            return _error(e.motivo, 1)
        except (CapacidadNoMedida, NoPublicable) as e:
            return _error(e, 1)
        except NavegadorError as e:
            return _error(e, 2)

    return envuelta


@_con_paradas
def _sonda(args: argparse.Namespace, vault: Path) -> int:
    from datetime import datetime

    from trovefy.landing.hosting import (
        CapacidadNoMedida,
        elegir_hosting,
        elegir_resumen,
        guardar_tienda,
        sondear,
    )
    from trovefy.vault.escritura import ZONA_NEGOCIO
    from trovefy.vault.producto import ruta_producto

    if not ruta_producto(vault, args.producto).is_file():
        raise FileNotFoundError(f"no existe productos/{args.producto}/PRODUCTO.md")
    pais = args.pais.strip().upper()
    ahora = datetime.now(ZONA_NEGOCIO)
    if guardar_tienda(vault, pais, args.tienda, ahora):
        print(f"Tienda de {pais} guardada en config/mercados.yaml (palabra tuya, {ahora:%Y-%m-%d}).")
    dominio = {"si": True, "no": False, None: None}[args.dominio_propio]
    c = sondear(vault, args.producto, pais, args.tienda.strip().rstrip("/"), dominio, args.url, ahora=ahora,
                campo_vacio=args.campo_vacio)
    print(f"Capacidades ({c.fecha}): {elegir_resumen(c)}")
    print(f"Tu contenido de Impultienda está restaurado (respaldo en landing/{pais}/respaldo/).")
    try:
        h = elegir_hosting(c)
        print(f"Hosting: {h.ruta} — {h.motivo}")
    except CapacidadNoMedida as e:
        print(f"Hosting: {e}")
    return 0


@_con_paradas
def _capturar(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.landing import panel

    if not panel.hay_terminal():  # I-1: una persona delante, no una tubería ni un agente
        return _error(panel.SIN_TERMINAL)
    entrada = panel.capturar_pantalla(vault, args.url)
    print(f"Pantalla «Diseño de tienda → Contenido» confirmada ({entrada['fecha']}): {entrada['url']}")
    return 0


@_con_paradas
def _publicar(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.landing.entrada import cargar_datos
    from trovefy.landing.publicar import avisos_publicacion, publicar
    from trovefy.vault.producto import estado_pais

    d = cargar_datos(vault, args.producto, args.pais, correr=_orden())
    for aviso in avisos_publicacion(vault, d):
        print(f"Aviso: {aviso}")
    url = publicar(vault, d, args.url, campo_vacio=args.campo_vacio)
    print(f"{d.pais} → {estado_pais(vault, d.p_id, d.pais)}: {url}")
    return 0


_ACCIONES_IMPULTIENDA = {"sonda": _sonda, "capturar": _capturar, "publicar": _publicar}


def _faltan(vault: Path, p_id: str, pais: str) -> list[str]:
    from trovefy.landing.entrada import ruta_landing
    from trovefy.landing.plantilla import leer_landing_yaml

    raiz = ruta_landing(vault, p_id, pais)
    faltan = []
    if not (raiz / "assets" / "vistas.json").is_file():
        faltan.append(f"medios (trovefy landing medios --producto {p_id} --pais {pais})")
    if not (raiz / "landing.yaml").is_file():
        faltan.append(f"borrador (trovefy landing preparar --producto {p_id} --pais {pais})")
    if not (raiz / "index.html").is_file():
        faltan.append(f"landing guardada (trovefy landing guardar --producto {p_id} --pais {pais})")
    if not (raiz / "QA.md").is_file():
        faltan.append("QA")
    if not (raiz / "nativo.md").is_file():
        faltan.append("veredicto del nativo")
    if not leer_landing_yaml(vault, p_id, pais).get("url"):  # roto o enlazado → EntradaInvalida (sale 2)
        faltan.append("publicar")
    return faltan


def _linea_hosting(vault: Path) -> str:
    """`Hosting:` según la sonda (`capacidades_vigentes` + `elegir_hosting`): la ruta y su motivo, o «no medido»
    (sin sonda, con algo sin medir o con la evidencia rota) y la orden de la sonda. La skill decide con esto si
    hay que medir Impultienda (M4)."""
    from trovefy.landing.hosting import (
        CapacidadNoMedida,
        capacidades_vigentes,
        elegir_hosting,
    )

    try:
        h = elegir_hosting(capacidades_vigentes(vault))
    except CapacidadNoMedida as e:
        return f"Hosting: {e}"
    except ValueError as e:
        return f"Hosting: no medido: {e} (trovefy landing sonda)"
    return f"Hosting: {h.ruta} — {h.motivo}"


def _estado(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.landing.entrada import EstadoNoPermite, cargar_datos

    try:
        d = cargar_datos(vault, args.producto, args.pais, correr=_orden())
    except EstadoNoPermite as e:
        print(f"{args.pais.upper()}: no puede tener landing aún")
        print(str(e))
        return 1
    print(f"{d.pais}: {d.estado}")
    print(f"PDF vigente: {d.pdf.name} ({d.pdf_paginas} páginas)")
    print(f"Precio: {d.precio} {d.moneda} · secciones: {len(d.secciones)} · marca: {d.marca}")
    print(f"Dominio: {d.dominio or 'no medido: falta el paso 07'} · tienda: {d.tienda or 'no medida'}")
    print(_linea_hosting(vault))
    faltan = _faltan(vault, d.p_id, d.pais)
    print("falta: " + ("; ".join(faltan) if faltan else "nada"))
    return 0


def _paginas(texto: str) -> tuple[int, ...]:
    try:
        paginas = tuple(int(x) for x in texto.split(",") if x.strip())
    except ValueError:
        raise ValueError(f"--paginas mal escrito: «{texto}» (números separados por comas: 1,4,7)") from None
    if not paginas:
        raise ValueError("--paginas vacío: hace falta al menos una página")
    return paginas


def _medios(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.landing.entrada import cargar_datos
    from trovefy.landing.medios import preparar_medios

    d = cargar_datos(vault, args.producto, args.pais, correr=_orden())
    assets = preparar_medios(vault, d, _paginas(args.paginas), ejecutar=_orden())
    print(f"Medios listos en {assets.relative_to(vault).as_posix()} (vistas de {d.pdf.name})")
    return 0


def _hosting_por_defecto(vault: Path) -> tuple[str, str | None]:
    """(hosting, aviso): el que elija la sonda; con algo «no medido», Cloudflare provisional (R6)."""
    from trovefy.landing.hosting import (
        CapacidadNoMedida,
        capacidades_vigentes,
        elegir_hosting,
    )

    try:
        return elegir_hosting(capacidades_vigentes(vault)).ruta, None
    except CapacidadNoMedida as e:
        return "cloudflare", f"hosting {e}; de momento cloudflare provisional"


def _preparar(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.landing.entrada import cargar_datos
    from trovefy.landing.plantilla import preparar

    d = cargar_datos(vault, args.producto, args.pais, correr=_orden())
    hosting, aviso = (args.hosting, None) if args.hosting else _hosting_por_defecto(vault)
    if aviso:
        print(f"Aviso: {aviso}")
    destino = _borrador(d.p_id, d.pais)
    ya = [] if args.rehacer else [r for r in ("index.html", "assets/estilo.css") if (destino / r).exists()]
    ruta = preparar(vault, d, hosting, destino, rehacer=args.rehacer)
    print(f"Borrador ({hosting}): {ruta}")
    for rel in ya:
        print(f"El {rel} del borrador ya existía y no se ha tocado (usa --rehacer para empezar de cero).")
    return 0


def _guardar(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.landing.entrada import cargar_datos
    from trovefy.landing.plantilla import guardar

    d = cargar_datos(vault, args.producto, args.pais, correr=_orden())
    version = guardar(vault, d, _borrador(d.p_id, d.pais))
    print(f"Landing guardada en el vault: versión {version}")
    return 0


def _validar(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.landing.entrada import cargar_datos
    from trovefy.landing.validar import validar

    d = cargar_datos(vault, args.producto, args.pais, correr=_orden())
    r = validar(vault, d)
    if r.fallos:
        print(f"{len(r.fallos)} fallo(s):")
        for f in r.fallos:
            print(f"- {f}")
    else:
        print("Landing sin fallos.")
    if r.avisos:
        print(f"{len(r.avisos)} aviso(s) (no bloquean):")
        for a in r.avisos:
            print(f"- {a}")
    return 0 if r.ok else 1


def _qa(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.landing.entrada import EntradaInvalida, cargar_datos
    from trovefy.landing.plantilla import leer_landing_yaml
    from trovefy.landing.qa import archivo_qa, ejecutar_qa

    d = cargar_datos(vault, args.producto, args.pais, correr=_orden())
    url = None
    if args.publicada:
        url = leer_landing_yaml(vault, d.p_id, d.pais).get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise EntradaInvalida(f"la landing de {d.pais} no tiene URL publicada: trovefy landing publicar")
    r = ejecutar_qa(vault, d, url)
    for comprobacion, estado, detalle in r.filas:
        print(f"[{estado}] {comprobacion}: {detalle}")
    print(f"QA {'apta' if r.ok else 'no apta'}: landing/{d.pais}/{archivo_qa(url is not None)}")
    return 0 if r.ok else 1


def _texto(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.landing.entrada import cargar_datos
    from trovefy.landing.nativo import texto_landing

    d = cargar_datos(vault, args.producto, args.pais, correr=_orden())
    t = texto_landing(vault, d.p_id, d.pais)
    print(f"Versión: {t.version}")
    print(f"Texto-sha256: {t.sha256}")
    print()
    print(t.texto, end="")
    return 0


def _nativo(args: argparse.Namespace, vault: Path) -> int:
    from datetime import datetime

    from trovefy.landing.entrada import EntradaInvalida, cargar_datos
    from trovefy.landing.nativo import registrar_veredicto
    from trovefy.producto.qc_registro import parsear_veredicto
    from trovefy.vault.escritura import ZONA_NEGOCIO

    d = cargar_datos(vault, args.producto, args.pais, correr=_orden())
    notas = Path(args.notas_archivo).read_bytes().decode("utf-8")  # tal cual, con sus \r\n si los trae
    veredicto = args.veredicto or parsear_veredicto(notas)
    if veredicto is None:
        raise EntradaInvalida("no medido: la respuesta del nativo no termina en «VEREDICTO: ok|corregir»")
    ruta = registrar_veredicto(vault, d.p_id, d.pais, veredicto, notas, datetime.now(ZONA_NEGOCIO),
                               version=args.version.strip(), texto_sha256=args.texto_sha256)
    print(f"Veredicto del nativo: {veredicto} ({ruta.relative_to(vault).as_posix()})")
    return 0


def _resena(args: argparse.Namespace, vault: Path) -> int:
    from datetime import date

    from trovefy.landing.validar import anadir_resena

    try:
        fecha = date.fromisoformat(args.fecha)
    except ValueError:
        raise ValueError(f"--fecha mal escrita: «{args.fecha}» (AAAA-MM-DD)") from None
    rid = anadir_resena(vault, args.producto, args.pais, args.texto, fecha, args.fuente)
    print(f"Reseña real añadida: {rid}")
    return 0


_ACCIONES = {"estado": _estado, "medios": _medios, "preparar": _preparar, "guardar": _guardar,
             "validar": _validar, "qa": _qa, "texto": _texto, "nativo": _nativo,
             "resena": _resena}


def _ejecutar(args: argparse.Namespace) -> int:
    from trovefy.landing.entrada import EntradaInvalida, EstadoNoPermite
    from trovefy.secretos import RevisionSecretosNoDisponible
    from trovefy.vault.rutas import vault_root

    try:
        return _ACCIONES[args.accion](args, vault_root())
    except EstadoNoPermite as e:
        return _error(e, 1)
    except (EntradaInvalida, RevisionSecretosNoDisponible, ValueError, FileNotFoundError) as e:
        return _error(e)
    except subprocess.CalledProcessError as e:
        return _error(f"falló la orden {e.cmd[0] if isinstance(e.cmd, list) else e.cmd} (código {e.returncode})")
    except subprocess.TimeoutExpired as e:
        return _error(f"la orden {e.cmd[0] if isinstance(e.cmd, list) else e.cmd} tardó demasiado")
    except KeyboardInterrupt:
        print("INTERRUMPIDA: cancelado por el usuario (Ctrl-C).", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001 - la CLI nunca muestra un traceback
        return _error(f"fallo inesperado ({type(e).__name__})", 3)


registrar("landing", _configurar, _ejecutar, ayuda="landing propia por país: preparar, QA y publicar")

# Tareas 8–9 (sonda, captura y publicación): se registran aparte de las de arriba.
_ACCIONES.update(_ACCIONES_IMPULTIENDA)
