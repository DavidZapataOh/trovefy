from datetime import date
from decimal import Decimal

import pytest
import yaml
from trovefy.economia.config import (
    PLANTILLA,
    EconomiaInvalida,
    admite_downsell,
    cargar_economia,
    cargar_texto,
    costes_de,
    fijar,
    iniciar_economia,
    upsells_permitidos,
)
from trovefy.economia.modelo import Cifra, Costes, Tomas

HOY = date(2026, 11, 13)


def _ruta(v):
    return v / "config" / "economia.yaml"


def _editar(v, cambio):
    datos = yaml.safe_load(_ruta(v).read_text(encoding="utf-8"))
    cambio(datos)
    _ruta(v).write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_plantilla_carga(tmp_path):
    iniciar_economia(tmp_path)
    c = cargar_economia(tmp_path)
    assert c.tomas == Tomas(Decimal(0), Decimal("0.10"), Decimal("0.05"))
    assert (c.reglas.cpa_test_factor, c.reglas.cpa_escala_factor, c.reglas.be_minimo_usd) == (
        Decimal("0.5"), Decimal("0.65"), Decimal(8))
    assert c.reglas.aov_objetivo_usd == Decimal(30)
    assert c.escalera.front_eur == (Decimal(12), Decimal(24)) and c.escalera.precio_minimo == Decimal(10)
    assert c.escalera.front_usd == (Decimal(17), Decimal(27))
    assert (c.escalera.bump, c.escalera.u1, c.escalera.u2, c.escalera.u3) == (
        Decimal("0.35"), Decimal("1.4"), Decimal("2.2"), Decimal("0.9"))
    assert c.escalera.downsell == Decimal("0.40")
    assert c.escalera.downsell_rango == (Decimal("0.30"), Decimal("0.50"))
    assert c.escalera.bump_activo_test1 is False and sum(c.autopsia.pesos.values()) == 100
    assert c.autopsia.pesos["probabilidad_percibida"] == 20 and c.autopsia.pesos["prueba_garantia"] == 10
    assert (c.autopsia.mejora_min_puntos, c.autopsia.mejora_eje_min, c.autopsia.cobertura_min) == (10, 2, 70)
    assert c.autopsia.nota_media == (45, 70)
    assert c.ruta_activa is None and c.rutas == {"impultienda_whop": ("impultienda", "whop"), "hotmart": ("hotmart",)}
    assert c.reembolsos_pct == Decimal("0.05")
    assert c.plataformas["impultienda"].upsells_por_plan == 1
    assert c.plataformas["whop"].comision_pct is None and c.plataformas["whop"].admite_downsell is None


def test_plantilla_cada_hoja_con_fuente_y_fecha(tmp_path):
    iniciar_economia(tmp_path)
    datos = yaml.safe_load(_ruta(tmp_path).read_text(encoding="utf-8"))

    def hojas(nodo):
        if isinstance(nodo, dict) and "valor" in nodo:
            yield nodo
        elif isinstance(nodo, dict):
            for v in nodo.values():
                yield from hojas(v)

    todas = list(hojas(datos))
    assert len(todas) > 30
    for h in todas:
        assert set(h) == {"valor", "fuente", "fecha"} and h["fuente"] and str(h["fecha"]) == "2026-11-13"


def test_sin_archivo(tmp_path):
    with pytest.raises(FileNotFoundError, match="trovefy economia iniciar"):
        cargar_economia(tmp_path)


def test_costes_sin_rellenar_no_medido(tmp_path):
    iniciar_economia(tmp_path)
    c = costes_de(cargar_economia(tmp_path))
    assert isinstance(c, Cifra) and c.valor is None
    assert c.motivo.startswith("no medido: falta ruta_activa")
    fijar(tmp_path, "ruta_activa", "impultienda_whop", "paso 10 verificado", HOY)
    assert costes_de(cargar_economia(tmp_path)).motivo == (
        "no medido: falta plataformas.impultienda.comision_pct en config/economia.yaml")


def _rellenar_whop(v):
    fijar(v, "ruta_activa", "impultienda_whop", "paso 10 verificado", HOY)
    for campo, valor in (("comision_pct", "0"), ("comision_fija_usd", "0"), ("impuestos_pct", "0")):
        fijar(v, f"plataformas.impultienda.{campo}", valor, "plan Free", HOY)
    fijar(v, "plataformas.whop.comision_pct", "0.03", "tarifa de Whop", HOY)
    fijar(v, "plataformas.whop.comision_fija_usd", "0.30", "tarifa de Whop", HOY)
    fijar(v, "plataformas.whop.impuestos_pct", "0", "Whop no descuenta IVA", HOY)


def test_costes_suman_capas(tmp_path):
    iniciar_economia(tmp_path)
    _rellenar_whop(tmp_path)
    c = costes_de(cargar_economia(tmp_path))
    assert c == Costes(Decimal("0.03"), Decimal("0.30"), Decimal(0), Decimal("0.05"))
    assert all(isinstance(x, Decimal) for x in (c.comision_pct, c.comision_fija_usd, c.impuestos_pct, c.reembolsos_pct))


def test_upsells_y_downsell_de_la_primera_plataforma(tmp_path):
    iniciar_economia(tmp_path)
    assert upsells_permitidos(cargar_economia(tmp_path)) is None
    fijar(tmp_path, "ruta_activa", "impultienda_whop", "paso 10 verificado", HOY)
    c = cargar_economia(tmp_path)
    assert upsells_permitidos(c) == 1 and admite_downsell(c) is None
    fijar(tmp_path, "plataformas.impultienda.admite_downsell", "true", "P-05 resuelta", HOY)
    assert admite_downsell(cargar_economia(tmp_path)) is True


def test_fijar_cambia_valor_fuente_y_fecha(tmp_path):
    iniciar_economia(tmp_path)
    fijar(tmp_path, "tomas.u1", "0.12", "medido en 3 tests", date(2026, 12, 1))
    hoja = yaml.safe_load(_ruta(tmp_path).read_text(encoding="utf-8"))["tomas"]["u1"]
    assert Decimal(str(hoja["valor"])) == Decimal("0.12")
    assert hoja["fuente"] == "medido en 3 tests" and str(hoja["fecha"]) == "2026-12-01"
    assert cargar_economia(tmp_path).tomas.u1 == Decimal("0.12")
    assert _ruta(tmp_path).read_text(encoding="utf-8").startswith("#")


def test_fijar_a_null(tmp_path):
    iniciar_economia(tmp_path)
    fijar(tmp_path, "plataformas.impultienda.upsells_por_plan", None, "plan cambiado: por medir", HOY)
    assert cargar_economia(tmp_path).plataformas["impultienda"].upsells_por_plan is None


def test_fijar_clave_inexistente(tmp_path):
    iniciar_economia(tmp_path)
    antes = _ruta(tmp_path).read_bytes()
    with pytest.raises(KeyError):
        fijar(tmp_path, "plataformas.inventada.x", "1", "nada", HOY)
    with pytest.raises(KeyError):
        fijar(tmp_path, "plataformas.whop", "1", "no es una hoja", HOY)
    assert _ruta(tmp_path).read_bytes() == antes


def test_fijar_valor_invalido_no_escribe(tmp_path):
    iniciar_economia(tmp_path)
    antes = _ruta(tmp_path).read_bytes()
    with pytest.raises(EconomiaInvalida):
        fijar(tmp_path, "plataformas.whop.comision_pct", "1.5", "error", HOY)
    with pytest.raises(EconomiaInvalida):
        fijar(tmp_path, "ruta_activa", "inventada", "error", HOY)
    with pytest.raises(EconomiaInvalida):
        fijar(tmp_path, "tomas.u1", "mucho", "error", HOY)
    assert _ruta(tmp_path).read_bytes() == antes


def test_fijar_sin_fuente_no_escribe(tmp_path):
    iniciar_economia(tmp_path)
    antes = _ruta(tmp_path).read_bytes()
    with pytest.raises(EconomiaInvalida):
        fijar(tmp_path, "tomas.u1", "0.12", "  ", HOY)
    assert _ruta(tmp_path).read_bytes() == antes


def test_fijar_con_secreto_no_escribe(tmp_path):
    iniciar_economia(tmp_path)
    antes = _ruta(tmp_path).read_bytes()
    with pytest.raises(ValueError, match="secreto"):
        fijar(tmp_path, "tomas.u1", "0.12", "clave " + "sk" + "-" + "q" * 24, HOY)
    assert _ruta(tmp_path).read_bytes() == antes


def test_pesos_que_no_suman_100(tmp_path):
    iniciar_economia(tmp_path)
    _editar(tmp_path, lambda d: d["autopsia"]["peso"]["avatar"].update(valor=15))
    with pytest.raises(EconomiaInvalida, match="100"):
        cargar_economia(tmp_path)


def test_pesos_con_ejes_distintos(tmp_path):
    iniciar_economia(tmp_path)

    def cambio(d):
        d["autopsia"]["peso"]["inventado"] = d["autopsia"]["peso"].pop("avatar")

    _editar(tmp_path, cambio)
    with pytest.raises(EconomiaInvalida):
        cargar_economia(tmp_path)


def test_downsell_fuera_de_rango(tmp_path):
    iniciar_economia(tmp_path)
    _editar(tmp_path, lambda d: d["escalera"]["downsell"].update(valor=0.6))
    with pytest.raises(EconomiaInvalida, match="downsell"):
        cargar_economia(tmp_path)


def test_hoja_sin_fuente(tmp_path):
    iniciar_economia(tmp_path)
    _editar(tmp_path, lambda d: d["reglas"]["be_minimo_usd"].pop("fuente"))
    with pytest.raises(EconomiaInvalida, match="reglas.be_minimo_usd"):
        cargar_economia(tmp_path)


def test_numero_ilegible(tmp_path):
    iniciar_economia(tmp_path)
    _editar(tmp_path, lambda d: d["reglas"]["be_minimo_usd"].update(valor="ocho"))
    with pytest.raises(EconomiaInvalida, match="reglas.be_minimo_usd"):
        cargar_economia(tmp_path)


def test_porcentaje_fuera_de_rango(tmp_path):
    iniciar_economia(tmp_path)
    _editar(tmp_path, lambda d: d["reembolsos_pct"].update(valor=1.2))
    with pytest.raises(EconomiaInvalida, match="reembolsos_pct"):
        cargar_economia(tmp_path)


def test_ruta_activa_que_no_existe(tmp_path):
    iniciar_economia(tmp_path)
    _editar(tmp_path, lambda d: d["ruta_activa"].update(valor="inventada"))
    with pytest.raises(EconomiaInvalida, match="ruta_activa"):
        cargar_economia(tmp_path)


def test_iniciar_no_sobrescribe(tmp_path):
    ruta = iniciar_economia(tmp_path)
    assert ruta == _ruta(tmp_path)
    ruta.write_text("editado: true", encoding="utf-8")
    with pytest.raises(FileExistsError):
        iniciar_economia(tmp_path)
    assert ruta.read_text(encoding="utf-8") == "editado: true"


def test_cifra_sin_valor_exige_motivo():
    with pytest.raises(ValueError):
        Cifra(None)
    with pytest.raises(ValueError):
        Cifra(None, "falta algo")
    assert Cifra(Decimal(1)).motivo is None


def test_cargar_texto_valida_igual(tmp_path):
    assert cargar_texto(PLANTILLA.read_text(encoding="utf-8")).reglas.be_minimo_usd == Decimal(8)
    with pytest.raises(EconomiaInvalida):
        cargar_texto("tomas: 3")
