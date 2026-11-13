import json
import os
from datetime import UTC, datetime

import pytest
from ejecutor.fabricas import alerta
from trovefy_ejecutor.auditoria import Auditoria
from trovefy_ejecutor.comandos import MotivoRechazo, nota_motivo
from trovefy_ejecutor.ejecutar import Resultado, ResultadoOp
from trovefy_ejecutor.esquema import cargar_propuesta
from trovefy_ejecutor.estado import FilaPropuesta
from trovefy_ejecutor.reloj import ZONA_COT
from trovefy_ejecutor.vault_copia import CopiaVault

T = datetime(2026, 11, 12, 14, 7, tzinfo=ZONA_COT)


def vault(tmp_path):
    v = tmp_path / "v"
    v.mkdir()
    return v


def fila(clase="no_gasto", **datos):
    p = cargar_propuesta(alerta())
    return FilaPropuesta(id=p.id, tipo="presupuesto" if clase == "gasto" else p.tipo, clase=clase, cuenta=None, estado="ejecutada",
                         propuesta=p, recibida=T, actualizada=T, chat_id=1, message_id=2, datos=datos)


def test_fuera_de_las_tres_carpetas_es_error(tmp_path):
    c = CopiaVault(vault(tmp_path), tmp_path / "pend")
    for mala in ("wiki/x.md", "propuestas/../wiki/x.md", "raw/otra/x.md", "/etc/x", "propuestas"):
        with pytest.raises(ValueError):
            c.escribir(mala, "no")


def test_escribe_y_crea_subcarpetas(tmp_path):
    v = vault(tmp_path)
    c = CopiaVault(v, tmp_path / "pend")
    assert c.escribir("raw/telegram/motivos/a.md", "x") is True
    assert (v / "raw/telegram/motivos/a.md").read_text() == "x"
    assert oct((v / "raw/telegram/motivos/a.md").stat().st_mode & 0o777) == "0o640"
    assert c.estado() == "ok"


def test_raiz_inexistente_no_se_crea(tmp_path):
    c = CopiaVault(tmp_path / "v", tmp_path / "pend")
    assert c.escribir("propuestas/a.md", "x") is False
    assert not (tmp_path / "v").exists()


def test_vault_no_escribible_queda_pendiente(tmp_path):
    v = vault(tmp_path)
    (v / "propuestas").mkdir()
    (v / "propuestas").chmod(0o500)
    c = CopiaVault(v, tmp_path / "pend")
    try:
        if os.access(v / "propuestas", os.W_OK):
            pytest.skip("se ejecuta como root")
        assert c.escribir("propuestas/P-20261112-001.md", "x") is False and c.estado() == "no escribible"
        assert oct((tmp_path / "pend").stat().st_mode & 0o777) == "0o700"
    finally:
        (v / "propuestas").chmod(0o700)
    assert c.reintentar() == 0 and (v / "propuestas/P-20261112-001.md").read_text() == "x"
    assert c.estado() == "ok"


def test_pendientes_en_orden_y_roto_aparte(tmp_path):
    v = vault(tmp_path)
    pend = tmp_path / "pend"
    c = CopiaVault(v, pend)
    (v / "propuestas").mkdir()
    (v / "propuestas").chmod(0o500)
    try:
        if os.access(v / "propuestas", os.W_OK):
            pytest.skip("se ejecuta como root")
        c.escribir("propuestas/a.md", "uno")
        c.escribir("propuestas/a.md", "dos")
    finally:
        (v / "propuestas").chmod(0o700)
    (pend / "0.json").write_text("{no es json")
    assert c.reintentar() == 0
    assert (v / "propuestas/a.md").read_text() == "dos"
    assert (pend / "rotos" / "0.json").exists()


def test_motivo_nunca_sobrescribe(tmp_path):
    v = vault(tmp_path)
    c = CopiaVault(v, tmp_path / "pend")
    n = nota_motivo(MotivoRechazo("P-20261112-001", "no me gusta", T), None)
    assert c.motivo(n) is True
    assert c.motivo(type(n)(n.ruta_relativa, "OTRO")) is False
    assert (v / n.ruta_relativa).read_text() == n.contenido
    assert c.reintentar() == 0 and not list((tmp_path / "pend").glob("*.json"))


def test_enlace_simbolico_en_carpeta_no_se_sigue(tmp_path):
    v = vault(tmp_path)
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (v / "propuestas").symlink_to(fuera)
    c = CopiaVault(v, tmp_path / "pend")
    assert c.escribir("propuestas/a.md", "x") is False
    assert not list(fuera.iterdir())
    assert c.estado() == "no escribible"
    assert not list((tmp_path / "pend").glob("*.json"))


def test_enlace_simbolico_en_subcarpeta_no_se_sigue(tmp_path):
    v = vault(tmp_path)
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (v / "raw/telegram").mkdir(parents=True)
    (v / "raw/telegram/motivos").symlink_to(fuera)
    c = CopiaVault(v, tmp_path / "pend")
    assert c.escribir("raw/telegram/motivos/a.md", "x") is False
    assert not list(fuera.iterdir())


def test_enlace_simbolico_en_destino_se_reemplaza_sin_seguirlo(tmp_path):
    v = vault(tmp_path)
    (v / "propuestas").mkdir()
    objetivo = tmp_path / "secreto.txt"
    objetivo.write_text("intacto")
    (v / "propuestas/a.md").symlink_to(objetivo)
    c = CopiaVault(v, tmp_path / "pend")
    assert c.escribir("propuestas/a.md", "nuevo") is True
    assert objetivo.read_text() == "intacto"
    assert not (v / "propuestas/a.md").is_symlink()
    assert (v / "propuestas/a.md").read_text() == "nuevo"
    # con nuevo=True, un enlace colgante en el destino cuenta como existente
    (v / "propuestas/b.md").symlink_to(tmp_path / "no-existe")
    assert c.escribir("propuestas/b.md", "x", nuevo=True) is False
    assert not (tmp_path / "no-existe").exists()


def test_raiz_del_vault_enlace_es_valida(tmp_path):
    real = vault(tmp_path)
    enlace = tmp_path / "enlace"
    enlace.symlink_to(real)
    c = CopiaVault(enlace, tmp_path / "pend")
    assert c.escribir("propuestas/a.md", "x") is True
    assert (real / "propuestas/a.md").read_text() == "x"


def test_auditoria_conserva_hashes(tmp_path):
    v = vault(tmp_path)
    reloj = iter([datetime(2026, 11, 12, 15, 0, tzinfo=UTC), datetime(2026, 11, 13, 3, 0, tzinfo=UTC),
                  datetime(2026, 11, 13, 6, 0, tzinfo=UTC)])
    a = Auditoria(tmp_path / "a.jsonl", lambda: next(reloj))
    for i in range(3):
        a.anotar("transicion", id=f"P-20261112-00{i}", tipo="noop", de="recibida", a="enviada")
    c = CopiaVault(v, tmp_path / "pend")
    from datetime import date
    assert c.auditoria(a.ruta, date(2026, 11, 12)) is True
    assert c.auditoria(a.ruta, date(2026, 11, 12)) is True  # idempotente
    copia = v / "ledger/auditoria/2026-11-12.jsonl"
    lineas = [json.loads(x) for x in copia.read_text().splitlines()]
    # 15:00Z = 10:00 COT (12), 03:00Z = 22:00 COT (12), 06:00Z = 01:00 COT (13)
    assert [x["n"] for x in lineas] == [1, 2]
    assert lineas[0]["hash_prev"] == "0" * 64 and lineas[1]["hash_prev"] == lineas[0]["hash"]
    assert c.auditoria(a.ruta, date(2026, 11, 13)) is True
    assert [json.loads(x)["n"] for x in (v / "ledger/auditoria/2026-11-13.jsonl").read_text().splitlines()] == [3]


def test_auditoria_sin_origen_no_falla(tmp_path):
    from datetime import date
    c = CopiaVault(vault(tmp_path), tmp_path / "pend")
    assert c.auditoria(tmp_path / "no.jsonl", date(2026, 11, 12)) is True


def test_resultado_redactado(tmp_path):
    v = vault(tmp_path)
    c = CopiaVault(v, tmp_path / "pend")
    op = ResultadoOp("120", "daily_budget", "fallida", 1, 2, None, "falló bot123456:AA-x_y", error="x")
    r = Resultado("fallida", "token EAABsbCS1iHgBAZB0 caducado", (op,), parcial=True, ids_creados={"campana": "999"})
    assert c.resultado(fila("gasto", callback_id="cb1"), r, "FALLÓ: bot123456:AA-x_y") is True
    t = (v / "propuestas/P-20261112-010.md").read_text()
    assert "tipo: propuesta-resultado" in t and "callback_id: cb1" in t and "parcial: true" in t
    assert "tipo_propuesta: presupuesto" in t and "estado: ejecutada" in t
    assert "EAAB" not in t and "bot123456" not in t and "999" in t and "daily_budget" in t


def test_resultado_sin_r_y_callback_null(tmp_path):
    v = vault(tmp_path)
    c = CopiaVault(v, tmp_path / "pend")
    assert c.resultado(fila(), None, "texto") is True
    t = (v / "propuestas/P-20261112-010.md").read_text()
    assert "callback_id: null" in t and "parcial: false" in t and "texto" in t


def test_sin_vault_no_hace_nada(tmp_path):
    from datetime import date
    c = CopiaVault(None, tmp_path / "pend")
    assert c.resultado(fila(), None, "t") is True
    assert c.escribir("propuestas/a.md", "x") is True
    assert c.auditoria(tmp_path / "x", date(2026, 11, 12)) is True
    assert c.reintentar() == 0 and c.estado() == "ok"
    assert not (tmp_path / "pend").exists()
