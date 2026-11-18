"""Test Events por el MCP de Meta, solo lectura (plan 19, Tarea 8): los cuatro eventos y Purchase una sola vez."""

import importlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from embudo.ejemplos_embudo import PAIS, P, vault_embudo
from trovefy import cli
from trovefy.tracking.eventos import (
    capi_en_meta,
    contar_eventos,
    diferencia,
    evaluar_eventos,
)
from trovefy.tracking.salida import leer_tracking

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "tracking"
BIEN = {"PageView": 3, "ViewContent": 2, "InitiateCheckout": 2, "Purchase": 1}


def _json(nombre: str):
    return json.loads((FIX / nombre).read_text(encoding="utf-8"))


def test_contar_eventos():
    assert contar_eventos(_json("stats-antes.json")) == {"PageView": 12, "ViewContent": 4, "InitiateCheckout": 1,
                                                          "Purchase": 0}
    # Envuelto por el cliente MCP y con un conteo como texto; «Lead» no cuenta.
    assert contar_eventos({"structuredContent": _json("stats-despues.json")}) == {
        "PageView": 15, "ViewContent": 6, "InitiateCheckout": 3, "Purchase": 1}
    assert contar_eventos({"data": []}) == {"PageView": 0, "ViewContent": 0, "InitiateCheckout": 0, "Purchase": 0}


def test_diferencia_de_instantaneas():
    antes = contar_eventos(_json("stats-antes.json"))
    despues = contar_eventos(_json("stats-despues.json"))
    assert diferencia(antes, despues) == BIEN
    assert diferencia(None, despues) is None
    assert diferencia(despues, antes) is None  # bajó: ventanas distintas, no se puede restar


def test_forma_desconocida_no_medido():
    for raro in (None, "x", {"error": "sin permiso"}, {"data": [{"value": "PageView", "count": -1}]},
                 {"data": [{"value": "PageView", "count": True}]}):
        assert contar_eventos(raro) is None
    estado, motivos = evaluar_eventos(None)
    assert estado == "no_medido" and motivos[0].startswith("no medido")


def test_cuatro_eventos_verificado():
    assert evaluar_eventos(BIEN) == ("verificado", [])


def test_purchase_doble_falla():
    conteo = diferencia(contar_eventos(_json("stats-antes.json")), contar_eventos(_json("stats-purchase-doble.json")))
    estado, motivos = evaluar_eventos(conteo)
    assert estado == "no_verificado"
    assert "no verificado: Purchase duplicado (2 para 1 pedido)" in motivos


def test_purchase_ausente_no_medido():
    estado, motivos = evaluar_eventos({**BIEN, "Purchase": 0})
    assert estado == "no_medido" and "no medido: Purchase no llegó" in motivos


def test_otro_evento_ausente():
    estado, motivos = evaluar_eventos({**BIEN, "InitiateCheckout": 0})
    assert estado == "no_medido" and "no medido: InitiateCheckout no llegó" in motivos


def test_varios_pedidos():
    assert evaluar_eventos({**BIEN, "Purchase": 2}, pedidos_de_prueba=2)[0] == "verificado"
    estado, motivos = evaluar_eventos({**BIEN, "Purchase": 1}, pedidos_de_prueba=2)
    assert estado == "no_verificado" and any("falta" in m for m in motivos)
    with pytest.raises(ValueError):
        evaluar_eventos(BIEN, pedidos_de_prueba=0)


def test_capi_en_meta():
    assert capi_en_meta(_json("detalles-con-servidor.json")) is True
    sin = _json("detalles-con-servidor.json")
    sin["structuredContent"]["server_last_fired_time"] = None
    assert capi_en_meta(sin) is False
    assert capi_en_meta({"web": [{"event_name": "Purchase", "server_events": 0}]}) is False
    assert capi_en_meta({"web": [{"event_name": "Purchase", "server_events": 3}]}) is True
    assert capi_en_meta({"id": "1111111111111111", "name": "X"}) is None
    assert capi_en_meta("nada") is None


# --- CLI ---------------------------------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path, monkeypatch):
    tracking_cli = importlib.import_module("trovefy.tracking_cli")

    from tracking.test_publico import _abrir

    v = vault_embudo(tmp_path)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setattr(tracking_cli, "_ahora",
                        lambda: datetime(2026, 11, 17, 12, 0, 0, tzinfo=ZoneInfo("America/Bogota")))
    monkeypatch.setattr(tracking_cli, "_abrir", _abrir({}))
    assert cli.main(["tracking", "preparar", "--producto", P, "--pais", PAIS]) == 0
    assert cli.main(["tracking", "dataset", "--producto", P, "--pais", PAIS,
                     "--instantanea", str(FIX / "datasets.json")]) == 0
    return v


def _eventos(*extra: str) -> list[str]:
    return ["tracking", "eventos", "--producto", P, "--pais", PAIS, *extra]


def _compra(v: Path) -> Path:
    return v / "productos" / P / "checkout" / PAIS / "compra" / "events-manager.json"


def test_cli_eventos_verificado_y_capi(vault, capsys):
    assert cli.main(_eventos("--antes", str(FIX / "stats-antes.json"), "--despues", str(FIX / "stats-despues.json"),
                             "--detalles", str(FIX / "detalles-con-servidor.json"))) == 0
    t = leer_tracking(vault, P, PAIS)
    assert (t.estado, t.eventos, t.fuente_eventos, t.capi) == ("verificado", BIEN, "mcp", "visto_en_meta")
    resumen = json.loads(_compra(vault).read_text(encoding="utf-8"))
    assert resumen["fuente"] == "mcp" and resumen["conteo"] == BIEN and resumen["capi"] is True


def test_cli_eventos_no_guarda_crudo(vault, capsys):
    assert cli.main(_eventos("--antes", str(FIX / "stats-antes.json"), "--despues", str(FIX / "stats-despues.json"))) == 0
    for archivo in (vault / "productos").rglob("*"):
        if archivo.is_file():
            texto = archivo.read_text(encoding="utf-8", errors="ignore")
            assert "client_conversation_id" not in texto and "start_time" not in texto and "Lead" not in texto


def test_cli_eventos_purchase_doble(vault, capsys):
    assert cli.main(_eventos("--antes", str(FIX / "stats-antes.json"),
                             "--despues", str(FIX / "stats-purchase-doble.json"))) == 1
    assert "Purchase duplicado" in capsys.readouterr().out
    assert leer_tracking(vault, P, PAIS).estado == "no_verificado"


def test_cli_capi_no_visto_no_verifica(vault, capsys):
    sin = _json("detalles-con-servidor.json")
    sin["structuredContent"]["server_last_fired_time"] = None
    ruta = vault.parent / "det.json"
    ruta.write_text(json.dumps(sin), encoding="utf-8")
    assert cli.main(_eventos("--antes", str(FIX / "stats-antes.json"), "--despues", str(FIX / "stats-despues.json"),
                             "--detalles", str(ruta))) == 1
    t = leer_tracking(vault, P, PAIS)
    assert t.estado == "no_verificado" and t.capi != "visto_en_meta"


def test_manual_con_captura_registra_fuente(vault, tmp_path, capsys):
    png = tmp_path / "te.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    assert cli.main(["checkout", "evidencia", "--producto", P, "--pais", PAIS, "--clave", "test-events",
                     "--desde", str(png)]) == 0
    assert cli.main(_eventos("--manual", "PageView=3,ViewContent=2,InitiateCheckout=2,Purchase=1",
                             "--captura", "test-events")) == 0
    t = leer_tracking(vault, P, PAIS)
    assert (t.estado, t.fuente_eventos, t.eventos) == ("verificado", "captura", BIEN)
    assert json.loads(_compra(vault).read_text(encoding="utf-8"))["fuente"] == "captura"


def test_manual_sin_captura_rechazado(vault, capsys):
    assert cli.main(_eventos("--manual", "PageView=3,ViewContent=2,InitiateCheckout=2,Purchase=1")) == 2
    assert cli.main(_eventos("--manual", "PageView=3,ViewContent=2,InitiateCheckout=2,Purchase=1",
                             "--captura", "test-events")) == 2
    assert "captura" in capsys.readouterr().err
    assert leer_tracking(vault, P, PAIS).fuente_eventos is None


def test_manual_mal_escrito(vault, tmp_path, capsys):
    png = tmp_path / "te.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    cli.main(["checkout", "evidencia", "--producto", P, "--pais", PAIS, "--clave", "test-events", "--desde", str(png)])
    for malo in ("PageView=3", "PageView=x,ViewContent=2,InitiateCheckout=2,Purchase=1",
                 "PageView=3,ViewContent=2,InitiateCheckout=2,Purchase=1,Lead=4"):
        assert cli.main(_eventos("--manual", malo, "--captura", "test-events")) == 2


def test_cli_mezcla_de_fuentes(vault, capsys):
    assert cli.main(_eventos("--antes", str(FIX / "stats-antes.json"))) == 2
    assert cli.main(_eventos("--antes", str(FIX / "stats-antes.json"), "--despues", str(FIX / "stats-despues.json"),
                             "--manual", "PageView=1,ViewContent=1,InitiateCheckout=1,Purchase=1",
                             "--captura", "test-events")) == 2


def test_cli_forma_desconocida(vault, capsys):
    ruta = vault.parent / "raro.json"
    ruta.write_text('{"error": "x"}', encoding="utf-8")
    assert cli.main(_eventos("--antes", str(ruta), "--despues", str(FIX / "stats-despues.json"))) == 1
    assert "no medido" in capsys.readouterr().out
    assert leer_tracking(vault, P, PAIS).estado == "dataset"


def test_cli_sin_dataset(tmp_path, monkeypatch, capsys):
    v = vault_embudo(tmp_path)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    assert cli.main(["tracking", "preparar", "--producto", P, "--pais", PAIS]) == 0
    assert cli.main(_eventos("--antes", str(FIX / "stats-antes.json"), "--despues", str(FIX / "stats-despues.json"))) == 2
