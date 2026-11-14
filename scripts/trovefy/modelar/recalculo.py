"""``trovefy modelar recalcular``: rehace solo la economía de ``ESCALERA.md`` (resolución 10 del contrato).

Las comisiones se conocen tras el paso 10 de ``/arranque``, cuando el país ya puede estar en ``modelado`` o
más allá (``escribir`` se niega desde ``producido``). Esto relee la escalera escrita (precios, ``activo``,
piezas y avisos de la escalera), recalcula la economía con ``trovefy.modelar.salida.economia_pais``, la
configuración de hoy y el cambio del BCE del día, y reescribe ``ESCALERA.md`` versionando la anterior. No
toca precios, ``activo``, ``OFERTA.md``, la aprobación, ``PRODUCTO.md`` ni el estado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import yaml

from trovefy.economia.calculo import AVISO_BE_BAJO
from trovefy.economia.config import (
    ConfigEconomia,
    admite_downsell,
    costes_de,
    upsells_permitidos,
)
from trovefy.economia.escalera import (
    PASOS,
    EscaleraPais,
    PasoEscalera,
    _activo_downsell,
    _activo_upsell,
)
from trovefy.economia.modelo import Cifra
from trovefy.fx import Cambio
from trovefy.modelar.esquema import PiezaEscalera
from trovefy.modelar.salida import _version_libre, economia_pais, render_escalera
from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter
from trovefy.vault.escritura import anadir_log, escribir_atomico
from trovefy.vault.producto import (
    ESTADOS_FASE2,
    EstadoInesperado,
    estado_pais,
    pais_elegido,
    ruta_producto,
)

ESTADOS_RECALCULO = ESTADOS_FASE2[ESTADOS_FASE2.index("modelado"):]
AVISO_ACTIVOS = ("con la config actual cambiaría qué pasos van activos: rehaz /modelar si el país sigue en "
                 "modelado")
# Avisos que pone la economía (trovefy.economia.calculo); el resto de `avisos` es de la escalera y se conserva.
_PREFIJO_AVISO_AOV = "AOV estimado "


def _es_aviso_economia(aviso: str) -> bool:
    return aviso == AVISO_BE_BAJO or aviso.startswith(_PREFIJO_AVISO_AOV)


def _dec(x: object) -> Decimal:
    return Decimal(str(x))


def _escalera_de(pais: str, bloque: dict) -> EscaleraPais:
    """La ``EscaleraPais`` tal como quedó escrita en el frontmatter (sin recalcular precios)."""
    moneda = bloque.get("moneda") or ""
    front_eur = (Cifra(_dec(bloque["front_eur"])) if bloque.get("front_eur") is not None
                 else Cifra(None, bloque.get("front_eur_motivo") or "no medido: sin front en EUR"))
    avisos = tuple(a for a in bloque.get("avisos") or () if not _es_aviso_economia(a))
    pasos = bloque.get("pasos")
    if pasos is None:
        motivo = bloque.get("pasos_motivo") or "no medido: escalera sin pasos"
        return EscaleraPais(pais, moneda, None, front_eur, bloque.get("fuente_precio") or "", avisos, motivo)
    return EscaleraPais(
        pais, moneda,
        {n: PasoEscalera(n, _dec(pasos[n]["precio"]), moneda, bool(pasos[n]["activo"]), pasos[n].get("motivo_inactivo"))
         for n in PASOS},
        front_eur, bloque.get("fuente_precio") or "", avisos, None,
    )


def _piezas_de(paises: dict) -> tuple[PiezaEscalera, ...]:
    for bloque in paises.values():
        pasos = bloque.get("pasos")
        if pasos:
            return tuple(PiezaEscalera(n, pasos[n]["titulo"], pasos[n]["entregable"]) for n in PASOS
                         if pasos[n].get("titulo") is not None)
    return ()


def _partir(texto: str) -> tuple[dict, str]:
    """Frontmatter y cuerpo de un texto con el formato de ``frontmatter.renderizar``."""
    fin = texto.index("\n---\n", 3)
    return yaml.safe_load(texto[4:fin + 1]) or {}, texto[fin + 5:]


@dataclass(frozen=True)
class Recalculo:
    """Resultado de ``recalcular``: ``version`` es None cuando la economía sale igual (nada escrito);
    ``activos_distintos`` lista los ``<país>.<paso>`` cuyo ``activo`` cambiaría con la config actual."""

    ruta: Path
    version: Path | None
    activos_distintos: tuple[str, ...] = ()


def activos_distintos(escaleras: dict[str, EscaleraPais], config: ConfigEconomia) -> tuple[str, ...]:
    """Pasos cuyo ``activo`` escrito no es el que daría la config actual (no se cambia: solo se avisa)."""
    esperado = {
        "front": True,
        "bump": config.escalera.bump_activo_test1,
        "u1": True,
        "u2": _activo_upsell(2, upsells_permitidos(config))[0],
        "u3": _activo_upsell(3, upsells_permitidos(config))[0],
        "downsell": _activo_downsell(admite_downsell(config))[0],
    }
    return tuple(f"{p}.{n}" for p, e in escaleras.items() if e.pasos
                 for n in PASOS if e.pasos[n].activo != esperado[n])


def _sin_economia_fecha(texto: str) -> tuple[dict, str]:
    meta, cuerpo = _partir(texto)
    meta.pop("economia_fecha", None)
    return meta, cuerpo


def recalcular(vault: Path, p_id: str, config: ConfigEconomia, cambio: Cambio | None, hoy: date,
               ahora: datetime) -> Recalculo:
    """Reescribe la economía de ``ESCALERA.md`` versionando la anterior; devuelve un ``Recalculo``.

    Si el texto nuevo es igual al anterior (sin contar ``economia_fecha``) no escribe nada, ni versión ni
    log (``version`` None). ``EstadoInesperado`` si el país elegido no ha llegado a ``modelado``;
    ``FileNotFoundError`` sin ``ESCALERA.md``. Nada se escribe si algo falla antes de la escritura.
    """
    vault = Path(vault)
    pais, _, _ = pais_elegido(vault, p_id)
    estado = estado_pais(vault, p_id, pais)
    if estado not in ESTADOS_RECALCULO:
        raise EstadoInesperado(f"{pais} está en {estado or 'sin estado'}: recalcular solo trabaja desde modelado; "
                               "antes, usa `trovefy modelar escribir`")
    carpeta = ruta_producto(vault, p_id).parent
    ruta = carpeta / "ESCALERA.md"
    if not ruta.is_file():
        raise FileNotFoundError("falta ESCALERA.md: /modelar")
    anterior = ruta.read_text(encoding="utf-8")
    meta, _ = frontmatter.leer(ruta)
    paises = meta.get("paises")
    if not isinstance(paises, dict) or not paises:
        raise ValueError("ESCALERA.md no trae paises: rehaz /modelar")
    try:
        fecha = date.fromisoformat(str(meta.get("fecha")))
        escaleras = {p: _escalera_de(p, b) for p, b in paises.items()}
        piezas = _piezas_de(paises)
    except (KeyError, TypeError, ValueError, ArithmeticError) as e:
        raise ValueError(f"ESCALERA.md no se puede leer ({type(e).__name__}): rehaz /modelar") from None

    distintos = activos_distintos(escaleras, config)
    economias = {p: economia_pais(e, config, cambio) for p, e in escaleras.items()}
    texto = render_escalera(escaleras, economias, cambio, fecha, producto=meta.get("producto") or p_id,
                            piezas=piezas, costes=costes_de(config))
    nuevo, cuerpo = _partir(texto)
    try:
        igual = _sin_economia_fecha(anterior) == (nuevo, cuerpo)
    except (ValueError, yaml.YAMLError):
        igual = False
    if igual:
        return Recalculo(ruta, None, distintos)
    con_fecha: dict = {}
    for k, v in nuevo.items():
        con_fecha[k] = v
        if k == "fecha":
            con_fecha["economia_fecha"] = hoy.isoformat()
    texto = frontmatter.renderizar(con_fecha, cuerpo)
    patron = buscar_secreto(texto)  # RevisionSecretosNoDisponible: no se escribe nada
    if patron:
        raise ValueError(f"ESCALERA.md: aparece un secreto ({patron}); no se escribe nada")

    version = _version_libre(carpeta / "versiones", "ESCALERA", hoy, set())
    escribir_atomico(version, anterior)
    escribir_atomico(ruta, texto)
    anadir_log(vault, "modelar", f"{p_id} {pais}: economía de la escalera recalculada",
               [ruta.relative_to(vault).as_posix(), version.relative_to(vault).as_posix()], ahora=ahora)
    return Recalculo(ruta, version, distintos)
