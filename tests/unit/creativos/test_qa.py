"""QA automática de la tanda (plan 21, Tarea 8): una tanda buena y una rota por regla."""

from decimal import Decimal

import yaml
from trovefy.creativos import coste, qa, registro
from trovefy.creativos.brief import cargar_ficha
from trovefy.creativos.contexto import cargar_contexto
from trovefy.creativos.estaticos import escribir_pieza
from trovefy.producto.medios import escribir_medio

from .ejemplos import AHORA, PAIS, P, crear_vault, info_buena, jpeg, tanda_buena


def _revisar(vault, ctx, cfg, ficha, carpeta, sondeo=info_buena, volumen=lambda _r: -3.0):
    return qa.revisar_tanda(vault, ctx, cfg, ficha, carpeta, sondeo=sondeo, volumen=volumen)


def _bloquean(h):
    return [(x.ad, x.regla) for x in h if x.bloquea]


def test_qa_buena_sin_hallazgos(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    h = _revisar(vault, ctx, cfg, ficha, carpeta)
    assert _bloquean(h) == []
    assert any(x.regla == "meta" and not x.bloquea for x in h)  # sin lista de riesgo: no medido, no bloquea
    piezas = [(e.ad, ficha.brief(e.ad).tipo) for e in ficha.elegidos]
    qa.escribir_qa_auto(carpeta, piezas, h, AHORA)
    assert registro.estado(carpeta, piezas).automatica == "ok"


def _con_brief(vault, carpeta, cambio):
    datos = yaml.safe_load((carpeta / "brief.yaml").read_text(encoding="utf-8"))
    cambio(datos)
    (carpeta / "brief.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    ctx = cargar_contexto(vault, P, PAIS)
    return ctx, datos


def test_titulo_41(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    b = ficha.candidatos[0]
    from dataclasses import replace
    ficha2 = replace(ficha, candidatos=(replace(b, titulo="а" * 41), *ficha.candidatos[1:]))
    assert ("AD01", "texto") in _bloquean(_revisar(vault, ctx, cfg, ficha2, carpeta))


def test_video_31s(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    h = _revisar(vault, ctx, cfg, ficha, carpeta, sondeo=lambda r: {**info_buena(r), "duracion": 31.0})
    assert ("AD02", "video") in _bloquean(h)


def test_video_mudo_falla(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    h = _revisar(vault, ctx, cfg, ficha, carpeta, volumen=lambda _r: float("-inf"))
    assert ("AD02", "video") in _bloquean(h)


def test_imagen_1080x1080(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    escribir_pieza(vault, carpeta, "AD01", jpeg(1080, 1080), "jpg")
    assert ("AD01", "imagen") in _bloquean(_revisar(vault, ctx, cfg, ficha, carpeta))


def test_url_sin_utm(tmp_path):
    vault = crear_vault(tmp_path, landing=None)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    assert (None, "url") in _bloquean(_revisar(vault, ctx, cfg, ficha, carpeta))


def test_nombre_mal(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    from dataclasses import replace
    e = replace(ficha.elegidos[0], angulo_corto="x" * 30)
    ficha2 = replace(ficha, grupo="G1 extra larguísimo de más", elegidos=(e, *ficha.elegidos[1:]))
    assert ("AD01", "nombre") in _bloquean(_revisar(vault, ctx, cfg, ficha2, carpeta))


def test_precio_otro(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    from dataclasses import replace
    b = replace(ficha.candidatos[0], precio_dicho="само 9,90 €")
    ficha2 = replace(ficha, candidatos=(b, *ficha.candidatos[1:]))
    assert ("AD01", "precio") in _bloquean(_revisar(vault, ctx, cfg, ficha2, carpeta))


def test_precio_en_cifras_en_la_voz(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    ruta = carpeta / "guiones" / "AD02.yaml"
    g = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    g["segmentos"][0]["texto_voz"] = "Струва само 13,90 евро."
    ruta.write_text(yaml.safe_dump(g, allow_unicode=True), encoding="utf-8")
    assert ("AD02", "precio") in _bloquean(_revisar(vault, ctx, cfg, ficha, carpeta))


def test_archivo_sin_origen_falla(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    escribir_medio(carpeta / "AD03.mp4", b"\x00\x00\x00\x18ftypmp42otro", base=vault)  # no pasa por el manifiesto
    assert ("AD03", "archivo") in _bloquean(_revisar(vault, ctx, cfg, ficha, carpeta))


def test_coste_sobre_tope(tmp_path, monkeypatch):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    monkeypatch.setattr(qa, "gastado_usd", lambda _f: Decimal("6.50"))
    assert (None, "coste") in _bloquean(_revisar(vault, ctx, cfg, ficha, carpeta))
    assert coste.tope_vigente(vault, P, PAIS, "t1", cfg) == Decimal("6.00")


def test_riesgo_meta_sin_lista_no_medido(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    meta = [x for x in _revisar(vault, ctx, cfg, ficha, carpeta) if x.regla == "meta"]
    assert meta and all(not x.bloquea and x.texto.startswith("no medido") for x in meta)
    from dataclasses import replace
    cfg2 = replace(cfg, expresiones_riesgo={"bg": ("ти помага",)})
    assert ("AD01", "meta") in _bloquean(_revisar(vault, ctx, cfg2, ficha, carpeta))


def test_ficha_desde_disco(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, _, carpeta = tanda_buena(vault)
    assert len(cargar_ficha(carpeta, ctx, cfg).elegidos) == 10
