"""`trovefy checkout plan | aprobar | releer` (plan 19, Tarea 11): el checkout por el MCP, etapa a etapa.

La CLI nunca llama al MCP: Claude lo llama en la sesión. trovefy orquesta los **datos**:

1. Claude lee la tienda por el MCP (``listar_tiendas``, ``listar_productos``, ``ver_markets``, ``ver_postcompra``),
   guarda las respuestas en ``~/.cache/trovefy/checkout/<p-id>/<PAIS>/<nombre>.json`` y ejecuta
   ``trovefy checkout releer --respuesta <archivo>``: de ahí salen los ids y la foto de la tienda.
2. ``trovefy checkout plan``: el plan de la etapa siguiente (``checkout/<PAIS>/PLAN-MCP.json``, solo con ids ya
   conocidos) y su resumen en seco en español (``PLAN-MCP.md``), que Claude enseña al usuario.
3. El usuario aprueba con la frase atada a ese plan, «sí, aplica la etapa N (xxxx)» (``xxxx``: los cuatro
   primeros caracteres de la huella del plan; ver `trovefy.tienda.mcp.frase_aprobacion`):
   ``trovefy checkout aprobar --cita "<la frase>"`` escribe ``APROBACION.md`` con la cita, la fecha y la huella del
   plan, y deja el mensaje marcado para ese plan en el registro (un mensaje aprueba un solo plan; lista de citas
   usadas en ``checkout/<PAIS>/mcp/citas-usadas.json``). **Solo lo ejecuta el usuario**, en su terminal
   (``apimart_gasto`` se lo niega a Claude en cualquier forma); sin terminal, la frase tiene que ser un mensaje entero
   que el usuario escribió en el chat después del plan (lo anota el hook ``UserPromptSubmit``; ver
   `trovefy.checkout.mensajes`).
4. Claude aplica cada operación del plan, en orden (la guarda del hook solo deja pasar las del plan aprobado; las de
   dos pasos, primero la vista previa y luego ``confirmar: true`` con su token; cada llamada, una sola vez), relee
   y vuelve al paso 1 con el archivo de esa etapa. Tras releer, la aprobación de la etapa se retira y se cierra en
   el registro: nada de esa etapa se puede repetir sin una nueva frase.

Códigos de salida: 0 bien · 1 algo no está bien o falta medirlo · 2 error de uso o de entrada. Nunca una traza.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from trovefy.checkout.etapas import Paso
from trovefy.checkout.mensajes import (
    cerrar_mensajes,
    es_mensaje_del_usuario,
    huella_mensaje,
    usar_mensaje,
)
from trovefy.checkout.operaciones import (
    LECTURAS_BASE,
    Operacion,
    Plan,
    planificar,
    resumen_en_seco,
)
from trovefy.checkout.relectura import (
    ESTADO_MCP,
    comprobacion,
    escribir_checkout,
    estado_nuevo,
    instantanea,
    leer_respuestas,
    relectura_a_dict,
    relectura_de_dict,
    releer,
    secreto_en,
    valores_de,
    valores_de_escritura,
)
from trovefy.tienda.mcp import (
    APROBACION,
    PLAN_MCP,
    casa_con_operacion,
    creado_de,
    es_la_frase,
    frase_aprobacion,
    huella_del_plan,
    motivo_aprobacion,
    olvidar_escrituras,
    redactar_urls_firmadas,
)

PLAN_MD = "PLAN-MCP.md"
HISTORIAL = "mcp"
CITAS_USADAS = "citas-usadas.json"
NO_ES_TUYA = ("no veo ese mensaje tuyo: la aprobación tiene que ser tu mensaje entero, escrito por ti en el chat "
              "después de ver el resumen. Escríbelo tú (la frase del resumen, tal cual) o ejecuta tú este comando en "
              "tu terminal")


def hay_terminal() -> bool:
    """¿Hay una persona delante? stdin y stdout son una terminal (ruling I-1; como `trovefy.tienda.confirmacion`)."""
    try:
        return os.isatty(sys.stdin.fileno()) and os.isatty(sys.stdout.fileno())
    except (AttributeError, OSError, ValueError):
        return False


class ErrorDeUso(ValueError):
    """Salida 2."""


# --- utilidades ---------------------------------------------------------------------------------------------------


def configurar(sub: argparse._SubParsersAction, comunes) -> None:
    plan = sub.add_parser("plan", help="el plan de la etapa siguiente del MCP y su resumen en seco")
    comunes(plan)
    plan.add_argument("--plan-tienda", help="plan de Impultienda con el que se calcula (por defecto, el leído)")
    plan.add_argument("--sin-telefono", action="store_true", help="no pedir teléfono en el checkout")
    aprobar = sub.add_parser("aprobar", help="registra tu «sí» al plan de la etapa, con tus palabras literales")
    comunes(aprobar)
    aprobar.add_argument("--cita", required=True, help="el mensaje del usuario, tal cual, entre comillas")
    rel = sub.add_parser("releer", help="lee lo que Claude guardó del MCP: ids, relectura y CHECKOUT.md")
    comunes(rel)
    rel.add_argument("--respuesta", required=True,
                     help="el JSON con las llamadas, en ~/.cache/trovefy/checkout/<p-id>/<PAIS>/")


def _contexto(producto: str, pais: str):
    from trovefy.embudo.contexto import cargar_contexto, exigir_estado
    from trovefy.vault.rutas import vault_root

    vault = vault_root()
    ctx = cargar_contexto(vault, producto, pais.strip().upper())
    exigir_estado(ctx, "con_landing")
    return vault, ctx


def _carpeta(ctx) -> Path:
    from trovefy.embudo.contexto import ruta_pais

    return ruta_pais(ctx)


def ruta_cache(ctx) -> Path:
    return Path.home() / ".cache" / "trovefy" / "checkout" / ctx.producto / ctx.pais


def cargar_estado(ctx) -> dict:
    ruta = _carpeta(ctx) / ESTADO_MCP
    if not ruta.exists():
        return estado_nuevo()
    if ruta.is_symlink():
        raise ErrorDeUso(f"{ESTADO_MCP} es un enlace: no se lee")
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ErrorDeUso(f"{ESTADO_MCP} está roto ({type(exc).__name__}): no sigo") from exc
    if not isinstance(datos, dict) or datos.get("version") != 1:
        raise ErrorDeUso(f"{ESTADO_MCP} no tiene la forma esperada: no sigo")
    return {**estado_nuevo(), **datos}


def guardar_estado(ctx, estado: dict) -> None:
    from trovefy.vault.escritura import escribir_atomico

    patron = secreto_en(estado)
    if patron:
        raise ErrorDeUso(f"{ESTADO_MCP}: aparece un secreto ({patron}); no se guarda")
    escribir_atomico(_carpeta(ctx) / ESTADO_MCP, json.dumps(estado, ensure_ascii=False, indent=1, sort_keys=True))


def _historial(ctx, etapa: int) -> Path:
    d = _carpeta(ctx) / HISTORIAL / f"etapa-{etapa}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _retirar_aprobacion(ctx, etapa: int | None) -> None:
    """La aprobación viva deja de valer (queda la copia del historial): la guarda ya no deja repetir esa etapa."""
    viva = _carpeta(ctx) / APROBACION
    if viva.is_symlink() or viva.exists():
        if etapa and not viva.is_symlink() and viva.is_file():
            destino = _historial(ctx, etapa) / APROBACION
            if not destino.exists():
                shutil.copyfile(viva, destino)
        viva.unlink()


def _leer_plan(ctx) -> dict | None:
    ruta = _carpeta(ctx) / PLAN_MCP
    if not ruta.exists():
        return None
    if ruta.is_symlink():
        raise ErrorDeUso(f"{PLAN_MCP} es un enlace: no se lee")
    try:
        plan = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ErrorDeUso(f"{PLAN_MCP} está roto ({type(exc).__name__})") from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("operaciones"), list) \
            or plan.get("huella") != huella_del_plan(plan):
        raise ErrorDeUso(f"{PLAN_MCP} no está íntegro (su huella no casa): rehazlo con trovefy checkout plan")
    return plan


def _aprobacion_viva(ctx, plan: dict | None, estado: dict) -> bool:
    """¿La aprobación de la etapa vale? Lo mismo que mira la guarda (`motivo_aprobacion`: huella, frase y mensaje del
    usuario en el registro, marcado y sin cerrar) y que la etapa esté aprobada en el estado."""
    from trovefy.tienda.mcp import _frontmatter

    ruta = _carpeta(ctx) / APROBACION
    if plan is None or not ruta.is_file() or ruta.is_symlink():
        return False
    meta = _frontmatter(ruta.read_text(encoding="utf-8"))
    return (motivo_aprobacion(plan, meta, producto=ctx.producto, pais=ctx.pais) is None
            and estado.get("aprobada") == plan.get("etapa"))


def _opciones(estado: dict, args) -> tuple[object, dict | None]:
    from trovefy.checkout.receta import OpcionesReceta
    from trovefy.mapa import cargar, limites_de_plan
    from trovefy.tienda.mcp import RAIZ

    mapa = cargar(RAIZ / "templates" / "impultienda" / "mapa.yaml")
    inst = estado.get("instantanea") or {}
    leido = args.plan_tienda or (inst.get("tienda") or {}).get("plan") or "Max"
    plan = next((k for k in (mapa.get("limites_plan") or {}) if k.casefold() == str(leido).casefold()), str(leido))
    moneda = (inst.get("tienda") or {}).get("moneda") or (inst.get("markets") or {}).get("moneda_tienda") or "USD"
    return OpcionesReceta(plan, telefono=not args.sin_telefono, moneda_tienda=moneda), limites_de_plan(mapa, plan)


def _receta(ctx, estado: dict, args):
    from trovefy.checkout.emails import CLAVES_EMAIL, ruta_email
    from trovefy.checkout.receta import ajustes_de_checkout

    opciones, limites = _opciones(estado, args)
    emails = {c: r for c in CLAVES_EMAIL if (r := ruta_email(_carpeta(ctx), c)).is_file()}
    ajustes, avisos = ajustes_de_checkout(ctx, limites, emails, opciones)
    return opciones, ajustes, avisos


def _plan_de_json(plan: dict) -> Plan:
    ops = []
    for det, op in zip(plan.get("detalle") or [], plan["operaciones"], strict=True):
        ops.append(Operacion(n=det["n"], ajustes=tuple(det["ajustes"]), herramienta=op["herramienta"],
                             argumentos=op["argumentos"], lectura=det.get("lectura"), clave=det["clave"],
                             dos_pasos=det.get("dos_pasos", False),
                             solo_vista_previa=det.get("solo_vista_previa", False), frase=det.get("frase", "")))
    return Plan(operaciones=ops, manuales=[], ya_estan=[], huella=plan["huella"],
                huella_catalogo=plan.get("catalogo_huella", ""), etapa=plan.get("etapa", 1))


def _escribir_checkout(vault, ctx, estado: dict, args, ahora: datetime) -> Path:
    from trovefy.tienda.mcp import cargar_catalogo

    opciones, ajustes, avisos = _receta(ctx, estado, args)
    plan = planificar(ctx, ajustes, cargar_catalogo(), estado, etapa=max(estado.get("etapa") or 1, 1))
    relecturas = [relectura_de_dict(d) for d in (estado.get("relecturas") or {}).values()]
    parados = {a: m.get("motivo", "revisar a mano") for m in (estado.get("manuales") or {}).values()
               for a in m.get("ajustes", [])}
    if estado.get("plan_huella"):
        plan.huella = estado["plan_huella"]
    fuera, manual = comprobacion(ctx)  # COMPROBACION.md de `trovefy checkout comprobar` (Tarea 12)
    return escribir_checkout(vault, ctx, plan, relecturas, fuera, manual, ajustes=ajustes, ahora=ahora,
                             tienda_plan=opciones.plan, avisos=[*avisos, *estado.get("avisos", [])],
                             parados=parados, aprobaciones=estado.get("aprobaciones"))


# --- plan ---------------------------------------------------------------------------------------------------------


def plan(args, ahora: datetime) -> int:
    from trovefy.tienda.mcp import cargar_catalogo
    from trovefy.vault.escritura import anadir_log, escribir_atomico

    vault, ctx = _contexto(args.producto, args.pais)
    estado = cargar_estado(ctx)
    etapa_viva = estado.get("etapa") or 0
    if etapa_viva and estado.get("aprobada") == etapa_viva and estado.get("releida") != etapa_viva:
        raise ErrorDeUso(f"la etapa {etapa_viva} está aprobada y sin releer: aplica sus llamadas, guarda las "
                         "respuestas y ejecuta trovefy checkout releer antes de pedir otro plan")
    if not estado.get("lecturas_completas"):
        faltan = estado.get("faltan_lecturas") or list(LECTURAS_BASE)
        print(f"no medido: faltan las lecturas del MCP ({', '.join(faltan)}): léelas, guarda las respuestas y "
              "ejecuta trovefy checkout releer")
        return 1
    tipo = ((estado.get("instantanea") or {}).get("tienda") or {}).get("tipo")
    if tipo != "store":
        print(f"revisar a mano: la tienda es de tipo «{tipo}»; esta receta es para una tienda clásica (con landing): "
              "no planifico nada")
        return 1
    opciones, ajustes, avisos = _receta(ctx, estado, args)
    etapa = etapa_viva + 1 if (etapa_viva == 0 or estado.get("releida") == etapa_viva) else etapa_viva
    p = planificar(ctx, ajustes, cargar_catalogo(), estado, etapa=etapa)
    p.avisos = list(dict.fromkeys([*avisos, *estado.get("avisos", [])]))
    carpeta = _carpeta(ctx)
    _retirar_aprobacion(ctx, None)
    vivo = carpeta / PLAN_MCP
    estado["opciones"] = {"plan": opciones.plan, "telefono": opciones.telefono}
    if not p.operaciones:
        for viejo in (vivo, carpeta / PLAN_MD):
            if viejo.exists() or viejo.is_symlink():
                viejo.unlink()
        estado["aprobada"] = None
        guardar_estado(ctx, estado)
        _escribir_checkout(vault, ctx, estado, args, ahora)
        texto = resumen_en_seco(p, ctx)
        print(texto)
        print("No queda nada que aplicar por el conector. Lo de «a mano» y la comprobación desde fuera siguen "
              "(trovefy checkout comprobar).")
        return 0
    creado = ahora.isoformat()
    datos = {"producto": ctx.producto, "pais": ctx.pais, "etapa": etapa, "creado": creado,
             "operaciones": [{"herramienta": o.herramienta, "argumentos": o.argumentos} for o in p.operaciones]}
    p.huella = huella_del_plan(datos)  # H1: la que se aprueba (y la de la frase del resumen)
    detalle = [{"n": o.n, "clave": o.clave, "ajustes": list(o.ajustes), "herramienta": o.herramienta,
                "lectura": o.lectura, "dos_pasos": o.dos_pasos, "solo_vista_previa": o.solo_vista_previa,
                "frase": o.frase} for o in p.operaciones]
    datos.update({"huella": p.huella, "catalogo_huella": p.huella_catalogo,
                  "detalle": detalle, "lecturas_despues": p.lecturas_despues,
                  "pendientes": [{"frase": e.frase, "faltan": list(e.faltan)} for e in p.pendientes]})
    texto = resumen_en_seco(p, ctx)
    for nombre, contenido in (("PLAN-MCP.json", datos), ("PLAN-MCP.md", texto)):
        patron = secreto_en(contenido)
        if patron:
            raise ErrorDeUso(f"{nombre}: aparece un secreto ({patron}); no se escribe nada")
    escribir_atomico(vivo, json.dumps(datos, ensure_ascii=False, indent=1))
    escribir_atomico(carpeta / PLAN_MD, texto)
    historial = _historial(ctx, etapa)
    shutil.copyfile(vivo, historial / PLAN_MCP)
    shutil.copyfile(carpeta / PLAN_MD, historial / PLAN_MD)
    estado.update(etapa=etapa, aprobada=None, plan_huella=p.huella)
    guardar_estado(ctx, estado)
    rel = [x.relative_to(vault).as_posix() for x in (vivo, carpeta / PLAN_MD)]
    anadir_log(vault, "checkout", f"{ctx.producto} {ctx.pais}: plan del MCP, etapa {etapa} "
                                  f"({len(p.operaciones)} llamadas)", rel, ahora=ahora)
    print(texto)
    return 0


# --- aprobar ------------------------------------------------------------------------------------------------------


def validar_cita(cita: str, plan: dict) -> str | None:
    """Por qué la cita no vale como aprobación de ``plan`` (None si vale): vacía, con controles invisibles o que no
    es, entera, la frase atada a ese plan (H3; sin mirar mayúsculas ni tildes). Sin lista de afirmaciones: un «sí»,
    un «ok» o un «sí, pero…» no aprueban nada."""
    if not isinstance(cita, str) or not cita.strip():
        return "hace falta tu mensaje literal (--cita)"
    raros = sorted({f"U+{ord(c):04X}" for c in cita if unicodedata.category(c) in ("Cc", "Cf") and c not in "\n\t"})
    if raros:
        return f"la cita lleva caracteres de control ({', '.join(raros)}): escríbela de nuevo sin ellos"
    frase = frase_aprobacion(plan.get("etapa"), plan.get("huella", ""))
    if not es_la_frase(cita, plan.get("etapa"), plan.get("huella", "")):
        return f"para aprobar este plan escribe exactamente «{frase}» (está atada a este plan; nada más en el mensaje)"
    return None


def _citas_usadas(ctx) -> Path:
    return _carpeta(ctx) / HISTORIAL / CITAS_USADAS


def _leer_usadas(ctx) -> list[dict]:
    ruta = _citas_usadas(ctx)
    if not ruta.exists():
        return []
    if ruta.is_symlink():
        raise ErrorDeUso(f"{CITAS_USADAS} es un enlace: no se lee")
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ErrorDeUso(f"{CITAS_USADAS} está roto ({type(exc).__name__}): no sigo") from exc
    if not isinstance(datos, list):
        raise ErrorDeUso(f"{CITAS_USADAS} no tiene la forma esperada: no sigo")
    return [d for d in datos if isinstance(d, dict)]


def aprobar(args, ahora: datetime) -> int:
    from trovefy.vault.escritura import anadir_log, escribir_atomico

    vault, ctx = _contexto(args.producto, args.pais)
    estado = cargar_estado(ctx)
    plan = _leer_plan(ctx)
    if plan is None:
        raise ErrorDeUso("no hay plan que aprobar: primero trovefy checkout plan")
    if plan.get("etapa") != estado.get("etapa") or plan.get("huella") != estado.get("plan_huella"):
        raise ErrorDeUso("el plan escrito no es el de la etapa en curso: rehazlo con trovefy checkout plan")
    if estado.get("aprobada") == plan["etapa"]:
        raise ErrorDeUso(f"la etapa {plan['etapa']} ya está aprobada")
    patron = secreto_en(args.cita)
    if patron:
        raise ErrorDeUso(f"la cita lleva algo con forma de secreto ({patron}): no se guarda")
    motivo = validar_cita(args.cita, plan)
    if motivo:
        raise ErrorDeUso(motivo)
    creado = creado_de(plan)
    if creado is None:
        raise ErrorDeUso(f"{PLAN_MCP} sin fecha de creación: rehazlo con trovefy checkout plan")
    cita = args.cita.strip()
    usadas = _leer_usadas(ctx)
    if any(u.get("h") == huella_mensaje(cita) for u in usadas):
        raise ErrorDeUso("ese mensaje ya aprobó un plan: cada plan se aprueba con su propia frase")
    terminal = hay_terminal()
    if not (terminal or es_mensaje_del_usuario(cita, desde=creado)):
        raise ErrorDeUso(NO_ES_TUYA)
    # Un mensaje aprueba un solo plan: queda marcado en el registro (lo que mira la guarda) y en la lista de al lado.
    usado = usar_mensaje(cita, desde=creado, huella=plan["huella"], terminal=terminal, ahora=ahora.timestamp())
    if usado is None:
        raise ErrorDeUso(NO_ES_TUYA if not terminal else
                         "no puedo anotar tu aprobación en el registro de mensajes (o ese mensaje ya se usó)")
    fecha = ahora.isoformat(timespec="seconds")
    texto = (f"---\nplan_huella: {plan['huella']}\ncita: {json.dumps(cita, ensure_ascii=False)}\n"
             f"fecha: {json.dumps(fecha)}\netapa: {plan['etapa']}\nproducto: {ctx.producto}\npais: {ctx.pais}\n---\n\n"
             f"# Aprobación · etapa {plan['etapa']}\n\nPalabras literales del usuario:\n\n"
             + "\n".join(f"> {x}" for x in cita.splitlines()) + "\n")
    viva = _carpeta(ctx) / APROBACION
    escribir_atomico(viva, texto)
    shutil.copyfile(viva, _historial(ctx, plan["etapa"]) / APROBACION)
    usadas.append({"h": usado["h"], "t": usado["t"], "huella": plan["huella"], "etapa": plan["etapa"],
                   "via": "terminal" if terminal else "chat"})
    escribir_atomico(_citas_usadas(ctx), json.dumps(usadas, ensure_ascii=False, indent=1))
    estado["aprobada"] = plan["etapa"]
    estado.setdefault("aprobaciones", []).append({"etapa": plan["etapa"], "fecha": fecha, "cita": cita,
                                                  "plan_huella": plan["huella"]})
    guardar_estado(ctx, estado)
    anadir_log(vault, "checkout", f"{ctx.producto} {ctx.pais}: etapa {plan['etapa']} del MCP aprobada",
               [viva.relative_to(vault).as_posix()], ahora=ahora)
    print(f"Etapa {plan['etapa']} aprobada con tus palabras: «{cita}». Ya puedo aplicar sus "
          f"{len(plan['operaciones'])} llamadas, en orden.")
    return 0


# --- releer -------------------------------------------------------------------------------------------------------


def _archivo_en_cache(ctx, ruta: str) -> Path:
    cache = ruta_cache(ctx)
    p = Path(ruta).expanduser()
    if p.is_symlink() or not p.is_file():
        raise ErrorDeUso(f"{ruta}: no es un archivo normal (guárdalo en ~/.cache/trovefy/checkout/{ctx.producto}/"
                         f"{ctx.pais}/)")
    try:
        p.resolve().relative_to(cache.resolve())
    except ValueError as exc:
        raise ErrorDeUso(f"las respuestas del MCP van en ~/.cache/trovefy/checkout/{ctx.producto}/{ctx.pais}/ "
                         "(fuera del vault: pueden llevar datos de la tienda)") from exc
    return p


def _guardar_redactado(ruta: Path, texto: str) -> None:
    tmp = ruta.with_name(f".{ruta.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(texto)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, ruta)


_CLAVE_SUBIDA = re.compile(r'("(?:codigo|url_subida|upload_url|url_firmada)"\s*:\s*)"[^"]*"')
NO_GUARDADA_CRUDO = "no se guardó: el archivo no se entendía y tenía algo con forma de secreto"


def _redactar_crudo(ruta: Path) -> None:
    """La copia de la caché que no se pudo leer como respuestas: sin URLs firmadas ni códigos de subida; con algo con
    forma de secreto, no se guarda nada de ella."""
    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        texto = ""
    if secreto_en(texto):
        limpio = json.dumps({"llamadas": [], "nota": NO_GUARDADA_CRUDO}, ensure_ascii=False)
    else:
        limpio = redactar_urls_firmadas(_CLAVE_SUBIDA.sub(r'\1"[redactado]"', texto))
    _guardar_redactado(ruta, limpio)


def releer_cli(args, ahora: datetime) -> int:
    from trovefy.tienda.mcp import cargar_catalogo

    vault, ctx = _contexto(args.producto, args.pais)
    ruta = _archivo_en_cache(ctx, args.respuesta)
    catalogo = cargar_catalogo()
    try:
        respuestas, guardable = leer_respuestas(ruta, catalogo)
    except ValueError:
        _redactar_crudo(ruta)  # aunque no se entienda, la copia de la caché no se queda con URLs firmadas ni secretos
        raise
    _guardar_redactado(ruta, guardable)  # la copia de la caché, ya sin URLs firmadas ni secretos
    for r in respuestas:
        h = catalogo.get(r.herramienta)
        if h is None or h.clase not in ("lectura", "escritura"):
            raise ErrorDeUso(f"{r.herramienta}: no es una herramienta permitida del catálogo")
    estado = cargar_estado(ctx)
    plan_json = _leer_plan(ctx)
    aprobado = _aprobacion_viva(ctx, plan_json, estado)
    plan = _plan_de_json(plan_json) if aprobado else None

    escrituras: dict[int, object] = {}
    secretos: set[int] = set()
    lecturas: dict[str, object] = {}
    html: dict[str, object] = {}
    avisos: list[str] = []
    for r in respuestas:
        h = catalogo[r.herramienta]
        if h.clase == "lectura":
            if r.secreto:
                avisos.append(f"no medido: la respuesta de {r.herramienta} tenía algo con forma de secreto ("
                              f"{r.secreto}): no se guardó")
                lecturas.pop(r.herramienta, None)
                continue
            if r.herramienta == "impultienda_leer_html_postcompra":
                html[str(r.argumentos.get("oferta_id"))] = r.respuesta
            else:
                lecturas[r.herramienta] = r.respuesta
            continue
        op = None if plan is None else next(
            (o for o, j in zip(plan.operaciones, plan_json["operaciones"], strict=True)
             if casa_con_operacion(j, h, r.argumentos)), None)
        if op is None:
            raise ErrorDeUso(f"esa escritura no está en el plan aprobado ({r.herramienta}): no se anota nada")
        vista = isinstance(r.respuesta, dict) and r.respuesta.get("modo") == "vista_previa"
        if vista and not op.solo_vista_previa:
            continue  # la vista previa de un cambio en dos pasos: lo aplica la confirmación
        if r.secreto:
            secretos.add(op.n)
            escrituras.pop(op.n, None)
        else:
            escrituras[op.n] = r.respuesta
            secretos.discard(op.n)
    if html:
        lecturas["impultienda_leer_html_postcompra"] = html

    inst, avisos_inst = instantanea(ctx, lecturas, estado.get("instantanea"))
    valores = valores_de(ctx, inst, estado.get("valores"))
    for n, resp in escrituras.items():
        op = plan.operaciones[n - 1]
        nuevos, av = valores_de_escritura(Paso(op.clave, op.ajustes, op.herramienta, op.argumentos, op.lectura,
                                               op.solo_vista_previa), resp)
        valores.update(nuevos)
        avisos += av
    faltan = [b for b in LECTURAS_BASE if b not in lecturas]
    if "<store_id>" not in valores and "impultienda_listar_tiendas" not in faltan:
        faltan.insert(0, "impultienda_listar_tiendas")
    estado.update(instantanea=inst, valores=valores, lecturas_completas=not faltan, faltan_lecturas=faltan)
    estado["avisos"] = list(dict.fromkeys([*avisos_inst, *[a for a in avisos if not a.startswith("no medido: la "
                                                                                                    "respuesta")]]))

    rels = []
    if plan is not None:
        rels = releer(plan, inst, escrituras, ctx=ctx, valores=valores, secretos=frozenset(secretos))
        por_op: dict[str, list[str]] = {}
        for r in rels:
            por_op.setdefault(r.operacion, []).append(r.estado)
            estado.setdefault("relecturas", {})[r.ajuste] = relectura_a_dict(r)
        for op in plan.operaciones:
            if op.clave not in por_op:
                continue
            peor = next((e for e in ("distinto", "no_medido", "pendiente_aprobar_panel") if e in por_op[op.clave]),
                        "ok")
            estado.setdefault("hechas", {})[op.clave] = {"estado": peor, "etapa": plan.etapa}
            if peor == "distinto":
                intentos = estado.setdefault("intentos", {}).get(op.clave, 0) + 1
                estado["intentos"][op.clave] = intentos
                if intentos >= 2:
                    estado.setdefault("manuales", {})[op.clave] = {
                        "ajustes": list(op.ajustes),
                        "motivo": "revisar a mano: siguió distinto tras corregirlo una vez (se para y lo haces tú "
                                  "en tu panel)"}
        estado["releida"] = plan.etapa
        _retirar_aprobacion(ctx, plan.etapa)
        cerrar_mensajes(plan.huella)  # la aprobación ya no vale, ni repuesta a mano
        olvidar_escrituras(plan.huella)  # M1: fuera del registro de la guarda las escrituras de esta etapa
    guardar_estado(ctx, estado)
    if estado.get("etapa"):
        _escribir_checkout(vault, ctx, estado, argparse.Namespace(plan_tienda=(estado.get("opciones") or {}).get(
            "plan"), sin_telefono=not (estado.get("opciones") or {}).get("telefono", True)), ahora)

    bien = not avisos and not faltan
    for r in rels:
        linea = f"- {r.ajuste}: {r.estado}"
        if r.estado != "ok":
            bien = False
            linea += f" ({r.evidencia})" + (f" — apruébalo aquí: {r.enlace}" if r.enlace else "")
        print(linea)
    for a in avisos:
        print(f"- {a}")
    if faltan:
        print(f"no medido: faltan las lecturas del MCP ({', '.join(faltan)})")
    distintos = [r.ajuste for r in rels if r.estado == "distinto"]
    if distintos:
        print("Distinto: se corrige una vez en la etapa siguiente; si sigue distinto, pasa a mano.")
    print("Siguiente: trovefy checkout plan" if not faltan else "Siguiente: lee lo que falta y vuelve a releer")
    return 0 if bien else 1


# --- despacho -----------------------------------------------------------------------------------------------------


def ejecutar(accion: str, args, ahora: datetime) -> int:
    from trovefy.embudo.contexto import EstadoIncorrecto

    try:
        if accion == "plan":
            return plan(args, ahora)
        if accion == "aprobar":
            return aprobar(args, ahora)
        return releer_cli(args, ahora)
    except EstadoIncorrecto as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (ErrorDeUso, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
