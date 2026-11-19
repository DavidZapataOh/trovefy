"""Plan 20, Tarea 6: el paso 18 con la compra real del producto (`ensayo compra|reembolso --desde-producto`)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import yaml
from trovefy.arranque.ensayo import (
    RUTA_ENSAYO,
    registrar_compra,
    registrar_compra_desde_producto,
    registrar_reembolso_desde_producto,
)
from trovefy.arranque.estado import aplicar_verificacion, cargar, marcar_bloqueado
from trovefy.arranque.verificadores.ensayo import verificar_ensayo
from trovefy.cli import main
from trovefy_ejecutor.auditoria import Auditoria
from trovefy_ejecutor.vault_copia import CopiaVault

from .conftest import P
from .test_gates import pegar

DIA = date(2026, 11, 13)


def _cambiar(vault, viejo, nuevo):
    ruta = vault / "productos" / P / "PRODUCTO.md"
    texto = ruta.read_text()
    assert viejo in texto
    ruta.write_text(texto.replace(viejo, nuevo))


def test_compra_desde_producto(ficha_verde):
    vault, _ = ficha_verde
    fila = registrar_compra_desde_producto(vault, P, "ZZ")
    assert fila == {"pedido": "ORD-0001", "importe": "12.90", "moneda": "EUR", "pasarela": "impultienda",
                    "fecha": "2026-11-21", "producto": P, "pais": "ZZ"}
    assert yaml.safe_load((vault / RUTA_ENSAYO).read_text())["compras"] == [fila]


def test_compra_con_precio_distinto_falla(ficha_verde):
    vault, _ = ficha_verde
    _cambiar(vault, "      importe: '12.90'\n      moneda: EUR\n      plataforma:",
             "      importe: '1.00'\n      moneda: EUR\n      plataforma:")
    with pytest.raises(ValueError, match="no es el precio de venta"):
        registrar_compra_desde_producto(vault, P, "ZZ")
    assert not (vault / RUTA_ENSAYO).exists()


def test_compra_no_vista_en_plataforma_falla(ficha_verde):
    vault, _ = ficha_verde
    _cambiar(vault, "visto: true", "visto: false")
    with pytest.raises(ValueError, match="plataforma"):
        registrar_compra_desde_producto(vault, P, "ZZ")


def test_compra_pasarela_desconocida_falla(ficha_verde):
    vault, _ = ficha_verde
    _cambiar(vault, "plataforma: impultienda", "plataforma: stripe")
    with pytest.raises(ValueError, match="stripe"):
        registrar_compra_desde_producto(vault, P, "ZZ")


def test_reembolso_sin_procesar_falla(ficha_verde):
    vault, _ = ficha_verde
    registrar_compra_desde_producto(vault, P, "ZZ")
    _cambiar(vault, "procesado: true", "procesado: false")
    with pytest.raises(ValueError, match="no está procesado"):
        registrar_reembolso_desde_producto(vault, P, "ZZ")


def test_desde_lo_pegado_sin_compra_prueba(ficha_verde):
    # el producto real: sin compra_prueba en PRODUCTO.md, con la captura del pedido y la del reembolso
    vault, f = ficha_verde
    ruta = f.carpeta / "PRODUCTO.md"
    texto = ruta.read_text()
    ruta.write_text(texto[:texto.index("    compra_prueba:")] + texto[texto.index("  YZ:"):])
    with pytest.raises(ValueError, match="no hay compra de prueba"):
        registrar_compra_desde_producto(vault, P, "ZZ")
    pegar(f, "pedido", "captura", fecha="2026-11-18T11:45:01-05:00", valores={"pedido": "3600"})
    fila = registrar_compra_desde_producto(vault, P, "ZZ")
    assert (fila["pedido"], fila["importe"], fila["moneda"], fila["fecha"]) == ("3600", "12.90", "EUR", "2026-11-18")
    with pytest.raises(ValueError, match="reembolso no está procesado"):
        registrar_reembolso_desde_producto(vault, P, "ZZ")
    pegar(f, "reembolso", "captura", fecha="2026-11-19T10:00:00-05:00")
    assert registrar_reembolso_desde_producto(vault, P, "ZZ") == {"pedido": "3600", "fecha": "2026-11-19"}


def test_manual_sigue_con_tope_10(tmp_path):
    with pytest.raises(ValueError, match="máximo 10"):
        registrar_compra(tmp_path, "ord-1", Decimal("12.90"), "EUR", "impultienda", "2026-11-21")


class Ctx:
    """Noop aceptado y ejecutado y montaje en validate_only en la copia de la auditoría (como test_ensayo.py)."""

    def __init__(self, tmp_path, vault):
        self.vault = vault
        self.origen = tmp_path / "ejecutor" / "auditoria.jsonl"
        self.t = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
        self.aud = Auditoria(self.origen, reloj=self._reloj)
        self.copia = CopiaVault(vault, tmp_path / "pend")

    def _reloj(self):
        self.t += timedelta(seconds=1)
        return self.t

    def noop_y_montaje(self):
        previo = "enviada"
        for a in ("aceptada", "ejecutada"):
            self.aud.anotar("transicion", id="P-20261113-001", tipo="noop", de=previo, a=a)
            previo = a
        self.aud.anotar("ejecucion", id="P-20261113-002", tipo="crear_estructura_pausada", validate_only=True,
                        ok=True, detalle="")

    def copiar(self):
        assert self.copia.auditoria(self.origen, DIA)


def test_cierra_el_18_desde_bloqueado(ficha_verde, tmp_path):
    vault, _ = ficha_verde
    marcar_bloqueado(vault, "18", "compra y reembolso de prueba esperan al producto real (fase 2)")
    ctx = Ctx(tmp_path, vault)
    ctx.noop_y_montaje()
    ctx.copiar()
    registrar_compra_desde_producto(vault, P, "ZZ")
    registrar_reembolso_desde_producto(vault, P, "ZZ")
    p = aplicar_verificacion(vault, "18", verificar_ensayo(vault))
    assert p.estado == "verificado" and RUTA_ENSAYO in p.evidencia
    assert next(x for x in cargar(vault) if x.id == "18").estado == "verificado"


def test_cli_modos_excluyentes(ficha_verde, capsys):
    vault, _ = ficha_verde
    codigo = main(["arranque", "ensayo", "compra", "--desde-producto", P, "--pais", "ZZ", "--pedido", "X1",
                   "--vault", str(vault)])
    assert codigo == 2 and "uno de los dos modos" in capsys.readouterr().err
    assert main(["arranque", "ensayo", "compra", "--pedido", "X1", "--vault", str(vault)]) == 2
    assert main(["arranque", "ensayo", "compra", "--desde-producto", P, "--vault", str(vault)]) == 2


def test_cli_desde_producto(ficha_verde, capsys):
    vault, _ = ficha_verde
    assert main(["arranque", "ensayo", "compra", "--desde-producto", P, "--pais", "ZZ", "--vault", str(vault)]) == 0
    assert "Comprueba con `trovefy arranque verificar 18`" in capsys.readouterr().out
    assert main(["arranque", "ensayo", "reembolso", "--desde-producto", P, "--pais", "ZZ",
                 "--vault", str(vault)]) == 0
    assert "ORD-0001" in (vault / "log.md").read_text()


def test_cli_producto_inexistente_sin_traza(tmp_path, capsys):
    assert main(["arranque", "ensayo", "compra", "--desde-producto", P, "--pais", "ZZ", "--vault", str(tmp_path)]) == 2
    assert "Traceback" not in capsys.readouterr().err
