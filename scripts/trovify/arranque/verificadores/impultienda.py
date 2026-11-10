"""Paso 09: Impultienda con plan activo (Free basta) y al menos una tienda.

Lee las pantallas `plan`, `tiendas` y `pasarelas` de `templates/impultienda/mapa.yaml` con el perfil de
navegador «impultienda». Solo lectura: si cambia una firma, devuelve «no medido» sin hacer clics.
Mientras el mapa tenga `capturado: null` (construido desde la página pública, no desde tu pantalla real)
el resultado es siempre «no medido» y la captura queda como evidencia provisional.
"""

from collections.abc import Callable
from pathlib import Path

from trovify.arranque.estado import ResultadoVerificacion
from trovify.arranque.verificadores import verificador
from trovify.arranque.verificadores.base import (
    aviso_confirmacion,
    guardar_evidencia,
    huella_mapa,
    lector_de_mapa,
    mapa_confirmado,
    registrar_lector,
)
from trovify.arranque.verificadores.meta_ids import capturar_por_defecto, no_medido
from trovify.arranque.verificadores.pantallas import (
    campos_de,
    capturar_pantallas,
    desactualizado,
    provisional_de,
)
from trovify.mapa import FirmaAusente, MapaInvalido, cargar
from trovify.vault.rutas import vault_root

RAIZ = Path(__file__).resolve().parents[4]
RUTA_MAPA = RAIZ / "templates/impultienda/mapa.yaml"
PANTALLAS = ["plan", "tiendas", "pasarelas"]
COMANDO_ABRIR = "trovify navegador abrir impultienda https://app.impultienda.ar/"


def normalizar_pasarelas(texto: str) -> str:
    """«Whop, Stripe» → «whop,stripe»; «Ninguna» → «»."""
    nombres = [n.strip().lower() for n in texto.split(",")]
    return ",".join(n for n in nombres if n and n not in ("ninguna", "ninguno", "—", "-"))


def _falla(motivo: str, arreglo: str) -> ResultadoVerificacion:
    return ResultadoVerificacion(False, [], motivo, [arreglo], {}, [f"✗ {motivo}"])


def evaluar_impultienda(plan: dict, tiendas: dict, pasarelas: dict) -> ResultadoVerificacion:
    """`ok=True` si hay plan activo y al menos una tienda; un campo ilegible es «no medido»."""
    nombre, estado, n, conectadas = plan.get("plan"), plan.get("estado"), tiendas.get("tiendas"), pasarelas.get("pasarelas")
    for campo, valor in (("plan", nombre), ("estado del plan", estado), ("número de tiendas", n), ("pasarelas", conectadas)):
        if valor is None:
            return no_medido(f"no medido: no se pudo leer el campo «{campo}» de Impultienda")
    if estado.lower() not in ("activo", "activa", "active"):
        return _falla(f"el plan de Impultienda no está activo ({estado})", "reactiva o elige el plan Free en Impultienda y vuelve a verificar")
    if not n.isdigit():
        return no_medido("no medido: el número de tiendas de Impultienda no se entiende")
    if int(n) < 1:
        return _falla("Impultienda no tiene ninguna tienda", "crea tu primera tienda en Impultienda (idioma del primer mercado) y vuelve a verificar")
    datos = {"plan": nombre, "tiendas": n, "pasarelas": normalizar_pasarelas(conectadas)}
    return ResultadoVerificacion(True, [], f"plan {nombre} activo con {n} tienda(s)", [], datos, [f"✓ plan {nombre} ({estado}), {n} tienda(s)"])


def verificar_impultienda(
    vault: Path | None = None, capturar: Callable | None = None, mapa: dict | None = None
) -> ResultadoVerificacion:
    vault = vault_root() if vault is None else Path(vault)
    try:
        mapa = cargar(RUTA_MAPA) if mapa is None else mapa
    except MapaInvalido as exc:
        return no_medido(f"no medido: {exc}")
    mapa = mapa_confirmado(vault, "09", mapa)
    capturas, motivo = capturar_pantallas("impultienda", mapa, PANTALLAS, capturar or capturar_por_defecto)
    if motivo:
        return no_medido(motivo)
    if mapa["capturado"] is None:
        return provisional_de(vault, "09", capturas, aviso_confirmacion(vault, "09", mapa))
    try:
        campos = campos_de(mapa, capturas)
    except FirmaAusente as exc:
        return desactualizado(exc.pantalla)
    r = evaluar_impultienda(campos["plan"], campos["tiendas"], campos["pasarelas"])
    if r.ok is not True:
        return r
    evidencia = [guardar_evidencia(vault, "09", f"captura-{n}", png) for n, (_, png) in capturas.items() if png]
    evidencia.append(guardar_evidencia(vault, "09", "datos", {"mapa_capturado": mapa["capturado"], **r.datos}))
    return ResultadoVerificacion(True, evidencia, r.motivo, [], r.datos, r.lineas)


registrar_lector("09", lector_de_mapa(lambda: cargar(RUTA_MAPA)), huella=lambda: huella_mapa(cargar(RUTA_MAPA)))


@verificador("09")
def _v09(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_impultienda(vault)
