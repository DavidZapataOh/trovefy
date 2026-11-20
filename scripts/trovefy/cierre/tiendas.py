"""Tiendas del cierre (``config/cierre.yaml``) y esquema de pedidos de Impultienda (P-20).

**Qué hacen los vídeos:** una tienda por idioma (L1 0:22:57); el cierre sale «contra la pasarela» (C1 0:50:20).

La tienda se empareja con su producto-país por el host (la URL de la tienda, su dominio propio o su subdominio frente a
``config/mercados.yaml → <PAIS>.tienda`` y ``PRODUCTO.md → paises.<PAIS>.{landing,checkout}.url``). Lo que no empareja
va a la lista de avisos: nunca se adivina. La compra de prueba de la fase 2 se apunta en ``pedidos_prueba`` con la
confirmación del usuario (resolución 19) y no cuenta como venta.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import yaml

from trovefy.vault.escritura import escribir_atomico

RUTA = Path("config") / "cierre.yaml"
RUTA_ESQUEMA = Path("config") / "esquemas" / "impultienda-pedidos.yaml"
CABECERA = (
    "# Tiendas del cierre (plan 24): qué tienda de Impultienda cobra qué producto-país. Lo escribe\n"
    "# `trovefy cierre tiendas` con la respuesta de impultienda_listar_tiendas; tus comentarios de arriba se conservan.\n"
    "# pedidos_prueba: la compra de prueba de la fase 2 (no cuenta como venta). La apunta `trovefy cierre prueba`\n"
    "# con tu confirmación.\n"
)
# Claves que pueden traer datos personales: nunca pasan al esquema ni al vault.
PERSONALES = frozenset({"email", "correo", "nombre", "name", "comprador", "cliente", "telefono", "phone", "direccion",
                        "address", "documento", "dni", "ip", "first_name", "last_name", "buyer", "customer"})
# Lo mínimo que necesita el cierre de la respuesta de impultienda_listar_ventas.
REQUERIDAS = {"periodo.desde": "str", "periodo.hasta": "str", "detalle.has_more": "bool",
              "detalle.ventas[].orden": "str", "detalle.ventas[].fecha": "str", "detalle.ventas[].total": "num",
              "detalle.ventas[].moneda": "str"}


@dataclass(frozen=True)
class Tienda:
    store_id: str
    url: str
    producto: str
    pais: str


def contenido(datos: object) -> dict:
    """``structuredContent`` (o ``result``) de una respuesta del MCP, o la propia respuesta."""
    for _ in range(2):
        if isinstance(datos, dict) and isinstance(datos.get("structuredContent"), dict):
            datos = datos["structuredContent"]
        elif isinstance(datos, dict) and isinstance(datos.get("result"), dict):
            datos = datos["result"]
    return datos if isinstance(datos, dict) else {}


def host(valor: object) -> str | None:
    if not isinstance(valor, str) or not valor.strip():
        return None
    v = valor.strip().lower()
    h = urlparse(v if "://" in v else f"https://{v}").hostname
    return h.removeprefix("www.") if h else None


def _hosts_tienda(t: dict) -> set[str]:
    hs = {host(t.get(k)) for k in ("url", "dominio_propio")}
    sub = t.get("subdominio")
    if isinstance(sub, str) and sub.strip():
        hs.add(host(sub) if "." in sub else None)
        url = host(t.get("url"))
        if url and "." not in sub and url.startswith(f"{sub.lower()}."):
            hs.add(url)
    return {h for h in hs if h}


def _candidatos(vault: Path) -> dict[tuple[str, str], set[str]]:
    """(producto, país) → hosts de su tienda (mercados.yaml), su landing y su checkout."""
    from trovefy.vault import frontmatter

    mercados = {}
    ruta_m = Path(vault) / "config" / "mercados.yaml"
    if ruta_m.is_file():
        mercados = yaml.safe_load(ruta_m.read_text(encoding="utf-8")) or {}
    salida: dict[tuple[str, str], set[str]] = {}
    for ruta in sorted((Path(vault) / "productos").glob("*/PRODUCTO.md")):
        try:
            meta, _ = frontmatter.leer(ruta)
        except (OSError, ValueError):
            continue
        paises = meta.get("paises") if isinstance(meta, dict) else None
        for pais, b in (paises or {}).items() if isinstance(paises, dict) else ():
            if not isinstance(b, dict):
                continue
            hs = {host((b.get(k) or {}).get("url")) if isinstance(b.get(k), dict) else None
                  for k in ("landing", "checkout")}
            m = mercados.get(pais) if isinstance(mercados, dict) else None
            if isinstance(m, dict):
                hs.add(host(m.get("tienda")))
            hs = {h for h in hs if h}
            if hs:
                salida[(ruta.parent.name, str(pais))] = hs
    return salida


def emparejar_tiendas(instantanea_tiendas: dict, vault: Path) -> tuple[list[Tienda], list[str]]:
    """Tiendas de ``impultienda_listar_tiendas`` con su producto-país; lo que no empareja (o empareja con dos) es aviso."""
    tiendas = contenido(instantanea_tiendas).get("tiendas")
    if not isinstance(tiendas, list):
        return [], ["no medido: forma de impultienda_listar_tiendas desconocida"]
    candidatos = _candidatos(vault)
    salida: list[Tienda] = []
    avisos: list[str] = []
    for t in tiendas:
        if not isinstance(t, dict) or not isinstance(t.get("id"), str):
            continue
        hs = _hosts_tienda(t)
        parejas = [k for k, v in candidatos.items() if v & hs]
        nombre = host(t.get("url")) or t["id"]
        if len(parejas) == 1:
            salida.append(Tienda(t["id"], str(t.get("url") or ""), *parejas[0]))
        elif not parejas:
            avisos.append(f"la tienda {nombre} no casa con ningún producto-país (ni mercados.yaml ni landing/checkout)")
        else:
            avisos.append(f"la tienda {nombre} casa con varios producto-país ({', '.join('/'.join(p) for p in parejas)}):"
                          " apúntala a mano en config/cierre.yaml")
    return salida, avisos


def _cabecera_existente(texto: str) -> str:
    lineas = []
    for ln in texto.splitlines():
        if ln.startswith("#") or not ln.strip():
            lineas.append(ln)
        else:
            break
    return ("\n".join(lineas).rstrip() + "\n") if any(x.strip() for x in lineas) else CABECERA


def cargar(vault: Path) -> dict:
    ruta = Path(vault) / RUTA
    if not ruta.is_file():
        return {"tiendas": [], "pedidos_prueba": []}
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    if not isinstance(datos, dict):
        raise ValueError("config/cierre.yaml no es un mapa")  # noqa: TRY004 - dato de un archivo
    datos.setdefault("tiendas", [])
    datos.setdefault("pedidos_prueba", [])
    if not isinstance(datos["tiendas"], list) or not isinstance(datos["pedidos_prueba"], list):
        raise ValueError("config/cierre.yaml: tiendas y pedidos_prueba deben ser listas")  # noqa: TRY004
    return datos


def _guardar(vault: Path, datos: dict) -> Path:
    ruta = Path(vault) / RUTA
    previo = ruta.read_text(encoding="utf-8") if ruta.is_file() else ""
    cuerpo = yaml.safe_dump(datos, allow_unicode=True, sort_keys=False, default_flow_style=False)
    escribir_atomico(ruta, _cabecera_existente(previo) + cuerpo)
    return ruta


def tiendas_de(vault: Path) -> list[Tienda]:
    salida = []
    for t in cargar(vault)["tiendas"]:
        if isinstance(t, dict) and all(isinstance(t.get(k), str) for k in ("store_id", "producto", "pais")):
            salida.append(Tienda(t["store_id"], str(t.get("url") or ""), t["producto"], t["pais"]))
    return salida


def escribir_tiendas(vault: Path, tiendas: list[Tienda]) -> Path:
    """Añade o actualiza por ``store_id``; no quita tiendas ni pedidos de prueba que ya estaban."""
    datos = cargar(vault)
    por_id = {t.get("store_id"): t for t in datos["tiendas"] if isinstance(t, dict)}
    for t in tiendas:
        por_id[t.store_id] = {"store_id": t.store_id, "url": t.url, "producto": t.producto, "pais": t.pais}
    datos["tiendas"] = list(por_id.values())
    return _guardar(vault, datos)


def registrar_prueba(vault: Path, tienda: str, orden: str, fuente: str) -> Path:
    """Apunta la compra de prueba (resolución 19). ``fuente`` lleva las palabras del usuario."""
    if not orden.strip() or not fuente.strip():
        raise ValueError("faltan la orden o la fuente (tus palabras)")
    datos = cargar(vault)
    otros = [p for p in datos["pedidos_prueba"] if not (isinstance(p, dict) and p.get("tienda") == tienda
                                                         and str(p.get("orden")) == orden)]
    datos["pedidos_prueba"] = [*otros, {"tienda": tienda, "orden": orden, "fuente": fuente}]
    return _guardar(vault, datos)


def pedidos_de_prueba(vault: Path, store_id: str | None = None) -> set[str]:
    """Órdenes de la compra de prueba (de una tienda, o de todas)."""
    try:
        lista = cargar(vault)["pedidos_prueba"]
    except (OSError, ValueError):
        return set()
    return {str(p["orden"]) for p in lista if isinstance(p, dict) and p.get("orden") is not None
            and (store_id is None or p.get("tienda") == store_id)}


# --- esquema P-20 --------------------------------------------------------------------------------------------------


def _tipo(v: object) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "num"
    if isinstance(v, str):
        return "str"
    if v is None:
        return "null"
    return "lista" if isinstance(v, list) else "mapa"


def _recorrer(v: object, camino: str, salida: dict[str, str]) -> None:
    if isinstance(v, dict):
        for k, x in v.items():
            if str(k).lower() in PERSONALES:
                continue
            _recorrer(x, f"{camino}.{k}" if camino else str(k), salida)
    elif isinstance(v, list):
        for x in v[:20]:
            _recorrer(x, f"{camino}[]", salida)
        salida.setdefault(camino, "lista")
    else:
        t = _tipo(v)
        if t != "null" or camino not in salida:
            salida[camino] = t


def esquema_pedidos(instantanea_ventas: dict) -> dict:
    """Claves y tipos observados en la respuesta de ``impultienda_listar_ventas`` (sin datos personales)."""
    campos: dict[str, str] = {}
    _recorrer(contenido(instantanea_ventas), "", campos)
    return dict(sorted(campos.items()))


def escribir_esquema(vault: Path, esquema: dict, fecha: date) -> Path:
    ruta = Path(vault) / RUTA_ESQUEMA
    texto = ("# Esquema de pedidos de Impultienda (P-20, plan 24): claves y tipos observados, sin datos personales.\n"
             + yaml.safe_dump({"fuente": "impultienda_listar_ventas (MCP)", "fecha": fecha.isoformat(),
                               "campos": esquema}, allow_unicode=True, sort_keys=False))
    escribir_atomico(ruta, texto)
    return ruta


def cargar_esquema(vault: Path) -> dict | None:
    ruta = Path(vault) / RUTA_ESQUEMA
    if not ruta.is_file():
        return None
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    return datos.get("campos") if isinstance(datos, dict) and isinstance(datos.get("campos"), dict) else None




def validar_ventas(instantanea: dict, esquema: dict | None = None) -> list[str]:
    """Diferencias de forma frente a lo que el cierre necesita (y al esquema guardado, si lo hay)."""
    vistos = esquema_pedidos(instantanea)
    esperados = dict(REQUERIDAS)
    for k, t in (esquema or {}).items():
        if k in REQUERIDAS:
            esperados[k] = t
    difs = []
    for clave, tipo in esperados.items():
        visto = vistos.get(clave)
        if visto is None:
            if clave.startswith("detalle.ventas[]") and not contenido(instantanea).get("detalle", {}).get("ventas"):
                continue  # sin ventas en el periodo: no hay filas que mirar
            difs.append(f"falta {clave}")
        elif tipo == "num" and visto == "str":
            continue  # importes como texto: se leen con Decimal
        elif visto != tipo and visto != "null":
            difs.append(f"{clave}: se esperaba {tipo} y llega {visto}")
    return difs
