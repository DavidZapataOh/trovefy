"""Pasos 10 (Whop) y 10b (Hotmart, respaldo): dónde y cómo se cobra.

Paso 10: antes de pedirte el KYC se mide en la documentación pública de Whop si paga a Colombia
(`medir_pago_a_co`, sin navegador). Si la lista de países excluye claramente a Colombia, devuelve ok=False y recomienda el 10b; el paso 10 solo
queda `bloqueado` cuando el usuario lo confirma y lo marca. Después se lee el panel de Whop (perfil «whop») y la pantalla de
pasarelas de Impultienda (perfil «impultienda»), con los mapas de `templates/`.
Paso 10b: producto de prueba y cuenta bancaria colombiana para el retiro de HotPay Internacional
(perfil «hotmart»). Segundo respaldo (Lemon Squeezy): solo en la guía.
Mientras un mapa tenga `capturado: null` el resultado es «no medido»: nunca se certifica con un mapa supuesto.
"""

import re
import urllib.request
from collections.abc import Callable
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from trovefy.arranque.estado import ResultadoVerificacion
from trovefy.arranque.verificadores import verificador
from trovefy.arranque.verificadores.base import (
    aviso_confirmacion,
    guardar_evidencia,
    huella_mapa,
    lector_de_mapa,
    mapa_confirmado,
    registrar_lector,
)
from trovefy.arranque.verificadores.impultienda import normalizar_pasarelas
from trovefy.arranque.verificadores.meta_ids import capturar_por_defecto, no_medido
from trovefy.arranque.verificadores.pantallas import (
    campos_de,
    capturar_pantallas,
    desactualizado,
    provisional_de,
)
from trovefy.mapa import FirmaAusente, MapaInvalido, cargar
from trovefy.vault.escritura import ZONA_NEGOCIO
from trovefy.vault.rutas import vault_root

RAIZ = Path(__file__).resolve().parents[4]
URL_HOTMART_BANCO = "https://help.hotmart.com/es/article/23867226765709/"
URL_DOCS_WHOP = "https://docs.whop.com/manage-your-business/manage-payouts/set-up-payouts"
# Países que la lista real incluye: si no están, la página cambió y no se concluye nada de ella.
_CONTROL = {"Argentina", "Brazil", "Chile", "Mexico", "Peru", "Spain", "Germany", "Canada", "Australia", "France"}


def _bajar(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "trovefy"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(5_000_000).decode("utf-8", errors="replace")


_CONTROL_MIN = {c.casefold() for c in _CONTROL}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr", "path", "use", "circle", "rect"}
_TITULO = re.compile(r"h[1-6]")


class _Nodo:
    __slots__ = ("hijos", "tag")

    def __init__(self, tag: str):
        self.tag = tag
        self.hijos: list = []

    def texto(self) -> str:
        partes, pila = [], [self]
        while pila:
            x = pila.pop()
            if isinstance(x, str):
                partes.append(x)
            else:
                pila.extend(reversed(x.hijos))
        return re.sub(r"\s+", " ", "".join(partes)).strip()

    def elementos(self) -> list["_Nodo"]:
        return [h for h in self.hijos if isinstance(h, _Nodo)]


class _Arbol(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raiz = _Nodo("#raiz")
        self.pila = [self.raiz]

    def handle_starttag(self, tag, attrs):
        n = _Nodo(tag)
        self.pila[-1].hijos.append(n)
        if tag not in _VOID:
            self.pila.append(n)

    def handle_startendtag(self, tag, attrs):
        self.pila[-1].hijos.append(_Nodo(tag))

    def handle_endtag(self, tag):
        for i in range(len(self.pila) - 1, 0, -1):
            if self.pila[i].tag == tag:
                del self.pila[i:]
                return

    def handle_data(self, data):
        if self.pila[-1].tag not in ("script", "style"):
            self.pila[-1].hijos.append(data)


def _en_orden(raiz: _Nodo) -> list[tuple[_Nodo, int]]:
    """Recorrido en orden del documento: (nodo, índice donde termina su subárbol)."""
    salida: list[list] = []

    def visitar(n: _Nodo):
        pila = [(n, iter(n.elementos()), len(salida))]
        salida.append([n, 0])
        while pila:
            _, it, i = pila[-1]
            hijo = next(it, None)
            if hijo is None:
                salida[i][1] = len(salida)
                pila.pop()
            else:
                pila.append((hijo, iter(hijo.elementos()), len(salida)))
                salida.append([hijo, 0])

    visitar(raiz)
    return [(n, f) for n, f in salida]


def _nombre(texto: str) -> str:
    """Nombre del país de un elemento de lista: lo anterior a « — », « – », « - », «:» o «(»."""
    return re.split(r" [—–-] |:|\(", texto.casefold(), maxsplit=1)[0].strip()


def _elementos_de_lista(n: _Nodo) -> list[str] | None:
    """Elementos de un contenedor de lista, o None si no lo es (ul/ol: li; table: primera celda; div: hijos hoja)."""
    if n.tag in ("ul", "ol"):
        return [_nombre(li.texto()) for li in n.elementos() if li.tag == "li"]
    if n.tag == "table":
        filas, pila = [], [n]
        while pila:
            x = pila.pop()
            if x.tag == "tr":
                celdas = [c for c in x.elementos() if c.tag in ("td", "th")]
                if celdas:
                    filas.append(_nombre(celdas[0].texto()))
            else:
                pila.extend(reversed(x.elementos()))
        return filas
    if n.tag == "div":
        hijos = n.elementos()
        if len(hijos) >= 4 and all(not any(d.tag in ("div", "ul", "ol", "table") or _TITULO.fullmatch(d.tag) for d in _descendientes(h)) for h in hijos):
            return [_nombre(h.texto()) for h in hijos]
    return None


def _descendientes(n: _Nodo):
    pila = list(n.elementos())
    while pila:
        x = pila.pop()
        yield x
        pila.extend(x.elementos())


def _listas_bajo(orden, patron: re.Pattern[str]) -> list[list[str]]:
    """Para cada encabezado cuyo texto casa con `patron`: la primera lista que le sigue, antes del siguiente
    encabezado del mismo nivel o superior."""
    salida = []
    for i, (n, fin) in enumerate(orden):
        if not _TITULO.fullmatch(n.tag) or not patron.search(n.texto()):
            continue
        for m, _ in orden[fin:]:
            if _TITULO.fullmatch(m.tag) and int(m.tag[1]) <= int(n.tag[1]):
                break
            items = _elementos_de_lista(m)
            if items is not None:
                salida.append(items)
                break
    return salida


_SOPORTADOS = re.compile(r"(?i)(?<![a-z])(?<!not )supported countries")
_EXCLUIDOS = re.compile(r"(?i)(unsupported|not supported|restricted|sanctioned|excluded) countries")


def medir_pago_a_co(fetch: Callable[[str], str] | None = None) -> bool | None:
    """¿Lista la documentación pública de Whop a Colombia entre los países de pago?

    Se lee la estructura HTML: el encabezado «Supported countries» y la primera lista que le sigue (ul/ol, tabla o
    una cuadrícula de elementos hoja, que es lo que usa la página real); lo que quede fuera de esa lista se ignora.
    True si la lista se reconoce (>= 4 países de control) y tiene a Colombia y ningún encabezado de excluidos/
    restringidos la lista; False si se reconoce y no la tiene; None si no hay encabezado, lista o no se reconoce.
    """
    try:
        pagina = (fetch or _bajar)(URL_DOCS_WHOP)
        arbol = _Arbol()
        arbol.feed(pagina)
        arbol.close()
    except Exception:  # noqa: BLE001  red, TLS o formato: no se concluye nada
        return None
    orden = _en_orden(arbol.raiz)
    reconocidas = [items for items in _listas_bajo(orden, _SOPORTADOS) if len(set(items) & _CONTROL_MIN) >= 4]
    if not reconocidas:
        return None
    if any("colombia" in items for items in _listas_bajo(orden, _EXCLUIDOS)):
        return None
    return any("colombia" in items for items in reconocidas)


def evaluar_whop(pago_a_co: bool | None, kyc: str | None, conectado_en_impultienda: bool | None) -> ResultadoVerificacion:
    def r(ok, motivo, arreglos):
        return ResultadoVerificacion(ok, [], motivo, arreglos, {}, [("✓ " if ok else "✗ " if ok is False else "? ") + motivo])

    if pago_a_co is False:
        return r(False, "Whop no paga a Colombia según su documentación pública", ["seguir con el paso 10b (Hotmart)"])
    if pago_a_co is None or kyc is None or conectado_en_impultienda is None:
        return r(None, "no medido: falta saber si Whop paga a Colombia, el estado del KYC o la conexión con Impultienda", [])
    if kyc in ("pendiente", "rechazado"):
        return r(False, f"la verificación de identidad (KYC) de Whop está {kyc}", ["completa o espera el KYC en Whop (Dashboard > Balances)"])
    if kyc != "aprobado":
        return r(None, "no medido: no se entiende el estado del KYC de Whop", [])
    if not conectado_en_impultienda:
        return r(False, "Whop no está conectado en Impultienda", ["conecta Whop en Impultienda (Configuraciones > Pasarelas de pago)"])
    return r(True, "Whop paga a Colombia, el KYC está aprobado y Whop está conectado en Impultienda", [])


def evaluar_hotmart(producto_prueba: bool | None, retiro_registrado: bool | None) -> ResultadoVerificacion:
    def r(ok, motivo, arreglos):
        return ResultadoVerificacion(ok, [], motivo, arreglos, {}, [("✓ " if ok else "✗ " if ok is False else "? ") + motivo])

    if producto_prueba is None or retiro_registrado is None:
        return r(None, "no medido: no se pudo leer el producto de prueba o la cuenta de retiro de Hotmart", [])
    arreglos = []
    if not producto_prueba:
        arreglos.append("crea un producto de prueba en Hotmart (menú Productos)")
    if not retiro_registrado:
        arreglos.append(
            "registra tu cuenta bancaria colombiana en Mi cuenta > Datos financieros > Nueva cuenta "
            "(Hotmart solo muestra el formulario después de tu primera venta)"
        )
    if arreglos:
        faltan = [m for m, f in (("producto de prueba", producto_prueba), ("cuenta de retiro", retiro_registrado)) if not f]
        return r(False, f"falta en Hotmart: {' y '.join(faltan)}", arreglos)
    return r(True, "producto de prueba creado y retiro HotPay Internacional a banco colombiano registrado", [])


def _kyc(texto: str | None) -> str | None:
    if texto is None:
        return None
    t = texto.strip().lower()
    if t in ("verified", "approved", "aprobado", "verificado", "verificada"):
        return "aprobado"
    if t in ("pending", "in review", "under review", "pendiente", "en revisión", "en análisis"):
        return "pendiente"
    if t in ("rejected", "declined", "rechazado"):
        return "rechazado"
    return t


def _mapa(ruta_relativa: str, dado: dict | None) -> dict:
    return dado if dado is not None else cargar(RAIZ / ruta_relativa)


def verificar_whop(
    vault: Path | None = None,
    capturar: Callable | None = None,
    fetch: Callable[[str], str] | None = None,
    mapa: dict | None = None,
    mapa_impultienda: dict | None = None,
) -> ResultadoVerificacion:
    vault = vault_root() if vault is None else Path(vault)
    pago = medir_pago_a_co(fetch)
    nota_pago = guardar_evidencia(
        vault, "10", "pago-a-co",
        {"pago_a_co": {True: "si", False: "no", None: "no medido"}[pago], "fuente": URL_DOCS_WHOP, "fecha": f"{datetime.now(ZONA_NEGOCIO):%Y-%m-%d}"},
        provisional=pago is None,  # sin medida no hay evidencia
    )
    if pago is False:
        # Solo documentación: no se bloquea el paso; lo marca el usuario (o la skill tras confirmarlo con él).
        r = evaluar_whop(False, None, None)
        r.arreglos.append('tras confirmarlo contigo: `trovefy arranque bloqueado 10 --motivo "Whop no paga a Colombia"`')
        r.lineas += [f"  fuente: {URL_DOCS_WHOP}", f"  medida guardada: {nota_pago}"]
        return r
    if pago is None:
        m = f"no medido: no se pudo leer la lista pública de países de pago de Whop ({URL_DOCS_WHOP})"
        return no_medido(m)
    linea_co = f"✓ la documentación pública de Whop lista a Colombia ({URL_DOCS_WHOP})"

    def con_co(r: ResultadoVerificacion) -> ResultadoVerificacion:
        """Lo medido en la documentación se muestra también cuando el panel no se puede leer."""
        r.lineas.insert(0, linea_co)
        return r

    try:
        mapa = mapa_confirmado(vault, "10", _mapa("templates/whop/mapa.yaml", mapa))
        mapa_imp = mapa_confirmado(vault, "09", _mapa("templates/impultienda/mapa.yaml", mapa_impultienda))
    except MapaInvalido as exc:
        return con_co(no_medido(f"no medido: {exc}"))
    cap_fn = capturar or capturar_por_defecto
    whop, motivo = capturar_pantallas("whop", mapa, ["balances"], cap_fn)
    if motivo:
        return con_co(no_medido(motivo))
    if mapa["capturado"] is None:
        prov = con_co(provisional_de(vault, "10", whop, aviso_confirmacion(vault, "10", mapa)))
        prov.lineas.append(f"  medida guardada: {nota_pago}")
        return prov
    imp, motivo = capturar_pantallas("impultienda", mapa_imp, ["pasarelas"], cap_fn)
    if motivo:
        return con_co(no_medido(motivo))
    if mapa_imp["capturado"] is None:
        return con_co(provisional_de(vault, "10", {**whop, "pasarelas_impultienda": imp["pasarelas"]}))
    try:
        kyc = _kyc(campos_de(mapa, whop)["balances"]["kyc"])
        conectadas = campos_de(mapa_imp, imp)["pasarelas"]["pasarelas"]
    except FirmaAusente as exc:
        return con_co(desactualizado(exc.pantalla))
    conectado = None if conectadas is None else "whop" in normalizar_pasarelas(conectadas).split(",")
    r = evaluar_whop(True, kyc, conectado)
    if r.ok is not True:
        return con_co(r)
    datos = {"pago_a_co": "si", "kyc": "aprobado", "conectado_en_impultienda": "si"}
    evidencia = [nota_pago]
    if whop["balances"][1]:
        evidencia.append(guardar_evidencia(vault, "10", "captura-whop", whop["balances"][1]))
    evidencia.append(guardar_evidencia(vault, "10", "datos", {"fuente_pago_a_co": URL_DOCS_WHOP, "mapa_capturado": mapa["capturado"], **datos}))
    return ResultadoVerificacion(True, evidencia, r.motivo, [], datos, [linea_co, *r.lineas])


def _entero(texto: str | None) -> int | None:
    return int(texto) if texto is not None and texto.isdigit() else None


def _retiro(campos: dict) -> bool | None:
    cuentas, pais, estado = _entero(campos.get("cuentas")), campos.get("pais"), campos.get("estado_cuenta")
    if cuentas is None:
        return None
    if cuentas == 0:
        return False
    if pais is None or estado is None:
        return None
    return pais.strip().lower() == "colombia" and estado.strip().lower() in ("aprobada", "aprobado", "approved")


def verificar_hotmart(
    vault: Path | None = None, capturar: Callable | None = None, mapa: dict | None = None
) -> ResultadoVerificacion:
    vault = vault_root() if vault is None else Path(vault)
    try:
        mapa = mapa_confirmado(vault, "10b", _mapa("templates/hotmart/mapa.yaml", mapa))
    except MapaInvalido as exc:
        return no_medido(f"no medido: {exc}")
    nombres = ["productos", "datos_financieros"]
    capturas, motivo = capturar_pantallas("hotmart", mapa, nombres, capturar or capturar_por_defecto)
    if motivo:
        return no_medido(motivo)
    if mapa["capturado"] is None:
        return provisional_de(vault, "10b", capturas, aviso_confirmacion(vault, "10b", mapa))
    try:
        campos = campos_de(mapa, capturas)
    except FirmaAusente as exc:
        return desactualizado(exc.pantalla)
    n = _entero(campos["productos"].get("productos"))
    if n is not None and n >= 1 and _entero(campos["datos_financieros"].get("cuentas")) == 0:
        m = f"pendiente de primera venta: Hotmart solo muestra el formulario bancario tras la primera venta ({URL_HOTMART_BANCO})"
        return ResultadoVerificacion(None, [], m, ["haz tu primera venta y registra entonces tu cuenta bancaria colombiana"], {}, [f"? {m}"])
    r = evaluar_hotmart(None if n is None else n >= 1, _retiro(campos["datos_financieros"]))
    if r.ok is not True:
        return r
    evidencia = [guardar_evidencia(vault, "10b", f"captura-{k}", png) for k, (_, png) in capturas.items() if png]
    datos = {"producto_prueba": "si", "retiro_registrado": "si"}
    evidencia.append(guardar_evidencia(vault, "10b", "datos", {"mapa_capturado": mapa["capturado"], **datos}))
    return ResultadoVerificacion(True, evidencia, r.motivo, [], datos, r.lineas)


registrar_lector(
    "10", lector_de_mapa(lambda: _mapa("templates/whop/mapa.yaml", None)),
    huella=lambda: huella_mapa(_mapa("templates/whop/mapa.yaml", None)),
)
registrar_lector(
    "10b",
    lector_de_mapa(lambda: _mapa("templates/hotmart/mapa.yaml", None)),
    ("productos.firma", "productos.productos", "datos_financieros.firma", "datos_financieros.cuentas"),
    huella=lambda: huella_mapa(_mapa("templates/hotmart/mapa.yaml", None)),
)


@verificador("10")
def _v10(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_whop(vault)


@verificador("10b")
def _v10b(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_hotmart(vault)
