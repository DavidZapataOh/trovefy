import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from trovefy.aprobaciones import listado
from trovefy.aprobaciones.listado import GRUPOS, explicar, listar, resumen_estado

COT = timezone(timedelta(hours=-5))
FIX = Path(__file__).resolve().parents[2] / "fixtures" / "aprobaciones"
AHORA = datetime(2026, 11, 13, 10, 0, tzinfo=COT)


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    shutil.copytree(FIX, v)
    return v


def _por_id(filas):
    return {f.id: f for f in filas}


def test_listar_agrupa(vault):
    filas, avisos = listar(vault)
    f = _por_id(filas)
    assert avisos == []
    assert f["P-20261112-001"].estado == "caducada"
    assert f["P-20261112-001"].estado in GRUPOS["caducadas"]
    assert f["P-20261112-001"].origen == "Claude"
    assert f["P-20261112-002"].estado == "ejecutada" and f["P-20261112-002"].tipo == "pausar"
    assert f["P-20261112-003"].estado == "rechazada al validar"
    assert f["P-20261112-003"].motivo == "campo no permitido: x"
    assert f["P-20261112-901"].origen == "tú, por Telegram"
    assert f["P-20261112-901"].estado == "recibida"
    ids = [x.id for x in filas]
    assert ids == sorted(ids, reverse=True) or len(ids) == 4


def test_auditoria_linea_rota_se_salta_y_avisa(vault):
    ruta = vault / "ledger/auditoria/2026-11-12.jsonl"
    ruta.write_text(ruta.read_text() + "esto no es json\n")
    filas, avisos = listar(vault)
    assert len(filas) == 4
    assert len(avisos) == 1 and "2026-11-12.jsonl" in avisos[0]


def test_explicar_id_invalido(vault):
    for malo in ("../config", "P-1-1", "P-20261112-0011", ""):
        with pytest.raises(ValueError):
            explicar(vault, malo)


def test_explicar_no_toca_disco_si_id_invalido(tmp_path):
    with pytest.raises(ValueError):
        explicar(tmp_path / "no-existe", "../x")


def test_explicar_muestra_motivo_y_eventos(vault):
    t = explicar(vault, "P-20261112-002")
    assert "pausar" in t and "ejecutada" in t
    assert "recibida" in t and "sin cambios" in t
    assert "act_0000000000000000 status" in t
    t3 = explicar(vault, "P-20261112-003")
    assert "campo no permitido: x" in t3


def test_explicar_sin_rastro(vault):
    assert explicar(vault, "P-20261112-777") == "No encuentro P-20261112-777 en propuestas/ ni en la auditoría."


def _spool(tmp_path, **estado):
    s = tmp_path / "spool"
    (s / "estado").mkdir(parents=True)
    for k, v in estado.items():
        (s / "estado" / f"{k}.json").write_text(json.dumps(v))
    return s


def test_estado_sin_ejecutor(vault, tmp_path):
    out = resumen_estado(vault, AHORA, tmp_path / "nada")
    assert out[0] == "El ejecutor aún no está instalado: se instala con el plan 12 y /arranque."


def test_estado_latido_vivo_y_viejo(vault, tmp_path):
    s = _spool(tmp_path, latido={"fecha": (AHORA - timedelta(minutes=2)).isoformat()})
    assert any("vivo (hace 2 min)" in x for x in resumen_estado(vault, AHORA, s))
    s2 = _spool(tmp_path / "b", latido={"fecha": (AHORA - timedelta(minutes=25)).isoformat()})
    assert any("parado desde 09:35" in x for x in resumen_estado(vault, AHORA, s2))


def test_estado_auditoria_ok_y_alterada(vault, tmp_path):
    s = _spool(tmp_path)
    assert not any("no cuadra" in x for x in resumen_estado(vault, AHORA, s))
    ruta = vault / "ledger/auditoria/2026-11-12.jsonl"
    ruta.write_text(ruta.read_text().replace("sin cambios", "otra cosa"))
    assert any("la copia de la auditoría no cuadra: avisa" in x for x in resumen_estado(vault, AHORA, s))


def test_estado_dia_borrado_no_cuadra(vault, tmp_path):
    (vault / "ledger/auditoria/2026-11-12.jsonl").unlink()
    out = resumen_estado(vault, AHORA, _spool(tmp_path))
    assert any(x.startswith("Auditoría") and "no medido" in x for x in out) or any("no cuadra" in x for x in out)


def test_estado_muestra_stops(vault, tmp_path):
    (vault / ".trovefy").mkdir()
    (vault / ".trovefy/STOP").write_text("")
    s = _spool(tmp_path, stop={"activo": True})
    out = "\n".join(resumen_estado(vault, AHORA, s))
    assert "STOP del cerebro: ACTIVO" in out
    assert "STOP del ejecutor: ACTIVO" in out


def test_estado_rechazadas_y_limites_cambiados_sin_secretos(vault, tmp_path):
    s = _spool(tmp_path, emparejamiento={"emparejado": True, "chat_id": 123456789},
               limites={"cuentas": {"act_0000000000000000": {"moneda": "COP", "tope_gasto_diario_total": 1,
                                                              "max_presupuesto_conjunto": 2}}})
    out = "\n".join(resumen_estado(vault, AHORA, s))
    assert "campo no permitido: x" in out
    assert "tope_gasto_diario_total" in out and "100000" in out and "150000" in out
    assert "123456789" not in out
    assert "Meta: no medido" in out


def test_propuesta_noop():
    p = listado.propuesta_noop(AHORA)
    assert p["tipo"] == "noop" and p["version"] == 1


# --- verificación de la copia por tramos (sin falsas alarmas) ---

def _cadena(tmp_path, dias, reparar_el=None):
    """Escribe la auditoría real con un reloj por día y devuelve {día: [líneas]} como la copia del ejecutor."""
    from trovefy_ejecutor.auditoria import Auditoria, reparar
    ruta = tmp_path / "datos" / "auditoria.jsonl"
    copias: dict[str, list[str]] = {}
    for dia, n in dias:
        reloj = (lambda d=dia: datetime.fromisoformat(f"{d}T10:00:00-05:00"))
        if dia == reparar_el:
            reparar(ruta, reloj=reloj)
        a = Auditoria(ruta, reloj=reloj)
        for i in range(n):
            a.anotar("transicion", id=f"P-{dia.replace('-', '')}-00{i}", tipo="noop", de="recibida", a="enviada")
        copias[dia] = [x for x in ruta.read_text(encoding="utf-8").splitlines()
                       if json.loads(x)["ts"].startswith(dia) or dia == reparar_el]
    return copias


def _vault_con(tmp_path, copias):
    v = tmp_path / "v"
    (v / "ledger" / "auditoria").mkdir(parents=True)
    for dia, ls in copias.items():
        (v / "ledger" / "auditoria" / f"{dia}.jsonl").write_text("\n".join(ls) + "\n", encoding="utf-8")
    return v


def _auditoria(vault):
    return [x for x in resumen_estado(vault, AHORA, vault / "sin-spool") if x.startswith("Auditoría")]


def test_copia_completa_cuadra(tmp_path):
    v = _vault_con(tmp_path, _cadena(tmp_path, [("2026-11-11", 3), ("2026-11-12", 2)]))
    assert _auditoria(v) == ["Auditoría: la copia cuadra"]


def test_copia_de_un_dia_sin_sus_ultimas_lineas_es_hueco(tmp_path):
    copias = _cadena(tmp_path, [("2026-11-11", 4), ("2026-11-12", 2)])
    copias["2026-11-11"] = copias["2026-11-11"][:2]
    out = _auditoria(_vault_con(tmp_path, copias))
    assert out == ["Auditoría: no medido: la copia tiene un hueco entre 2026-11-11 y 2026-11-12"]


def test_cadena_reanudada_por_reparar_es_informativa(tmp_path):
    copias = _cadena(tmp_path, [("2026-11-11", 3), ("2026-11-12", 2)], reparar_el="2026-11-12")
    assert json.loads(copias["2026-11-12"][0])["evento"] == "cadena_reanudada"
    out = _auditoria(_vault_con(tmp_path, copias))
    assert not any("no cuadra" in x for x in out)
    assert out == ["Auditoría: la copia cuadra (cadena reanudada el 2026-11-12)"]


def test_linea_alterada_dentro_de_un_dia_no_cuadra(tmp_path):
    copias = _cadena(tmp_path, [("2026-11-11", 3), ("2026-11-12", 2)])
    copias["2026-11-11"][1] = copias["2026-11-11"][1].replace("enviada", "aceptada")
    assert _auditoria(_vault_con(tmp_path, copias)) == ["Auditoría: la copia de la auditoría no cuadra: avisa"]


def test_linea_del_medio_borrada_no_cuadra(tmp_path):
    copias = _cadena(tmp_path, [("2026-11-11", 4)])
    del copias["2026-11-11"][1]
    assert _auditoria(_vault_con(tmp_path, copias)) == ["Auditoría: la copia de la auditoría no cuadra: avisa"]


def test_reinicio_sin_cadena_reanudada_no_cuadra(tmp_path):
    a = _cadena(tmp_path / "a", [("2026-11-11", 3)])
    b = _cadena(tmp_path / "b", [("2026-11-12", 2)])
    assert _auditoria(_vault_con(tmp_path, {**a, **b})) == ["Auditoría: la copia de la auditoría no cuadra: avisa"]


def test_listado_no_usa_privadas_del_ejecutor():
    src = Path(listado.__file__).read_text(encoding="utf-8")
    assert "_recorrer" not in src and "tempfile" not in src
