import io
import itertools
import json
import multiprocessing
import stat
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import yaml
from PIL import Image
from trovefy.apimart.cliente import PeticionImagen, PeticionInvalida
from trovefy.apimart.gasto import gastado_usd, leer_costes
from trovefy.apimart.http import Credenciales, SinRed
from trovefy.apimart.lote import (
    MOTIVO_SIN_RESPUESTA,
    MOTIVO_STOP,
    ResultadoLote,
    descartar,
    generar_imagenes,
    leer_peticiones,
    reanudar,
)
from trovefy.apimart.precios import Precio
from trovefy.producto.config import cargar_config, iniciar_config
from trovefy.producto.medios import escribir_medio, leer_manifiesto, registrar_medio
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

    def __init__(self, tareas="completada", post_lanza=None, al_post=None, al_subir=None, coste=0.0085):
        self.tareas, self.post_lanza, self.al_post, self.al_subir = tareas, post_lanza, al_post, al_subir
        self.coste = coste
        self.rutas: list[str] = []
        self.cuerpos: list[dict] = []
        self.n = 0

    def __call__(self, req, timeout=None):
        ruta = req.full_url.removeprefix("https://api.apimart.ai")
        self.rutas.append(f"{req.get_method()} {ruta}")
        if ruta.startswith("/v1/uploads/images"):
            if self.al_subir:
                self.al_subir()
            return _Resp(json.dumps(fixture("subida-imagen.json")).encode())
        if ruta == "/v1/images/generations":
            self.cuerpos.append(json.loads(req.data))
            if self.al_post:
                self.al_post()
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
            datos["data"].update(id=tid, cost=self.coste, credits_cost=0.085)
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
    """Tope del producto como lo deja ``subir_tope``: la decisión con cita y el valor en PRODUCTO.md."""
    ruta = vault / "productos" / P / "PRODUCTO.md"
    meta, cuerpo = frontmatter.leer(ruta)
    frontmatter.escribir(ruta.parent / "decisiones" / "2026-11-14-090000-tope-apimart.md",
                         {"tipo": "decision", "producto": P, "decision": "tope_apimart", "tope_nuevo_usd": usd,
                          "cita": f"tope de {usd}"}, "# Tope\n")
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


# --- ronda de revisión de las Tareas 2–5 ------------------------------------------------------------

def _stop(vault):
    (vault / ".trovefy" / "STOP").write_text("")


def test_stop_a_mitad_de_lote_no_envia_mas(vault):
    falso = APIMartFalso(al_post=lambda: _stop(vault))
    r = lote(vault, abrir=falso)
    assert r.detenido == MOTIVO_STOP
    assert falso.rutas.count("POST /v1/images/generations") == 1
    assert r.generadas == ("portada",)  # la ya enviada se sondea y se guarda (está pagada)
    assert [f.imagen for f in leer_costes(vault, P) if f.estado == "enviando"] == ["portada"]


def _medio_propio(vault, id_="logo", datos=PNG, pieza_raiz=None):
    raiz = pieza_raiz or vault / "productos" / P / "entregable"
    sha = escribir_medio(raiz / "medios" / f"{id_}.png", datos, base=vault)
    registrar_medio(raiz, id_, f"{id_}.png", sha, "propio")
    return raiz / "medios" / f"{id_}.png"


def pet_ref(id_, refs=("logo",)):
    return PeticionImagen(id_, "principal", f"ilustración {id_}", "2:3", "1k", tuple(refs))


def test_stop_antes_de_subir_referencia_no_sube(vault):
    _medio_propio(vault, "logo")
    _medio_propio(vault, "foto")
    falso = APIMartFalso(al_subir=lambda: _stop(vault))
    r = lote(vault, [pet_ref("portada", ("logo", "foto"))], abrir=falso)
    assert r.detenido == MOTIVO_STOP
    assert sum(x.startswith("POST /v1/uploads/images") for x in falso.rutas) == 1
    assert "POST /v1/images/generations" not in falso.rutas
    assert leer_costes(vault, P) == []


def test_stop_en_reanudar_no_sondea(vault):
    reloj = iter(range(0, 100_000, 700))
    lote(vault, [pet("portada"), pet("mockup")], abrir=APIMartFalso(tareas="en_proceso"), reloj=lambda: next(reloj))
    llamadas = []

    def abrir(req, timeout=None):
        llamadas.append(req.full_url)
        _stop(vault)
        return APIMartFalso()(req, timeout)

    r = reanudar(vault, P, cred=CRED, abrir=abrir, abrir_publico=publico, dormir=lambda s: None, ahora=lambda: T0)
    assert r.detenido == MOTIVO_STOP and len(r.generadas) == 1 and len(llamadas) == 1


def test_envio_sin_respuesta_no_se_reenvia_en_otro_lote(vault):
    r = lote(vault, [pet("portada")], abrir=APIMartFalso(post_lanza=SinRed("sin red")))
    assert r.detenido
    falso = APIMartFalso()
    r2 = lote(vault, [pet("portada"), pet("mockup")], abrir=falso)
    assert falso.rutas.count("POST /v1/images/generations") == 1  # solo mockup
    assert r2.pendientes == ("portada",) and r2.generadas == ("mockup",)
    assert r2.avisos == (f"portada: {MOTIVO_SIN_RESPUESTA}",)
    assert MOTIVO_SIN_RESPUESTA == "sin respuesta del envío; revisa el panel de APIMart"
    # reanudar tampoco la toca: no hay task_id que sondear
    r3 = reanudar(vault, P, cred=CRED, abrir=explota, abrir_publico=explota, dormir=lambda s: None, ahora=lambda: T0)
    assert r3.generadas == () and r3.pendientes == ("portada",)
    assert gastado_usd(leer_costes(vault, P)) == Decimal("0.0170")


def test_descartar_permite_reenviar_y_conserva_el_estimado(vault):
    lote(vault, [pet("portada")], abrir=APIMartFalso(post_lanza=SinRed("sin red")))
    assert descartar(vault, P, "principal", "portada", ahora=lambda: T0) == 1
    filas = leer_costes(vault, P)
    assert filas[-1].estado == "fallida" and filas[-1].coste_estimado_usd == Decimal("0.0085")
    assert gastado_usd(filas) == Decimal("0.0085")
    falso = APIMartFalso()
    r = lote(vault, [pet("portada")], abrir=falso)
    assert r.generadas == ("portada",) and falso.rutas.count("POST /v1/images/generations") == 1
    assert gastado_usd(leer_costes(vault, P)) == Decimal("0.0170")
    assert "descart" in (vault / "log.md").read_text(encoding="utf-8")


def test_descartar_sin_envio_bloqueado_falla(vault):
    lote(vault, [pet("portada")])
    with pytest.raises(ValueError):
        descartar(vault, P, "principal", "portada", ahora=lambda: T0)
    with pytest.raises(ValueError):
        descartar(vault, P, "principal", "nada", ahora=lambda: T0)


def test_referencias_se_suben_y_van_en_el_cuerpo(vault):
    _medio_propio(vault, "logo")
    falso = APIMartFalso()
    r = lote(vault, [pet_ref("portada")], abrir=falso)
    assert r.generadas == ("portada",)
    assert falso.rutas[0] == "POST /v1/uploads/images?retention_days=3"
    assert falso.cuerpos[0]["image_urls"] == ["https://cdn.example/uploads/reference.png"]
    man = leer_manifiesto(vault / "productos" / P / "entregable")
    assert man["logo"]["origen"] == "propio" and man["portada"]["origen"] == "apimart"
    assert (vault / "data" / "cache" / "apimart-subidas.json").is_file()


def test_referencia_cambiada_no_se_sube(vault):
    ruta = _medio_propio(vault, "logo")
    otro = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(otro, "PNG")
    ruta.write_bytes(otro.getvalue())  # mismo nombre y modo, otros bytes
    falso = APIMartFalso()
    r = lote(vault, [pet_ref("portada")], abrir=falso)
    assert r.detenido and "referencias de portada" in r.detenido and "sha256" in r.detenido
    assert falso.rutas == [] and leer_costes(vault, P) == []


def test_referencia_enlace_simbolico_no_se_sube(vault, tmp_path_factory):
    ruta = _medio_propio(vault, "logo")
    fuera = tmp_path_factory.mktemp("fuera") / "secreto.png"
    fuera.write_bytes(PNG)
    ruta.unlink()
    ruta.symlink_to(fuera)
    falso = APIMartFalso()
    r = lote(vault, [pet_ref("portada")], abrir=falso)
    assert r.detenido and falso.rutas == [] and leer_costes(vault, P) == []


def _texto_guardado(vault):
    ent = vault / "productos" / P / "entregable"
    return "".join(p.read_text(encoding="utf-8") for p in (ent / "costes.csv", ent / ".apimart-intentos.jsonl",
                                                           vault / "log.md") if p.exists())


@pytest.mark.parametrize("fallo", ["post_http", "post_urlerror", "subida"])
def test_la_clave_no_se_guarda_en_ningun_sitio(vault, fallo):
    import http.client
    import urllib.error

    _medio_propio(vault, "logo")
    falso = APIMartFalso()
    if fallo == "post_http":
        falso.post_lanza = http.client.BadStatusLine(f"Bearer {CLAVE}")
    elif fallo == "post_urlerror":
        falso.post_lanza = urllib.error.URLError(f"caída con {CLAVE}")
    else:
        def subir_mal():
            raise http.client.IncompleteRead(CLAVE.encode())
        falso.al_subir = subir_mal
    r = lote(vault, [pet("mockup"), pet_ref("portada")], abrir=falso)
    assert r.detenido and CLAVE not in r.detenido and CLAVE not in repr(r)
    assert CLAVE not in _texto_guardado(vault)


def test_la_clave_no_se_guarda_en_un_lote_bueno(vault):
    _medio_propio(vault, "logo")
    r = lote(vault, [pet("mockup"), pet_ref("portada")])
    assert r.generadas == ("mockup", "portada") and CLAVE not in repr(r)
    assert CLAVE not in _texto_guardado(vault)
    assert CLAVE not in (vault / "productos" / P / "entregable" / "medios" / "medios.json").read_text()


def test_coste_real_cero_usa_el_estimado(vault):
    lote(vault, [pet("portada")], abrir=APIMartFalso(coste=0))
    filas = leer_costes(vault, P)
    assert filas[-1].estado == "completada"
    assert gastado_usd(filas) == Decimal("0.0085")
    man = leer_manifiesto(vault / "productos" / P / "entregable")
    assert Decimal(man["portada"]["coste_usd"]) == Decimal("0.0085")


def test_faltan_cuenta_solo_las_que_se_generarian(vault):
    lote(vault, [pet("il-01")])  # ya generada: se omitirá
    poner_tope(vault, "0.01")    # 0,0085 gastado: no cabe otra
    dep = _depositar_falso()
    r = lote(vault, [pet("portada"), pet("il-01"), pet("mockup")], depositar=dep)
    assert r.detenido.startswith("tope") and "faltan 2 imágenes" in r.detenido
    assert "Faltan 2 imágenes" in dep.llamadas[0]["texto"]


# --- concurrencia real: el POST del proceso A se queda dentro mientras B intenta entrar ---------

def _post_contendido(vault, papel, barrera, registro):
    import os
    import time as _t

    primero = [True]

    def al_post():
        inicio = _t.monotonic()
        if papel == "a" and primero[0]:
            primero[0] = False
            barrera.wait(10)   # B arranca su lote ahora, con A dentro del POST y con el cerrojo
            _t.sleep(0.5)      # tiempo de sobra para que B llegue al flock
        with open(registro, "a") as f:
            f.write(f"post {papel} {inicio} {_t.monotonic()} {os.getpid()}\n")

    if papel == "b":
        barrera.wait(10)
        with open(registro, "a") as f:
            f.write(f"entra b {_t.monotonic()}\n")
    ids = ["a1", "a2"] if papel == "a" else ["b1", "b2"]
    lote(vault, [pet(i) for i in ids], abrir=APIMartFalso(al_post=al_post), depositar=lambda *a, **k: "P-1")


def test_dos_procesos_compiten_de_verdad_por_el_cerrojo(vault, tmp_path_factory):
    poner_tope(vault, "0.02")  # caben 2 imágenes de 0,0085; la 3.ª no
    registro = tmp_path_factory.mktemp("reg") / "posts.txt"
    ctx = multiprocessing.get_context("fork")
    barrera = ctx.Barrier(2)
    procs = [ctx.Process(target=_post_contendido, args=(vault, papel, barrera, registro)) for papel in "ab"]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    lineas = [x.split() for x in registro.read_text().splitlines()]
    posts = sorted((float(x[2]), float(x[3])) for x in lineas if x[0] == "post")
    entra_b = next(float(x[2]) for x in lineas if x[0] == "entra")
    primero_a = min(float(x[2]) for x in lineas if x[0] == "post" and x[1] == "a")
    fin_primero_a = next(float(x[3]) for x in lineas if x[0] == "post" and float(x[2]) == primero_a)
    assert primero_a < entra_b < fin_primero_a  # B intentó entrar con A dentro del POST
    assert all(fin <= sig_ini for (_, fin), (sig_ini, _) in itertools.pairwise(posts))  # nunca a la vez
    assert len(posts) == 2
    filas = leer_costes(vault, P)
    assert sum(f.estado == "completada" for f in filas) == 2 and gastado_usd(filas) <= Decimal("0.02")
