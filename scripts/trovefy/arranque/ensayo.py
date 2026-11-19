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
    fila = {"pedido": pedido, "importe": f"{importe:f}", "moneda": moneda.upper(), "pasarela": pasarela, "fecha": fecha}
    return _anadir_compra(vault, fila)


def _anadir_compra(vault: Path, fila: dict) -> dict:
    datos = leer_ensayo(vault)
    if any(c.get("pedido") == fila["pedido"] for c in datos.get("compras", [])):
        raise ValueError(f"ya hay una compra de prueba con el pedido {fila['pedido']}: no se sobrescribe")
    datos.setdefault("compras", []).append(fila)
    datos.setdefault("reembolsos", [])
    _guardar(vault, datos)
    return fila


# --- compra y reembolso del producto real (plan 20, Tarea 6) ----------------------------------------------
# La compra de prueba del paso 18 es la del producto real que guía /checkout (plan 19): se toma de
# ``paises.<PAIS>.compra_prueba`` de PRODUCTO.md o, si falta, de las evidencias que ya pegó el usuario
# (``checkout/<PAIS>/evidencia/``: ``pedido`` y ``reembolso``). Se hace al precio real de venta (resolución 28):
# en vez del tope de 10, el importe tiene que ser el precio del checkout.


def _ficha(vault: Path, producto: str, pais: str):
    from trovefy.listo.ficha import leer_ficha

    f = leer_ficha(vault, producto, pais)
    if not f.datos:
        raise ValueError(f"{producto} no tiene el bloque del país {pais} en PRODUCTO.md")
    return f


def _pegado_fuerte(f, clave: str):
    from trovefy.listo.gates import pegados

    fuertes = [p for p in pegados(f, clave) if p.tipo in ("captura", "texto")]
    return fuertes[-1] if fuertes else None


def registrar_compra_desde_producto(vault: Path, producto: str, pais: str) -> dict:
    """Registra en el ensayo la compra de prueba del producto real. ``ValueError`` sin escribir nada si no está vista
    en la plataforma, si no es al precio de venta del checkout o si la pasarela no es una de `PASARELAS`."""
    from trovefy.listo.ficha import campo

    vault = Path(vault)
    f = _ficha(vault, producto, pais)
    pasarela = campo(f.datos, "checkout.plataforma")
    if pasarela not in PASARELAS:
        raise ValueError(f"checkout.plataforma «{pasarela}»: debe ser una de {', '.join(PASARELAS)}")
    precio, moneda_venta = campo(f.datos, "checkout.precio.importe"), campo(f.datos, "checkout.precio.moneda")
    try:
        venta = Decimal(str(precio))
    except (InvalidOperation, ValueError):
        raise ValueError("falta checkout.precio.importe (el precio de venta) en PRODUCTO.md") from None
    if not venta.is_finite() or venta <= 0 or not isinstance(moneda_venta, str) or not _MONEDA.fullmatch(moneda_venta):
        raise ValueError("checkout.precio no es un importe y una moneda válidos")
    compra = campo(f.datos, "compra_prueba")
    if isinstance(compra, dict) and compra:
        if campo(compra, "plataforma.visto") is not True:
            raise ValueError("la compra de prueba no está vista en la plataforma (compra_prueba.plataforma.visto)")
        pedido, fecha = str(compra.get("pedido") or ""), str(compra.get("fecha") or "")
        try:
            importe = Decimal(str(compra.get("importe")))
        except (InvalidOperation, ValueError):
            raise ValueError("compra_prueba.importe no es un número") from None
        moneda = compra.get("moneda")
        if importe != venta or moneda != moneda_venta:
            raise ValueError(f"la compra de prueba ({importe} {moneda}) no es el precio de venta del checkout "
                             f"({venta} {moneda_venta})")
    else:
        p = _pegado_fuerte(f, "pedido")
        if p is None:
            raise ValueError("no hay compra de prueba vista en la plataforma: ni compra_prueba en PRODUCTO.md ni una "
                             "captura del pedido (trovefy checkout evidencia --clave pedido)")
        pedido = p.valores.get("pedido") or ""
        if not pedido:
            raise ValueError("la captura del pedido no dice su número: regístrala con --valor pedido=<número>")
        fecha, importe, moneda = str(p.fecha)[:10], venta, moneda_venta
    _pedido_valido(pedido)
    _fecha_valida(fecha)
    _sin_secreto(pedido=pedido, moneda=str(moneda), pasarela=str(pasarela), fecha=fecha)
    fila = {"pedido": pedido, "importe": f"{importe:f}", "moneda": str(moneda).upper(), "pasarela": pasarela,
            "fecha": fecha, "producto": producto, "pais": pais}
    return _anadir_compra(vault, fila)


def registrar_reembolso_desde_producto(vault: Path, producto: str, pais: str) -> dict:
    """Registra el reembolso de la compra de prueba del producto real: ``compra_prueba.reembolso.procesado`` con su
    fecha o, si falta, la captura del reembolso que pegó el usuario. ``ValueError`` si no está procesado."""
    from trovefy.listo.ficha import campo

    vault = Path(vault)
    f = _ficha(vault, producto, pais)
    reembolso = campo(f.datos, "compra_prueba.reembolso")
    if isinstance(reembolso, dict) and reembolso:
        if reembolso.get("procesado") is not True:
            raise ValueError("el reembolso de la compra de prueba no está procesado (compra_prueba.reembolso)")
        fecha = str(reembolso.get("fecha") or "")
        pedido = str(campo(f.datos, "compra_prueba.pedido") or "")
    else:
        p = _pegado_fuerte(f, "reembolso")
        if p is None:
            raise ValueError("el reembolso no está procesado: ni compra_prueba.reembolso en PRODUCTO.md ni una captura "
                             "del reembolso (trovefy checkout evidencia --clave reembolso)")
        fecha = str(p.fecha)[:10]
        pedido = p.valores.get("pedido") or ""
        if not pedido:
            pedidos = [c.get("pedido") for c in leer_ensayo(vault).get("compras", [])
                       if c.get("producto") == producto and c.get("pais") == pais]
            pedido = pedidos[-1] if pedidos else ""
    return registrar_reembolso(vault, pedido, fecha)


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
        os.fchmod(fd, 0o640)  # mkstemp da 0600 y eso pone a cero la máscara de la ACL del vault: el ejecutor no lo leería
        with os.fdopen(fd, "wb") as f:
            f.write(_png_minimo())
        os.replace(tmp, imagen)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    ruta = carpeta / NOMBRE_PROPUESTA
    escribir_atomico(ruta, json.dumps(datos, ensure_ascii=False, indent=2) + "\n")
    os.chmod(ruta, 0o640)  # legible por el usuario del ejecutor a través de la ACL del vault
    return ruta
