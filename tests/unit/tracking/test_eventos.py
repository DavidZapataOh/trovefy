"""Test Events por el MCP de Meta, solo lectura (plan 19, Tarea 8): los cuatro eventos y Purchase una sola vez."""

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from embudo.ejemplos_embudo import PAIS, P, vault_embudo
from trovefy import cli
from trovefy.tracking.eventos import (
    capi_en_meta,
    contar_eventos,
    cubos_de_eventos,
    diferencia,
    evaluar_eventos,
)
from trovefy.tracking.salida import leer_tracking

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "tracking"
BIEN = {"PageView": 3, "ViewContent": 2, "InitiateCheckout": 2, "Purchase": 1}
DATASET = "1111111111111111"
ANTES_HORA = "2026-11-17T11:30:00+00:00"
DESDE = datetime(2026, 11, 17, 11, 30, tzinfo=ZoneInfo("UTC"))


def _json(nombre: str):
    return json.loads((FIX / nombre).read_text(encoding="utf-8"))


def test_contar_eventos():
    assert contar_eventos(_json("stats-antes.json")) == {"PageView": 12, "ViewContent": 4, "InitiateCheckout": 1,
                                                          "Purchase": 0}
    # Envuelto por el cliente MCP y con un conteo como texto; «Lead» no cuenta.
    assert contar_eventos({"structuredContent": _json("stats-despues.json")}) == {
        "PageView": 15, "ViewContent": 6, "InitiateCheckout": 3, "Purchase": 1}
    assert contar_eventos({"data": []}) == {"PageView": 0, "ViewContent": 0, "InitiateCheckout": 0, "Purchase": 0}


def _cubos(nombre: str):
    return cubos_de_eventos(_json(nombre))


def test_diferencia_de_instantaneas():
    assert diferencia(_cubos("stats-antes.json"), _cubos("stats-despues.json")) == BIEN
    assert diferencia(None, _cubos("stats-despues.json")) is None
    assert diferencia(_cubos("stats-despues.json"), _cubos("stats-antes.json")) is None  # bajó: no se puede restar


def _stats(*cubos: tuple[str, dict[str, int]], **extra) -> dict:
    return {"data": [{"start_time": t, "aggregation": "event",
                      "data": [{"value": e, "count": n} for e, n in filas.items()]} for t, filas in cubos], **extra}


def test_ventana_deslizante_por_cubo():
    # Entre «antes» y «después» la ventana se movió: el cubo de las 09:00 ya no está. Restar los totales daría
    # negativo (o, peor, un número falso); por cubo solo cuentan los cubos desde el más nuevo de «antes».
    antes = _stats(("2026-11-17T09:00:00+0000", {"PageView": 50, "Purchase": 3}),
                   ("2026-11-17T10:00:00+0000", {"PageView": 4}),
                   ("2026-11-17T11:00:00+0000", {"PageView": 1}))
    despues = _stats(("2026-11-17T10:00:00+0000", {"PageView": 4}),
                     ("2026-11-17T11:00:00+0000", {"PageView": 3, "ViewContent": 2, "InitiateCheckout": 1}),
                     ("2026-11-17T12:00:00+0000", {"PageView": 1, "InitiateCheckout": 1, "Purchase": 1}))
    assert diferencia(cubos_de_eventos(antes), cubos_de_eventos(despues)) == BIEN
    # Un cubo viejo que reaparece con más eventos no cuenta: es de antes de la prueba.
    despues_viejo = _stats(("2026-11-17T10:00:00+0000", {"PageView": 9, "Purchase": 2}),
                           *[(c["start_time"], {f["value"]: f["count"] for f in c["data"]}) for c in despues["data"][1:]])
    assert diferencia(cubos_de_eventos(antes), cubos_de_eventos(despues_viejo)) == BIEN


def test_ventana_que_pierde_el_cubo_mas_nuevo_no_medido():
    antes = _stats(("2026-11-17T11:00:00+0000", {"PageView": 1}))
    despues = _stats(("2026-11-17T12:00:00+0000", {"PageView": 5}))
    assert diferencia(cubos_de_eventos(antes), cubos_de_eventos(despues)) is None


def test_paginacion_no_medido():
    base = _stats(("2026-11-17T11:00:00+0000", {"PageView": 1}))
    con_mas = {**base, "paging": {"cursors": {"after": "x"}, "next": "https://graph.facebook.example/next"}}
    assert cubos_de_eventos(con_mas) is None
    assert contar_eventos(con_mas) is None
    assert cubos_de_eventos({"structuredContent": con_mas}) is None
    sin_mas = {**base, "paging": {"cursors": {"after": "x"}}}
    assert cubos_de_eventos(sin_mas) == {datetime(2026, 11, 17, 11, tzinfo=ZoneInfo("UTC")):
                                         {"PageView": 1, "ViewContent": 0, "InitiateCheckout": 0, "Purchase": 0}}


def test_cubo_sin_hora_no_medido():
    assert cubos_de_eventos({"data": [{"aggregation": "event", "data": [{"value": "PageView", "count": 1}]}]}) is None
    assert cubos_de_eventos({"data": [{"start_time": "ayer", "data": [{"value": "PageView", "count": 1}]}]}) is None


def test_forma_desconocida_no_medido():
    for raro in (None, "x", {"error": "sin permiso"}, {"data": [{"value": "PageView", "count": -1}]},
                 {"data": [{"value": "PageView", "count": True}]}):
        assert contar_eventos(raro) is None
    estado, motivos = evaluar_eventos(None)
    assert estado == "no_medido" and motivos[0].startswith("no medido")


def test_cuatro_eventos_verificado():
    assert evaluar_eventos(BIEN) == ("verificado", [])


def test_purchase_doble_falla():
    conteo = diferencia(_cubos("stats-antes.json"), _cubos("stats-purchase-doble.json"))
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
    assert capi_en_meta(_json("detalles-con-servidor.json"), DATASET, DESDE) is True
    sin = _json("detalles-con-servidor.json")
    sin["structuredContent"]["server_last_fired_time"] = None
    assert capi_en_meta(sin, DATASET, DESDE) is False
    assert capi_en_meta({"id": DATASET, "name": "X"}, DATASET, DESDE) is None
    assert capi_en_meta("nada", DATASET, DESDE) is None


def test_capi_solo_claves_conocidas():
    # Una clave cualquiera con «server» (un conteo, un booleano) ya no vale: solo server_last_fired_time.
    assert capi_en_meta({"id": DATASET, "web": [{"event_name": "Purchase", "server_events": 3}]}, DATASET, DESDE) is None
    assert capi_en_meta({"id": DATASET, "is_server_side": True}, DATASET, DESDE) is None


def test_capi_de_antes_de_la_prueba_no_vale():
    viejo = {"id": DATASET, "server_last_fired_time": "2026-11-17T11:00:00+0000"}
    assert capi_en_meta(viejo, DATASET, DESDE) is False
    assert capi_en_meta({"id": DATASET, "server_last_fired_time": "no es una fecha"}, DATASET, DESDE) is None


def test_capi_de_otro_dataset_no_medido():
    otro = {"id": "2222222222222222", "server_last_fired_time": "2026-11-17T11:41:00+0000"}
    assert capi_en_meta(otro, DATASET, DESDE) is None
    assert capi_en_meta({"server_last_fired_time": "2026-11-17T11:41:00+0000"}, DATASET, DESDE) is None


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
    monkeypatch.setattr(tracking_cli, "_esperar", lambda host: None)
    checkout_cli = importlib.import_module("trovefy.checkout_cli")
    monkeypatch.setattr(checkout_cli, "_ahora",
                        lambda: datetime(2026, 11, 17, 7, 0, 0, tzinfo=ZoneInfo("America/Bogota")))
    assert cli.main(["tracking", "preparar", "--producto", P, "--pais", PAIS]) == 0
    assert cli.main(["tracking", "dataset", "--producto", P, "--pais", PAIS,
                     "--instantanea", str(FIX / "datasets.json")]) == 0
    return v


def _eventos(*extra: str) -> list[str]:
    return ["tracking", "eventos", "--producto", P, "--pais", PAIS, "--antes-hora", ANTES_HORA, *extra]


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
    assert cli.main(_eventos("--antes", str(FIX / "stats-antes.json"), "--despues", str(FIX / "stats-despues.json"),
                             "--detalles", str(FIX / "detalles-con-servidor.json"))) == 0
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


def _captura(vault, tmp_path) -> None:
    png = tmp_path / "te.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    assert cli.main(["checkout", "evidencia", "--producto", P, "--pais", PAIS, "--clave", "test-events",
                     "--desde", str(png)]) == 0


MANUAL_BIEN = "PageView=3,ViewContent=2,InitiateCheckout=2,Purchase=1"


def test_cli_sin_capi_no_verifica(vault, capsys):
    """H1: sin lectura de la CAPI el estado no pasa a verificado (ruling: la CAPI es obligatoria)."""
    assert cli.main(_eventos("--antes", str(FIX / "stats-antes.json"), "--despues", str(FIX / "stats-despues.json"))) == 1
    assert "no verificado: falta CAPI" in capsys.readouterr().out
    t = leer_tracking(vault, P, PAIS)
    assert t.estado == "dataset" and t.eventos == BIEN
    assert any("no verificado: falta CAPI" in m for m in t.motivos)


def test_manual_con_captura_sin_capi_no_verifica(vault, tmp_path, capsys):
    _captura(vault, tmp_path)
    assert cli.main(_eventos("--manual", MANUAL_BIEN, "--captura", "test-events")) == 1
    t = leer_tracking(vault, P, PAIS)
    assert (t.estado, t.fuente_eventos, t.eventos) == ("dataset", "captura", BIEN)
    assert any("no verificado: falta CAPI" in m for m in t.motivos)
    assert json.loads(_compra(vault).read_text(encoding="utf-8"))["fuente"] == "captura"


def test_manual_con_capi_ya_vista_verifica(vault, tmp_path, capsys):
    assert cli.main(_eventos("--antes", str(FIX / "stats-antes.json"), "--despues", str(FIX / "stats-despues.json"),
                             "--detalles", str(FIX / "detalles-con-servidor.json"))) == 0
    _captura(vault, tmp_path)
    assert cli.main(_eventos("--manual", MANUAL_BIEN, "--captura", "test-events")) == 0
    t = leer_tracking(vault, P, PAIS)
    assert (t.estado, t.fuente_eventos, t.capi) == ("verificado", "captura", "visto_en_meta")


def test_manual_con_detalles_verifica(vault, tmp_path, capsys):
    _captura(vault, tmp_path)
    assert cli.main(_eventos("--manual", MANUAL_BIEN, "--captura", "test-events",
                             "--detalles", str(FIX / "detalles-con-servidor.json"))) == 0
    assert leer_tracking(vault, P, PAIS).estado == "verificado"


def test_manual_captura_anterior_a_antes_rechazada(vault, tmp_path, monkeypatch, capsys):
    checkout_cli = importlib.import_module("trovefy.checkout_cli")
    monkeypatch.setattr(checkout_cli, "_ahora",
                        lambda: datetime(2026, 11, 17, 6, 0, 0, tzinfo=ZoneInfo("America/Bogota")))  # 11:00 UTC
    _captura(vault, tmp_path)
    assert cli.main(_eventos("--manual", MANUAL_BIEN, "--captura", "test-events")) == 2
    assert "antes" in capsys.readouterr().err
    assert leer_tracking(vault, P, PAIS).fuente_eventos is None


def test_manual_exige_antes_hora(vault, tmp_path, capsys):
    _captura(vault, tmp_path)
    assert cli.main(["tracking", "eventos", "--producto", P, "--pais", PAIS, "--manual", MANUAL_BIEN,
                     "--captura", "test-events"]) == 2
    assert "--antes-hora" in capsys.readouterr().err


def test_antes_hora_mal_o_futura(vault, capsys):
    for mala in ("2026-11-17T11:30:00", "ayer", "2026-11-18T23:00:00+00:00"):
        assert cli.main(["tracking", "eventos", "--producto", P, "--pais", PAIS, "--antes-hora", mala,
                         "--antes", str(FIX / "stats-antes.json"), "--despues", str(FIX / "stats-despues.json")]) == 2


def test_pedidos_acotado(vault, capsys):
    for n in ("0", "6", "-1"):
        assert cli.main(_eventos("--antes", str(FIX / "stats-antes.json"), "--despues", str(FIX / "stats-despues.json"),
                                 "--pedidos", n)) == 2
    assert leer_tracking(vault, P, PAIS).fuente_eventos is None


def test_capi_de_otro_dataset_en_cli(vault, capsys):
    otro = _json("detalles-con-servidor.json")
    otro["structuredContent"]["id"] = "2222222222222222"
    ruta = vault.parent / "otro.json"
    ruta.write_text(json.dumps(otro), encoding="utf-8")
    assert cli.main(_eventos("--antes", str(FIX / "stats-antes.json"), "--despues", str(FIX / "stats-despues.json"),
                             "--detalles", str(ruta))) == 1
    t = leer_tracking(vault, P, PAIS)
    assert t.estado == "dataset" and t.capi != "visto_en_meta"


def test_manual_sin_captura_rechazado(vault, capsys):
    assert cli.main(_eventos("--manual", MANUAL_BIEN)) == 2
    assert cli.main(_eventos("--manual", MANUAL_BIEN, "--captura", "test-events")) == 2
    assert "captura" in capsys.readouterr().err
    assert leer_tracking(vault, P, PAIS).fuente_eventos is None


def test_manual_mal_escrito(vault, tmp_path, capsys):
    _captura(vault, tmp_path)
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


def test_capi_en_meta_con_dataset_id():
    """`ads_get_dataset_details` puede traer `dataset_id` en vez de `id` (forma real de ads_get_datasets)."""
    from datetime import UTC, datetime

    datos = {"dataset_id": DATASET, "server_last_fired_time": "2099-01-01T00:00:00+0000"}
    assert capi_en_meta(datos, DATASET, datetime(2026, 1, 1, tzinfo=UTC)) is True


def test_forma_del_mcp_oficial_stats_y_metadata():
    """El MCP oficial de Meta devuelve ``stats`` con ``timestamp`` y los detalles dentro de ``metadata``."""
    from datetime import datetime

    from trovefy.tracking.eventos import capi_en_meta

    antes = {"dataset_id": "1", "aggregation": "event", "stats": []}
    despues = {"dataset_id": "1", "aggregation": "event", "stats": [
        {"aggregation": "event", "timestamp": "2026-11-18T00:00:00-0800",
         "data": [{"value": "PageView", "count": 5}, {"value": "Purchase", "count": 1}]}]}
    resta = diferencia(cubos_de_eventos(antes), cubos_de_eventos(despues))
    assert resta == {"PageView": 5, "ViewContent": 0, "InitiateCheckout": 0, "Purchase": 1}
    detalles = {"metadata": {"dataset_id": "1", "server_last_fired_time": "2026-11-18T08:30:16-0800"}}
    assert capi_en_meta(detalles, "1", datetime(2026, 11, 18, tzinfo=UTC)) is True
