"""Pasos 10 (Whop) y 10b (Hotmart, respaldo): dónde y cómo se cobra.

Paso 10: antes de pedirte el KYC se mide en la documentación pública de Whop si paga a Colombia
(`medir_pago_a_co`, sin navegador). Si la lista de países excluye claramente a Colombia, el paso 10 queda
`bloqueado` y el siguiente es el 10b. Después se lee el panel de Whop (perfil «whop») y la pantalla de
pasarelas de Impultienda (perfil «impultienda»), con los mapas de `templates/`.
Paso 10b: producto de prueba y cuenta bancaria colombiana para el retiro de HotPay Internacional
(perfil «hotmart»). Segundo respaldo (Lemon Squeezy): solo en la guía.
Mientras un mapa tenga `capturado: null` el resultado es «no medido»: nunca se certifica con un mapa supuesto.
"""

import html
import re
import urllib.request
from collections.abc import Callable
from pathlib import Path

from trovify.arranque.estado import ResultadoVerificacion, marcar_bloqueado
from trovify.arranque.verificadores import verificador
from trovify.arranque.verificadores.base import guardar_evidencia, resultado_provisional
from trovify.arranque.verificadores.impultienda import normalizar_pasarelas
from trovify.arranque.verificadores.meta_ids import capturar_por_defecto, no_medido
from trovify.arranque.verificadores.pantallas import (
    campos_de,
    capturar_pantallas,
    desactualizado,
)
from trovify.mapa import FirmaAusente, MapaInvalido, cargar
from trovify.vault.rutas import vault_root

RAIZ = Path(__file__).resolve().parents[4]
URL_DOCS_WHOP = "https://docs.whop.com/manage-your-business/manage-payouts/set-up-payouts"
# Países que la lista real incluye: si no están, la página cambió y no se concluye nada de ella.
_CONTROL = {"Argentina", "Brazil", "Chile", "Mexico", "Peru", "Spain", "Germany", "Canada", "Australia", "France"}


def _bajar(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "trovify"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(5_000_000).decode("utf-8", errors="replace")


def medir_pago_a_co(fetch: Callable[[str], str] | None = None) -> bool | None:
    """¿Lista la documentación pública de Whop a Colombia entre los países de pago?

    True si aparece; False solo si la lista se reconoce (varios países de control) y Colombia no está;
    None si la página no se pudo leer o cambió.
    """
    try:
        pagina = (fetch or _bajar)(URL_DOCS_WHOP)
    except Exception:  # noqa: BLE001  red, TLS o formato: no se concluye nada
        return None
    texto = html.unescape(re.sub(r"<[^>]+>", "\n", pagina))
    mejor: set[str] = set()
    for m in re.finditer("Supported countries", texto):
        resto = texto[m.end() : m.end() + 20000]
        resto = resto.split("Note that", 1)[0]
        paises = {ln.strip() for ln in resto.splitlines() if ln.strip()}
        if len(paises & _CONTROL) > len(mejor & _CONTROL) or (not mejor and paises):
            mejor = paises
    if "Colombia" in mejor:
        return True
    return False if len(mejor & _CONTROL) >= 4 else None


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
    if pago is False:
        r = evaluar_whop(False, None, None)
        r.lineas.append(f"  fuente: {URL_DOCS_WHOP}")
        marcar_bloqueado(vault, "10", "Whop no paga a Colombia: sigue con el paso 10b (Hotmart)")
        return r
    if pago is None:
        m = f"no medido: no se pudo leer la lista pública de países de pago de Whop ({URL_DOCS_WHOP})"
        return no_medido(m)
    linea_co = f"✓ la documentación pública de Whop lista a Colombia ({URL_DOCS_WHOP})"
    try:
        mapa = _mapa("templates/whop/mapa.yaml", mapa)
        mapa_imp = _mapa("templates/impultienda/mapa.yaml", mapa_impultienda)
    except MapaInvalido as exc:
        return no_medido(f"no medido: {exc}")
    cap_fn = capturar or capturar_por_defecto
    whop, motivo = capturar_pantallas("whop", mapa, ["balances"], cap_fn)
    if motivo:
        return no_medido(motivo)
    if mapa["capturado"] is None:
        prov = resultado_provisional(vault, "10", *whop["balances"])
        prov.lineas.insert(0, linea_co)
        return prov
    imp, motivo = capturar_pantallas("impultienda", mapa_imp, ["pasarelas"], cap_fn)
    if motivo:
        return no_medido(motivo)
    if mapa_imp["capturado"] is None:
        prov = resultado_provisional(vault, "10", *imp["pasarelas"])
        prov.lineas.insert(0, linea_co)
        return prov
    try:
        kyc = _kyc(campos_de(mapa, whop)["balances"]["kyc"])
        conectadas = campos_de(mapa_imp, imp)["pasarelas"]["pasarelas"]
    except FirmaAusente as exc:
        return desactualizado(exc.pantalla)
    conectado = None if conectadas is None else "whop" in normalizar_pasarelas(conectadas).split(",")
    r = evaluar_whop(True, kyc, conectado)
    if r.ok is not True:
        r.lineas.insert(0, linea_co)
        return r
    datos = {"pago_a_co": "si", "kyc": "aprobado", "conectado_en_impultienda": "si"}
    evidencia = [guardar_evidencia(vault, "10", "captura-whop", whop["balances"][1])] if whop["balances"][1] else []
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
        mapa = _mapa("templates/hotmart/mapa.yaml", mapa)
    except MapaInvalido as exc:
        return no_medido(f"no medido: {exc}")
    nombres = ["productos", "datos_financieros"]
    capturas, motivo = capturar_pantallas("hotmart", mapa, nombres, capturar or capturar_por_defecto)
    if motivo:
        return no_medido(motivo)
    if mapa["capturado"] is None:
        return resultado_provisional(vault, "10b", *capturas["productos"])
    try:
        campos = campos_de(mapa, capturas)
    except FirmaAusente as exc:
        return desactualizado(exc.pantalla)
    n = _entero(campos["productos"].get("productos"))
    r = evaluar_hotmart(None if n is None else n >= 1, _retiro(campos["datos_financieros"]))
    if r.ok is not True:
        return r
    evidencia = [guardar_evidencia(vault, "10b", f"captura-{k}", png) for k, (_, png) in capturas.items() if png]
    datos = {"producto_prueba": "si", "retiro_registrado": "si"}
    evidencia.append(guardar_evidencia(vault, "10b", "datos", {"mapa_capturado": mapa["capturado"], **datos}))
    return ResultadoVerificacion(True, evidencia, r.motivo, [], datos, r.lineas)


@verificador("10")
def _v10(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_whop(vault)


@verificador("10b")
def _v10b(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_hotmart(vault)
