"""Subcomando `trovify auditar`: auditar una oferta por país y registrar la elección del usuario."""

import argparse
import re
import sys

from trovify.cli import registrar

_FRASES = re.compile(r"^([A-Za-z]{2}):(.+)$")


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    e = sub.add_parser("ejecutar", help="audita la oferta en cada país y escribe productos/<p-id>/AUDITORIA.md")
    e.add_argument("--oferta", required=True, metavar="ID", help="oferta_id de wiki/ofertas/<ID>.md")
    e.add_argument("--pais", action="append", default=[], metavar="XX",
                   help="país a auditar (se repite; por defecto, los «candidato» de config/mercados.yaml)")
    e.add_argument("--frases", action="append", default=[], metavar='XX:"f1|f2"',
                   help="frases cortas en el idioma local del país, separadas por | (se repite por país)")
    el = sub.add_parser("elegir", help="registra el país que elige el usuario, con su cita literal")
    el.add_argument("--producto", required=True, metavar="P", help="p-id del producto (p-0001-…)")
    el.add_argument("--pais", required=True, metavar="XX")
    el.add_argument("--reserva", metavar="YY", help="país de reserva")
    el.add_argument("--cita", required=True, help="las palabras del usuario, literales")


def _error(msg: str, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def frases_de(valores: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for v in valores:
        m = _FRASES.match(v.strip())
        frases = [f.strip() for f in m.group(2).split("|") if f.strip()] if m else []
        if not frases:
            raise ValueError(f'frases mal formadas: «{v}»; usa XX:"frase 1|frase 2" (por ejemplo RO:"fise terapie|kit terapie")')
        out.setdefault(m.group(1).upper(), []).extend(frases)
    return out


def _ejecutar_auditoria(args: argparse.Namespace) -> int:
    from trovify.auditoria import orquestador
    from trovify.auditoria.paises import que_medir, recomendar
    from trovify.caza.orquestador import hoy_negocio
    from trovify.vault.rutas import vault_root

    vault = vault_root()
    try:
        frases = frases_de(args.frases)
        for pais, fs in frases.items():
            if len(fs) < 2:
                print(f"Aviso: con una sola frase en {pais} el «sin competencia» no se puede confirmar "
                      "(hacen falta dos).", file=sys.stderr)
        r = orquestador.auditar(vault, args.oferta, args.pais or None, frases, hoy=hoy_negocio())
    except (ValueError, FileNotFoundError) as exc:  # CazaEnCurso es un ValueError
        return _error(str(exc))
    sobran = sorted(set(frases) - {p.pais for p in r.paises})
    if sobran:
        print(f"Aviso: hay frases para {', '.join(sobran)}, que no se auditó; revisa --pais o config/mercados.yaml.",
              file=sys.stderr)
    print(f"Auditoría escrita: {r.ruta.relative_to(vault).as_posix()} (producto {r.p_id})")
    orden = sorted(r.paises, key=lambda p: (p.nota is None, -(p.nota or 0), p.pais))
    hueco = {True: "sí", False: "no", None: "no comprobado"}
    for i, p in enumerate(orden, 1):
        nota = "no medida" if p.nota is None else f"{p.nota:.0f}"
        extra = f" · no tirar: {p.no_tirar}" if p.no_tirar else ""
        motivo = f" ({p.hueco.motivo})" if p.hueco.hueco is None and p.hueco.motivo else ""
        print(f"{i}. {p.pais} — nota {nota} · hueco {hueco[p.hueco.hueco]}{motivo}{extra}")
        if p.hueco_medido:
            print(f"   {p.pais}: hueco {p.hueco_medido}" + (" (las frases de ese país no se usaron)"
                                                       if p.pais in frases else ""))
    print(f"Recomendación: {recomendar(r.paises)[2]}")
    if r.usadas_hoy is None or r.max_hoy is None:
        print("Búsquedas usadas hoy: no medido (sin contador del día)")
    else:
        print(f"Búsquedas usadas hoy: {r.usadas_hoy} de {r.max_hoy} (quedan {max(r.max_hoy - r.usadas_hoy, 0)}); "
              f"esta auditoría hizo {r.hechas or 0}")
    pendientes = que_medir(orden)
    if pendientes:
        print("Qué medir:")
        for x in pendientes:
            print(f"  - {x}")
    # Fin normal (también con la cuota del día agotada): 0. Bloqueo de Meta: 1 (PARADA, dura el día).
    # Racha de errores o navegador caído: 3 (INTERRUMPIDA). Error de uso o configuración: 2.
    if r.parada and r.tipo == "cuota":
        print("Cuota del día agotada: los países que faltaban quedaron «no medido: cuota del día agotada»; "
              "mañana, la misma orden sigue donde se quedó (lo medido no se repite).")
    elif r.parada and r.tipo == "errores":
        print(f"INTERRUMPIDA: {r.parada}. No es un bloqueo de Meta; lo que faltaba quedó «no medido». "
              "Se puede volver a intentar más tarde.")
        return 3
    elif r.parada:
        print(f"PARADA: {r.parada}. Meta bloqueó: no se buscó nada más y lo que faltaba quedó «no medido». "
              "No lances más búsquedas hoy.")
        return 1
    print("La elección es tuya: dímela y la registro.")
    return 0


def _ejecutar_eleccion(args: argparse.Namespace) -> int:
    from trovify.auditoria.salida import registrar_eleccion
    from trovify.caza.orquestador import hoy_negocio
    from trovify.vault.rutas import vault_root

    vault = vault_root()
    try:
        ruta = registrar_eleccion(vault, args.producto, args.pais, args.reserva, args.cita, hoy_negocio())
    except (ValueError, FileNotFoundError) as exc:
        return _error(str(exc))
    print(f"Elección registrada: {ruta.relative_to(vault).as_posix()}")
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.startswith(("Advertencia:", "Excepción:")):
            print(linea)
    from trovify.vault import frontmatter

    pais = args.pais.strip().upper()
    meta, _ = frontmatter.leer(vault / "productos" / args.producto / "PRODUCTO.md")
    estado = ((meta.get("paises") or {}).get(pais) or {}).get("estado")
    if estado == "aprobado":
        print(f"{pais} queda «aprobado» en productos/{args.producto}/PRODUCTO.md. La zona horaria de "
              "la cuenta publicitaria (paso 06 de /arranque) será la de ese país.")
    else:
        print(f"Decisión registrada con tu cita; el estado de {pais} sigue siendo {estado or 'sin estado'}.")
    return 0


def _ejecutar(args: argparse.Namespace) -> int:
    if args.accion == "ejecutar":
        return _ejecutar_auditoria(args)
    return _ejecutar_eleccion(args)


registrar("auditar", _configurar, _ejecutar)
