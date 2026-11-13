"""Registro del ensayo general: compra de prueba y su reembolso (`ledger/ensayo/ensayo-general.yaml`)."""

import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from trovefy.secretos import buscar_secreto
from trovefy.vault.escritura import escribir_atomico

RUTA_ENSAYO = "ledger/ensayo/ensayo-general.yaml"
PASARELAS = ("whop", "hotmart", "impultienda")
_PEDIDO = re.compile(r"[A-Za-z0-9_-]{3,64}")
_MONEDA = re.compile(r"[A-Za-z]{3}")
MAX_IMPORTE = Decimal(10)


def leer_ensayo(vault: Path) -> dict:
    """Contenido del registro; `{}` si no existe. ValueError si es ilegible."""
    ruta = Path(vault) / RUTA_ENSAYO
    if ruta.is_symlink():
        raise ValueError(f"{RUTA_ENSAYO} no puede ser un enlace simbólico")
    if not ruta.exists():
        return {}
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        raise ValueError(f"{RUTA_ENSAYO} no se puede leer") from None
    if not isinstance(datos, dict):
        raise ValueError(f"{RUTA_ENSAYO} no tiene el formato esperado")  # noqa: TRY004
    for clave in ("compras", "reembolsos"):
        if not isinstance(datos.get(clave, []), list) or not all(isinstance(x, dict) for x in datos.get(clave, [])):
            raise ValueError(f"{RUTA_ENSAYO} no tiene el formato esperado")
    return datos


def _guardar(vault: Path, datos: dict) -> None:
    escribir_atomico(Path(vault) / RUTA_ENSAYO, yaml.safe_dump(datos, allow_unicode=True, sort_keys=False))


def _sin_secreto(**campos: str) -> None:
    for nombre, valor in campos.items():
        if buscar_secreto(valor):
            raise ValueError(f"{nombre}: el valor parece un secreto; los secretos no se guardan en el vault")


def _pedido_valido(pedido: str) -> None:
    if not isinstance(pedido, str) or not _PEDIDO.fullmatch(pedido):
        raise ValueError("pedido: usa de 3 a 64 caracteres entre letras, números, «_» y «-»")


def _fecha_valida(fecha: str) -> None:
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha):
            raise ValueError
        date.fromisoformat(fecha)
    except (ValueError, TypeError):
        raise ValueError("fecha: usa el formato AAAA-MM-DD") from None


def registrar_compra(vault: Path, pedido: str, importe: Decimal, moneda: str, pasarela: str, fecha: str) -> dict:
    _pedido_valido(pedido)
    _sin_secreto(pedido=pedido, moneda=str(moneda), pasarela=str(pasarela), fecha=str(fecha))
    try:
        ok = isinstance(importe, Decimal) and importe.is_finite() and 0 < importe <= MAX_IMPORTE
    except InvalidOperation:
        ok = False
    if not ok:
        raise ValueError("importe: una compra de prueba es de unos US$ 1–5 (máximo 10, mayor que 0)")
    if not isinstance(moneda, str) or not _MONEDA.fullmatch(moneda):
        raise ValueError("moneda: usa el código de tres letras (p. ej. USD)")
    if pasarela not in PASARELAS:
        raise ValueError(f"pasarela: debe ser una de {', '.join(PASARELAS)}")
    _fecha_valida(fecha)
    datos = leer_ensayo(vault)
    if any(c.get("pedido") == pedido for c in datos.get("compras", [])):
        raise ValueError(f"ya hay una compra de prueba con el pedido {pedido}: no se sobrescribe")
    fila = {"pedido": pedido, "importe": f"{importe:f}", "moneda": moneda.upper(), "pasarela": pasarela, "fecha": fecha}
    datos.setdefault("compras", []).append(fila)
    datos.setdefault("reembolsos", [])
    _guardar(vault, datos)
    return fila


def registrar_reembolso(vault: Path, pedido: str, fecha: str) -> dict:
    _pedido_valido(pedido)
    _sin_secreto(pedido=pedido, fecha=str(fecha))
    _fecha_valida(fecha)
    datos = leer_ensayo(vault)
    if not any(c.get("pedido") == pedido for c in datos.get("compras", [])):
        raise ValueError(f"no hay una compra de prueba con el pedido {pedido}: registra antes la compra")
    if any(r.get("pedido") == pedido for r in datos.get("reembolsos", [])):
        raise ValueError(f"el pedido {pedido} ya tiene su reembolso registrado")
    fila = {"pedido": pedido, "fecha": fecha}
    datos.setdefault("reembolsos", []).append(fila)
    _guardar(vault, datos)
    return fila


# --- montaje de prueba del paso 18 (`trovefy arranque ensayo montaje`) ------------------------------------
# Un `crear_estructura_pausada` mínimo con `solo_validar: true`: el ejecutor solo pasa la campaña por
# validate_only (los conjuntos y anuncios no se validan sin crear sus padres) y no sube ni crea nada.
# Va en `propuestas/ensayo/`, donde trovefy-exec puede leer por la ACL del instalador. Los medios reales de
# /montar (bajo productos/) son una decisión de la Fase 3.

CARPETA_MONTAJE = "propuestas/ensayo"
NOMBRE_PROPUESTA = "montaje-ensayo.json"
NOMBRE_IMAGEN = "ensayo-imagen.png"
DATASET_DE_RELLENO = "1"  # solo dígitos; con solo_validar no se usa (solo se valida la campaña)
# Importes en unidades mínimas (spend_cap de la campaña, daily_budget del conjunto): pequeños, bajo los límites.
IMPORTES_PRUEBA = {"COP": (20000, 10000), "USD": (500, 100)}


def _png_minimo() -> bytes:
    """PNG de 1×1 píxel gris, generado aquí (sin archivos binarios en el repo)."""
    import struct
    import zlib

    def trozo(tipo: bytes, datos: bytes) -> bytes:
        return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)

    cabecera = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)  # 1×1, 8 bits, escala de grises
    return (b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", cabecera) + trozo(b"IDAT", zlib.compress(b"\x00\x80"))
            + trozo(b"IEND", b""))


def _datos_paso(vault: Path, id_: str) -> dict[str, str]:
    from trovefy.arranque.estado import cargar

    return next((p.datos for p in cargar(vault) if p.id == id_), {})


def _moneda(vault: Path, d06: dict[str, str]) -> str | None:
    if d06.get("moneda"):
        return d06["moneda"].upper()
    try:
        from trovefy.caja.config import cargar_caja

        m = cargar_caja(vault).cuenta.moneda
    except Exception:  # noqa: BLE001 - sin caja.yaml legible no hay moneda
        return None
    return m.upper() if isinstance(m, str) else None


def propuesta_montaje(vault: Path) -> dict:
    """Dict de la propuesta (sin id ni creada: los pone `trovefy buzon depositar`). ValueError si falta un dato."""
    vault = Path(vault)
    pagina = _datos_paso(vault, "05").get("page_id", "")
    if not re.fullmatch(r"\d{1,20}", pagina):
        raise ValueError("falta el page_id de la página del paso 05: verifica el paso 05")
    d06 = _datos_paso(vault, "06")
    act = d06.get("act_id", "").removeprefix("act_")
    if not re.fullmatch(r"\d{1,20}", act):
        raise ValueError("falta la cuenta publicitaria del paso 06: márcalo con --dato act_id=…")
    moneda = _moneda(vault, d06)
    if moneda not in IMPORTES_PRUEBA:
        raise ValueError(f"moneda del paso 06 sin importes de prueba ({moneda or 'no medida'}): usa COP o USD")
    dataset = _datos_paso(vault, "11").get("dataset_id", "")
    relleno = not re.fullmatch(r"\d{1,20}", dataset)
    origen = "arranque ensayo montaje" + (" (dataset de relleno: solo_validar no lo usa)" if relleno else "")
    tope, diario = IMPORTES_PRUEBA[moneda]
    texto = "Ensayo de Trovefy: solo se valida, no se crea nada"
    return {
        "version": 1, "tipo": "crear_estructura_pausada", "origen": origen, "cuenta": f"act_{act}",
        "pagina_id": pagina, "dataset_id": DATASET_DE_RELLENO if relleno else dataset,
        "medios": [{"ref": "ensayo", "ruta": f"{CARPETA_MONTAJE}/{NOMBRE_IMAGEN}",
                    "sha256": hashlib.sha256(_png_minimo()).hexdigest()}],
        "campana": {"nombre": "ENSAYO trovefy | solo validar", "objetivo": "OUTCOME_SALES",
                    "tipo_presupuesto": "ABO", "spend_cap": tope, "bid_strategy": "LOWEST_COST_WITHOUT_CAP"},
        "conjuntos": [{"nombre": "ENSAYO conjunto", "daily_budget": diario, "paises": ["CO"], "idiomas": ["es"],
                       "evento": "PURCHASE", "ubicaciones_excluidas": [],
                       "anuncios": [{"nombre": "ENSAYO anuncio", "medio": "ensayo", "texto": texto, "titulo": "Ensayo",
                                     "descripcion": "Ensayo", "cta": "SHOP_NOW", "url": "https://example.com/"}]}],
        "unidad": "minima", "moneda": moneda, "solo_validar": True,
    }


def preparar_montaje(vault: Path, ahora: datetime) -> Path:
    """Escribe la imagen de prueba y la propuesta en `propuestas/ensayo/`; devuelve la ruta de la propuesta."""
    from trovefy_ejecutor.esquema import PropuestaInvalida, cargar_propuesta

    vault = Path(vault)
    datos = propuesta_montaje(vault)
    try:  # misma validación que el buzón, con un id y una fecha de muestra
        cargar_propuesta({**datos, "id": "P-20000101-001", "creada": ahora.isoformat()})
    except PropuestaInvalida as e:
        raise ValueError(f"la propuesta de prueba no pasa el esquema: {e.motivo}") from None
    carpeta = vault / CARPETA_MONTAJE
    if carpeta.is_symlink() or (vault / "propuestas").is_symlink():
        raise ValueError(f"{CARPETA_MONTAJE} no puede ser un enlace simbólico")
    carpeta.mkdir(parents=True, exist_ok=True)
    imagen = carpeta / NOMBRE_IMAGEN
    fd, tmp = tempfile.mkstemp(dir=carpeta, prefix=f".{NOMBRE_IMAGEN}.", suffix=".tmp")  # nunca sigue un enlace plantado
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(_png_minimo())
        os.replace(tmp, imagen)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    ruta = carpeta / NOMBRE_PROPUESTA
    escribir_atomico(ruta, json.dumps(datos, ensure_ascii=False, indent=2) + "\n")
    return ruta
