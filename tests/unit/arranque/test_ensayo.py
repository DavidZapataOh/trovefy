import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from trovefy.arranque.ensayo import RUTA_ENSAYO, registrar_compra, registrar_reembolso
from trovefy.arranque.verificadores.ensayo import verificar_ensayo
from trovefy.cli import main
from trovefy_ejecutor.auditoria import Auditoria
from trovefy_ejecutor.vault_copia import CopiaVault

DIA = date(2026, 11, 13)
NOOP = "P-20261113-001"
MONTAJE = "P-20261113-002"


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    return v


class Ctx:
    def __init__(self, tmp_path, vault):
        self.vault = vault
        self.origen = tmp_path / "ejecutor" / "auditoria.jsonl"
        self.t = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
        self.aud = Auditoria(self.origen, reloj=self._reloj)
        self.copia = CopiaVault(vault, tmp_path / "pend")

    def _reloj(self):
        self.t += timedelta(seconds=1)
        return self.t

    def copiar(self):
        assert self.copia.auditoria(self.origen, DIA)

    def noop(self, id_=NOOP, estados=("aceptada", "ejecutada"), evento="transicion"):
        previo = "enviada"
        for a in estados:
            self.aud.anotar(evento, id=id_, tipo="noop", de=previo, a=a)
            previo = a

    def montaje(self, ok=True, validate_only=True):
        self.aud.anotar("ejecucion", id=MONTAJE, tipo="crear_estructura_pausada",
                        validate_only=validate_only, ok=ok, detalle="")


@pytest.fixture
def ctx(tmp_path, vault):
    return Ctx(tmp_path, vault)


def compra_y_reembolso(vault):
    registrar_compra(vault, "ord_test_01", Decimal("2.00"), "USD", "whop", "2026-11-13")
    registrar_reembolso(vault, "ord_test_01", "2026-11-13")


def todo(ctx):
    ctx.noop()
    ctx.montaje()
    ctx.copiar()
    compra_y_reembolso(ctx.vault)


def test_18_completo_verifica(ctx):
    todo(ctx)
    r = verificar_ensayo(ctx.vault)
    assert r.ok is True and RUTA_ENSAYO in r.evidencia
    assert any(e.endswith("2026-11-13.jsonl") for e in r.evidencia)


def test_18_compra_sin_reembolso_falla(ctx):
    ctx.noop(); ctx.montaje(); ctx.copiar()
    registrar_compra(ctx.vault, "ord_test_01", Decimal("2.00"), "USD", "whop", "2026-11-13")
    r = verificar_ensayo(ctx.vault)
    assert r.ok is False and "falta el reembolso de la compra de prueba ord_test_01" in r.motivo
    assert "trovefy arranque ensayo reembolso --pedido ord_test_01" in " ".join(r.arreglos)


def test_18_sin_compra(ctx):
    ctx.noop(); ctx.montaje(); ctx.copiar()
    r = verificar_ensayo(ctx.vault)
    assert r.ok is False and "falta la compra de prueba" in r.motivo


def test_18_noop_rechazado_no_cuenta(ctx):
    ctx.noop(estados=("rechazada",)); ctx.montaje(); ctx.copiar(); compra_y_reembolso(ctx.vault)
    r = verificar_ensayo(ctx.vault)
    assert r.ok is False and "falta un noop aceptado por Telegram" in r.motivo


def test_18_noop_aceptado_pero_no_ejecutado_no_cuenta(ctx):
    ctx.noop(estados=("aceptada",)); ctx.montaje(); ctx.copiar(); compra_y_reembolso(ctx.vault)
    assert verificar_ensayo(ctx.vault).ok is False


def test_18_noop_con_otro_evento_no_cuenta(ctx):
    ctx.aud.anotar("recibida", id=NOOP, tipo="noop", a="aceptada")
    ctx.montaje(); ctx.copiar(); compra_y_reembolso(ctx.vault)
    assert verificar_ensayo(ctx.vault).ok is False


def test_18_noop_fuera_de_001_799_no_cuenta(ctx):
    ctx.noop(id_="P-20261113-900"); ctx.montaje(); ctx.copiar(); compra_y_reembolso(ctx.vault)
    assert verificar_ensayo(ctx.vault).ok is False


def test_18_sin_validate_only_falla(ctx):
    ctx.noop(); ctx.montaje(ok=False); ctx.copiar(); compra_y_reembolso(ctx.vault)
    r = verificar_ensayo(ctx.vault)
    assert r.ok is False and "falta el montaje en validate_only" in r.motivo


def test_18_cadena_rota_falla(ctx):
    todo(ctx)
    ruta = ctx.vault / "ledger/auditoria/2026-11-13.jsonl"
    ruta.write_text(ruta.read_text().replace('"tipo":"noop"', '"tipo":"nooP"', 1))
    r = verificar_ensayo(ctx.vault)
    assert r.ok is False and "la copia de la auditoría no cuadra" in r.motivo


def test_18_linea_ilegible_es_cadena_rota(ctx):
    todo(ctx)
    ruta = ctx.vault / "ledger/auditoria/2026-11-13.jsonl"
    ruta.write_text(ruta.read_text() + "{basura\n")
    assert verificar_ensayo(ctx.vault).ok is False


def test_18_hueco_entre_dias_no_bloquea_si_los_eventos_estan_en_tramos_verificados(ctx):
    todo(ctx)
    dia2 = ctx.vault / "ledger/auditoria/2026-11-15.jsonl"
    lineas = (ctx.vault / "ledger/auditoria/2026-11-13.jsonl").read_text().splitlines()
    ult = json.loads(lineas[-1])
    ctx.aud.anotar("emparejado", user_id=1, chat_id=2)
    ctx.aud.anotar("emparejado", user_id=1, chat_id=2)
    ya = ctx.origen.read_text().splitlines()
    dia2.write_text(ya[-1] + "\n")  # salta una línea: hueco
    assert json.loads(ya[-1])["n"] > ult["n"] + 1
    r = verificar_ensayo(ctx.vault)
    assert r.ok is True


def test_18_copia_que_no_empieza_en_el_origen_cuenta_sus_tramos(ctx):
    ctx.aud.anotar("emparejado", user_id=1, chat_id=2)
    ctx.noop(); ctx.montaje(); ctx.copiar(); compra_y_reembolso(ctx.vault)
    ruta = ctx.vault / "ledger/auditoria/2026-11-13.jsonl"
    ruta.write_text("\n".join(ruta.read_text().splitlines()[1:]) + "\n")  # falta la línea 1
    assert verificar_ensayo(ctx.vault).ok is True


def test_18_eventos_en_un_tramo_que_no_cuadra_fallan(ctx):
    todo(ctx)
    ruta = ctx.vault / "ledger/auditoria/2026-11-13.jsonl"
    ls = ruta.read_text().splitlines()
    del ls[1]  # tramo con una línea del medio borrada
    ruta.write_text("\n".join(ls) + "\n")
    r = verificar_ensayo(ctx.vault)
    assert r.ok is False and "no cuadra" in r.motivo


def test_18_linea_final_a_medias_no_rompe(ctx):
    todo(ctx)
    ruta = ctx.vault / "ledger/auditoria/2026-11-13.jsonl"
    ruta.write_text(ruta.read_text() + '{"n": 9, "evento": "transi')
    assert verificar_ensayo(ctx.vault).ok is True


def test_18_no_usa_privadas_de_listado():
    from trovefy.arranque.verificadores import ensayo
    assert "_verificar_cadena" not in Path(ensayo.__file__).read_text()


def test_18_sin_copia_de_auditoria(ctx):
    compra_y_reembolso(ctx.vault)
    r = verificar_ensayo(ctx.vault)
    assert r.ok is False
    assert "el ejecutor copia la auditoría al vault (plan 12)" in " ".join(r.arreglos)


def test_18_no_copia_datos_ajenos_al_motivo(ctx):
    todo(ctx)
    assert "detalle" not in verificar_ensayo(ctx.vault).motivo


def test_compra_se_guarda_y_no_se_sobrescribe(vault):
    registrar_compra(vault, "ord_test_01", Decimal("2.00"), "usd", "whop", "2026-11-13")
    datos = yaml.safe_load((vault / RUTA_ENSAYO).read_text())
    assert datos["compras"][0]["moneda"] == "USD" and datos["compras"][0]["importe"] == "2.00"
    with pytest.raises(ValueError):
        registrar_compra(vault, "ord_test_01", Decimal("3.00"), "USD", "whop", "2026-11-13")
    assert yaml.safe_load((vault / RUTA_ENSAYO).read_text())["compras"][0]["importe"] == "2.00"


@pytest.mark.parametrize("importe", ["0", "50", "-1"])
def test_importe_fuera_de_rango(vault, importe):
    with pytest.raises(ValueError, match="US\\$ 1–5"):
        registrar_compra(vault, "ord_test_01", Decimal(importe), "USD", "whop", "2026-11-13")


@pytest.mark.parametrize("campo,valor", [("pedido", "a b"), ("moneda", "DOLAR"), ("pasarela", "stripe"), ("fecha", "13/11/2026")])
def test_campos_invalidos(vault, campo, valor):
    kw = {"pedido": "ord_test_01", "importe": Decimal(2), "moneda": "USD", "pasarela": "whop", "fecha": "2026-11-13"}
    kw[campo] = valor
    with pytest.raises(ValueError):
        registrar_compra(vault, **kw)


def test_reembolso_sin_compra_falla(vault):
    with pytest.raises(ValueError):
        registrar_reembolso(vault, "ord_test_01", "2026-11-13")


def test_reembolso_doble_falla(vault):
    registrar_compra(vault, "ord_test_01", Decimal(2), "USD", "whop", "2026-11-13")
    registrar_reembolso(vault, "ord_test_01", "2026-11-13")
    with pytest.raises(ValueError):
        registrar_reembolso(vault, "ord_test_01", "2026-11-13")


def test_ensayo_rechaza_secreto_en_pedido(vault):
    args = ["arranque", "ensayo", "compra", "--pedido", "EAAB" + "x" * 40, "--importe", "2.00",
            "--moneda", "USD", "--pasarela", "whop", "--vault", str(vault)]
    assert main(args) == 2
    assert not (vault / RUTA_ENSAYO).exists()


def test_cli_compra_reembolso_y_log(vault):
    base = ["arranque", "ensayo"]
    assert main([*base, "compra", "--pedido", "ord_test_01", "--importe", "2.00", "--moneda", "USD",
                 "--pasarela", "whop", "--fecha", "2026-11-13", "--vault", str(vault)]) == 0
    assert main([*base, "reembolso", "--pedido", "ord_test_01", "--vault", str(vault)]) == 0
    assert main([*base, "reembolso", "--pedido", "nada_01", "--vault", str(vault)]) == 2
    assert main([*base, "compra", "--pedido", "ord_test_02", "--importe", "50", "--moneda", "USD",
                 "--pasarela", "whop", "--vault", str(vault)]) == 2
    log = (vault / "log.md").read_text()
    assert "ensayo compra" in log and "ensayo reembolso" in log
