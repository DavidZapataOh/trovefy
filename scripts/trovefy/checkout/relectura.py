"""Relectura por el MCP y `CHECKOUT.md` (plan 19, Tarea 11).

Claude llama al MCP en la sesión y guarda lo que le devolvió en un archivo JSON (``{"llamadas": [{herramienta,
argumentos, respuesta}]}``) dentro de ``~/.cache/trovefy/checkout/<p-id>/<PAIS>/`` (fuera del vault: puede llevar
datos de la tienda). Aquí:

- `leer_respuestas` lo carga; las URLs firmadas de corta vida (M-5) se redactan antes de nada en las herramientas
  marcadas ``devuelve_url_firmada`` y, al guardar, en todo el archivo; una respuesta con algo con forma de secreto no
  se usa ni se guarda (su ajuste queda «no medido»);
- `instantanea` y `valores_de` sacan de las lecturas una foto normalizada de la tienda y los ids que piden las
  etapas siguientes; `valores_de_escritura`, los ids que solo da una escritura (el upsell creado, el mercado, la
  ``ruta`` del PDF, los bloques actuales de la vista previa);
- `releer` compara lo pedido con lo releído, operación a operación;
- `escribir_checkout` escribe ``checkout/<PAIS>/CHECKOUT.md`` y la parte ``paises.<PAIS>.checkout`` de
  ``PRODUCTO.md`` que lee el plan 20.

Al vault solo pasan valores normalizados, ids y conteos. Un formato de respuesta desconocido es «no medido», nunca
verde (ruling de la revisión T6–10).
"""
from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from trovefy.checkout.etapas import Paso, pieza_de
from trovefy.checkout.operaciones import REGLAS, Info, Plan, normalizar
from trovefy.checkout.receta import Ajuste, _texto, limpiar_bloques
from trovefy.embudo.contexto import Contexto, ruta_pais
from trovefy.secretos import buscar_secreto
from trovefy.tienda.mcp import URL_REDACTADA, Herramienta, redactar_urls_firmadas
from trovefy.vault import frontmatter
from trovefy.vault.escritura import anadir_log, escribir_atomico
from trovefy.vault.producto import actualizar_producto

EstadoRelectura = Literal["ok", "distinto", "pendiente_aprobar_panel", "no_medido"]
ESTADO_MCP = "MCP-ESTADO.json"
CHECKOUT_MD = "CHECKOUT.md"
_PENDIENTE = re.compile(r"pendiente[^\n]{0,60}aprobar", re.IGNORECASE)
_URL = re.compile(r"https://[^\s\"'<>\\)\]}»]+")
NO_GUARDADA = "no se guardó: tenía algo con forma de secreto"


def _textos(valor: object, salida: list[str]) -> list[str]:
    if isinstance(valor, str):
        salida.append(valor)
    elif isinstance(valor, dict):
        for k, v in valor.items():
            _textos(k, salida)
            _textos(v, salida)
    elif isinstance(valor, (list, tuple, set, frozenset)):
        for v in valor:
            _textos(v, salida)
    return salida


def secreto_en(valor: object) -> str | None:
    """Patrón del primer secreto en los textos (claves y valores, ya decodificados) de ``valor``; None si no hay.
    Como `trovefy.vault.producto.secreto_en`, pero con una sola pasada de `buscar_secreto` sobre todos los textos
    unidos por saltos de línea (cada pasada carga los patrones del hook)."""
    textos = _textos(valor, [])
    return buscar_secreto("\n".join(textos)) if textos else None


@dataclass(frozen=True)
class Relectura:
    ajuste: str
    leido: object
    igual: bool | None
    estado: EstadoRelectura
    pedido: object = None
    fuente: str = "mcp"
    evidencia: str = ""
    enlace: str | None = None
    operacion: str = ""


@dataclass(frozen=True)
class RespuestaMCP:
    herramienta: str
    argumentos: dict
    respuesta: object
    secreto: str | None = None


def estado_nuevo() -> dict:
    """El contenido inicial de ``MCP-ESTADO.json``."""
    return {"version": 1, "etapa": 0, "aprobada": None, "releida": None, "valores": {}, "instantanea": {},
            "lecturas_completas": False, "faltan_lecturas": [], "hechas": {}, "intentos": {}, "manuales": {},
            "relecturas": {}, "aprobaciones": [], "avisos": []}


# --- el archivo de respuestas -------------------------------------------------------------------------------------


_CLAVES_SUBIDA = frozenset({"codigo", "url_subida", "upload_url", "url_firmada"})


def _sin_codigos(valor: object) -> object:
    """Fuera los códigos y URLs de subida de corta vida (M-5): sirven para subir, no para releer."""
    if isinstance(valor, dict):
        return {k: (URL_REDACTADA if k in _CLAVES_SUBIDA and v is not None else _sin_codigos(v))
                for k, v in valor.items()}
    if isinstance(valor, list):
        return [_sin_codigos(v) for v in valor]
    return valor


def leer_respuestas(ruta: Path, catalogo: Mapping[str, Herramienta]) -> tuple[list[RespuestaMCP], str]:
    """Las llamadas del archivo y su versión para guardar (sin URLs firmadas ni respuestas con secretos).
    ``ValueError`` si el archivo no tiene la forma ``{"llamadas": [{herramienta, argumentos, respuesta}]}``."""
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"no puedo leer {Path(ruta).name}: {type(exc).__name__}") from exc
    llamadas = datos.get("llamadas") if isinstance(datos, dict) else None
    if not isinstance(llamadas, list):
        raise ValueError(  # noqa: TRY004 - dato de entrada: la CLI sale con 2
            "el archivo de respuestas va como {\"llamadas\": [{herramienta, argumentos, respuesta}]}")
    salida: list[RespuestaMCP] = []
    guardar: list[dict] = []
    for n, ll in enumerate(llamadas, 1):
        if not isinstance(ll, dict) or not isinstance(ll.get("herramienta"), str) \
                or not isinstance(ll.get("argumentos", {}), dict):
            raise ValueError(f"llamada {n}: va como {{herramienta, argumentos, respuesta}}")  # noqa: TRY004
        h = ll["herramienta"].removeprefix("mcp__impultienda__")
        args = ll.get("argumentos") or {}
        resp = ll.get("respuesta")
        herramienta = catalogo.get(h)
        if herramienta is not None and herramienta.devuelve_url_firmada:
            resp = _sin_codigos(json.loads(redactar_urls_firmadas(json.dumps(resp, ensure_ascii=False))))
        secreto = secreto_en(resp) or secreto_en(args)
        salida.append(RespuestaMCP(h, args, None if secreto else resp, secreto))
        guardar.append({"herramienta": h, "argumentos": NO_GUARDADA if secreto_en(args) else args,
                        "respuesta": NO_GUARDADA if secreto else resp})
    texto = redactar_urls_firmadas(json.dumps({"llamadas": guardar}, ensure_ascii=False, indent=1))
    return salida, texto


# --- instantánea de la tienda y valores --------------------------------------------------------------------------


def _host(url: object) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    try:
        return (urlsplit(url if "//" in url else "https://" + url).hostname or "").casefold() or None
    except ValueError:
        return None


def _tienda_de(ctx: Contexto, resp: object) -> tuple[dict | None, str | None]:
    tiendas = resp.get("tiendas") if isinstance(resp, dict) else None
    if not isinstance(tiendas, list):
        return None, "no medido: la respuesta de listar_tiendas no trae «tiendas»"
    host = _host(ctx.tienda)
    if host is None:
        return None, "no medido: falta la tienda del país en config/mercados.yaml"
    casan = [t for t in tiendas if isinstance(t, dict)
             and host in {_host(t.get("url")), _host(t.get("dominio_propio"))} - {None}]
    if len(casan) != 1:
        return None, f"no medido: no encuentro una sola tienda {host} en tu cuenta ({len(casan)})"
    return casan[0], None


def _precio_txt(valor: object) -> str | None:
    p = normalizar("precio", valor)
    return None if p is None else str(p)


def instantanea(ctx: Contexto, lecturas: Mapping[str, object], previa: dict | None = None) -> tuple[dict, list[str]]:
    """La foto normalizada de la tienda a partir de las lecturas (``{herramienta: respuesta}``; para
    ``leer_html_postcompra``, ``{oferta_id: respuesta}``), encima de ``previa``. Devuelve ``(instantanea, avisos)``."""
    inst = copy.deepcopy(previa or {})
    avisos: list[str] = []
    if "impultienda_listar_tiendas" in lecturas:
        t, motivo = _tienda_de(ctx, lecturas["impultienda_listar_tiendas"])
        if t is None:
            avisos.append(motivo or "no medido: tienda")
            inst.pop("tienda", None)
        else:
            inst["tienda"] = {k: t.get(k) for k in ("id", "nombre", "idioma", "moneda", "tipo", "plan")}
            if t.get("tipo") != "store":
                avisos.append(f"revisar a mano: la tienda es de tipo «{t.get('tipo')}»; esta receta es para una "
                              "tienda clásica (con landing)")
    r = lecturas.get("impultienda_listar_productos")
    if isinstance(r, dict) and isinstance(r.get("productos"), list):
        por_id = {}
        for p in r["productos"]:
            if isinstance(p, dict) and isinstance(p.get("id"), str):
                por_id[p["id"]] = {"id": p["id"], "titulo": p.get("titulo"), "tipo": p.get("tipo"),
                                   "precio": _precio_txt(p.get("precio")),
                                   "precio_original": _precio_txt(p.get("precio_original")),
                                   "solo_post_compra": p.get("solo_post_compra"),
                                   "estado_generacion": p.get("estado_generacion")}
        principales = [p for p in por_id.values() if p["tipo"] == "main"]
        inst["productos"] = {"por_id": por_id, "principal": principales[0] if len(principales) == 1 else None}
        if len(principales) != 1:
            avisos.append(f"no medido: la tienda tiene {len(principales)} productos principales")
        if r.get("has_more"):
            avisos.append("no medido: hay más productos que los leídos (pide la página siguiente)")
    r = lecturas.get("impultienda_ver_markets")
    if isinstance(r, dict) and isinstance(r.get("mercados"), list):
        inst["markets"] = {"activo": r.get("markets_activo"), "moneda_tienda": r.get("moneda_tienda"),
                           "mercados": [{"id": m.get("id"), "nombre": m.get("nombre"), "moneda": m.get("moneda"),
                                         "es_default": bool(m.get("es_default")),
                                         "paises": [p.get("codigo") if isinstance(p, dict) else p
                                                    for p in m.get("paises") or []]}
                                        for m in r["mercados"] if isinstance(m, dict)]}
    r = lecturas.get("impultienda_ver_postcompra")
    if isinstance(r, dict) and "funnels" in r:
        funnel = r.get("funnel") if isinstance(r.get("funnel"), dict) else {}
        ofertas = [{"oferta_id": o.get("oferta_id"), "item_id": o.get("item_id")}
                   for o in funnel.get("ofertas") or [] if isinstance(o, dict)]
        inst["postcompra"] = {"funnels": len(r.get("funnels") or []), "ofertas": ofertas}
    r = lecturas.get("impultienda_ver_recursos")
    if isinstance(r, dict) and isinstance(r.get("recursos"), list):
        mockups = [x for x in r["recursos"] if isinstance(x, dict) and "mockup" in str(x.get("nombre", "")).casefold()
                   and isinstance(x.get("url"), str) and x["url"].startswith("https://") and "?" not in x["url"]]
        inst["recursos"] = {"mockup": mockups[0]["url"] if mockups else None}
    html = lecturas.get("impultienda_leer_html_postcompra")
    if isinstance(html, dict):
        for oferta, h in html.items():
            if isinstance(h, dict) and "tiene_html" in h:
                inst.setdefault("html", {})[oferta] = {k: h.get(k) for k in ("tiene_html", "modo_html_activo",
                                                                             "guardado_por_mcp")}
    return inst, avisos


def valores_de(ctx: Contexto, inst: dict, valores: Mapping[str, object] | None = None) -> dict:
    """Los ids que da la foto de la tienda (encima de ``valores``)."""
    salida = dict(valores or {})
    t = inst.get("tienda") or {}
    if t.get("id"):
        salida["<store_id>"] = t["id"]
    prods = inst.get("productos") or {}
    if (prods.get("principal") or {}).get("id"):
        salida["<item_id:front>"] = prods["principal"]["id"]
    for clave in ("u1", "u2", "u3"):
        pieza = ctx.piezas.get(clave)
        if pieza is None:
            continue
        casan = [p for p in (prods.get("por_id") or {}).values() if p.get("tipo") == "upsell"
                 and normalizar("texto", p.get("titulo")) == normalizar("texto", pieza.titulo)]
        if len(casan) == 1:
            salida[f"<item_id:{clave}>"] = casan[0]["id"]
        item = salida.get(f"<item_id:{clave}>")
        oferta = next((o["oferta_id"] for o in (inst.get("postcompra") or {}).get("ofertas", [])
                       if item and o.get("item_id") == item and o.get("oferta_id")), None)
        if oferta:
            salida[f"<oferta_id:{clave}>"] = oferta
    mercados = (inst.get("markets") or {}).get("mercados") or []
    propio = [m for m in mercados if not m["es_default"] and ctx.pais in m["paises"]]
    if not propio:
        propio = [m for m in mercados if not m["es_default"] and m["moneda"] == ctx.moneda
                  and normalizar("texto", m["nombre"]) == normalizar("texto", f"{ctx.pais} {ctx.moneda}")]
    if len(propio) == 1 and propio[0].get("id"):
        salida["<market_id>"] = propio[0]["id"]
    if (inst.get("recursos") or {}).get("mockup"):
        salida["<url:mockup>"] = inst["recursos"]["mockup"]
    return salida


def valores_de_escritura(paso: Paso, respuesta: object) -> tuple[dict, list[str]]:
    """Los ids que solo da una escritura aplicada: ``(valores, avisos)``."""
    if not isinstance(respuesta, dict):
        return {}, []
    h, a = paso.herramienta, paso.argumentos
    piezas = [p for p in (pieza_de(x) for x in paso.ajustes) if p]
    if paso.solo_vista_previa and h == "impultienda_bloques_checkout":
        try:
            limpios, avisos = limpiar_bloques(respuesta.get("actuales"))
        except ValueError as exc:
            return {}, [f"no medido: {exc}"]
        return {f"<bloques:{a.get('posicion')}>": limpios}, avisos
    if h == "impultienda_crear_producto" and isinstance(respuesta.get("producto"), dict) and piezas:
        pid = respuesta["producto"].get("id")
        return ({f"<item_id:{piezas[0]}>": pid} if isinstance(pid, str) else {}), []
    if h == "impultienda_configurar_mercado" and isinstance(respuesta.get("mercado"), dict):
        mid = respuesta["mercado"].get("id")
        return ({"<market_id>": mid} if isinstance(mid, str) else {}), []
    if h == "impultienda_cargar_entregable" and a.get("modo") == "subir" and piezas:
        ruta = respuesta.get("ruta")
        return ({f"<ruta:{piezas[0]}>": ruta} if isinstance(ruta, str) and ruta else {}), []
    return {}, []


# --- releer -------------------------------------------------------------------------------------------------------


def pendiente_panel(respuesta: object) -> str | None:
    """Si la respuesta dice que el cambio quedó pendiente de «Aprobar» en el panel: el enlace para aprobarlo
    (``link_panel`` o la primera URL https; ``""`` si no trae ninguno). None si no está pendiente."""
    texto = json.dumps(respuesta, ensure_ascii=False)
    if not _PENDIENTE.search(texto):
        return None
    if isinstance(respuesta, dict) and isinstance(respuesta.get("link_panel"), str):
        return respuesta["link_panel"]
    m = _URL.search(redactar_urls_firmadas(texto))
    return m.group(0) if m else ""


def _error(respuesta: object) -> str | None:
    if isinstance(respuesta, dict) and respuesta.get("error"):
        texto = str(respuesta["error"])[:200]
        return None if secreto_en(texto) else texto
    return None


def releer(plan: Plan, instantaneas: dict, escrituras: Mapping[int, object] | None = None, *, ctx: Contexto,
           valores: Mapping[str, object] | None = None,
           secretos: frozenset[int] = frozenset()) -> list[Relectura]:
    """Pedido frente a releído de cada operación aplicada del plan (``escrituras``: ``{n: respuesta}``), con la foto
    normalizada de la tienda releída (`instantanea`). ``secretos``: operaciones cuya respuesta tenía forma de
    secreto (no se usa: «no medido»)."""
    salida: list[Relectura] = []
    for op in plan.operaciones:
        if op.n not in (escrituras or {}) and op.n not in secretos:
            continue
        r = (escrituras or {}).get(op.n)
        paso = Paso(op.clave, op.ajustes, op.herramienta, op.argumentos, op.lectura, op.solo_vista_previa)
        enlace = None
        if op.n in secretos or (r is not None and secreto_en(r)):
            pedido, leido, estado, evidencia = None, None, "no_medido", NO_GUARDADA
        elif (enlace := pendiente_panel(r)) is not None:
            pedido, leido, estado = None, None, "pendiente_aprobar_panel"
            evidencia = "quedó pendiente de «Aprobar» en tu panel: ábrelo y apruébalo"
        elif (error := _error(r)) is not None:
            pedido, leido, estado, evidencia = None, None, "distinto", f"el conector respondió con un error: {error}"
        else:
            info = Info(instantaneas, dict(valores or {}), paso, ctx)
            pedido, leido, estado = REGLAS[op.herramienta].releer(op.argumentos, info, r)
            evidencia = f"releído por el MCP ({(op.lectura or op.herramienta).removeprefix('impultienda_')})"
        igual = True if estado == "ok" else False if estado == "distinto" else None
        for ajuste in op.ajustes:
            salida.append(Relectura(ajuste, leido, igual, estado, pedido, "mcp", evidencia, enlace or None, op.clave))
    return salida


# --- CHECKOUT.md --------------------------------------------------------------------------------------------------


def _celda(valor: object) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, Path):
        texto = valor.name
    elif isinstance(valor, (list, tuple)):
        texto = ", ".join(str(x) for x in valor)
    else:
        texto = _texto(valor)
    return texto.replace("|", "/").replace("\n", " ")[:120]


def _peor(estados: list[str]) -> str:
    for e in ("distinto", "no_medido", "pendiente_aprobar_panel"):
        if e in estados:
            return e
    return "ok"


CERRADOS = frozenset({"ok", "captura", "dicho"})


@dataclass(frozen=True)
class Visto:
    """Un resultado de la comprobación desde fuera o del respaldo manual (la forma de `trovefy.checkout.fuera.
    EstadoFuera`): ``estado`` ok|falla|no_medido|parado|captura|dicho, ``fuente`` fuera|captura|dicho."""

    clave: str
    estado: str
    visto: str | None = None
    detalle: str = ""
    fuente: str | None = None
    evidencia: str | None = None


def comprobacion(ctx: Contexto) -> tuple[dict[str, Visto], dict[str, Visto]]:
    """``(fuera, manual)`` de ``checkout/<PAIS>/COMPROBACION.md`` (`trovefy checkout comprobar`, Tarea 12), por
    ajuste. Sin el archivo, o roto, ``({}, {})``: nada comprobado desde fuera."""
    ruta = ruta_pais(ctx) / "COMPROBACION.md"
    if not ruta.is_file() or ruta.is_symlink():
        return {}, {}
    try:
        meta, _ = frontmatter.leer(ruta)
    except (OSError, ValueError):
        return {}, {}
    fuera: dict[str, Visto] = {}
    manual: dict[str, Visto] = {}
    for e in (meta or {}).get("estados") or []:
        if not isinstance(e, dict) or not isinstance(e.get("clave"), str) or not isinstance(e.get("estado"), str):
            continue
        v = Visto(e["clave"], e["estado"], e.get("visto"), str(e.get("detalle") or ""), e.get("fuente"),
                  e.get("evidencia"))
        (manual if e.get("origen") == "manual" else fuera)[v.clave] = v
    return fuera, manual


def _visto(v: object) -> Visto:
    if isinstance(v, Visto):
        return v
    if isinstance(v, tuple):  # (fuente, evidencia): lo dado por bueno
        return Visto("", "ok", None, "", v[0], v[1] if len(v) > 1 else None)
    g = (lambda k: v.get(k)) if isinstance(v, dict) else (lambda k: getattr(v, k, None))
    return Visto(str(g("clave") or ""), str(g("estado") or "no_medido"), g("visto"), str(g("detalle") or ""),
                 g("fuente"), g("evidencia"))


def escribir_checkout(vault: Path, ctx: Contexto, plan: Plan, relecturas: list[Relectura],
                      fuera: Mapping[str, object] | None = None,
                      manual: Mapping[str, object] | None = None, *, ajustes: list[Ajuste],
                      ahora: datetime, tienda_plan: str, avisos: list[str] | tuple[str, ...] = (),
                      parados: Mapping[str, str] | None = None, aprobaciones: list[dict] | None = None) -> Path:
    """``checkout/<PAIS>/CHECKOUT.md`` y ``PRODUCTO.md:paises.<PAIS>.checkout``.

    ``relecturas``: las de todas las etapas (la última por ajuste manda). ``fuera`` y ``manual``: ``{ajuste:
    EstadoFuera}`` de la comprobación desde fuera y del respaldo manual (Tarea 12; `comprobacion` los lee de
    ``COMPROBACION.md``). Lo visto desde fuera manda sobre la relectura: un precio releído «ok» que fuera se ve mal
    queda a medias. Un ajuste a mano queda cerrado con su evidencia ``captura``/``dicho``/``ok``. ``parados``: ajustes
    que siguieron distintos tras la corrección. Estado: ``parado`` con alguno de esos o con algo ``parado`` desde fuera
    (escasez, D-01); ``completo`` si no queda nada por aplicar ni a medias y lo de a mano tiene evidencia; si no,
    ``a_medias``. ``ValueError`` sin escribir nada si el texto lleva un secreto."""
    fuera = {k: _visto(v) for k, v in (fuera or {}).items()}
    manual = {k: _visto(v) for k, v in (manual or {}).items()}
    parados = dict(parados or {})
    ultima: dict[str, Relectura] = {}
    for r in relecturas:
        ultima[r.ajuste] = r
    ya = {a.clave for a in plan.ya_estan}
    pendientes = {x for e in plan.pendientes for x in e.ajustes} | {x for o in plan.operaciones for x in o.ajustes}
    filas = ["| ajuste | pedido | releído | fuente | evidencia |", "|---|---|---|---|---|"]
    a_medias: list[str] = []
    a_mano: list[str] = []
    claves = {a.clave for a in ajustes}

    def _de_fuera(clave: str) -> str:
        v = fuera.get(clave)
        if v is None:
            return ""
        if v.estado not in CERRADOS:
            a_medias.append(f"- {clave}: visto desde fuera: {v.estado}: {v.detalle}")
        return f" · fuera: {v.estado}" + (f" ({v.visto})" if v.visto else "")

    for a in ajustes:
        pedido = _celda(a.valor)
        if a.clave in parados or a.clave in plan.motivos_manuales:
            motivo = parados.get(a.clave) or plan.motivos_manuales[a.clave]
            m = manual.get(a.clave) or fuera.get(a.clave)
            cerrado = m is not None and m.estado in CERRADOS and a.clave not in parados
            fuente = (m.fuente or "—") if m else "—"
            evidencia = f"a mano: {m.estado}" + (f" ({m.evidencia})" if m.evidencia else "") if m else "a mano"
            filas.append(f"| {a.clave} | {pedido} | {_celda(m.visto if m else None)} | {fuente} | "
                         f"{_celda(evidencia)} |")
            if not cerrado:
                extra = f" — {m.detalle}" if m and m.detalle and m.estado not in CERRADOS else ""
                a_mano.append(f"- {a.clave}: {motivo}{extra}")
            continue
        r = ultima.get(a.clave)
        if r is not None:
            ev = r.estado + (f" ({r.evidencia})" if r.evidencia else "") + _de_fuera(a.clave)
            filas.append(f"| {a.clave} | {pedido} | {_celda(r.leido)} | {r.fuente} | {_celda(ev)} |")
            if r.estado != "ok":
                extra = f" — aprueba aquí: {r.enlace}" if r.enlace else ""
                a_medias.append(f"- {a.clave}: {r.estado}: {r.evidencia}{extra}")
            continue
        if a.clave in ya:
            ev = "ya estaba así (lectura del MCP)" + _de_fuera(a.clave)
            filas.append(f"| {a.clave} | {pedido} | igual | mcp | {_celda(ev)} |")
            continue
        if a.clave in fuera:
            v = fuera[a.clave]
            filas.append(f"| {a.clave} | {pedido} | {_celda(v.visto)} | {v.fuente or 'fuera'} | "
                         f"{_celda(v.estado + (f' ({v.evidencia})' if v.evidencia else ''))} |")
            _de_fuera(a.clave)
            continue
        filas.append(f"| {a.clave} | {pedido} | — | — | pendiente |")
        cuando = "en una etapa siguiente" if a.clave in pendientes else "sin aplicar"
        a_medias.append(f"- {a.clave}: pendiente ({cuando})")
    for clave, v in fuera.items():  # lo que fuera mira sin ajuste propio (escasez, prueba social…)
        if clave not in claves and v.estado not in CERRADOS:
            a_medias.append(f"- {clave}: visto desde fuera: {v.estado}: {v.detalle}")
    parado_fuera = any(v.estado == "parado" for v in fuera.values())
    estado = ("parado" if parados or parado_fuera
              else "completo" if not a_medias and not a_mano else "a_medias")
    cuerpo = [f"# Checkout · {ctx.producto} · {ctx.pais}", "",
              ("Aplicado por el MCP de Impultienda tras tu aprobación, etapa a etapa, y releído por el MCP. Fuerza "
               "de la evidencia: mcp y fuera > captura > dicho."), "", *filas, ""]
    cuerpo += ["## A medias", "", *(a_medias or ["- nada"]), ""]
    cuerpo += ["## A mano", "", *(a_mano or ["- nada"]), ""]
    if avisos:
        cuerpo += ["## Avisos", "", *[f"- {x}" for x in dict.fromkeys(avisos)], ""]
    if aprobaciones:
        cuerpo += ["## Aprobaciones", ""]
        cuerpo += [f"- Etapa {x.get('etapa')} ({x.get('fecha')}): «{x.get('cita')}» · huella {x.get('plan_huella')}"
                   for x in aprobaciones]
        cuerpo.append("")
    meta = {"tipo": "checkout", "producto": ctx.producto, "pais": ctx.pais, "estado": estado,
            "fecha": ahora.isoformat(timespec="seconds"), "plan_huella": plan.huella,
            "catalogo_huella": plan.huella_catalogo, "tienda_plan": tienda_plan, "etapa": plan.etapa}
    texto = frontmatter.renderizar(meta, "\n".join(cuerpo))
    patron = secreto_en(texto)
    if patron:
        raise ValueError(f"CHECKOUT.md: aparece un secreto ({patron}); no se escribe nada")
    ruta = ruta_pais(ctx) / CHECKOUT_MD
    escribir_atomico(ruta, texto)
    front = ctx.piezas.get("front")
    bloque = {"estado": estado, "fecha": ahora.isoformat(timespec="seconds"), "plataforma": "impultienda",
              "url": ctx.checkout_url,
              "precio": {"importe": str(front.precio) if front else None, "moneda": ctx.moneda}}
    rel = ruta.relative_to(vault).as_posix()
    actualizar_producto(vault, ctx.producto, {"paises": {ctx.pais: {"checkout": bloque}}}, [], "checkout", ahora,
                        archivos_log=[rel])
    return ruta


def relectura_a_dict(r: Relectura) -> dict:
    d = asdict(r)
    d["leido"] = _celda(r.leido) if r.leido is not None else None
    d["pedido"] = _celda(r.pedido) if r.pedido is not None else None
    return d


def relectura_de_dict(d: dict) -> Relectura:
    return Relectura(**{k: d.get(k) for k in Relectura.__dataclass_fields__})


def anotar(vault: Path, que: str, archivos: list[str], ahora: datetime) -> None:
    anadir_log(vault, "checkout", que, archivos, ahora=ahora)
