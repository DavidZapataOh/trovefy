from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from trovefy.apimart.gasto import (
    CABECERA,
    CostesCorruptos,
    FilaCoste,
    TopeSuperado,
    alerta_tope,
    anotar_coste,
    avisar_tope,
    comprobar_tope,
    gastado_usd,
    leer_costes,
    ruta_costes,
    subir_tope,
)
from trovefy.aprobaciones.fuentes import BuzonNoDisponible
from trovefy.producto.config import cargar_config, iniciar_config, tope_de
from trovefy.vault import frontmatter
from trovefy_ejecutor.esquema import cargar_propuesta

P = "p-0042-respira"
COT = timezone(timedelta(hours=-5))
AHORA = datetime(2026, 11, 14, 10, 0, tzinfo=COT)


def fila(intento="i-1", estado="enviando", estimado="0.0085", real=None, **k):
    base = {"fecha": AHORA, "producto": P, "pieza": "principal", "imagen": "portada", "intento": intento,
            "task_id": "", "modelo": "gpt-image-2", "resolucion": "1k", "proporcion": "2:3", "estado": estado,
            "coste_estimado_usd": None if estimado is None else Decimal(estimado),
            "coste_real_usd": None if real is None else Decimal(real), "fuente_precio": "prueba",
            "sha256": "", "archivo": ""}
    return FilaCoste(**{**base, **k})


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "productos" / P).mkdir(parents=True)
    frontmatter.escribir(tmp_path / "productos" / P / "PRODUCTO.md",
                         {"id": P, "paises": {"ZZ": {"estado": "modelado"}}}, "# Respira\n\nCuerpo a mano.\n")
    iniciar_config(tmp_path)
    return tmp_path


def test_cabecera():
    assert CABECERA == ["fecha", "producto", "pieza", "imagen", "intento", "task_id", "modelo", "resolucion",
                        "proporcion", "estado", "coste_estimado_usd", "coste_real_usd", "fuente_precio", "sha256",
                        "archivo"]


def test_ultima_fila_por_intento():
    filas = [fila(estado="enviando"), fila(estado="completada", real="0.0080")]
    assert gastado_usd(filas) == Decimal("0.0080")


def test_fallida_sin_real_cuenta_estimado():
    assert gastado_usd([fila(), fila(estado="fallida")]) == Decimal("0.0085")
    assert gastado_usd([fila(estado="pendiente"), fila("i-2", "enviada")]) == Decimal("0.0170")


def test_tope_y_simulada_no_suman():
    assert gastado_usd([fila(estado="tope"), fila("i-2", "simulada"), fila("i-3", "completada", real="0.01")]) \
        == Decimal("0.01")
    assert gastado_usd([]) == Decimal(0)


def test_comprobar_tope_2_usd():
    with pytest.raises(TopeSuperado) as e:
        comprobar_tope(Decimal("1.9950"), Decimal("0.0085"), Decimal("2.00"))
    assert e.value.gastado == Decimal("1.9950") and e.value.tope == Decimal("2.00")
    assert e.value.estimado == Decimal("0.0085")
    comprobar_tope(Decimal("1.9915"), Decimal("0.0085"), Decimal("2.00"))  # el límite es inclusivo


def test_alerta_texto():
    a = alerta_tope(P, Decimal("1.995"), Decimal(2), 3, Decimal("0.0255"))
    assert a == {"tipo": "alerta", "origen": "/producto", "nivel": "aviso", "titulo": "Tope de APIMart alcanzado",
                 "texto": "p-0042-respira: gastado 1,9950 USD de 2,00. Faltan 3 imágenes (≈ 0,0255 USD). "
                          "No se generó nada más. Subir el tope es decisión tuya."}


def test_alerta_valida_con_esquema():
    alerta = alerta_tope(P, Decimal("1.9950"), Decimal("2.00"), 3, Decimal("0.0255"))
    p = cargar_propuesta({**alerta, "id": "P-20261114-001", "creada": AHORA.isoformat(), "version": 1})
    assert p.tipo == "alerta"


def test_costes_solo_se_anaden(vault):
    anotar_coste(vault, P, fila())
    ruta = ruta_costes(vault, P)
    antes = ruta.read_bytes()
    anotar_coste(vault, P, fila(estado="completada", real="0.0080", task_id="t-1", sha256="a" * 64,
                                archivo="medios/portada.png"))
    despues = ruta.read_bytes()
    assert despues.startswith(antes) and len(despues) > len(antes)
    assert antes.decode().splitlines()[0] == ",".join(CABECERA)
    filas = leer_costes(vault, P)
    assert [f.estado for f in filas] == ["enviando", "completada"]
    assert filas[1].coste_real_usd == Decimal("0.0080") and filas[0].coste_real_usd is None
    assert filas[0].fecha == AHORA and filas[1].task_id == "t-1"
    assert ruta == vault / "productos" / P / "entregable" / "costes.csv"
    assert "\r" not in despues.decode()


def test_sin_costes_es_lista_vacia(vault):
    assert leer_costes(vault, P) == []


def test_fila_corrupta(vault):
    anotar_coste(vault, P, fila())
    ruta = ruta_costes(vault, P)
    original = ruta.read_text() + "2026-11-14T10:00:00-05:00,p-0042-respira,principal,x,i-9,,m,1k,1:1,raro,0.1,,f,,\n"
    ruta.write_text(original)
    with pytest.raises(CostesCorruptos):
        leer_costes(vault, P)
    assert ruta.read_text() == original  # nunca se «arregla»
    with pytest.raises(CostesCorruptos):
        anotar_coste(vault, P, fila("i-2"))
    assert ruta.read_text() == original


@pytest.mark.parametrize("linea", ["no,es,la,cabecera\n", ",".join(CABECERA) + "\nx,y\n",
                                   ",".join(CABECERA) + "\n2026-11-14,p,principal,x,i,,m,1k,1:1,enviando,0.1,,f,,\n",
                                   ",".join(CABECERA) + "\n2026-11-14T10:00:00-05:00,p,principal,x,i,,m,1k,1:1,"
                                   "enviando,abc,,f,,\n"])
def test_formas_corruptas(vault, linea):
    ruta = ruta_costes(vault, P)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(linea)
    with pytest.raises(CostesCorruptos):
        leer_costes(vault, P)


def test_fila_de_otro_producto_o_con_salto(vault):
    with pytest.raises(ValueError):
        anotar_coste(vault, P, fila(producto="p-0043-dishai"))
    with pytest.raises(ValueError):
        anotar_coste(vault, P, fila(imagen="a\nb"))
    with pytest.raises(ValueError):
        anotar_coste(vault, P, fila(estado="raro"))
    with pytest.raises(ValueError):
        anotar_coste(vault, P, fila(fecha=datetime(2026, 11, 14)))


def _depositar_falso():
    llamadas = []

    def depositar(vault, datos, ahora=None):
        llamadas.append(datos)
        return f"P-20261114-{len(llamadas):03d}"

    depositar.llamadas = llamadas
    return depositar


def test_una_alerta_por_dia(vault):
    dep = _depositar_falso()
    args = (vault, P, Decimal("1.9950"), Decimal("2.00"), 3, Decimal("0.0255"))
    assert avisar_tope(*args, AHORA, dep) == "P-20261114-001"
    assert avisar_tope(*args, AHORA + timedelta(hours=2), dep) is None
    assert len(dep.llamadas) == 1 and dep.llamadas[0]["titulo"] == "Tope de APIMart alcanzado"
    filas = leer_costes(vault, P)
    assert [f.estado for f in filas] == ["tope", "tope"]  # la marca antes de depositar y luego el id
    assert filas[0].intento == filas[1].intento and filas[1].archivo == "alerta P-20261114-001"
    # otro día, otra alerta
    assert avisar_tope(*args, AHORA + timedelta(days=1), dep) == "P-20261114-002"


def test_sin_buzon_sigue_detenido(vault):
    def sin_buzon(vault, datos, ahora=None):
        raise BuzonNoDisponible("el buzón aún no está instalado (plan 12)")

    args = (vault, P, Decimal("1.9950"), Decimal("2.00"), 3, Decimal("0.0255"))
    assert avisar_tope(*args, AHORA, sin_buzon) is None
    assert gastado_usd(leer_costes(vault, P)) == 0
    # el buzón no recibió nada: más tarde, con buzón, sí se avisa
    dep = _depositar_falso()
    assert avisar_tope(*args, AHORA + timedelta(hours=1), dep) == "P-20261114-001"


def test_alerta_no_se_duplica_si_algo_falla_tras_depositar(vault):
    llamadas = []

    def deposita_y_revienta(vault, datos, ahora=None):
        llamadas.append(datos)
        raise RuntimeError("se cayó justo después de depositar")

    args = (vault, P, Decimal("1.9950"), Decimal("2.00"), 3, Decimal("0.0255"))
    with pytest.raises(RuntimeError):
        avisar_tope(*args, AHORA, deposita_y_revienta)
    dep = _depositar_falso()
    assert avisar_tope(*args, AHORA + timedelta(hours=1), dep) is None
    assert len(llamadas) == 1 and dep.llamadas == []


def test_costes_corruptos_no_invita_a_editar(vault):
    ruta = ruta_costes(vault, P)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("roto\n", encoding="utf-8")
    with pytest.raises(CostesCorruptos) as info:
        leer_costes(vault, P)
    texto = str(info.value).lower()
    assert "pide ayuda" in texto and "no lo edites" in texto


def test_tope_puede_superarse_solo_en_la_diferencia_documentada():
    import trovefy.apimart.gasto as g

    assert "L4" in g.comprobar_tope.__doc__ and "diferencia" in g.comprobar_tope.__doc__


def test_subir_tope_cita_literal(vault):
    cita = 'súbele a 3 dólares, "ya"'
    ruta = subir_tope(vault, P, Decimal(3), cita, AHORA)
    assert ruta.parent == vault / "productos" / P / "decisiones"
    assert ruta.name == "2026-11-14-100000-tope-apimart.md"
    texto = ruta.read_text(encoding="utf-8")
    assert f"> {cita}" in texto
    meta, _ = frontmatter.leer(ruta)
    assert meta["cita"] == cita and meta["tope_anterior_usd"] == "2.00" and meta["tope_nuevo_usd"] == "3"
    pmeta, cuerpo = frontmatter.leer(vault / "productos" / P / "PRODUCTO.md")
    assert pmeta["paises"] == {"ZZ": {"estado": "modelado"}} and cuerpo.startswith("# Respira\n\nCuerpo a mano.\n")
    assert tope_de(vault, P, cargar_config(vault)) == Decimal(3)
    assert "tope de APIMart" in (vault / "log.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("usd,cita", [(Decimal(3), ""), (Decimal(3), "   "), (Decimal("1.50"), "bájalo"),
                                      (Decimal("2.00"), "igual"), (Decimal("3.001"), "con decimales")])
def test_subir_tope_sin_cita_o_menor_falla(vault, usd, cita):
    with pytest.raises(ValueError):
        subir_tope(vault, P, usd, cita, AHORA)
    assert not (vault / "productos" / P / "decisiones").exists()
    assert "apimart_tope_usd" not in frontmatter.leer(vault / "productos" / P / "PRODUCTO.md")[0]


def test_subir_tope_con_secreto_falla(vault):
    with pytest.raises(ValueError):
        subir_tope(vault, P, Decimal(3), "sube a 3, clave sk-ant-api03-" + "a" * 90, AHORA)
    assert not (vault / "productos" / P / "decisiones").exists()
