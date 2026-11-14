"""Umbrales `referencia.*` y su regla R-013; migración de vaults creados antes de /ver-anuncios."""

from dataclasses import dataclass
from pathlib import Path

from trovefy.config.umbrales import UmbralFaltante, cargar
from trovefy.vault.escritura import escribir_atomico
from trovefy.vault.reglas import _ID, _paginas, _vigente, nueva_regla, planear_regla

FECHA = "2026-11-13"
TITULO = "Ranking de anuncios de referencia"
_FUENTE_RANKING = "cuongbigdigi rank.js:23-30; diseño §4.4"
_FUENTE_TOP = "Diseño §4.4 (--top 10)"
_FUENTE_RETENCION = "Diseño §4.4; contrato 4"

# clave -> (valor, fuente)
UMBRALES: dict[str, tuple[int, str]] = {
    "referencia.ranking.min_dias": (7, _FUENTE_RANKING),
    "referencia.ranking.max_variantes": (30, _FUENTE_RANKING),
    "referencia.ranking.peso_variantes": (2, _FUENTE_RANKING),
    "referencia.en_test.min_variantes": (3, _FUENTE_RANKING),
    "referencia.top": (10, _FUENTE_TOP),
    "referencia.medios.retencion_dias": (30, _FUENTE_RETENCION),
}
CLAVES = tuple(UMBRALES)
MENSAJE_FALTAN = "faltan umbrales referencia.*: ejecuta `trovefy ver-anuncios preparar`"

_TEXTO = {
    "regla": (
        "Un anuncio de referencia entra en el ranking tras `referencia.ranking.min_dias` (7) días "
        "activo; las variantes cuentan hasta `referencia.ranking.max_variantes` (30), con peso "
        "`referencia.ranking.peso_variantes` (2). Con al menos `referencia.en_test.min_variantes` (3) "
        "variantes se considera en test. El informe muestra los `referencia.top` (10) primeros y los "
        "vídeos y lotes del MCP se borran a los `referencia.medios.retencion_dias` (30) días."
    ),
    "porque": (
        "Un anuncio que sigue activo tras una semana y que su dueño sigue variando es la señal más "
        "barata de que vende. El material ajeno no es nuestro: se analiza y caduca, no se archiva."
    ),
    "como": (
        "`/ver-anuncios` lee estos umbrales de `config/umbrales.yaml`, ordena, enseña el top y "
        "limpia ~/.cache/trovefy/referencia/ pasada la retención. Nada ajeno se guarda en el cerebro."
    ),
    "fuente": "Diseño §4.4; cuongbigdigi rank.js:23-30; contrato 4.",
}


@dataclass(frozen=True)
class UmbralesReferencia:
    min_dias: int
    max_variantes: int
    peso_variantes: int
    en_test_min_variantes: int
    top: int
    retencion_dias: int


def cargar_umbrales_referencia(vault: Path) -> UmbralesReferencia:
    umbrales = cargar(Path(vault) / "config" / "umbrales.yaml")
    if any(c not in umbrales for c in CLAVES):
        raise UmbralFaltante(MENSAJE_FALTAN)
    return UmbralesReferencia(*(int(umbrales[c].valor) for c in CLAVES))


def _bloques(rid: str) -> str:
    return "".join(
        f'\n{clave}:\n  valor: {valor}\n  fuente: "{fuente}"\n  fecha: "{FECHA}"\n'
        f'  gana_sobre: "—"\n  regla: {rid}\n'
        for clave, (valor, fuente) in UMBRALES.items()
    )


def _ya_preparado(vault: Path) -> bool:
    pedidas = set(CLAVES)
    return any(_vigente(meta) and pedidas <= set(meta.get("umbrales") or [])
               for _rid, _p, meta in _paginas(vault))


def preparar_vault(vault: Path) -> list[str]:
    """Añade los umbrales `referencia.*` y la regla que los cita a un vault anterior."""
    vault = Path(vault)
    if _ya_preparado(vault):
        return []
    numeros = [int(m.group(1)) for rid, _p, _m in _paginas(vault) if (m := _ID.fullmatch(rid))]
    rid = f"R-{max(numeros, default=0) + 1:03d}"
    ruta = vault / "config" / "umbrales.yaml"
    original = ruta.read_text(encoding="utf-8")
    if original and not original.endswith("\n"):
        original += "\n"
    ampliado = original + _bloques(rid)
    valores = {c: float(v) for c, (v, _f) in UMBRALES.items()}
    argumentos = (vault, TITULO, _TEXTO["regla"], _TEXTO["porque"], _TEXTO["como"], _TEXTO["fuente"])
    escribir_atomico(ruta, ampliado)
    try:
        plan = planear_regla(*argumentos, umbrales=valores, fecha=FECHA)
        if plan.id != rid:
            raise ValueError(f"La regla nueva sería {plan.id}, no {rid}; no se ha cambiado nada")
        nueva_regla(*argumentos, umbrales=valores, fecha=FECHA)
    except BaseException:
        escribir_atomico(ruta, original)
        raise
    # nueva_regla reserializa el YAML entero; se deja tal cual el original con los bloques añadidos
    escribir_atomico(ruta, ampliado)
    return [f"Regla nueva: {rid} ({TITULO})",
            f"Umbrales añadidos a config/umbrales.yaml: {', '.join(CLAVES)}"]
