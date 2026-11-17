import json
import multiprocessing
import stat
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import yaml
from trovefy.apimart.cliente import PeticionImagen, PeticionInvalida
from trovefy.apimart.gasto import gastado_usd, leer_costes
from trovefy.apimart.http import Credenciales, SinRed
from trovefy.apimart.lote import (
    ResultadoLote,
    generar_imagenes,
    leer_peticiones,
    reanudar,
)
from trovefy.apimart.precios import Precio
from trovefy.producto.config import cargar_config, iniciar_config
from trovefy.producto.medios import leer_manifiesto
from trovefy.vault import frontmatter

from .ayudas import CLAVE, fixture

P = "p-0042-respira"
COT = timezone(timedelta(hours=-5))
T0 = datetime(2026, 11, 14, 10, 0, tzinfo=COT)
CRED = Credenciales("https://api.apimart.ai", CLAVE)
PRECIO = Precio("gpt-image-2", "1k", Decimal("0.0085"), "prueba", date(2026, 11, 14))
PNG = fixture("png-1x1.png")


class _Resp:
    def __init__(self, cuerpo, codigo=200):
        self.status, self._c = codigo, cuerpo

    def read(self, *_a):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None


class APIMartFalso:
    """Despacha por ruta: generación → task_id; tareas → completada (o en proceso); balance → ilimitado."""

    def __init__(self, tareas="completada", post_lanza=None):
        self.tareas, self.post_lanza = tareas, post_lanza
        self.rutas: list[str] = []
        self.n = 0

    def __call__(self, req, timeout=None):
        ruta = req.full_url.removeprefix("https://api.apimart.ai")
        self.rutas.append(f"{req.get_method()} {ruta}")
        if ruta == "/v1/images/generations":
            if self.post_lanza:
                raise self.post_lanza
            self.n += 1
            return _Resp(json.dumps({"code": 200, "data": [{"status": "submitted", "task_id": f"task_{self.n}"}]})
                         .encode())
        if ruta.startswith("/v1/tasks/"):
            tid = ruta.rsplit("/", 1)[1]
            if self.tareas == "en_proceso":
                return _Resp(json.dumps(fixture("tarea-en-proceso.json")).encode())
            datos = fixture("tarea-completada.json")
            datos["data"].update(id=tid, cost=0.0085, credits_cost=0.085)
            datos["data"]["result"]["images"][0]["url"] = [f"https://upload.apimart.ai/f/image/{tid}.png"]
            return _Resp(json.dumps(datos).encode())
        if ruta == "/v1/balance":
            return _Resp(json.dumps({"success": True, "remain_balance": 0, "remain_credits": -1,
                                     "unlimited_quota": True}).encode())
        raise AssertionError(f"ruta inesperada {ruta}")


def publico(req, timeout=None):
    assert "Authorization" not in req.headers
    return _Resp(PNG)


def explota(*_a, **_k):
    raise AssertionError("no debía llamar a la red")


def pet(id_, prompt=None, pieza="principal"):
    return PeticionImagen(id_, pieza, prompt or f"ilustración {id_}", "2:3", "1k")


PETS = [pet("portada"), pet("mockup"), pet("il-01")]


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "productos" / P).mkdir(parents=True)
    frontmatter.escribir(tmp_path / "productos" / P / "PRODUCTO.md", {"id": P}, "# Respira\n")
    (tmp_path / ".trovefy").mkdir()
    iniciar_config(tmp_path)
    return tmp_path


def poner_tope(vault, usd):
    ruta = vault / "productos" / P / "PRODUCTO.md"
    meta, cuerpo = frontmatter.leer(ruta)
    frontmatter.escribir(ruta, {**meta, "apimart_tope_usd": usd}, cuerpo)


def _depositar_falso():
    llamadas = []

    def depositar(vault, datos, ahora=None):
        llamadas.append(datos)
        return f"P-20261114-{len(llamadas):03d}"

    depositar.llamadas = llamadas
    return depositar


def lote(vault, peticiones=PETS, abrir=None, **k):
    opciones = {"cred": CRED, "cfg": cargar_config(vault), "precio": PRECIO, "abrir": abrir or APIMartFalso(),
                "abrir_publico": publico, "dormir": lambda s: None, "ahora": lambda: T0,
                "depositar": _depositar_falso(), **k}
    return generar_imagenes(vault, P, list(peticiones), **opciones)


def test_lote_genera_y_registra(vault):
    falso = APIMartFalso()
    r = lote(vault, abrir=falso)
    assert r == ResultadoLote(("portada", "mockup", "il-01"), (), (), (), None, None)
    medios = vault / "productos" / P / "entregable" / "medios"
    for i in ("portada", "mockup", "il-01"):
        assert stat.S_IMODE((medios / f"{i}.png").stat().st_mode) == 0o640
    man = leer_manifiesto(vault / "productos" / P / "entregable")
    assert man["portada"]["origen"] == "apimart" and man["portada"]["task_id"] == "task_1"
    assert man["portada"]["modelo"] == "gpt-image-2" and len(man["portada"]["prompt_sha256"]) == 64
    filas = leer_costes(vault, P)
    assert gastado_usd(filas) == Decimal("0.0255")
    assert [f.estado for f in filas] == ["enviando", "enviada", "completada"] * 3
    assert filas[2].sha256 == man["portada"]["sha256"] and filas[2].archivo == "medios/portada.png"
    assert "/v1/balance" not in " ".join(falso.rutas)
    assert "/producto" in (vault / "log.md").read_text(encoding="utf-8")


def test_pieza_bono_va_a_su_raiz(vault):
    lote(vault, [pet("il-01", pieza="bono-1")])
    raiz = vault / "productos" / P / "entregable" / "bonos" / "bono-1"
    assert (raiz / "medios" / "il-01.png").is_file()
    assert leer_costes(vault, P)[-1].archivo == "bonos/bono-1/medios/il-01.png"


def test_stop_no_llama(vault):
    (vault / ".trovefy" / "STOP").write_text("")
    r = lote(vault, abrir=explota, abrir_publico=explota)
    assert r.detenido == "STOP del cerebro activo: no se genera nada" and r.generadas == ()
    assert leer_costes(vault, P) == []


def test_sin_precio_no_envia(vault):
    r = lote(vault, abrir=explota, precio=None)
    assert r.detenido.startswith("no medido: precio") and leer_costes(vault, P) == []


def test_saldo_ilimitado_no_sustituye_al_tope(vault):
    poner_tope(vault, "0.01")
    falso = APIMartFalso()
    dep = _depositar_falso()
    r = lote(vault, abrir=falso, depositar=dep)
    assert r.generadas == ("portada",) and r.detenido.startswith("tope")
    assert r.alerta_id == "P-20261114-001"
    assert not any("balance" in x for x in falso.rutas)
    assert falso.rutas.count("POST /v1/images/generations") == 1


def test_tope_para_y_avisa_una_vez(vault):
    poner_tope(vault, "0.01")
    dep = _depositar_falso()
    r1 = lote(vault, depositar=dep)
    assert r1.detenido.startswith("tope") and len(dep.llamadas) == 1
    assert "Faltan 2 imágenes" in dep.llamadas[0]["texto"]
    r2 = lote(vault, depositar=dep)
    assert r2.detenido.startswith("tope") and r2.alerta_id is None and len(dep.llamadas) == 1
    assert r2.omitidas == ("portada",)


def test_imagen_ya_generada_no_se_repite(vault):
    lote(vault, [pet("portada")])
    falso = APIMartFalso()
    r = lote(vault, [pet("portada")], abrir=falso)
    assert r.omitidas == ("portada",) and r.generadas == () and falso.rutas == []


def test_cambiar_prompt_regenera(vault):
    lote(vault, [pet("portada")])
    falso = APIMartFalso()
    r = lote(vault, [pet("portada", "otra portada")], abrir=falso)
    assert r.generadas == ("portada",) and falso.rutas.count("POST /v1/images/generations") == 1
    man = leer_manifiesto(vault / "productos" / P / "entregable")
    assert man["portada"]["task_id"] == "task_1"  # el del falso nuevo
    assert gastado_usd(leer_costes(vault, P)) == Decimal("0.0170")


def test_envio_sin_respuesta_cuenta_como_gastado(vault):
    r = lote(vault, abrir=APIMartFalso(post_lanza=SinRed("sin red")))
    assert r.detenido and "portada" in r.detenido and "gastado" in r.detenido
    filas = leer_costes(vault, P)
    assert [f.estado for f in filas] == ["enviando"]
    assert gastado_usd(filas) == Decimal("0.0085")


def test_envio_que_lanza_url_error(vault):
    import urllib.error

    r = lote(vault, abrir=APIMartFalso(post_lanza=urllib.error.URLError("caída")))
    assert r.detenido and gastado_usd(leer_costes(vault, P)) == Decimal("0.0085")


def test_pendiente_no_se_reenvia_en_otro_lote(vault):
    reloj = iter(range(0, 100_000, 700))
    r = lote(vault, [pet("portada")], abrir=APIMartFalso(tareas="en_proceso"), reloj=lambda: next(reloj))
    assert r.pendientes == ("portada",)
    falso = APIMartFalso()
    r2 = lote(vault, [pet("portada")], abrir=falso)
    assert r2.pendientes == ("portada",) and "POST /v1/images/generations" not in falso.rutas
    assert gastado_usd(leer_costes(vault, P)) == Decimal("0.0085")


def test_reanudar_no_reenvia(vault):
    reloj = iter(range(0, 100_000, 700))
    r = lote(vault, [pet("portada")], abrir=APIMartFalso(tareas="en_proceso"), reloj=lambda: next(reloj))
    assert r.pendientes == ("portada",)
    assert [f.estado for f in leer_costes(vault, P)] == ["enviando", "enviada", "pendiente"]
    falso = APIMartFalso()
    r2 = reanudar(vault, P, cred=CRED, abrir=falso, abrir_publico=publico, dormir=lambda s: None, ahora=lambda: T0)
    assert r2.generadas == ("portada",)
    assert all(x.startswith("GET /v1/tasks/") for x in falso.rutas) and falso.rutas
    man = leer_manifiesto(vault / "productos" / P / "entregable")
    assert man["portada"]["task_id"] == "task_1" and man["portada"]["origen"] == "apimart"
    assert gastado_usd(leer_costes(vault, P)) == Decimal("0.0085")
    # ya completada: otro lote la omite
    assert lote(vault, [pet("portada")], abrir=explota).omitidas == ("portada",)
    # y reanudar ya no tiene nada que hacer
    assert reanudar(vault, P, cred=CRED, abrir=explota, abrir_publico=explota, dormir=lambda s: None,
                    ahora=lambda: T0).generadas == ()


def _proceso(vault, ids):
    lote(vault, [pet(i) for i in ids], depositar=lambda *a, **k: "P-1")


def test_dos_procesos_no_superan_el_tope(vault):
    poner_tope(vault, "0.02")  # 2 imágenes de 0,0085 caben; la 3.ª no
    ctx = multiprocessing.get_context("fork")
    procs = [ctx.Process(target=_proceso, args=(vault, ids)) for ids in (["a1", "a2"], ["b1", "b2"])]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
        assert p.exitcode == 0
    filas = leer_costes(vault, P)
    assert sum(f.estado == "completada" for f in filas) <= 2
    assert gastado_usd(filas) <= Decimal("0.02")


def test_simular_no_llama(vault):
    r = lote(vault, abrir=explota, abrir_publico=explota, simular=True)
    assert r.detenido is None and r.generadas == ()
    filas = leer_costes(vault, P)
    assert [f.estado for f in filas] == ["simulada"] * 3 and gastado_usd(filas) == 0
    assert not (vault / "productos" / P / "entregable" / "medios").exists()


def test_peticion_invalida_no_gasta(vault):
    with pytest.raises(PeticionInvalida):
        lote(vault, [pet("portada"), PeticionImagen("x", "principal", "p", "3:5", "1k")], abrir=explota)
    assert leer_costes(vault, P) == []


def test_resolucion_distinta_del_precio(vault):
    with pytest.raises(PeticionInvalida):
        lote(vault, [PeticionImagen("x", "principal", "p", "1:1", "4k")], abrir=explota)


def _yaml(vault, datos):
    ruta = vault / "productos" / P / "entregable" / "imagenes.yaml"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")


def test_leer_peticiones(vault):
    _yaml(vault, [{"id": "portada", "pieza": "principal", "prompt": "una portada", "proporcion": "2:3",
                   "resolucion": "1k", "referencias": ["logo"]},
                  {"id": "il-01", "pieza": "bono-1", "prompt": "otra", "proporcion": "1:1", "resolucion": "1k"}])
    ps = leer_peticiones(vault, P)
    assert ps[0] == PeticionImagen("portada", "principal", "una portada", "2:3", "1k", ("logo",))
    assert ps[1].referencias == ()


@pytest.mark.parametrize("datos", [
    [{"id": "a", "pieza": "principal", "prompt": "x", "proporcion": "1:1", "resolucion": "1k"}] * 2,
    {"no": "lista"},
    [{"id": "a", "pieza": "principal", "prompt": "x", "proporcion": "1:1"}],
    [{"id": "a", "pieza": "principal", "prompt": "x", "proporcion": "1:1", "resolucion": "1k", "otra": 1}],
    [{"id": "a", "pieza": "principal", "prompt": 3, "proporcion": "1:1", "resolucion": "1k"}],
])
def test_leer_peticiones_invalidas(vault, datos):
    _yaml(vault, datos)
    with pytest.raises(PeticionInvalida):
        leer_peticiones(vault, P)


def test_sin_imagenes_yaml(vault):
    with pytest.raises(FileNotFoundError):
        leer_peticiones(vault, P)
