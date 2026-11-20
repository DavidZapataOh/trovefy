"""Vault ficticio para /montar (plan 22): la tanda t1 cerrada de verdad por /creativos (plan 21) para
``p-0099-prueba-abc123`` en ``ZZ`` (búlgaro), más lo que pide montar: dataset, página, cuenta COP, umbrales, caja,
config/montar.yaml y un spool del ejecutor sano. Nunca la red, el HOME real, /var/spool ni el vault real."""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import yaml
from trovefy.trm import Trm
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO
from unit.creativos.ejemplos import PAIS, P
from unit.creativos.test_manifest import cerrada

RAIZ = Path(__file__).resolve().parents[3]
CUENTA = "act_0000000000000000"
DATASET = "1111111111111111"
PAGINA = "2222222222222222"
AHORA = datetime(2026, 11, 20, 10, 0, tzinfo=ZONA_NEGOCIO)
TRM = Trm(Decimal("4000.00"), date(2026, 11, 20), date(2026, 11, 20))

LIMITES = {"version": 1, "cuentas_permitidas": [CUENTA], "cuentas": {CUENTA: {
    "moneda": "COP", "offset": 1, "zona_horaria": "America/Bogota", "tope_gasto_diario_total": 400000,
    "max_presupuesto_conjunto": 40000, "max_presupuesto_campana_cbo": 132000, "spend_cap_test": 400000,
    "spend_cap_test_prorroga": 400000}}}
META = {"fecha": "2026-11-20T09:00:00-05:00", "cuenta": CUENTA, "currency": "COP", "offset": 1,
        "timezone_name": "America/Bogota", "account_status": 1, "amount_spent": "0", "spend_cap": "5000000",
        "validate_only": {"ok": True, "motivo": None}}


def escribir_spool(base: Path, ahora: datetime = AHORA, *, limites: dict | None = None, meta: dict | None = None,
                   stop: bool = False) -> Path:
    carpeta = base / "spool" / "estado"
    carpeta.mkdir(parents=True, exist_ok=True)
    (base / "spool" / "entrada").mkdir(parents=True, exist_ok=True)
    datos = {"latido": {"fecha": (ahora - timedelta(minutes=1)).isoformat()},
             "stop": {"activo": stop}, "limites": limites or LIMITES, "meta": meta or META}
    for nombre, d in datos.items():
        (carpeta / f"{nombre}.json").write_text(json.dumps(d), encoding="utf-8")
    return base / "spool"


def vault_montar(tmp_path: Path) -> Path:
    """La tanda t1 cerrada (5 al test, 5 de reserva) y todo lo que /montar lee."""
    vault, *_ = cerrada(tmp_path)
    from trovefy.arranque.estado import marcar_hecho
    from trovefy.vault.producto import actualizar_producto

    marcar_hecho(vault, "05", datos={"page_id": PAGINA})
    actualizar_producto(vault, P, {"paises": {PAIS: {"tracking": {
        "dataset_id": DATASET, "dataset_nombre": "PRUEBA ZZ", "estado": "verificado"}}}}, [], "/test", AHORA)
    cfg = vault / "config"
    shutil.copy(RAIZ / "templates" / "cerebro" / "config" / "umbrales.yaml", cfg / "umbrales.yaml")
    caja = yaml.safe_load((RAIZ / "templates" / "cerebro" / "config" / "caja.yaml").read_text(encoding="utf-8"))
    caja["cuenta"] = {"id": CUENTA, "moneda": "COP"}
    (cfg / "caja.yaml").write_text(yaml.safe_dump(caja, allow_unicode=True), encoding="utf-8")
    montar = yaml.safe_load((RAIZ / "templates" / "cerebro" / "config" / "montar.yaml").read_text(encoding="utf-8"))
    montar["dsa"]["beneficiario"]["valor"] = "Beneficiario Prueba"
    montar["dsa"]["pagador"]["valor"] = "Pagador Prueba"
    (cfg / "montar.yaml").write_text(yaml.safe_dump(montar, allow_unicode=True), encoding="utf-8")
    frontmatter.escribir(vault / "productos" / P / "checkout" / PAIS / "TRACKING.md",
                         {"tipo": "tracking", "producto": P, "pais": PAIS, "dataset_id": DATASET,
                          "dataset_nombre": "PRUEBA ZZ", "estado": "verificado",
                          "ejecutor": {"dataset_permitido": True, "pagina_permitida": True, "lectura_ok": True,
                                       "fecha": "2026-11-19T10:00:00-05:00"}}, "# Tracking\n")
    return vault


def manifest_filas(vault: Path, tanda: str = "t1") -> tuple[Path, list[dict]]:
    import csv

    ruta = vault / "productos" / P / "creativos" / PAIS / tanda / "manifest.csv"
    return ruta, list(csv.DictReader(ruta.read_text(encoding="utf-8").splitlines()))


def reescribir_manifest(vault: Path, filas: list[dict], tanda: str = "t1") -> None:
    """Reescribe el manifiesto (la tanda deja de estar aprobada: otro sha)."""
    import csv
    import io

    from trovefy.creativos.manifest import CABECERA

    ruta, _ = manifest_filas(vault, tanda)
    s = io.StringIO()
    w = csv.DictWriter(s, fieldnames=CABECERA, lineterminator="\n")
    w.writeheader()
    for f in filas:
        w.writerow(f)
    ruta.write_text(s.getvalue(), encoding="utf-8")


__all__ = [
    "AHORA",
    "CUENTA",
    "DATASET",
    "PAGINA",
    "PAIS",
    "TRM",
    "P",
    "escribir_spool",
    "manifest_filas",
    "reescribir_manifest",
    "vault_montar",
]
