"""Un MCP de Impultienda falso para los tests de la Tarea 11 (nunca se llama al MCP real).

Guarda una tienda clásica en memoria y responde con las formas de los esquemas reales (`config/impultienda_tools.json`,
«Devuelve (structuredContent)»), con ids ficticios. Cada llamada pasa antes por la guarda del hook
(`hooks/impultienda_guard.py`): si la guarda no la deja pasar, el test falla, como fallaría en la sesión real.
Las herramientas en dos pasos devuelven una vista previa con su ``token`` y aplican solo con ``confirmar: true`` y
ese token.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from trovefy.tienda.mcp import cargar_catalogo

CATALOGO = cargar_catalogo()
STORE = "00000000-0000-4000-8000-000000000001"
FRONT = "00000000-0000-4000-8000-000000000002"
DEFAULT = "00000000-0000-4000-8000-000000000009"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "checkout" / "mcp"
# Lo que devuelve el servidor en la vista previa de una subida: una URL firmada de corta vida (M-5).
URL_FIRMADA = ("https://almacen.ejemplo.test/subidas/prueba.pdf?X-Amz-Signature=ab12cd34ef56ab12cd34ef56"
               "&X-Amz-Expires=7200")


def fixture(nombre: str) -> dict:
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


def _uuid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012x}"


class GuardaDeniega(AssertionError):
    pass


class MCPFalso:
    def __init__(self, guarda) -> None:
        self.guarda = guarda
        tiendas = fixture("listar_tiendas.json")
        self.tiendas = tiendas["tiendas"]
        self.productos = fixture("listar_productos.json")["productos"]
        markets = fixture("ver_markets.json")
        self.markets_activo = markets["markets_activo"]
        self.mercados = markets["mercados"]
        self.precios_fijos: dict[tuple[str, str | None], float] = {}
        self.funnels: list[dict] = []
        self.recursos: list[dict] = []
        self.checkout: dict = {"pedir_apellido": True, "pedir_telefono": False, "ocultar_barra_compradores": False}
        self.diseno: dict = {"minutos_timer_bump": 7}
        self.bloques = {"arriba": [], "abajo": [
            {"tipo": "countdown", "minutos": 7, "texto": "La oferta termina en"},
            {"tipo": "text", "etiqueta": "p", "texto": "Pago seguro y entrega por email."},
        ]}
        self.html: dict[str, dict] = {}
        self.subidas: dict[str, str] = {}   # ruta → nombre del archivo pedido
        self.subidos: set[str] = set()      # rutas con el PUT hecho
        self.entregables: dict[str, str] = {}
        self.tokens: dict[str, tuple[str, str]] = {}
        self.escrituras: list[tuple[str, dict]] = []
        self.siguiente = 0x100
        self.nombre_tienda_falla = False

    # --- utilidades -------------------------------------------------------------------------------------------

    def _nuevo_id(self) -> str:
        self.siguiente += 1
        return _uuid(self.siguiente)

    def llamar(self, herramienta: str, argumentos: dict) -> dict:
        decision = self.guarda.clasificar("mcp__impultienda__" + herramienta, copy.deepcopy(argumentos))
        if decision != ("allow", ""):
            raise GuardaDeniega(f"{herramienta}: {decision}")
        h = CATALOGO[herramienta]
        if h.clase == "escritura":
            self.escrituras.append((herramienta, copy.deepcopy(argumentos)))
        return getattr(self, herramienta.removeprefix("impultienda_"))(**copy.deepcopy(argumentos))

    def _dos_pasos(self, nombre: str, argumentos: dict, aplicar, vista: dict | None = None) -> dict:
        base = {k: v for k, v in argumentos.items() if k not in ("confirmar", "token")}
        huella = json.dumps([nombre, base], sort_keys=True)
        if not argumentos.get("confirmar"):
            token = hashlib.sha256(huella.encode()).hexdigest()[:16]
            self.tokens[token] = (nombre, huella)
            return {"modo": "vista_previa", "token": token, **(vista or {})}
        if self.tokens.pop(argumentos.get("token"), None) != (nombre, huella):
            return {"error": "token inválido o vencido"}
        return aplicar()

    def _tienda(self, store_id: str) -> dict:
        return next(t for t in self.tiendas if t["id"] == store_id)

    def _producto(self, item_id: str | None) -> dict:
        if item_id is None:
            return next(p for p in self.productos if p["tipo"] == "main")
        return next(p for p in self.productos if p["id"] == item_id)

    def subir_pdf(self, url: str) -> None:
        """El PUT del PDF a la URL firmada (lo hace Claude con curl)."""
        assert url == URL_FIRMADA
        for ruta in self.subidas:
            self.subidos.add(ruta)

    def usuario_sube_recurso(self, nombre: str) -> None:
        self.recursos.insert(0, {"id": self._nuevo_id(), "tipo": "imagen", "nombre": nombre,
                                 "url": f"https://cdn.prueba.impultienda.example/recursos/{nombre}",
                                 "peso": 1000, "ancho": 800, "alto": 800, "subido": "2026-11-17"})

    def oferta_de(self, item_id: str) -> str | None:
        for f in self.funnels:
            for o in f["ofertas"]:
                if o["item_id"] == item_id:
                    return o["oferta_id"]
        return None

    # --- lecturas ---------------------------------------------------------------------------------------------

    def listar_tiendas(self, incluir_archivadas: bool = False) -> dict:
        return {"total": len(self.tiendas), "tiendas": copy.deepcopy(self.tiendas)}

    def listar_productos(self, store_id: str, tipo: str | None = None, limit: int = 50, offset: int = 0) -> dict:
        ps = [dict(p, estado_generacion=("uploaded" if p["id"] in self.entregables else p["estado_generacion"]))
              for p in self.productos]
        return {"total": len(ps), "count": len(ps), "offset": 0, "has_more": False, "productos": ps}

    def ver_markets(self, store_id: str) -> dict:
        mercados = []
        for m in self.mercados:
            fijos = sum(1 for (mid, _) in self.precios_fijos if mid == m["id"])
            mercados.append({**copy.deepcopy(m), "precios_fijos": fijos})
        return {"markets_activo": self.markets_activo, "multidivisa_lista": True, "moneda_tienda": "USD",
                "mercados": mercados, "link_panel": "https://impultienda.ar/panel/markets"}

    def ver_postcompra(self, store_id: str, funnel_id: str | None = None) -> dict:
        funnel = copy.deepcopy(self.funnels[0]) if self.funnels else None
        solo = [{"item_id": p["id"], "titulo": p["titulo"]} for p in self.productos if p.get("solo_post_compra")]
        return {"tienda": "x", "plan_permite_postcompra": True,
                "funnels": [{"funnel_id": f["funnel_id"], "nombre": f["nombre"], "activo": True}
                            for f in self.funnels],
                "funnel": funnel, "solo_postcompra": solo, "downsell": None,
                "link_panel": "https://impultienda.ar/panel/upsells"}

    def ver_recursos(self, store_id: str, tipo: str = "todos", limit: int = 50) -> dict:
        return {"recursos": copy.deepcopy(self.recursos), "total": len(self.recursos),
                "uso": {"usado": 1, "tope": 100}, "link_panel": "https://impultienda.ar/panel/recursos"}

    def leer_html_postcompra(self, store_id: str, oferta_id: str, desde: int = 0) -> dict:
        h = self.html.get(oferta_id, {})
        html = h.get("html", "")
        return {"modo_html_activo": h.get("activo", False), "tiene_html": bool(html), "total_chars": len(html),
                "desde": 0, "hasta": len(html), "siguiente_desde": None, "guardado_por_mcp": bool(html),
                "version_anterior": False, "avisos": [], "tokens": [], "html": html[:12000]}

    # --- escrituras -------------------------------------------------------------------------------------------

    def configurar_tienda(self, store_id: str, **cambios) -> dict:
        t = self._tienda(store_id)
        anterior = {k: t.get(k) for k in cambios}
        if not self.nombre_tienda_falla:
            t.update(cambios)
        return {"aplicado": list(cambios), "anterior": anterior, "nuevo": cambios,
                "link_panel": "https://impultienda.ar/panel/tienda"}

    def cambiar_idioma(self, store_id: str, idioma: str) -> dict:
        t = self._tienda(store_id)
        antes, t["idioma"] = t["idioma"], idioma
        return {"idioma_anterior": antes, "idioma_nuevo": idioma, "link_panel": "https://impultienda.ar/panel"}

    def activar_markets(self, store_id: str, activar: bool, confirmar: bool = False, token: str | None = None):
        antes = self.markets_activo

        def aplicar():
            self.markets_activo = activar
            return {"modo": "aplicado", "markets_activo_antes": antes, "markets_activo": activar}
        return self._dos_pasos("activar_markets", {"store_id": store_id, "activar": activar, "confirmar": confirmar,
                                                   "token": token}, aplicar)

    def configurar_mercado(self, store_id: str, nombre: str | None = None, moneda: str | None = None,
                           paises: list | None = None, market_id: str | None = None, confirmar: bool = False,
                           token: str | None = None) -> dict:
        args = {"store_id": store_id, "nombre": nombre, "moneda": moneda, "paises": paises, "confirmar": confirmar,
                "token": token}

        def aplicar():
            m = {"id": self._nuevo_id(), "nombre": nombre, "moneda": moneda, "es_default": False,
                 "paises": [{"codigo": p, "nombre": p} for p in paises or []], "precios_fijos": 0, "avisos": []}
            self.mercados.append(m)
            return {"modo": "creado", "mercado": copy.deepcopy(m)}
        return self._dos_pasos("configurar_mercado", args, aplicar)

    def asignar_paises(self, store_id: str, market_id: str, paises: list, confirmar: bool = False,
                       token: str | None = None) -> dict:
        def aplicar():
            m = next(x for x in self.mercados if x["id"] == market_id)
            m["paises"] += [{"codigo": p, "nombre": p} for p in paises]
            return {"modo": "aplicado", "mercado": copy.deepcopy(m), "se_suman": paises, "se_mueven": [],
                    "ya_estaban": []}
        return self._dos_pasos("asignar_paises", {"store_id": store_id, "market_id": market_id, "paises": paises,
                                                  "confirmar": confirmar, "token": token}, aplicar)

    def editar_producto(self, store_id: str, item_id: str | None = None, **cambios) -> dict:
        p = self._producto(item_id)
        antes = {k: p.get(k) for k in cambios}
        if "nombre" in cambios:
            p["titulo"] = cambios["nombre"]
        if "solo_post_compra" in cambios:
            p["solo_post_compra"] = cambios["solo_post_compra"]
        return {"producto": {"id": p["id"]}, "antes": antes, "ahora": cambios, "link_panel": "https://x.example/p"}

    def fijar_precio(self, store_id: str, precio: float, item_id: str | None = None, **resto) -> dict:
        p = self._producto(item_id)
        antes = {"precio": p["precio"], "precio_original": p["precio_original"]}
        p["precio"] = precio
        if "precio_original" in resto:
            p["precio_original"] = resto["precio_original"]
        return {"producto": {"id": p["id"]}, "antes": antes,
                "ahora": {"precio": precio, "precio_original": p["precio_original"]}, "moneda": "USD"}

    def precio_por_pais(self, store_id: str, market_id: str, item_id: str | None = None, precio=None,
                        precio_original=None, valor_mostrado=None, confirmar: bool = False,
                        token: str | None = None) -> dict:
        args = {"store_id": store_id, "market_id": market_id, "item_id": item_id, "precio": precio,
                "precio_original": precio_original, "confirmar": confirmar, "token": token}
        m = next(x for x in self.mercados if x["id"] == market_id)
        clave = (market_id, item_id)

        def aplicar():
            anterior = self.precios_fijos.get(clave)
            self.precios_fijos[clave] = precio
            return {"modo": "aplicado", "mercado": {"id": market_id, "nombre": m["nombre"], "moneda": m["moneda"]},
                    "producto": {"id": item_id or FRONT, "tipo": "ebook"},
                    "precio_anterior": None if anterior is None else {"precio": anterior},
                    "precio_fijo": {"precio": precio, "precio_original": None, "valor_mostrado": None},
                    "accion": "creado" if anterior is None else "actualizado"}
        return self._dos_pasos("precio_por_pais", args, aplicar)

    def cargar_entregable(self, store_id: str, tipo: str, item_id: str, modo: str, **resto) -> dict:
        if modo == "subir":
            ruta = f"entregables/{store_id[-4:]}/{item_id[-4:]}/{resto['nombre_archivo']}"
            self.subidas[ruta] = resto["nombre_archivo"]
            return {"modo": "subir", "url_subida": URL_FIRMADA, "ruta": ruta, "vence": "2026-11-17T14:00:00Z"}
        ruta = resto["ruta"]
        if ruta not in self.subidos:
            return {"error": "el archivo no está en el almacenamiento"}
        self.entregables[item_id] = ruta
        return {"modo": "confirmar", "guardado": ruta, "link_panel": "https://impultienda.ar/panel/entregables"}

    def configurar_checkout(self, store_id: str, **cambios) -> dict:
        self.checkout.update(cambios)
        return {"aplicado": list(cambios), "link_panel": "https://impultienda.ar/panel/checkout"}

    def disenar_checkout(self, store_id: str, **cambios) -> dict:
        anterior = {k: self.diseno.get(k) for k in cambios}
        self.diseno.update(cambios)
        return {"aplicado": dict(cambios), "anterior": anterior, "link_panel": "https://impultienda.ar/panel/diseno"}

    def bloques_checkout(self, store_id: str, posicion: str, bloques: list, confirmar: bool = False,
                         token: str | None = None) -> dict:
        actuales = copy.deepcopy(self.bloques[posicion])

        def aplicar():
            self.bloques[posicion] = copy.deepcopy(bloques)
            return {"modo": "aplicado", "posicion": posicion, "bloques": len(bloques), "html_conservados": 0,
                    "link_panel": "https://impultienda.ar/panel/checkout"}
        return self._dos_pasos("bloques_checkout", {"store_id": store_id, "posicion": posicion, "bloques": bloques,
                                                    "confirmar": confirmar, "token": token}, aplicar,
                               {"actuales": actuales, "nuevos": bloques})

    def crear_producto(self, store_id: str, nombre: str, tipo: str, precio: float | None = None, **resto) -> dict:
        p = {"id": self._nuevo_id(), "origen": "ebook_ia", "titulo": nombre, "tipo": tipo, "precio": precio,
             "precio_original": None, "moneda": None, "descripcion": "", "activo": True,
             "solo_post_compra": bool(resto.get("solo_post_compra")), "suscripcion": False,
             "estado_generacion": "draft", "creado": "2026-11-17"}
        self.productos.append(p)
        return {"producto": {"id": p["id"], "nombre": nombre, "tipo": tipo, "precio": precio, "moneda": "USD"},
                "proximo_paso": "cargar el entregable"}

    def crear_funnel_postcompra(self, store_id: str, nombre: str, modo: str = "siempre", confirmar: bool = False,
                                token: str | None = None, **resto) -> dict:
        def aplicar():
            fid = self._nuevo_id()
            ofertas = [o for p in self.productos if p.get("solo_post_compra") for o in self._ofertas(p["id"], "15%")]
            self.funnels.append({"funnel_id": fid, "nombre": nombre, "ofertas": ofertas})
            return {"modo": "aplicado", "funnel": {"funnel_id": fid, "nombre": nombre}, "activo": True}
        return self._dos_pasos("crear_funnel_postcompra", {"store_id": store_id, "nombre": nombre, "modo": modo,
                                                           "confirmar": confirmar, "token": token}, aplicar)

    def agregar_oferta_postcompra(self, store_id: str, item_id: str, funnel_id: str | None = None) -> dict:
        f = self.funnels[0]
        f["ofertas"] += self._ofertas(item_id, "20%")
        return {"funnel": {"funnel_id": f["funnel_id"]}, "agregado": item_id, "link_panel": "https://x.example/u"}

    def _ofertas(self, item_id: str, descuento: str) -> list[dict]:
        """Como el funnel real: el upsell con su descuento por defecto y un downsell de recuperación (40 %, R-c)
        del mismo producto."""
        return [{"oferta_id": self._nuevo_id(), "item_id": item_id, "tipo": tipo, "descuento": d}
                for tipo, d in (("upsell", descuento), ("downsell", "40%"))]

    def modificar_oferta_postcompra(self, store_id: str, item_id: str, descuento_pct: float | None = None,
                                    precio_final: float | None = None, aplicar_a: str = "upsell",
                                    funnel_id: str | None = None) -> dict:
        tipos = ("upsell", "downsell") if aplicar_a == "ambas" else (aplicar_a,)
        ofertas = [o for f in self.funnels for o in f["ofertas"] if o["item_id"] == item_id and o["tipo"] in tipos]
        if not ofertas or descuento_pct is None:
            return {"error": "ese producto no está en el funnel"}
        antes = ofertas[0]["descuento"]
        for o in ofertas:
            o["descuento"] = f"{descuento_pct:g}%"
        p = self._producto(item_id)
        return {"producto": {"id": item_id, "titulo": p["titulo"]}, "ofertas_actualizadas": len(ofertas),
                "antes": antes, "descuento": ofertas[0]["descuento"],
                "precio_que_ve_el_comprador": f"{p['precio'] * (1 - descuento_pct / 100):.2f} USD"}

    def guardar_html_postcompra(self, store_id: str, oferta_id: str, html: str, confirmar: bool = False,
                                token: str | None = None) -> dict:
        def aplicar():
            self.html.setdefault(oferta_id, {})["html"] = html
            return {"modo": "aplicado", "link_panel": "https://impultienda.ar/panel/upsells"}
        return self._dos_pasos("guardar_html_postcompra", {"store_id": store_id, "oferta_id": oferta_id,
                                                           "html": html, "confirmar": confirmar, "token": token},
                               aplicar)

    def alternar_html_postcompra(self, store_id: str, oferta_id: str, activo: bool, confirmar: bool = False,
                                 token: str | None = None) -> dict:
        def aplicar():
            self.html.setdefault(oferta_id, {})["activo"] = activo
            return {"modo": "aplicado", "activo": activo, "link_panel": "https://impultienda.ar/panel/upsells"}
        return self._dos_pasos("alternar_html_postcompra", {"store_id": store_id, "oferta_id": oferta_id,
                                                            "activo": activo, "confirmar": confirmar,
                                                            "token": token}, aplicar)

    def link_subida_recursos(self, store_id: str) -> dict:
        return {"link": "https://impultienda.ar/subir/c0d1g0s3cr3t0l4rg0abcdef123456", "vence": "30 min",
                "max_archivos": 50, "codigo": "c0d1g0s3cr3t0l4rg0abcdef123456",
                "api": "https://impultienda.ar/api/recursos"}
