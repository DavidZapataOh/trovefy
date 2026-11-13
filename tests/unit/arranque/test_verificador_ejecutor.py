import json
import os
from pathlib import Path

import pytest
from trovefy.arranque.estado import marcar_hecho
from trovefy.arranque.verificadores import REGISTRO
from trovefy.arranque.verificadores.ejecutor import verificar_bot, verificar_meta
from trovefy.vault.andamio import crear_vault

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "ejecutor_estado"
META_OK = json.loads((FIX / "meta.json").read_text())
EMP_OK = json.loads((FIX / "emparejamiento.json").read_text())
ARREGLO_EMP = "sudo -u trovefy-exec /home/trovefy-exec/.local/bin/trovefy-ejecutor emparejar"
ARREGLO_META = "sudo -u trovefy-exec /home/trovefy-exec/.local/bin/trovefy-ejecutor comprobar-meta"


@pytest.fixture
def vault(tmp_path_factory):
    v = tmp_path_factory.mktemp("vault")
    crear_vault(v)
    return v


def estado(raiz, nombre, datos):
    (raiz / "estado").mkdir(parents=True, exist_ok=True)
    (raiz / "estado" / nombre).write_text(json.dumps(datos))


def paso06(vault, moneda="COP", zona="America/Bogota"):
    marcar_hecho(vault, "06", datos={"act_id": "0000000000000000", "moneda": moneda, "zona": zona})


def limites(raiz, offset=1, moneda="COP", cuenta="act_0000000000000000"):
    estado(raiz, "limites.json", {"version": 1, "cuentas": {cuenta: {"moneda": moneda, "offset": offset}}})


def todo(r):
    return json.dumps([r.motivo, r.lineas, r.arreglos, r.evidencia, r.datos])


def test_registrados():
    assert REGISTRO["12"] is verificar_bot and REGISTRO["13"] is verificar_meta


def test_12_emparejado_verifica(tmp_path, vault):
    estado(tmp_path, "emparejamiento.json", {**EMP_OK, "user_id": 123})
    r = verificar_bot(vault, raiz=tmp_path)
    assert r.ok is True and r.evidencia
    assert "123" not in (vault / r.evidencia[0]).read_text() and "123" not in todo(r)


def test_12_servicio_sin_arrancar_se_arranca_en_el_13(tmp_path, vault):
    estado(tmp_path, "emparejamiento.json", EMP_OK)
    r = verificar_bot(vault, raiz=tmp_path)
    assert r.ok is True and "el servicio arranca en el paso 13" in r.lineas
    assert not any("systemctl" in a for a in r.arreglos)  # sin META_TOKEN, arrancarlo saldría con 2


def test_12_latido_viejo_pide_reiniciar(tmp_path, vault):
    estado(tmp_path, "emparejamiento.json", EMP_OK)
    estado(tmp_path, "latido.json", {"fecha": "2020-01-01T00:00:00+00:00"})
    r = verificar_bot(vault, raiz=tmp_path)
    assert r.ok is True and any("no late" in x for x in r.lineas)
    assert "sudo systemctl restart trovefy-ejecutor" in r.arreglos


def test_12_sin_ejecutor_instalado_no_medido(tmp_path, vault):
    r = verificar_bot(vault, raiz=tmp_path / "no-existe")
    assert r.ok is None and "el ejecutor" in r.motivo and "instalado" in r.motivo


def test_12_sin_emparejar_falla(tmp_path, vault):
    (tmp_path / "estado").mkdir()
    r = verificar_bot(vault, raiz=tmp_path)
    assert r.ok is False and ARREGLO_EMP in r.arreglos
    estado(tmp_path, "emparejamiento.json", {"emparejado": False, "fecha": "x"})
    assert verificar_bot(vault, raiz=tmp_path).ok is False


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignora permisos")
def test_12_sin_permiso_no_medido(tmp_path, vault):
    estado(tmp_path, "emparejamiento.json", EMP_OK)
    (tmp_path / "estado" / "emparejamiento.json").chmod(0)
    r = verificar_bot(vault, raiz=tmp_path)
    assert r.ok is None and "grupo trovefy" in r.motivo


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignora permisos")
def test_12_raiz_sin_acceso_no_medido(tmp_path, vault):
    raiz = tmp_path / "raiz"
    estado(raiz, "emparejamiento.json", EMP_OK)
    raiz.chmod(0)  # como la carpeta del ejecutor para quien no está en el grupo: ni siquiera se ve estado/
    try:
        r = verificar_bot(vault, raiz=raiz)
    finally:
        raiz.chmod(0o755)
    assert r.ok is None
    assert r.motivo == ("no medido: tu usuario no está en el grupo trovefy "
                        "(cierra y abre la terminal y Claude Code tras instalar)")


def test_estado_con_token_no_se_lee(tmp_path, vault):
    token = "EAAB" + "x" * 60
    paso06(vault)
    estado(tmp_path, "meta.json", {**META_OK, "extra": token})
    r = verificar_meta(vault, raiz=tmp_path)
    assert r.ok is None and "secreto" in r.motivo and token not in todo(r)
    estado(tmp_path, "emparejamiento.json", {**EMP_OK, "x": token})
    r = verificar_bot(vault, raiz=tmp_path)
    assert r.ok is None and token not in todo(r)


def test_13_cop_con_offset_oficial_verifica_y_cita_d37(tmp_path, vault):
    paso06(vault)
    estado(tmp_path, "meta.json", META_OK)
    limites(tmp_path)
    r = verificar_meta(vault, raiz=tmp_path)
    assert r.ok is True and r.datos["moneda"] == "COP" and r.datos["offset"] == "1"
    assert any("D-37" in x for x in r.lineas)
    assert "0000000000000000" not in todo(r)


def test_13_usd_offset_100_verifica(tmp_path, vault):
    paso06(vault, "USD", "America/Bogota")
    estado(tmp_path, "meta.json", {**META_OK, "currency": "USD", "offset": 100})
    limites(tmp_path, 100, "USD")
    r = verificar_meta(vault, raiz=tmp_path)
    assert r.ok is True and not any("D-37" in x for x in r.lineas)


def test_offsets_oficiales_de_la_resolucion():
    from trovefy.arranque.verificadores.ejecutor import OFFSETS_OFICIALES

    assert OFFSETS_OFICIALES == {"COP": 1, "USD": 100}


@pytest.mark.parametrize("cambio,frase", [
    ({"offset": None}, "offset sin confirmar (P-21)"),
    ({"offset": 100}, "el offset 100 no es el oficial de COP (1)"),
    ({"currency": "USD"}, "la moneda de Meta (USD) no coincide con la del paso 06 (COP)"),
    ({"timezone_name": "Europe/Sofia"}, "zona horaria"),
    ({"account_status": 2}, "la cuenta no está activa"),
    ({"validate_only": {"ok": False, "motivo": "permiso ads_management"}}, "validate_only falló: permiso ads_management"),
])
def test_13_falla_con_motivo(tmp_path, vault, cambio, frase):
    paso06(vault)
    estado(tmp_path, "meta.json", {**META_OK, **cambio})
    r = verificar_meta(vault, raiz=tmp_path)
    assert r.ok is False and frase in r.motivo and ARREGLO_META in r.arreglos


def test_13_otra_cuenta_no_medido(tmp_path, vault):
    paso06(vault)
    estado(tmp_path, "meta.json", {**META_OK, "cuenta": "act_0000000000000001"})
    r = verificar_meta(vault, raiz=tmp_path)
    assert r.ok is None and "otra cuenta" in r.motivo and "0000000000000001" not in todo(r)


def test_13_sin_meta_json_falla(tmp_path, vault):
    paso06(vault)
    (tmp_path / "estado").mkdir()
    r = verificar_meta(vault, raiz=tmp_path)
    assert r.ok is False and ARREGLO_META in r.arreglos


def test_13_moneda_sin_offset_oficial_no_medido(tmp_path, vault):
    paso06(vault, "EUR", "Europe/Madrid")
    estado(tmp_path, "meta.json", {**META_OK, "currency": "EUR", "timezone_name": "Europe/Madrid"})
    r = verificar_meta(vault, raiz=tmp_path)
    assert r.ok is None and "(P-21)" in r.motivo


@pytest.mark.parametrize("prep", [
    None,
    lambda raiz: limites(raiz, None),
    lambda raiz: limites(raiz, 100),
    lambda raiz: limites(raiz, 1, cuenta="act_0000000000000001"),
    lambda raiz: estado(raiz, "limites.json", {"cuentas": []}),
])
def test_13_offset_no_fijado_en_limites_no_medido(tmp_path, vault, prep):
    paso06(vault)
    estado(tmp_path, "meta.json", META_OK)
    if prep:
        prep(tmp_path)
    r = verificar_meta(vault, raiz=tmp_path)
    assert r.ok is None
    assert r.motivo == "no medido: el offset aún no está fijado en limites.yaml (repite comprobar-meta)"
    assert ARREGLO_META in r.arreglos and "0000000000000001" not in todo(r)
    assert "sudo systemctl start trovefy-ejecutor" in r.arreglos  # sin latido: limites.json lo escribe el servicio
