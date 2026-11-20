"""Gates puros de `/listo` sobre la evidencia que dejaron `/landing` (plan 18) y `/tracking` + `/checkout` (plan 19).

Cada gate devuelve un `Gate` con estado ``ok``, ``falla``, ``no_medido`` (el texto empieza por «no medido: ») o
``no_aplica``; ``excepcion`` solo lo pone `trovefy.listo.veredicto` cuando el usuario aprobó la excepción que cubre
ese gate (`trovefy.listo.EXCEPCION_DE_GATE`). ``cubre_excepcion`` es falso cuando el fallo no es el hecho que cubre
esa excepción (un dataset compartido no lo excusa «tracking verificado»).

De dónde sale la evidencia de la compra de prueba (resoluciones 30 y 31): del bloque ``compra_prueba`` de
``PRODUCTO.md`` si existe y, si no, de lo que ya registró el plan 19: el índice de evidencias pegadas
(``checkout/<PAIS>/evidencia/indice.yaml``, claves ``pedido``, ``email-entrega``, ``pdf-descargado`` y ``reembolso``)
y el resumen de eventos de ``trovefy tracking eventos`` (``checkout/<PAIS>/compra/events-manager.json``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from urllib.parse import parse_qs, urlsplit

import yaml

from trovefy.listo.ficha import FichaPais, campo, ruta_evidencia
from trovefy.vault import frontmatter

EstadoGate = Literal["ok", "falla", "no_medido", "no_aplica", "excepcion"]
UTM_OBLIGATORIOS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")
_DATASET = re.compile(r"\d{1,20}")
_RESUMEN_EVENTOS = "compra/events-manager.json"  # bajo checkout/<PAIS>/ (trovefy tracking eventos)
_FUERTES = ("captura", "texto")  # lo que pega el usuario; su palabra sola («dicho») no basta para la compra


@dataclass(frozen=True)
class Gate:
    clave: str
    estado: EstadoGate
    texto: str
    evidencia: tuple[str, ...] = ()
    arreglo: str | None = None
    cubre_excepcion: bool = True  # False: el fallo no es el hecho que cubre la excepción de este gate


def ok(clave: str, texto: str, evidencia=(), arreglo: str | None = None) -> Gate:
    return Gate(clave, "ok", texto, tuple(evidencia), arreglo)


def falla(clave: str, texto: str, evidencia=(), arreglo: str | None = None, cubre: bool = True) -> Gate:
    return Gate(clave, "falla", texto, tuple(evidencia), arreglo, cubre)


def no_medido(clave: str, motivo: str, arreglo: str | None = None, evidencia=(), cubre: bool = True) -> Gate:
    texto = motivo if motivo.startswith("no medido: ") else f"no medido: {motivo}"
    return Gate(clave, "no_medido", texto, tuple(evidencia), arreglo, cubre)


def _peor(clave: str, partes: list[Gate], evidencia: list[str]) -> Gate:
    """Junta sub-comprobaciones: una falla manda; si no, un no medido; si no, ok."""
    for estado in ("falla", "no_medido"):
        malas = [g for g in partes if g.estado == estado]
        if malas:
            arreglo = next((g.arreglo for g in malas if g.arreglo), None)
            texto = "; ".join(g.texto.removeprefix("no medido: ") for g in malas)
            if estado == "no_medido":
                texto = "no medido: " + texto
            return Gate(clave, estado, texto, tuple(evidencia), arreglo, all(g.cubre_excepcion for g in malas))
    return ok(clave, "; ".join(g.texto for g in partes), evidencia)


def _vault(f: FichaPais) -> Path:
    return f.carpeta.parent.parent


def pegados(f: FichaPais, clave: str) -> list:
    """Las evidencias pegadas válidas (`trovefy.embudo.pegado`) de esa clave, en orden de llegada; [] si no hay o
    el índice no se puede leer. Solo cuentan las que siguen en su sitio (`ruta_evidencia`)."""
    from trovefy.embudo.pegado import indice

    try:
        lista = indice(_vault(f), SimpleNamespace(vault=_vault(f), producto=f.producto, pais=f.pais)).get(clave, [])
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        return []
    return [p for p in lista if ruta_evidencia(f, p.ruta)]


def _fecha(valor: object) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        try:
            return date.fromisoformat(valor[:10])
        except ValueError:
            return None
    return None


def _host(url: object) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        h = urlsplit(url.strip()).hostname
    except ValueError:
        return None
    return h.lower() if h else None


def hosts_tienda(f: FichaPais) -> set[str]:
    """Los hosts que sirven la tienda: el del checkout y, si la landing la sirve Impultienda, el de su dominio propio
    (con y sin ``www.``), como `trovefy.checkout.fuera.hosts_de_la_tienda`."""
    from trovefy.checkout.fuera import hosts_de_la_tienda

    ctx = SimpleNamespace(tienda=None, checkout_url=campo(f.datos, "checkout.url"),
                          landing_hosting=campo(f.datos, "landing.hosting"), landing_url=campo(f.datos, "landing.url"))
    try:
        return {h.lower() for h in hosts_de_la_tienda(ctx)}
    except (TypeError, ValueError):
        return set()


# --- UTM hasta el checkout ------------------------------------------------------------------------------------------


def gate_utm(f: FichaPais) -> Gate:
    """``landing.qa.utm_checkout``: el clic de la landing llega al checkout con los cinco ``utm_*`` de §4.9.
    `interceptado: true` (la QA del 18 aún no llegó al checkout real) no vale (resolución 22)."""
    c = "utm_checkout"
    u = campo(f.datos, "landing.qa.utm_checkout")
    arreglo = "/trovefy:checkout (recorrido demo: trovefy checkout demo)"
    if not isinstance(u, dict):
        return no_medido(c, "falta landing.qa.utm_checkout (QA de /landing y recorrido demo de /checkout)", arreglo)
    if u.get("interceptado") is True:
        return no_medido(c, "el clic se interceptó en la QA: falta el recorrido demo hasta el checkout real", arreglo)
    captura = ruta_evidencia(f, u.get("captura"))
    if u.get("ok") is not True:
        return falla(c, "la QA dice que las UTM no llegan intactas al checkout", [captura] if captura else [], arreglo)
    if captura is None:
        return no_medido(c, "falta la captura del checkout con las UTM (o no está dentro del producto)", arreglo)
    destino = u.get("destino")
    host = _host(destino)
    if host is None:
        return no_medido(c, "falta la URL de destino del clic", arreglo, [captura])
    params = parse_qs(urlsplit(destino).query, keep_blank_values=True)
    faltan = [p for p in UTM_OBLIGATORIOS if not (params.get(p) and params[p][0].strip())]
    if faltan:
        return falla(c, "al checkout le faltan " + ", ".join(faltan), [captura], arreglo)
    if params["utm_source"][0] != "fb" or params["utm_medium"][0] != "paid":
        return falla(c, "utm_source y utm_medium deben ser fb y paid (plantilla de §4.9)", [captura], arreglo)
    tienda = hosts_tienda(f)
    if not tienda:
        return no_medido(c, "falta checkout.url para saber cuál es la tienda", arreglo, [captura])
    if host not in tienda:
        return falla(c, f"el clic va a otro sitio ({host}), no al checkout de la tienda", [captura], arreglo)
    return ok(c, f"el clic llega al checkout ({host}) con los cinco utm_*", [captura])


# --- compra de prueba ---------------------------------------------------------------------------------------------


def _compra_plataforma(f: FichaPais) -> Gate:
    c = "compra"
    arreglo = "/trovefy:checkout (compra de prueba: impultienda_listar_ventas o tu captura del pedido)"
    plataforma = campo(f.datos, "compra_prueba.plataforma")
    if isinstance(plataforma, dict):
        ev = ruta_evidencia(f, plataforma.get("evidencia"))
        if plataforma.get("visto") is True and plataforma.get("fuente") in ("mcp", "captura") and ev:
            return ok(c, f"pedido {campo(f.datos, 'compra_prueba.pedido') or '¿?'} visto en la plataforma "
                         f"({plataforma.get('fuente')})", [ev])
        if plataforma.get("visto") is False:
            return falla(c, "la plataforma no muestra la compra de prueba", [ev] if ev else [], arreglo)
    lista = pegados(f, "pedido")
    fuertes = [p for p in lista if p.tipo in _FUERTES]
    if fuertes:
        p = fuertes[-1]
        pedido = p.valores.get("pedido") or "sin número"
        return ok(c, f"pedido {pedido} visto en la plataforma ({p.tipo} que pegaste)", [p.ruta])
    if lista:
        return falla(c, "la compra de prueba solo está dicha (tu palabra sola no basta): pega la captura del pedido",
                     [lista[-1].ruta], "trovefy checkout evidencia --clave pedido --desde <captura>")
    return no_medido(c, "la compra de prueba no está registrada en la plataforma", arreglo)


def _resumen_eventos(f: FichaPais) -> tuple[dict | None, str | None]:
    rel = f"checkout/{f.pais}/{_RESUMEN_EVENTOS}"
    ev = ruta_evidencia(f, rel)
    if ev is None:
        return None, None
    try:
        datos = json.loads((f.carpeta / ev).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None, ev
    return (datos if isinstance(datos, dict) else None), ev


def _compra_events_manager(f: FichaPais) -> Gate:
    """Purchase visto exactamente una vez por pedido de prueba en el dataset del producto-país."""
    c = "compra"
    arreglo = "/trovefy:tracking (trovefy tracking eventos con ads_get_dataset_stats antes y después)"
    dataset = campo(f.datos, "tracking.dataset_id")
    em = campo(f.datos, "compra_prueba.events_manager")
    if isinstance(em, dict):
        n, pedidos, otro = em.get("purchase"), 1, em.get("dataset_id")
        ev = ruta_evidencia(f, em.get("evidencia"))
        fuente = em.get("fuente") or "sin fuente"
    else:
        datos, ev = _resumen_eventos(f)
        if datos is None:
            motivo = (f"{ev} no se puede leer" if ev else
                      "falta el conteo de Purchase en Events Manager (compra_prueba.events_manager o "
                      f"checkout/{f.pais}/{_RESUMEN_EVENTOS})")
            return no_medido(c, motivo, arreglo)
        conteo = datos.get("conteo") if isinstance(datos.get("conteo"), dict) else {}
        n, pedidos, otro = conteo.get("Purchase"), datos.get("pedidos", 1), datos.get("dataset_id")
        fuente = "MCP ads_get_dataset_stats" if datos.get("fuente") == "mcp" else str(datos.get("fuente"))
    evidencia = [ev] if ev else []
    if ev is None:
        return no_medido(c, "el conteo de Events Manager no trae su evidencia dentro del producto", arreglo)
    if isinstance(pedidos, bool) or not isinstance(pedidos, int) or pedidos < 1:
        return no_medido(c, "el resumen de eventos no dice cuántos pedidos de prueba hubo", arreglo, evidencia)
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        return no_medido(c, "el número de Purchase no es un conteo", arreglo, evidencia)
    if dataset is None:
        return no_medido(c, "falta tracking.dataset_id para saber en qué dataset mirar", arreglo, evidencia)
    if otro is not None and str(otro) != str(dataset):
        return falla(c, f"el Purchase contado es de otro dataset ({otro}), no del de este producto-país",
                     evidencia, arreglo)
    if n == 0:
        return falla(c, "Meta no vio la compra de prueba (0 Purchase)", evidencia, arreglo)
    if n > pedidos:
        return falla(c, f"Purchase llegó {n} veces para {pedidos} pedido{'s' if pedidos > 1 else ''}: hay dos "
                        "emisores (D-17); deja solo el CAPI nativo de la tienda", evidencia, arreglo)
    if n < pedidos:
        return falla(c, f"faltan Purchase en Events Manager ({n} para {pedidos} pedidos)", evidencia, arreglo)
    return ok(c, f"Purchase visto una sola vez por pedido en Events Manager ({fuente})", evidencia)


def gate_compra(f: FichaPais) -> Gate:
    """La compra de prueba vista en la plataforma **y** una sola vez en Events Manager. No admite excepción."""
    partes = [_compra_plataforma(f), _compra_events_manager(f)]
    evidencia = [e for g in partes for e in g.evidencia]
    return replace(_peor("compra", partes, evidencia), cubre_excepcion=False)


# --- entrega y reembolso ------------------------------------------------------------------------------------------


def gate_entrega(f: FichaPais) -> Gate:
    """Llegó el email de entrega y el PDF se descarga. Vale el bloque ``compra_prueba.entrega`` o lo pegado
    (``email-entrega`` y ``pdf-descargado``; para la entrega vale también su cita literal, resolución 31)."""
    c = "entrega"
    arreglo = "/trovefy:checkout (pega el email de entrega y di si el PDF se descarga)"
    e = campo(f.datos, "compra_prueba.entrega")
    if isinstance(e, dict):
        ev = ruta_evidencia(f, e.get("evidencia"))
        if e.get("email") is False:
            return falla(c, "el email de entrega no llegó", [ev] if ev else [], arreglo, cubre=False)
        if e.get("pdf_descargable") is False:
            return falla(c, "el PDF no se descarga", [ev] if ev else [], arreglo, cubre=False)
        if e.get("email") is True and e.get("pdf_descargable") is True:
            if ev is None:
                return no_medido(c, "la entrega no trae su evidencia dentro del producto", arreglo, cubre=False)
            return ok(c, "llegó el email de entrega y el PDF se descarga", [ev])
    email, pdf = pegados(f, "email-entrega"), pegados(f, "pdf-descargado")
    partes = []
    if email:
        partes.append(ok(c, f"email de entrega ({email[-1].tipo})", [email[-1].ruta]))
    else:
        partes.append(no_medido(c, "falta el email de entrega (trovefy checkout evidencia --clave email-entrega)",
                                arreglo))
    if pdf:
        partes.append(ok(c, f"PDF descargado ({pdf[-1].tipo})", [pdf[-1].ruta]))
    else:
        partes.append(no_medido(c, "falta que digas si el PDF se descarga (trovefy checkout evidencia --clave "
                                   "pdf-descargado)", arreglo))
    return replace(_peor(c, partes, [x for g in partes for x in g.evidencia]), cubre_excepcion=False)


def _fecha_compra(f: FichaPais) -> date | None:
    d = _fecha(campo(f.datos, "compra_prueba.fecha"))
    if d is not None:
        return d
    fuertes = [p for p in pegados(f, "pedido") if p.tipo in _FUERTES]
    return _fecha(fuertes[-1].fecha) if fuertes else None


def gate_reembolso(f: FichaPais) -> Gate:
    """El reembolso de la compra de prueba, procesado, con fecha no anterior a la compra y su evidencia."""
    c = "reembolso"
    arreglo = "reembolsa la compra de prueba en tu panel y regístralo con /trovefy:checkout"
    r = campo(f.datos, "compra_prueba.reembolso")
    compra = _fecha_compra(f)
    if isinstance(r, dict):
        ev = ruta_evidencia(f, r.get("evidencia"))
        if r.get("procesado") is False:
            return falla(c, "el reembolso no está procesado", [ev] if ev else [], arreglo)
        if r.get("procesado") is True:
            if ev is None:
                return no_medido(c, "el reembolso no trae su evidencia dentro del producto", arreglo)
            cuando = _fecha(r.get("fecha"))
            if cuando is None:
                return no_medido(c, "la fecha del reembolso no se entiende (AAAA-MM-DD)", arreglo, [ev])
            if compra is not None and cuando < compra:
                return falla(c, f"el reembolso ({cuando}) es anterior a la compra ({compra})", [ev], arreglo)
            return ok(c, f"reembolso procesado el {cuando}", [ev])
    lista = pegados(f, "reembolso")
    fuertes = [p for p in lista if p.tipo in _FUERTES]
    if fuertes:
        p = fuertes[-1]
        cuando = _fecha(p.fecha)
        if compra is not None and cuando is not None and cuando < compra:
            return falla(c, f"la captura del reembolso ({cuando}) es anterior a la compra ({compra})", [p.ruta],
                         arreglo)
        return ok(c, f"reembolso visto ({p.tipo} que pegaste)", [p.ruta])
    if lista:
        return falla(c, "el reembolso solo está dicho (tu palabra sola no basta): pega la captura", [lista[-1].ruta],
                     "trovefy checkout evidencia --clave reembolso --desde <captura>")
    return no_medido(c, "el reembolso de la compra de prueba no está registrado", arreglo)


# --- dominio --------------------------------------------------------------------------------------------------------


def gate_dominio(landing_url: str | None, dominio: str | None, paso08) -> Gate:
    """La landing vive en el dominio del paso 07 (o en un subdominio suyo) y el dominio está verificado en Meta
    (paso 08). El estado del 08 se toma tal como está: su verificador lee una pantalla con sesión y ya no se ejecuta;
    ``hecho`` vale en la fase 2 (resoluciones 32, 38 y 41)."""
    c = "dominio"
    if not dominio:
        return no_medido(c, "falta el dominio del paso 07", "trovefy arranque hecho 07 --dato dominio=<tu-dominio>")
    host = _host(landing_url)
    if host is None:
        return no_medido(c, "falta landing.url", "/trovefy:landing")
    if host != dominio and not host.endswith("." + dominio):
        return falla(c, f"la landing ({host}) no está en tu dominio verificado ({dominio})",
                     arreglo="publica la landing en tu dominio, o aprueba la excepción «dominio verificado»")
    if paso08 is None:
        return no_medido(c, "falta el paso 08 en config/arranque.yaml")
    evidencia = tuple(e for e in (paso08.evidencia or []) if isinstance(e, str))
    if paso08.estado == "verificado" and evidencia:
        return ok(c, f"landing en {host}; dominio {dominio} verificado en Meta (paso 08)", evidencia)
    if paso08.estado in ("verificado", "hecho"):
        return ok(c, f"landing en {host}; dominio {dominio} marcado como hecho en el paso 08 (vale en la fase 2: "
                     "su verificador lee un panel con sesión y ya no se ejecuta)", evidencia)
    return falla(c, f"el paso 08 (verificar {dominio} en Meta) está {paso08.estado}",
                 arreglo="verifica el dominio en tu navegador (Business Settings → Dominios) y marca el paso 08")


# --- dataset --------------------------------------------------------------------------------------------------------


def datasets_de_otros(vault: Path, producto: str, pais: str) -> tuple[dict[str, str], list[str]]:
    """``({dataset_id: "p-id/PAIS"}, notas)`` de los demás producto-país del vault. Una ficha ilegible no se
    salta en silencio: va en ``notas`` («no se pudo leer …»)."""
    otros: dict[str, str] = {}
    notas: list[str] = []
    carpeta = Path(vault) / "productos"
    for ruta in sorted(carpeta.glob("*/PRODUCTO.md")) if carpeta.is_dir() else ():
        p_id = ruta.parent.name
        try:
            meta, _ = frontmatter.leer(ruta)
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
            notas.append(f"no se pudo leer productos/{p_id}/PRODUCTO.md")
            continue
        paises = meta.get("paises") if isinstance(meta, dict) else None
        if paises is None:
            continue
        if not isinstance(paises, dict):
            notas.append(f"no se pudo leer productos/{p_id}/PRODUCTO.md (paises no es un mapa)")
            continue
        for otro_pais, bloque in paises.items():
            if (p_id, otro_pais) == (producto, pais) or not isinstance(bloque, dict):
                continue
            d = campo(bloque, "tracking.dataset_id")
            if d is not None:
                otros[str(d)] = f"{p_id}/{otro_pais}"
    return otros, notas


def _tracking_verificado(f: FichaPais) -> Gate:
    from trovefy.tracking.salida import leer_tracking

    c = "dataset"
    arreglo = "/trovefy:tracking (trovefy tracking eventos)"
    try:
        t = leer_tracking(_vault(f), f.producto, f.pais)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        return falla(c, f"TRACKING.md no se puede leer ({exc})", arreglo=arreglo)
    if t is None:
        return no_medido(c, f"falta checkout/{f.pais}/TRACKING.md", arreglo)
    dataset = campo(f.datos, "tracking.dataset_id")
    if t.dataset_id is not None and dataset is not None and str(t.dataset_id) != str(dataset):
        return falla(c, "TRACKING.md es de otro dataset que PRODUCTO.md", arreglo=arreglo, cubre=False)
    if t.estado == "verificado":
        return ok(c, "eventos verificados (TRACKING.md)", [f"checkout/{f.pais}/TRACKING.md"])
    motivos = [m for m in t.motivos if m]
    return falla(c, f"los eventos no están verificados (TRACKING.md en «{t.estado}»"
                    + (f": {'; '.join(motivos)}" if motivos else "") + ")",
                 [f"checkout/{f.pais}/TRACKING.md"], arreglo)


def gate_dataset(f: FichaPais, otros: dict[str, str], notas: list[str] | tuple[str, ...] = ()) -> Gate:
    """Un dataset por producto-país (§4.1), nombrado «PRODUCTO PAÍS», con un único emisor de Purchase (D-17) y los
    eventos verificados en ``TRACKING.md``. Solo la parte de los eventos la cubre la excepción «tracking
    verificado»; lo demás nunca se excusa."""
    c = "dataset"
    arreglo = "/trovefy:tracking"
    t = campo(f.datos, "tracking")
    if not isinstance(t, dict):
        return no_medido(c, "falta el bloque tracking en PRODUCTO.md", arreglo, cubre=False)
    dataset = t.get("dataset_id")
    if dataset is None:
        return no_medido(c, "falta tracking.dataset_id", arreglo, cubre=False)
    dataset = str(dataset)
    if not _DATASET.fullmatch(dataset):
        return falla(c, f"tracking.dataset_id no es un id de dataset ({dataset})", arreglo=arreglo, cubre=False)
    nombre = t.get("dataset_nombre")
    if not isinstance(nombre, str) or not nombre.strip().upper().endswith(" " + f.pais):
        return falla(c, f"el nombre del dataset debe terminar en « {f.pais}» («PRODUCTO PAÍS»): {nombre!r}",
                     arreglo=arreglo, cubre=False)
    emisor = t.get("emisor_purchase")
    if isinstance(emisor, (list, tuple, set)) and len(set(map(str, emisor))) > 1:
        return falla(c, f"Purchase tiene {len(set(map(str, emisor)))} emisores (D-17): deja uno solo", arreglo=arreglo,
                     cubre=False)
    if not isinstance(emisor, str) or not emisor.strip():
        return no_medido(c, "falta tracking.emisor_purchase", arreglo, cubre=False)
    if dataset in otros:
        return falla(c, f"el dataset {dataset} ya lo usa {otros[dataset]}: va uno por producto-país",
                     arreglo=arreglo, cubre=False)
    if notas:
        return no_medido(c, "; ".join(notas) + " (no sé si su dataset es el mismo)", cubre=False)
    eventos = _tracking_verificado(f)
    if eventos.estado != "ok":
        texto = eventos.texto if eventos.estado == "no_medido" else f"dataset {nombre} ({emisor}); {eventos.texto}"
        return replace(eventos, texto=texto)
    return ok(c, f"dataset {nombre}, uno por producto-país, Purchase solo desde {emisor}; eventos verificados",
              eventos.evidencia)


# --- creativos ------------------------------------------------------------------------------------------------------

NO_APLICA_CREATIVOS = "no aplica hasta la fase 3: aún no hay creativos"


def gate_creativos(f: FichaPais) -> Gate:
    """Plan 21, Tarea 12: sin ``creativos/<PAIS>/`` (o vacía) no aplica (la fase 2 sigue pasando). Con carpeta, ``ok``
    solo con la tanda vigente cerrada, sin nada por rehacer, ``manifest.csv`` y cada pieza con el mismo ``sha256``
    que se cerró, y en ``QA.md`` la automática, el ``revisor``, el ``nativo`` y Whisper (cada vídeo) en ``ok`` sobre
    la tanda actual. Nunca se pone en verde solo."""
    import csv
    import hashlib

    from trovefy.creativos import registro

    c = "creativos"
    carpeta = f.carpeta / "creativos" / f.pais
    if not carpeta.is_dir() or not any(carpeta.iterdir()):
        return Gate(c, "no_aplica", NO_APLICA_CREATIVOS)
    bloque = f.datos.get("creativos") if isinstance(f.datos.get("creativos"), dict) else {}
    vigente = bloque.get("vigente")
    tandas = bloque.get("tandas") if isinstance(bloque.get("tandas"), dict) else {}
    tanda = tandas.get(vigente) if isinstance(vigente, str) else None
    arreglo = "/trovefy:creativos"
    if not isinstance(tanda, dict):
        return falla(c, "hay creativos sin cerrar: /creativos", arreglo=arreglo, cubre=False)
    pendientes = [r for r in tanda.get("rehacer") or [] if isinstance(r, dict) and not r.get("resuelto")]
    if pendientes:
        detalle = "; ".join(f"{', '.join(r.get('ads') or [])} ({r.get('motivo')})" for r in pendientes)
        return falla(c, f"faltan por rehacer: {detalle}", arreglo=arreglo, cubre=False)
    if not tanda.get("cerrada"):
        return falla(c, f"hay creativos sin cerrar: /creativos ({vigente})", arreglo=arreglo, cubre=False)
    dir_tanda = carpeta / vigente
    manifiesto = dir_tanda / "manifest.csv"
    try:
        crudo = manifiesto.read_bytes()
    except OSError:
        return falla(c, f"falta {vigente}/manifest.csv", arreglo=arreglo, cubre=False)
    if hashlib.sha256(crudo).hexdigest() != tanda.get("manifest_sha256"):
        return falla(c, "la tanda cambió después de cerrarla (manifest.csv)", arreglo=arreglo, cubre=False)
    vault = _vault(f)
    piezas = []
    for fila in csv.DictReader(crudo.decode("utf-8").splitlines()):
        ruta = vault / fila.get("archivo", "")
        if registro.sha_archivo(ruta) != fila.get("sha256"):
            return falla(c, f"la tanda cambió después de cerrarla ({fila.get('id')})", arreglo=arreglo, cubre=False)
        piezas.append((fila.get("id", ""), fila.get("tipo", "")))
    est = registro.estado(dir_tanda, piezas)
    if not est.ok:
        return falla(c, "QA de la tanda sin terminar: " + "; ".join(est.faltan()), arreglo=arreglo, cubre=False)
    rel = f"creativos/{f.pais}/{vigente}"
    return ok(c, f"tanda {vigente} cerrada y revisada ({len(piezas)} piezas)",
              [f"{rel}/QA.md", f"{rel}/{est.hoja}" if est.hoja else f"{rel}/qc"])

