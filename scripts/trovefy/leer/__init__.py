"""`/leer` (plan 23): parte diario e intradía, cortes y surf propuestos como en los vídeos.

**Qué hacen los vídeos:** «Claude lee tus campañas todos los días» y responde con la tabla por conjunto, el número
puesto y el motivo (C1 54:20); apaga a los US$ 3 sin pagos iniciados, con CPC > US$ 0,60 o con menos del 15 % de pagos
iniciados sobre visitas (C1 20:05, C1 54:20); mata la oferta sin ventas a los US$ 25 (C1 1:24:15); surfea ×2 cada 2 h
con ROAS ≥ 2 y ventas nuevas, −50 % con ROAS ≤ 1,75 y todo a la base a las 23:00 (S1 10:27, S2 14:10, S2 14:40).

Claude llama a los MCP (solo lectura) y guarda la respuesta cruda en ``~/.cache/trovefy/leer/``; la CLI
``trovefy leer`` **nunca** llama a un MCP ni a Meta: normaliza las instantáneas, aplica las reglas (funciones puras) y
deposita **propuestas** en el buzón con ``trovefy.aprobaciones.fuentes.depositar``. Toda pausa o cambio de presupuesto
lo ejecuta el ejecutor tras el Aceptar del usuario en Telegram: el método es el de los vídeos, cambia quién pulsa.

Módulos: `economia` (neto y ROAS neto), `modelo` (tipos), `importar` (instantáneas → lectura en USD), `reglas`
(cortes y veredictos), `surf` (×2, −50 % y base), `fiabilidad`, `diagnostico` (R-014), `propuestas` (buzón y
memoria), `estado` (``test → muerto | candidato`` tras la ejecución) y `parte` (Markdown).
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from trovefy.config.umbrales import UmbralFaltante, cargar

SKILL = "/leer"

Umbrales = Mapping[str, Decimal]


def cargar_umbrales(vault: Path) -> dict[str, Decimal]:
    """``config/umbrales.yaml`` del vault como ``Decimal`` (por el texto del float, sin errores binarios)."""
    return {k: Decimal(str(u.valor)) for k, u in cargar(Path(vault) / "config" / "umbrales.yaml").items()}


def umbral(u: Umbrales, clave: str) -> Decimal:
    """El valor del umbral; ``UmbralFaltante`` si el vault no lo tiene (``trovefy leer completar`` lo añade)."""
    if clave not in u:
        raise UmbralFaltante(clave)
    return u[clave]


def usd(centavos: int | None) -> str:
    """Centavos de USD en texto con coma decimal: 2540 → «25,40»; ``None`` → «—»."""
    if centavos is None:
        return "—"
    return f"{Decimal(centavos) / 100:.2f}".replace(".", ",")


def num(d: Decimal | None, decimales: int = 2) -> str:
    if d is None:
        return "—"
    return f"{d:.{decimales}f}".replace(".", ",")
