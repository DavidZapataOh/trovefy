"""Cierre a `con_checkout` (plan 19, Tarea 16) y excepciones aprobadas por el usuario.

Siete requisitos, en orden; con todo en verde (o con una excepción válida del usuario donde se admite) el país pasa
de `con_landing` a `con_checkout` con `avanzar_estado`. Una excepción nunca cuenta como verde: se distingue de
`True`, se lista en la evidencia del paso y en `log.md`. `checkout completo` y `compra de prueba registrada` no
admiten excepción.
"""

import importlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from embudo.ejemplos_embudo import PAIS, P, escribir_md, vault_embudo
from trovefy import cli
from trovefy.checkout.cierre import (
    REQUISITOS,
    SIN_EXCEPCION,
    ExcepcionAprobada,
    cerrar,
    registrar_excepcion,
    requisitos_checkout,
)
from trovefy.tracking.modelo import Tracking, emisores_por_defecto
from trovefy.tracking.salida import escribir_tracking
from trovefy.vault import frontmatter
from trovefy.vault.producto import EstadoInesperado, actualizar_producto, estado_pais

AHORA = datetime(2026, 11, 18, 12, 0, 0, tzinfo=ZoneInfo("America/Bogota"))
DATASET = "1111111111111111"
CABECERA = ["| ajuste | pedido | releído | fuente | evidencia |", "|---|---|---|---|---|"]
FILAS_BIEN = ["| producto.front.precio | 13.90 | 13.90 | mcp | ok |",
              "| checkout.idioma | bg | bg | fuera | ok |",
              "| checkout.foto | mockup.png | mockup.png | captura | a mano: captura |"]
PALABRAS = "Sí, apruebo cerrar sin InitiateCheckout: Impultienda no lo manda en la prueba"


def _carpeta(v: Path) -> Path:
    return v / "productos" / P / "checkout" / PAIS


def _tracking(v: Path, estado: str = "verificado", ejecutor: dict | None = None, motivos: list | None = None):
    ejecutor = {"dataset_permitido": True, "pagina_permitida": True, "lectura_ok": True,
                "fecha": "2026-11-17"} if ejecutor is None else ejecutor
    t = Tracking(producto=P, pais=PAIS, dataset_nombre="SOMATIX ZZ", dataset_id=DATASET,
                 emisores=emisores_por_defecto("impultienda", "impultienda"), pixel_publico="ok",
                 pixel_config="mcp", capi="visto_en_meta",
                 eventos={"PageView": 3, "ViewContent": 0, "InitiateCheckout": 0 if estado != "verificado" else 2,
                          "Purchase": 1},
                 fuente_eventos="mcp", estado=estado, motivos=motivos or [], ejecutor=ejecutor or None)
    escribir_tracking(v, t, AHORA)


def _checkout(v: Path, estado: str = "completo", filas: list[str] | None = None) -> None:
    cuerpo = "\n".join(["# Checkout", "", *CABECERA, *(FILAS_BIEN if filas is None else filas), ""])
    escribir_md(_carpeta(v) / "CHECKOUT.md", {"tipo": "checkout", "producto": P, "pais": PAIS, "estado": estado},
                cuerpo)


def _embudo(v: Path, estado: str = "ok") -> None:
    escribir_md(_carpeta(v) / "embudo.md", {"tipo": "embudo_demo", "producto": P, "pais": PAIS, "estado": estado})


def _compra(v: Path, *, reembolso: bool = True) -> None:
    compra = {"pedido": "1001", "fecha": "2026-11-17", "importe": "13.90", "moneda": "EUR",
              "plataforma": {"visto": True, "fuente": "mcp", "evidencia": "compra/pedido.json"}}
    if reembolso:
        compra["reembolso"] = {"procesado": True, "fecha": "2026-11-17", "evidencia": "compra/reembolso.json"}
    actualizar_producto(v, P, {"paises": {PAIS: {"compra_prueba": compra}}}, [], "checkout", AHORA)


def _esquema(v: Path) -> None:
    ruta = v / "config" / "esquemas" / "impultienda-pedidos.yaml"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(yaml.safe_dump({"fuente": "impultienda_listar_ventas", "fecha": "2026-11-17",
                                    "columnas": ["pedido", "estado"]}), encoding="utf-8")


@pytest.fixture
def vault(tmp_path):
    return vault_embudo(tmp_path)


@pytest.fixture
def verde(vault):
    _tracking(vault)
    _checkout(vault)
    _embudo(vault)
    _compra(vault)
    _esquema(vault)
    return vault


def _por_nombre(reqs):
    return {n: (ok, detalle) for n, ok, detalle in reqs}


def _historial(v: Path) -> list:
    meta, _ = frontmatter.leer(v / "productos" / P / "PRODUCTO.md")
    return meta["paises"][PAIS]["historial"]


# --- requisitos y cierre ---------------------------------------------------------------------------------------


def test_requisitos_en_orden(verde):
    assert REQUISITOS == ("tracking verificado", "dataset en límites del ejecutor", "checkout completo",
                          "embudo demo ok", "compra de prueba registrada", "reembolso registrado", "esquema de pedidos")
    reqs = requisitos_checkout(verde, P, PAIS)
    assert [r[0] for r in reqs] == list(REQUISITOS)
    assert all(ok is True for _, ok, _ in reqs)


def test_cierre_todo_verde_avanza(verde):
    texto = cerrar(verde, P, PAIS, AHORA)
    assert estado_pais(verde, P, PAIS) == "con_checkout"
    paso = _historial(verde)[-1]
    assert (paso["de"], paso["a"]) == ("con_landing", "con_checkout")
    assert len(paso["evidencia"]) == len(REQUISITOS)
    assert not any("excepción" in e for e in paso["evidencia"])
    assert "con_checkout" in texto
    log = (verde / "log.md").read_text(encoding="utf-8")
    assert "con_landing → con_checkout" in log and "checkout cerrado" in log


def test_cierre_falta_reembolso_no_avanza(vault):
    _tracking(vault)
    _checkout(vault)
    _embudo(vault)
    _compra(vault, reembolso=False)
    _esquema(vault)
    antes = (vault / "productos" / P / "PRODUCTO.md").read_bytes()
    with pytest.raises(ValueError, match="reembolso registrado"):
        cerrar(vault, P, PAIS, AHORA)
    assert (vault / "productos" / P / "PRODUCTO.md").read_bytes() == antes
    assert estado_pais(vault, P, PAIS) == "con_landing"


def test_cierre_estado_incorrecto(tmp_path):
    v = vault_embudo(tmp_path, estado="producido")
    with pytest.raises(EstadoInesperado, match="con_landing"):
        cerrar(v, P, PAIS, AHORA)
    assert estado_pais(v, P, PAIS) == "producido"


def test_p20_no_medido_no_bloquea(verde):
    (verde / "config" / "esquemas" / "impultienda-pedidos.yaml").unlink()
    ok, detalle = _por_nombre(requisitos_checkout(verde, P, PAIS))["esquema de pedidos"]
    assert ok is None and detalle.startswith("no medido") and "P-20" in detalle
    cerrar(verde, P, PAIS, AHORA)
    assert estado_pais(verde, P, PAIS) == "con_checkout"
    assert any(e.startswith("esquema de pedidos: no medido") for e in _historial(verde)[-1]["evidencia"])


def test_checkout_con_dicho_en_precio_no_cierra(verde):
    _checkout(verde, filas=[*FILAS_BIEN[1:], "| producto.front.precio | 13.90 | 13,90 € | dicho | a mano: dicho |"])
    ok, detalle = _por_nombre(requisitos_checkout(verde, P, PAIS))["checkout completo"]
    assert ok is False and "producto.front.precio" in detalle and "dicho" in detalle
    with pytest.raises(ValueError, match="checkout completo"):
        cerrar(verde, P, PAIS, AHORA)
    assert estado_pais(verde, P, PAIS) == "con_landing"


def test_checkout_a_medias_no_cierra(verde):
    _checkout(verde, estado="a_medias")
    assert _por_nombre(requisitos_checkout(verde, P, PAIS))["checkout completo"][0] is False


def test_faltan_archivos_no_medido(vault):
    reqs = _por_nombre(requisitos_checkout(vault, P, PAIS))
    for nombre in ("tracking verificado", "dataset en límites del ejecutor", "checkout completo", "embudo demo ok",
                   "compra de prueba registrada", "reembolso registrado", "esquema de pedidos"):
        assert reqs[nombre][0] is None and reqs[nombre][1].startswith("no medido"), nombre
    with pytest.raises(ValueError):
        cerrar(vault, P, PAIS, AHORA)


def test_ejecutor_sin_pagina_falla(verde):
    _tracking(verde, ejecutor={"dataset_permitido": True, "pagina_permitida": False, "lectura_ok": True,
                               "fecha": "2026-11-17"})
    ok, detalle = _por_nombre(requisitos_checkout(verde, P, PAIS))["dataset en límites del ejecutor"]
    assert ok is False and "página" in detalle


def test_compra_solo_dicha_no_vale(vault, monkeypatch):
    from trovefy.embudo.contexto import cargar_contexto
    from trovefy.embudo.pegado import dicho

    ctx = cargar_contexto(vault, P, PAIS)
    dicho(vault, ctx, "pedido", "Ya compré, pedido 1001", AHORA)
    ok, detalle = _por_nombre(requisitos_checkout(vault, P, PAIS))["compra de prueba registrada"]
    assert ok is False and "dicho" in detalle


def test_compra_y_reembolso_con_captura_valen(vault, tmp_path):
    from trovefy.embudo.contexto import cargar_contexto
    from trovefy.embudo.pegado import guardar_pegado

    ctx = cargar_contexto(vault, P, PAIS)
    png = tmp_path / "c.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    guardar_pegado(vault, ctx, "pedido", png, {"pedido": "1001"}, AHORA)
    guardar_pegado(vault, ctx, "reembolso", png, None, datetime(2026, 11, 18, 12, 0, 1, tzinfo=AHORA.tzinfo))
    reqs = _por_nombre(requisitos_checkout(vault, P, PAIS))
    assert reqs["compra de prueba registrada"][0] is True
    assert reqs["reembolso registrado"][0] is True


# --- excepciones aprobadas por el usuario --------------------------------------------------------------------


def _con_tracking_sin_initiatecheckout(vault):
    _tracking(vault, estado="configurado", motivos=["eventos: no medido: InitiateCheckout no llegó"])
    _checkout(vault)
    _embudo(vault)
    _compra(vault)
    _esquema(vault)


def test_excepcion_valida_desbloquea_el_cierre(vault):
    _con_tracking_sin_initiatecheckout(vault)
    with pytest.raises(ValueError, match="tracking verificado"):
        cerrar(vault, P, PAIS, AHORA)
    ruta = registrar_excepcion(vault, P, PAIS, "tracking verificado", PALABRAS,
                               "InitiateCheckout no llega en la compra de prueba", AHORA)
    assert ruta.name == "2026-11-18-excepcion-tracking-verificado.md"
    meta, cuerpo = frontmatter.leer(ruta)
    assert (meta["pais"], meta["requisito"], meta["palabras_del_usuario"]) == (PAIS, "tracking verificado", PALABRAS)
    assert meta["motivo"] == "InitiateCheckout no llega en la compra de prueba"
    assert PALABRAS in cuerpo
    ok, detalle = _por_nombre(requisitos_checkout(vault, P, PAIS))["tracking verificado"]
    assert isinstance(ok, ExcepcionAprobada) and ok is not True and not ok
    assert detalle.startswith(f"excepción aprobada: «{PALABRAS}»")
    cerrar(vault, P, PAIS, AHORA)
    assert estado_pais(vault, P, PAIS) == "con_checkout"


def test_excepcion_aparece_en_la_evidencia_y_el_log(vault):
    _con_tracking_sin_initiatecheckout(vault)
    registrar_excepcion(vault, P, PAIS, "tracking-verificado", PALABRAS, "sin InitiateCheckout", AHORA)
    texto = cerrar(vault, P, PAIS, AHORA)
    evidencia = _historial(vault)[-1]["evidencia"]
    linea = next(e for e in evidencia if e.startswith("tracking verificado:"))
    assert "excepción aprobada por el usuario" in linea and PALABRAS in linea and "no es verde" in linea
    assert not linea.startswith("tracking verificado: ok")
    assert "excepción" in texto and PALABRAS in texto
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "excepciones aprobadas: tracking verificado" in log
    assert "decisiones/2026-11-18-excepcion-tracking-verificado.md" in log


def test_excepcion_sin_palabras_del_usuario_se_rechaza(vault):
    for vacias in ("", "   ", None):
        with pytest.raises(ValueError, match="palabras"):
            registrar_excepcion(vault, P, PAIS, "tracking verificado", vacias, "motivo", AHORA)
    assert not (vault / "productos" / P / "decisiones").exists()


def test_excepcion_sin_motivo_se_rechaza(vault):
    with pytest.raises(ValueError, match="motivo"):
        registrar_excepcion(vault, P, PAIS, "tracking verificado", PALABRAS, " ", AHORA)


@pytest.mark.parametrize("requisito", ["checkout completo", "compra de prueba registrada", "checkout-completo"])
def test_excepcion_sobre_checkout_completo_o_compra_se_rechaza(vault, requisito):
    assert {"checkout completo", "compra de prueba registrada"} == set(SIN_EXCEPCION)
    with pytest.raises(ValueError, match="no admite excepción"):
        registrar_excepcion(vault, P, PAIS, requisito, PALABRAS, "motivo", AHORA)
    assert not (vault / "productos" / P / "decisiones").exists()


def test_excepcion_requisito_desconocido(vault):
    with pytest.raises(ValueError, match="requisito desconocido"):
        registrar_excepcion(vault, P, PAIS, "píxel bonito", PALABRAS, "motivo", AHORA)


def test_excepcion_con_secreto_no_se_guarda(vault):
    with pytest.raises(ValueError, match="secreto"):
        registrar_excepcion(vault, P, PAIS, "tracking verificado", "vale, token " + "EAA" + "Bq7" * 10, "m", AHORA)
    assert not (vault / "productos" / P / "decisiones").exists()


def test_excepcion_escrita_a_mano_sin_palabras_no_vale(vault):
    _con_tracking_sin_initiatecheckout(vault)
    escribir_md(vault / "productos" / P / "decisiones" / "2026-11-18-excepcion-tracking-verificado.md",
                {"tipo": "decision", "decision": "excepcion_checkout", "fecha": "2026-11-18",
                 "registrada": AHORA.isoformat(), "fuente": "usuario", "producto": P, "pais": PAIS,
                 "requisito": "tracking verificado", "motivo": "x", "palabras_del_usuario": ""})
    assert _por_nombre(requisitos_checkout(vault, P, PAIS))["tracking verificado"][0] is False
    with pytest.raises(ValueError):
        cerrar(vault, P, PAIS, AHORA)


def test_excepcion_escrita_a_mano_sobre_checkout_no_vale(verde):
    _checkout(verde, estado="a_medias")
    escribir_md(verde / "productos" / P / "decisiones" / "2026-11-18-excepcion-checkout-completo.md",
                {"tipo": "decision", "decision": "excepcion_checkout", "fecha": "2026-11-18",
                 "registrada": AHORA.isoformat(), "fuente": "usuario", "producto": P, "pais": PAIS,
                 "requisito": "checkout completo", "motivo": "x", "palabras_del_usuario": "sí"})
    assert _por_nombre(requisitos_checkout(verde, P, PAIS))["checkout completo"][0] is False


def test_excepcion_de_otro_pais_no_vale(vault):
    _con_tracking_sin_initiatecheckout(vault)
    registrar_excepcion(vault, P, "ZY", "tracking verificado", PALABRAS, "motivo", AHORA)
    assert _por_nombre(requisitos_checkout(vault, P, PAIS))["tracking verificado"][0] is False


def test_excepcion_no_tapa_un_verde(verde):
    registrar_excepcion(verde, P, PAIS, "tracking verificado", PALABRAS, "motivo", AHORA)
    assert _por_nombre(requisitos_checkout(verde, P, PAIS))["tracking verificado"][0] is True


# --- CLI -------------------------------------------------------------------------------------------------------


@pytest.fixture
def cli_vault(vault, monkeypatch):
    checkout_cli = importlib.import_module("trovefy.checkout_cli")
    monkeypatch.setenv("TROVEFY_VAULT", str(vault))
    monkeypatch.setattr(checkout_cli, "_ahora", lambda: AHORA)
    monkeypatch.setattr(checkout_cli, "_hay_terminal", lambda: False)
    return vault


def _excepcion(*extra: str) -> list[str]:
    return ["checkout", "excepcion", "--producto", P, "--pais", PAIS, *extra]


def test_cli_excepcion_exige_un_mensaje_del_usuario(cli_vault, capsys):
    """Claude no puede inventar la aprobación: sin terminal, las palabras tienen que ser un mensaje del usuario."""
    assert cli.main(_excepcion("--requisito", "tracking verificado", "--dicho", PALABRAS, "--motivo", "m")) == 2
    assert "mensaje" in capsys.readouterr().err
    assert not (cli_vault / "productos" / P / "decisiones").exists()


def test_cli_excepcion_con_mensaje_del_usuario(cli_vault, capsys):
    from trovefy.checkout.mensajes import registrar_mensaje

    registrar_mensaje(PALABRAS)
    assert cli.main(_excepcion("--requisito", "tracking verificado", "--dicho", PALABRAS, "--motivo", "m")) == 0
    out = capsys.readouterr().out
    assert "decisiones/2026-11-18-excepcion-tracking-verificado.md" in out and "no cuenta como verde" in out


def test_cli_excepcion_checkout_completo_se_rechaza(cli_vault, monkeypatch, capsys):
    checkout_cli = importlib.import_module("trovefy.checkout_cli")
    monkeypatch.setattr(checkout_cli, "_hay_terminal", lambda: True)
    assert cli.main(_excepcion("--requisito", "checkout completo", "--dicho", PALABRAS, "--motivo", "m")) == 2
    assert "no admite excepción" in capsys.readouterr().err


def test_cli_cerrar(cli_vault, capsys):
    assert cli.main(["checkout", "cerrar", "--producto", P, "--pais", PAIS]) == 1
    out = capsys.readouterr().out
    assert "[no medido] tracking verificado" in out
    _tracking(cli_vault)
    _checkout(cli_vault)
    _embudo(cli_vault)
    _compra(cli_vault)
    _esquema(cli_vault)
    assert cli.main(["checkout", "cerrar", "--producto", P, "--pais", PAIS]) == 0
    assert "con_checkout" in capsys.readouterr().out
    assert estado_pais(cli_vault, P, PAIS) == "con_checkout"
