"""Recorrido de comprador en modo demo (plan 19, Tarea 13; resolución 22).

Qué hacen los vídeos: «recorrido completo como comprador» y los enlaces demo ``…/post-purchase/demo?t=…`` que no
cobran (V1 1:04:46, 1:12:35). Sin desvío.

Un comprador nuevo (Chromium sin perfil, 390 px, `fuera.proteger`: Meta y Clarity silenciados, pasarelas abortadas,
nada que no sea GET, sin ``fbclid``) abre la landing con los UTM de prueba, pulsa el botón de compra (el único clic
del recorrido), mira el checkout como en la Tarea 12 y abre el enlace demo de la oferta post-compra. **Nunca**
escribe en el formulario de pago ni pulsa «pagar».

``checkout/<PAIS>/embudo.md`` guarda el resultado (las URLs sin query: el enlace demo lleva un token) y sobrescribe
``landing.qa.utm_checkout`` con ``interceptado: false`` (resolución 22).
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlencode, urlsplit

from trovefy import navegador
from trovefy.checkout import fuera
from trovefy.checkout.receta import GUION_UPSELL, Ajuste
from trovefy.embudo.contexto import ruta_pais
from trovefy.idioma import detectar
from trovefy.secretos import buscar_secreto
from trovefy.tracking.modelo import utm_de_prueba
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO, escribir_atomico
from trovefy.vault.producto import actualizar_producto

EstadoPaso = Literal["ok", "falla", "no_medido"]
PASOS_FIJOS = ("landing", "boton", "checkout_utm", "checkout_precio", "checkout_idioma", "campos", "sin_bump")
BOTON = "a[data-tf-checkout]"
RUTA_DEMO = "/post-purchase/demo"
ARCHIVO = "embudo.md"
_DE_FUERA = {"producto.front.precio": "checkout_precio", "checkout.idioma": "checkout_idioma",
             "checkout.campos": "campos", "checkout.bump": "sin_bump"}


@dataclass(frozen=True)
class Paso:
    clave: str
    estado: EstadoPaso
    detalle: str
    url: str | None = None
    captura: str | None = None


def _sin_query(url: str | None) -> str | None:
    return url.split("?", 1)[0].split("#", 1)[0] if url else None


def validar_upsell_demo(url: str, ctx) -> str:
    """El enlace demo del post-compra tiene que ser https, del host de la tienda y de la ruta ``/post-purchase/demo``.
    Devuelve el enlace tal cual (con su token, que no se guarda); ``ValueError`` si no vale."""
    partes = urlsplit((url or "").strip())
    tienda = urlsplit(ctx.tienda or "")
    if partes.hostname is None or partes.hostname != tienda.hostname:
        raise ValueError(f"el enlace demo no es de la tienda ({tienda.hostname or 'sin tienda'}): no se abre")
    if partes.scheme != tienda.scheme or partes.path.rstrip("/") != RUTA_DEMO:
        raise ValueError(f"el enlace demo tiene que ser {tienda.scheme}://{tienda.hostname}{RUTA_DEMO}?t=…")
    return url.strip()


def _guardar_captura(page, capturas: Path, nombre: str, ctx) -> str | None:
    destino = Path(capturas) / f"demo-{nombre}.png"
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(destino), full_page=False)
        os.chmod(destino, 0o600)
    except Exception:  # noqa: BLE001 - una captura que falla no para el recorrido
        return None
    try:
        return destino.relative_to(ruta_pais(ctx).parent.parent).as_posix()
    except ValueError:
        return destino.name


def _vista(page, status: int | None) -> fuera.Vista:
    page.wait_for_timeout(fuera.ESPERA_JS_MS)
    page.wait_for_load_state("load", timeout=fuera.TIEMPO_CARGA_MS)
    page.evaluate(fuera.MARCAR_OCULTOS)
    return fuera.Vista(page.url, status, page.content())


def _ajustes_minimos(ctx) -> list[Ajuste]:
    return [Ajuste("producto.front.precio", str(ctx.piezas["front"].precio), "precio de la escalera", "S1 7:16", True),
            Ajuste("checkout.campos", "email,nombre,telefono", "email, nombre y teléfono", "V1 0:31:50", True)]


def _de_estado(e: fuera.EstadoFuera) -> EstadoPaso:
    if e.estado in ("ok", "captura", "dicho"):
        return "ok"
    return "no_medido" if e.estado == "no_medido" else "falla"


def _upsells(ctx) -> list[str]:
    return [c for c in ("u1", "u2", "u3")
            if (p := ctx.piezas.get(c)) is not None and p.activo and p.pdf is not None]


def _precios(texto: str) -> list[tuple[Decimal | None, str | None]]:
    return [fuera.leer_precio(m.group(0)) for m in fuera._PRECIO_MONEDA.finditer(texto)]


def _mirar_upsell(ctx, clave: str, pagina: fuera.PaginaPublica) -> tuple[EstadoPaso, str]:
    pieza = ctx.piezas[clave]
    esperado = pieza.precio.quantize(Decimal("0.01"))
    problemas: list[str] = []
    no_medido: list[str] = []
    precios = _precios(pagina.texto)
    monedas = {m for _, m in precios if m}
    if (esperado, ctx.moneda) in precios:
        pass
    elif monedas and ctx.moneda not in monedas:
        no_medido.append(f"precio: la oferta sale en {', '.join(sorted(monedas))} desde tu IP")
    else:
        vistos = ", ".join(fuera._precio_txt(p, m) or "?" for p, m in precios) or "ninguno"
        problemas.append(f"precio: no aparece {fuera._precio_txt(esperado, ctx.moneda)} (se ve {vistos}; ¿descuento "
                         "progresivo del funnel?)")
    idioma = detectar(pagina.texto, [ctx.idioma, "es", "en"])
    if idioma is None:
        no_medido.append("idioma: texto insuficiente")
    elif idioma != ctx.idioma:
        problemas.append(f"idioma: sale en «{idioma}»")
    esperadas = [c for c, _ in GUION_UPSELL]
    faltan = [c for c in esperadas if c not in pagina.guion]
    if faltan:
        problemas.append(f"guion: faltan {', '.join(faltan)}")
    elif [c for c in dict.fromkeys(pagina.guion) if c in esperadas] != esperadas:
        problemas.append("guion: los 8 puntos no van en orden")
    if problemas:
        return "falla", "; ".join(problemas + no_medido)
    if no_medido:
        return "no_medido", "no medido: " + "; ".join(no_medido)
    return "ok", "precio, idioma y los 8 puntos del guion"


def recorrer(page, ctx, capturas: Path, upsell_demo: str | None, *, ajustes: list[Ajuste] | None = None,
             indice: dict | None = None, esperar=None) -> list[Paso]:
    """Los pasos del recorrido (`PASOS_FIJOS` y un ``upsell_<clave>`` por upsell configurado). `page` es una página
    de Playwright ya protegida (`fuera.proteger`). El único clic es el del primer ``a[data-tf-checkout]``."""
    esperar = esperar or fuera._esperar
    pasos: list[Paso] = []
    tienda = urlsplit(ctx.tienda or "")
    pares = utm_de_prueba()

    def ir(url: str):
        esperar(urlsplit(url).hostname or "")
        return page.goto(url, wait_until="load", timeout=fuera.TIEMPO_CARGA_MS)

    def parar(desde: str, motivo: str) -> list[Paso]:
        resto = [*PASOS_FIJOS[PASOS_FIJOS.index(desde):], *(f"upsell_{c}" for c in _upsells(ctx))]
        return pasos + [Paso(c, "no_medido", motivo) for c in resto]

    # 1. landing con los UTM de prueba (sin fbclid)
    if not ctx.landing_url:
        return parar("landing", "no medido: la landing no está publicada (/landing)")
    base = ctx.landing_url.split("#", 1)[0]
    url_landing = f"{base}{'&' if '?' in base else '?'}{urlencode(pares)}"
    resp = ir(url_landing)
    status = getattr(resp, "status", None)
    captura = _guardar_captura(page, capturas, "landing", ctx)
    ok = status is not None and status < 400
    pasos.append(Paso("landing", "ok" if ok else "falla", f"HTTP {status}", _sin_query(page.url), captura))
    if not ok:
        return parar("boton", "no medido: la landing no cargó")

    # 2. el botón de compra (el único clic)
    boton = page.locator(BOTON)
    if boton.count() == 0:
        pasos.append(Paso("boton", "falla", f"la landing no tiene ningún {BOTON}", _sin_query(page.url)))
        return parar("checkout_utm", "no medido: sin botón de compra")
    navegaciones: list[str] = []
    if callable(getattr(type(page), "on", None)):  # la primera navegación tras el clic, antes de cualquier
        page.on("framenavigated",                   # redirección por JavaScript (p. ej. a la portada)
                lambda frame: navegaciones.append(frame.url) if frame == page.main_frame else None)
    esperar(tienda.hostname or "")
    boton.first.click(timeout=fuera.TIEMPO_CARGA_MS)
    page.wait_for_load_state("load", timeout=fuera.TIEMPO_CARGA_MS)
    destino = navegaciones[0] if navegaciones else page.url
    d = urlsplit(destino)
    en_tienda = d.hostname == tienda.hostname or d.hostname in fuera.hosts_de_la_tienda(ctx)
    pasos.append(Paso("boton", "ok" if en_tienda else "falla",
                      "lleva a la tienda" if en_tienda else f"lleva a otro sitio ({d.hostname})", _sin_query(destino)))

    # 3. los cinco utm_* llegan al checkout (la URL guardada solo lleva esos pares)
    pagina = fuera.analizar(destino, _vista(page, None))
    captura_checkout = _guardar_captura(page, capturas, "checkout", ctx)
    llegados = {k: v[0] for k, v in parse_qs(d.query).items() if k.startswith("utm_")}
    perdidos = [k for k, v in pares.items() if llegados.get(k) != v]
    utm_destino = _sin_query(destino) + (f"?{urlencode({k: llegados[k] for k in pares if k in llegados})}"
                                         if llegados else "")
    pasos.append(Paso("checkout_utm", "falla" if perdidos else "ok",
                      f"se pierden: {', '.join(perdidos)}" if perdidos else "los cinco utm_* llegan al checkout",
                      utm_destino, captura_checkout))

    # 4–8. el checkout, como en la Tarea 12 (con «Ver como <país>» si desde aquí sale otra moneda)
    ver_como = None
    if not (fuera._es_checkout(pagina, ctx) and pagina.moneda_vista == ctx.moneda
            and pagina.pais_visto in (None, ctx.pais)) and ctx.checkout_url:
        url = fuera.ver_como_url(ctx.checkout_url, ctx.pais)
        r = ir(url)
        ver_como = fuera.analizar(url, _vista(page, getattr(r, "status", None)))
    estados = fuera.comprobar_fuera(ctx, ajustes or _ajustes_minimos(ctx), pagina, indice or {}, ver_como=ver_como)
    por_clave = {e.clave: e for e in estados}
    for clave_fuera, clave in _DE_FUERA.items():
        e = por_clave.get(clave_fuera)
        if e is None:
            pasos.append(Paso(clave, "no_medido", "no medido: la receta no lo pide"))
            continue
        pasos.append(Paso(clave, _de_estado(e), e.detalle, _sin_query(e.evidencia or destino), captura_checkout))

    # 9. las ofertas post-compra, por su enlace demo (no cobra; no se pulsa nada)
    for n, clave in enumerate(_upsells(ctx)):
        nombre = f"upsell_{clave}"
        if not upsell_demo:
            pasos.append(Paso(nombre, "no_medido", "no medido: pega el enlace demo del post-compra (lo da "
                                                   "impultienda_ver_postcompra o tu panel): --upsell-demo URL"))
            continue
        try:
            enlace = validar_upsell_demo(upsell_demo, ctx)
        except ValueError as exc:
            pasos.append(Paso(nombre, "falla", f"rechazado: {exc}", _sin_query(upsell_demo)))
            continue
        if n > 0:
            pasos.append(Paso(nombre, "no_medido", "no medido: el demo solo enseña la primera oferta sin pulsar «no, "
                                                   "gracias»; mírala tú en tu panel", _sin_query(enlace)))
            continue
        r = ir(enlace)
        oferta = fuera.analizar(enlace, _vista(page, getattr(r, "status", None)))
        cap = _guardar_captura(page, capturas, f"upsell-{clave}", ctx)
        if urlsplit(oferta.url_final).path.rstrip("/") != RUTA_DEMO:
            pasos.append(Paso(nombre, "falla", f"el enlace demo redirige a {_sin_query(oferta.url_final)}",
                              _sin_query(enlace), cap))
            continue
        estado, detalle = _mirar_upsell(ctx, clave, oferta)
        pasos.append(Paso(nombre, estado, detalle, _sin_query(enlace), cap))

    return pasos


def ejecutar_demo(ctx, capturas: Path, upsell_demo: str | None, *, ajustes: list[Ajuste] | None = None,
                  indice: dict | None = None) -> list[Paso]:
    """El recorrido en Chromium: perfil vacío (``comprador``, sin perfil persistente), 390 px, red protegida."""
    from playwright.sync_api import Error as PlaywrightError

    try:
        with navegador.sesion(fuera.SERVICIO, visible=False, perfil_persistente=False, viewport=fuera.VIEWPORT,
                              _contexto=dict(fuera.CONTEXTO)) as page:
            fuera.proteger(page)
            return recorrer(page, ctx, capturas, upsell_demo, ajustes=ajustes, indice=indice)
    except (PlaywrightError, navegador.NavegadorError) as exc:
        raise ValueError(f"el navegador falló en el recorrido ({type(exc).__name__})") from None


def estado_embudo(pasos: list[Paso]) -> Literal["ok", "falla", "incompleto"]:
    if any(p.estado == "falla" for p in pasos):
        return "falla"
    if any(p.estado == "no_medido" for p in pasos):
        return "incompleto"
    return "ok"


def _celda(texto: object) -> str:
    return str(texto if texto not in (None, "") else "—").replace("|", "\\|").replace("\n", " ")


def escribir_embudo(vault: Path, ctx, pasos: list[Paso], ahora: datetime | None = None) -> Path:
    """``checkout/<PAIS>/embudo.md`` (``estado: ok | falla | incompleto``; URLs sin query salvo los ``utm_*`` del
    checkout) y ``landing.qa.utm_checkout`` en ``PRODUCTO.md`` con ``interceptado: false`` (resolución 22).
    ``ValueError`` (sin escribir) si algo tiene forma de secreto."""
    vault = Path(vault)
    ahora = (ahora or datetime.now(ZONA_NEGOCIO)).astimezone(ZONA_NEGOCIO)
    estado = estado_embudo(pasos)
    rel = f"checkout/{ctx.pais}/{ARCHIVO}"
    limpios = [Paso(p.clave, p.estado, p.detalle,
                    p.url if p.clave == "checkout_utm" else _sin_query(p.url), p.captura) for p in pasos]
    meta = {"tipo": "embudo_demo", "producto": ctx.producto, "pais": ctx.pais, "estado": estado,
            "fecha": ahora.isoformat(timespec="seconds"), "pasos": [asdict(p) for p in limpios]}
    filas = ["| paso | estado | detalle | url | captura |", "|---|---|---|---|---|"]
    filas += [f"| {p.clave} | {p.estado} | {_celda(p.detalle)} | {_celda(p.url)} | {_celda(p.captura)} |"
              for p in limpios]
    cuerpo = "\n".join([f"# Recorrido de comprador (demo) · {ctx.pais}", "",
                        f"Estado: **{estado}**. Perfil vacío, 390 px, sin pagar (V1 1:04:46, 1:12:35).", "",
                        *filas, ""])
    texto = frontmatter.renderizar(meta, cuerpo)
    patron = buscar_secreto(texto)
    if patron:
        raise ValueError(f"el recorrido lleva algo con forma de secreto ({patron}): no se guarda")
    ruta = ruta_pais(ctx) / ARCHIVO
    escribir_atomico(ruta, texto)
    utm = next((p for p in limpios if p.clave == "checkout_utm"), None)
    if utm is not None:
        cambios = {"paises": {ctx.pais: {"landing": {"qa": {"utm_checkout": {
            "ok": utm.estado == "ok", "destino": utm.url, "captura": utm.captura, "interceptado": False,
            "fuente": rel}}}}}}
        actualizar_producto(vault, ctx.producto, cambios, [f"- Recorrido demo {ctx.pais}: {estado} ({rel})"],
                            "checkout", ahora, archivos_log=[ruta.relative_to(vault).as_posix()])
    return ruta
