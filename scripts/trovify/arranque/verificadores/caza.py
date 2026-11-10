"""Paso 02: caza sin cuentas.

Contrato con el plan 07 (`/trovify:cazar --modo nicho`, que aún no existe): cada ficha
`wiki/ofertas/<id>.md` lleva en su frontmatter

    paises:
      <XX>:
        link_biblioteca: https://www.facebook.com/ads/library/?...

Basta una ficha con un `link_biblioteca` así para dar el paso por verificado.
"""

from pathlib import Path

from trovify.arranque.estado import ResultadoVerificacion
from trovify.arranque.verificadores import verificador
from trovify.vault.frontmatter import leer
from trovify.vault.rutas import vault_root

PREFIJO = "https://www.facebook.com/ads/library/"


def _enlace(ficha: Path) -> str | None:
    try:
        meta, _ = leer(ficha)
    except Exception:  # noqa: BLE001  # una ficha ilegible se salta, no rompe la verificación
        return None
    paises = meta.get("paises") if isinstance(meta, dict) else None
    if not isinstance(paises, dict):
        return None
    for datos in paises.values():
        link = datos.get("link_biblioteca") if isinstance(datos, dict) else None
        if isinstance(link, str) and link.startswith(PREFIJO):
            return link
    return None


@verificador("02")
def verificar_caza(vault: Path | None = None) -> ResultadoVerificacion:
    vault = vault_root() if vault is None else Path(vault)
    for ficha in sorted((vault / "wiki" / "ofertas").glob("*.md")):
        link = _enlace(ficha)
        if link:
            rel = ficha.relative_to(vault).as_posix()
            return ResultadoVerificacion(True, [rel, link], "hay una oferta con enlace reproducible en la Biblioteca de anuncios",
                                         [], {"oferta": ficha.stem}, [f"✓ {rel}"])
    motivo = "ninguna ficha de wiki/ofertas/ tiene un enlace reproducible a la Biblioteca de anuncios"
    return ResultadoVerificacion(
        False, [], motivo,
        ["corre `/trovify:cazar --modo nicho` (esa skill llega con el plan 07; hasta entonces este paso no puede verificarse)"],
        {}, [f"✗ {motivo}"],
    )
