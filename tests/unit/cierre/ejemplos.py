"""Vault y respuestas ficticias para `/cierre` (plan 24): ``p-0099-prueba-abc123`` en ``ZZ`` (EUR, Europe/Sofia),
cuenta ``act_0000000000000000`` en COP, tienda ``00000000-…`` (``https://prueba.impultienda.example``), campaña
``120000000000000001``. Nunca la red, el HOME real, /var/spool ni el vault real. Comisiones de juguete."""
from __future__ import annotations

import copy
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import yaml
from trovefy.cierre.tiendas import Tienda
from trovefy.fx import Cambio
from trovefy.trm import Trm
from trovefy.vault import frontmatter
from trovefy.vault.andamio import crear_vault
from trovefy.vault.escritura import ZONA_NEGOCIO

RAIZ = Path(__file__).resolve().parents[3]
FIXTURES = RAIZ / "tests" / "fixtures" / "cierre"
P = "p-0099-prueba-abc123"
PAIS = "ZZ"
CUENTA = "act_0000000000000000"
CAMPANA = "120000000000000001"
STORE = "00000000-0000-0000-0000-000000000000"
URL = "https://prueba.impultienda.example"
TIENDA = Tienda(STORE, URL, P, PAIS)
TRM = Trm(Decimal("4000.00"), date(2026, 11, 1), date(2026, 12, 31))
CAMBIO = Cambio({"EUR": 1.0, "USD": 1.10}, "2026-11-19")
DIA = date(2026, 11, 19)
MANANA = datetime(2026, 11, 20, 8, 30, tzinfo=ZONA_NEGOCIO)
NOCHE = datetime(2026, 11, 19, 23, 30, tzinfo=ZONA_NEGOCIO)


def fx(nombre: str) -> dict:
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


def escribir_json(ruta: Path, datos: dict) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    return ruta


def vault_cierre(tmp_path: Path, *, economia: bool = True, tiendas: bool = True, prueba: bool = True) -> Path:
    v = tmp_path / "vault"
    crear_vault(v)
    meta = {"tipo": "producto", "id": P, "fecha": "2026-11-18",
            "paises": {PAIS: {"estado": "test", "checkout": {"url": f"{URL}/o/prueba"},
                              "landing": {"url": "https://landing-prueba.example/"},
                              "trafico": {"campana": {"id": CAMPANA}, "activado": "2026-11-18T00:00:00-05:00",
                                          "inicio": "2026-11-18T00:00:00-05:00"}}}}
    frontmatter.escribir(v / "productos" / P / "PRODUCTO.md", meta, "\n# Producto de prueba\n")
    caja = yaml.safe_load((RAIZ / "templates/cerebro/config/caja.yaml").read_text(encoding="utf-8"))
    caja["cuenta"] = {"id": CUENTA, "moneda": "COP"}
    caja["tests"] = [{"producto": P, "pais": PAIS, "campana_id": CAMPANA, "estado": "vivo", "prorroga": False,
                      "ventas": None, "diario_usd": 25}]
    (v / "config" / "caja.yaml").write_text(yaml.safe_dump(caja, allow_unicode=True), encoding="utf-8")
    mercados = yaml.safe_load((RAIZ / "templates/cerebro/config/mercados.yaml").read_text(encoding="utf-8"))
    mercados[PAIS] = {"idioma": "bg", "moneda": "EUR", "zona": "Europe/Sofia", "tienda": None, "estado": "candidato"}
    (v / "config" / "mercados.yaml").write_text(yaml.safe_dump(mercados, allow_unicode=True), encoding="utf-8")
    if economia:
        ruta = v / "config" / "economia.yaml"
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
        datos["ruta_activa"]["valor"] = "impultienda_whop"
        for plat, (pct, fija) in {"impultienda": ("0", "0"), "whop": ("0.03", "0.30")}.items():
            for campo, val in (("comision_pct", pct), ("comision_fija_usd", fija), ("impuestos_pct", "0")):
                datos["plataformas"][plat][campo]["valor"] = val
        ruta.write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if tiendas:
        datos = {"tiendas": [{"store_id": STORE, "url": URL, "producto": P, "pais": PAIS}],
                 "pedidos_prueba": [{"tienda": STORE, "orden": "ORD-0003", "fuente": "usuario: «esa fue la de prueba»"}]
                 if prueba else []}
        (v / "config" / "cierre.yaml").write_text("# mis notas\n" + yaml.safe_dump(datos), encoding="utf-8")
    return v


def ventas_pagina(ventas: list[dict], *, desde="2026-11-13", hasta="2026-11-19", offset=0, has_more=False,
                  next_offset=None, zona="America/Bogota") -> dict:
    d = {"total": len(ventas), "count": len(ventas), "offset": offset, "has_more": has_more, "ventas": ventas}
    if next_offset is not None:
        d["next_offset"] = next_offset
    return {"structuredContent": {"periodo": {"desde": desde, "hasta": hasta, "timezone": zona},
                                  "cantidad_ventas": len(ventas), "detalle": d}}


def venta(orden: str, total: str = "13.90", fecha: str = "2026-11-19T10:00:00-05:00", post: bool = False,
          moneda: str = "EUR") -> dict:
    return {"orden": orden, "fecha": fecha, "total": total, "moneda": moneda, "metodo_pago": "impul_pay",
            "post_compra": post}


def campanas(dia: str, gasto: str = "99200", compras: str = "1", moneda: str = "COP") -> dict:
    base = copy.deepcopy(fx("entities-campanas.json"))
    base["currency"] = moneda
    ins = base["ad_entities"][0]["insights"]["data"][0]
    ins.update({"date_start": dia, "date_stop": dia, "amount_spent": gasto, "omni_purchase": compras})
    return base
