"""Vault y respuestas ficticias para `/leer` (plan 23): ``p-0099-prueba-abc123`` en ``ZZ``, cuenta
``act_0000000000000000`` en COP, una campaña de test ABO con 3 conjuntos. Nunca la red, el HOME real, /var/spool ni el
vault real. Las comisiones de prueba son números de juguete (no los de ninguna plataforma)."""
from __future__ import annotations

import copy
import json
import shutil
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import yaml
from trovefy.leer import cargar_umbrales
from trovefy.leer.economia import EconomiaLeer
from trovefy.leer.modelo import LecturaConjunto, LecturaOferta, Metricas
from trovefy.trm import Trm
from trovefy.vault import frontmatter
from trovefy.vault.andamio import crear_vault
from trovefy.vault.escritura import ZONA_NEGOCIO

RAIZ = Path(__file__).resolve().parents[3]
FIXTURES = RAIZ / "tests" / "fixtures" / "leer"
P = "p-0099-prueba-abc123"
PAIS = "ZZ"
CUENTA = "act_0000000000000000"
CAMPANA = "3333333333333333"
CONJUNTOS = {"AD01 G1 mapa": "4000000000000001", "AD02 G1 villano": "4000000000000002",
             "AD03 G1 sueño": "4000000000000003"}
ANUNCIOS = {n: {"id": f"500000000000000{i}", "conjunto": c, "angulo": n.split(" ", 2)[2], "formato": "video",
                "medio": f"productos/{P}/creativos/ZZ/t1/AD0{i}.mp4"}
            for i, (n, c) in enumerate(CONJUNTOS.items(), 1)}
T0 = datetime(2026, 11, 19, 0, 0, tzinfo=ZONA_NEGOCIO)
AHORA = datetime(2026, 11, 20, 7, 30, tzinfo=ZONA_NEGOCIO)
TRM = Trm(Decimal("4000.00"), date(2026, 11, 1), date(2026, 12, 31))
BASE = 20000  # US$ 5 en COP a 4.000
TRAFICO = {"cuenta": CUENTA, "moneda": "COP", "campana": {"id": CAMPANA, "nombre": "PRUEBA ZZ | G1 | ABO | 19-11-26"},
           "conjuntos": CONJUNTOS, "anuncios": ANUNCIOS, "spend_cap": {"minima": 400000, "usd": "100"},
           "diario_conjunto": {"minima": BASE, "usd": "5"}, "activado": T0.isoformat(), "inicio": T0.isoformat(),
           "montaje": "P-20261118-001", "tanda": "t1"}


def umbrales() -> dict[str, Decimal]:
    from trovefy.config.umbrales import cargar

    return {k: Decimal(str(x.valor)) for k, x in
            cargar(RAIZ / "templates" / "cerebro" / "config" / "umbrales.yaml").items()}


U = umbrales()
ECO = EconomiaLeer(Decimal(10), Decimal("17.56"), Decimal("0.03"), Decimal("0.30"), None)
ECO_NO = EconomiaLeer(None, None, None, None, "no medido: falta ruta_activa en config/economia.yaml")


def trm_de(_d):
    return TRM


def sin_trm(_d):
    return None


def met(gasto="0", clics=None, visitas=None, pi=None, compras=0, impresiones=1000, cpc=None) -> Metricas:
    c = int(Decimal(gasto) * 100)
    if cpc is not None and clics is None:
        clics = max(1, int(Decimal(gasto) / Decimal(cpc)))
    return Metricas(c, Decimal(c) * 40, "COP", impresiones, clics if clics is not None else 20, visitas, pi, compras)


def conj(gasto="0", visitas=None, pi=None, cpc=None, ventas=None, bruto=None, clics=None, estado="ACTIVE",
         presupuesto=BASE, hoy=None, nombre="AD01 G1 mapa", sid="4000000000000001", compras=0,
         angulo=None) -> LecturaConjunto:
    return LecturaConjunto(sid, "5000000000000001", nombre, angulo or nombre.split(" ", 2)[-1], estado,
                           met(gasto, clics=clics, visitas=visitas, pi=pi, cpc=cpc, compras=compras), ventas,
                           Decimal(bruto) if bruto is not None else None, presupuesto, "ACTIVE", hoy)


def of(gasto="0", ventas=0, horas=20, bruto=None, conjuntos=None, pixel=0, intradia=False, ventas_dia=None,
       pi_tienda=None, fallidos=0, gasto_c=None, zona="America/Bogota") -> LecturaOferta:
    from datetime import timedelta

    gc = gasto_c if gasto_c is not None else int(Decimal(gasto) * 100)
    return LecturaOferta(
        P, PAIS, CAMPANA, "COP", T0, T0 + timedelta(hours=horas), (T0 + timedelta(hours=horas)).date(), intradia,
        tuple(conjuntos or (conj(gasto),)), gc if gasto_c != -1 else None, ventas,
        Decimal(bruto) if bruto is not None else None, pixel, pi_tienda, fallidos, ventas_dia, 400000, BASE, zona,
        "TRM 4.000,00", ())


def fx(nombre: str) -> dict:
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


def vault_test(tmp_path: Path, *, estado: str = "test", ic: bool = False, economia: bool = True,
               trafico: dict | None = None) -> Path:
    """Vault con el país en ``test``, el test vivo en la caja y (opcional) la economía de juguete fijada."""
    v = tmp_path / "vault"
    crear_vault(v)
    meta = {"tipo": "producto", "id": P, "fecha": "2026-11-18",
            "paises": {PAIS: {"estado": estado, "trafico": copy.deepcopy(trafico or TRAFICO)}}}
    frontmatter.escribir(v / "productos" / P / "PRODUCTO.md", meta, "\n# Producto de prueba\n")
    frontmatter.escribir(v / "productos" / P / "ESCALERA.md",
                         {"tipo": "escalera", "fecha": "2026-11-18",
                          "paises": {PAIS: {"aov_usd": "17.56", "be_usd": "10", "cpa_be_usd": "10"}}}, "\n# E\n")
    eventos = {"PageView": 3, "InitiateCheckout": 2 if ic else None, "Purchase": 1}
    frontmatter.escribir(v / "productos" / P / "checkout" / PAIS / "TRACKING.md",
                         {"tipo": "tracking", "fecha": "2026-11-18", "eventos": eventos}, "\n# T\n")
    caja = yaml.safe_load((RAIZ / "templates/cerebro/config/caja.yaml").read_text(encoding="utf-8"))
    caja["cuenta"] = {"id": CUENTA, "moneda": "COP"}
    caja["tests"] = [{"producto": P, "pais": PAIS, "campana_id": CAMPANA, "estado": "vivo", "prorroga": False,
                      "ventas": None, "diario_usd": 15}]
    (v / "config" / "caja.yaml").write_text(yaml.safe_dump(caja, allow_unicode=True), encoding="utf-8")
    if economia:
        ruta = v / "config" / "economia.yaml"
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
        datos["ruta_activa"]["valor"] = "impultienda_whop"
        for plat, (pct, fija) in {"impultienda": ("0", "0"), "whop": ("0.03", "0.30")}.items():
            for campo, val in (("comision_pct", pct), ("comision_fija_usd", fija), ("impuestos_pct", "0")):
                datos["plataformas"][plat][campo]["valor"] = val
        ruta.write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    shutil.copy(RAIZ / "templates/cerebro/config/umbrales.yaml", v / "config" / "umbrales.yaml")
    assert cargar_umbrales(v)
    return v


def meta_adsets(filas: list[dict]) -> dict:
    """Respuesta de ``ads_get_ad_entities`` nivel conjunto con la forma de la fixture."""
    base = fx("meta-adset.json")
    plantilla = base["ad_entities"][0]
    salida = []
    for f in filas:
        x = copy.deepcopy(plantilla)
        x.update({k: v for k, v in f.items() if k != "insights"})
        x["insights"]["data"][0].update(f.get("insights", {}))
        salida.append(x)
    return {**base, "ad_entities": salida}


def utm(filas: list[tuple[str, int, str]], moneda: str = "EUR") -> dict:
    """``impultienda_campanas_utm`` nivel anuncio: (nombre del anuncio, ventas, ingresos)."""
    return {"structuredContent": {
        "periodo": {"desde": "2026-11-19", "hasta": "2026-11-19", "timezone": "America/Bogota"}, "nivel": "anuncio",
        "utm": {"nivel": "anuncio", "moneda": moneda, "fx_incompleto": False, "filas_omitidas": 0, "filas": [
            {"utm_source": "fb", "utm_medium": "paid", "utm_campaign": f"PRUEBA ZZ | G1 | ABO | 19-11-26|{CAMPANA}",
             "anuncio": f"{n}|{ANUNCIOS[n]['id']}", "ventas": v, "post_compra": 0, "ingresos": i,
             "ticket_promedio": i} for n, v, i in filas]},
        "meta_ads": {"disponible": False, "motivo": "prueba"}}}


def escribir_json(ruta: Path, datos: dict) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    return ruta
