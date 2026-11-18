"""Vault ficticio para el embudo del plan 19 (producto p-0099-prueba-abc123, país ZZ, tienda de prueba)."""

from __future__ import annotations

from pathlib import Path

import yaml
from trovefy.vault import frontmatter

P = "p-0099-prueba-abc123"
PAIS = "ZZ"
TIENDA = "https://prueba.impultienda.example"

MERCADOS = f"""\
ZZ: {{idioma: bg, moneda: EUR, zona: Europe/Sofia, banda_eur: [9, 19], estado: activo, tienda: "{TIENDA}"}}
ZY: {{idioma: ro, moneda: EUR, zona: Europe/Bucharest, banda_eur: [9, 19], estado: activo, tienda: null}}
"""

PASOS_FICTICIOS = {
    "front": {"precio": "13.90", "activo": True, "titulo": "Спокойно тяло", "entregable": "PDF principal"},
    "bump": {"precio": "4.90", "activo": False, "motivo_inactivo": "sin order bump (vídeos)",
             "titulo": "Чек-лист", "entregable": "Чек-лист"},
    "u1": {"precio": "19.90", "activo": True, "titulo": "Сън без болка", "entregable": "Следваща болка: сън"},
    "u2": {"precio": "24.90", "activo": False, "motivo_inactivo": "sin producir", "titulo": "U2", "entregable": "U2"},
    "u3": {"precio": "29.90", "activo": False, "motivo_inactivo": "sin producir", "titulo": "U3", "entregable": "U3"},
    "downsell": {"precio": "9.90", "activo": False, "motivo_inactivo": "sin downsell", "titulo": "D",
                 "entregable": "D"},
}


def escribir_md(ruta: Path, meta: dict, cuerpo: str = "Ficticio.\n") -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    frontmatter.escribir(ruta, meta, cuerpo)


def arranque(pasos: dict[str, str]) -> dict:
    return {"pasos": [{"id": i, "nombre": f"Paso {i}", "estado": e, "evidencia": ["x"] if e == "verificado" else [],
                       "datos": {}} for i, e in pasos.items()]}


def vault_embudo(tmp_path: Path, *, estado: str = "con_landing", pasos: dict | None = None,
                 cobro: dict[str, str] | None = None, pdf_u1: bool = True, landing: dict | None = None) -> Path:
    v = tmp_path / "v"
    prod = v / "productos" / P
    (v / "config").mkdir(parents=True)
    (v / "config" / "mercados.yaml").write_text(MERCADOS, encoding="utf-8")
    cobro = {"09": "verificado", "10": "hecho"} if cobro is None else cobro
    (v / "config" / "arranque.yaml").write_text(yaml.safe_dump(arranque(cobro)), encoding="utf-8")
    entregable = {"principal": {"version": 1, "pdf": "entregable/prueba-bg-v1.pdf", "paginas": 3}}
    if pdf_u1:
        entregable["u1"] = {"version": 1, "pdf": "entregable/upsells/u1/u1-bg-v1.pdf", "paginas": 2}
    escribir_md(prod / "PRODUCTO.md", {
        "tipo": "producto", "producto": P,
        "paises": {PAIS: {"estado": estado, "historial": []}},
        "entregable": {"bg": entregable},
    })
    escribir_md(prod / "ESCALERA.md", {
        "tipo": "escalera", "producto": P,
        "paises": {PAIS: {"moneda": "EUR", "pasos": PASOS_FICTICIOS if pasos is None else pasos}},
    })
    escribir_md(prod / "BRANDBOOK.md", {"tipo": "brandbook", "producto": P, "nombre_local": "Somatix"})
    for rel in ("entregable/prueba-bg-v1.pdf", "entregable/upsells/u1/u1-bg-v1.pdf"):
        (prod / rel).parent.mkdir(parents=True, exist_ok=True)
        (prod / rel).write_bytes(b"%PDF-1.7 ficticio")
    datos_landing = {"hosting": "impultienda", "version": "v1", "url": TIENDA + "/",
                     "checkout_url": "/checkout"} if landing is None else landing
    if datos_landing:
        ruta = prod / "landing" / PAIS / "landing.yaml"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(yaml.safe_dump(datos_landing), encoding="utf-8")
    return v
