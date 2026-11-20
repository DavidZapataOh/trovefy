"""Clips y música de la tanda con APIMart (plan 21, Tarea 7). Con APIMart falso."""

from decimal import Decimal

import pytest
from trovefy.apimart import cliente
from trovefy.apimart.musica import enviar_musica, leer_tarea_musica
from trovefy.apimart.video import descargar_binario, enviar_video, leer_tarea_video
from trovefy.creativos import clips, coste, escenas
from trovefy.creativos.contexto import cargar_contexto, ruta_tanda
from trovefy.creativos.guion import validar_video
from trovefy.producto.medios import escribir_medio, leer_manifiesto, registrar_medio

from .ejemplos import AHORA, PAIS, P, crear_vault, guion_video, png
from .falsos import CRED, APIMartFalso, publico, wav
from .test_voz import SIN_PRECIOS, ajustar

VIDEO = [("modelo_video", "seedance-2.0"), ("precio_video_usd_segundo", '"0.02"')]
MUSICA = [("licencia_musica_comercial", "true"), ("precio_musica_usd_pista", '"0.10"')]


def _api(falso):
    return clips.Apimart(
        enviar_video=lambda c: enviar_video(CRED, c, falso),
        enviar_musica=lambda c: enviar_musica(CRED, c, falso),
        esperar_video=lambda t: cliente.esperar(CRED, t, falso, lambda _s: None, leer=leer_tarea_video),
        esperar_musica=lambda t: cliente.esperar(CRED, t, falso, lambda _s: None, ruta="/v1/music/tasks/{}",
                                                 leer=leer_tarea_musica),
        descargar_video=lambda u: descargar_binario(u, publico),
        descargar_audio=lambda u: descargar_binario(u, publico, tipo="audio"),
        subir_imagen=lambda r: "https://upload.apimart.ai/f/img.png",
        subir_audio=lambda n, d: "https://upload.apimart.ai/f/voz.wav")


@pytest.fixture
def base(tmp_path):
    vault = crear_vault(tmp_path)
    carpeta = ruta_tanda(vault, P, PAIS, "t1")
    carpeta.mkdir(parents=True)
    return vault, carpeta


def _aprobar(vault):
    est = coste.Estimacion((coste.Partida("clips", 40, "segundo", Decimal("0.02"), "p"),))
    coste.aprobar(vault, P, PAIS, "t1", est, Decimal("6.00"), "sí", AHORA)


def _clips(vault, carpeta, cfg, plantilla="claymation", **kw):
    ctx = cargar_contexto(vault, P, PAIS)
    g = validar_video("AD09", guion_video(plantilla), cfg)
    falso = kw.pop("falso", APIMartFalso())
    r = clips.generar_clips(vault, P, escenas.destino(vault, ctx, cfg, "t1"), carpeta, g, cfg,
                            propios=ctx.medios_propios, api=_api(falso), ahora=lambda: AHORA, **kw)
    return r, falso, g


def test_clips_sin_coste_aprobado_no_envia(base):
    vault, carpeta = base
    cfg = ajustar(vault, *VIDEO)
    r, falso, _ = _clips(vault, carpeta, cfg)
    assert not falso.rutas and all(e.estado == "detenido" and "aprobar-coste" in e.motivo for e in r)


def test_sin_precio_de_video_no_medido(base):
    vault, carpeta = base
    r, falso, _ = _clips(vault, carpeta, ajustar(vault, *SIN_PRECIOS))
    assert not falso.rutas and r[0].motivo.startswith("no medido")


def test_clips_generados_y_registrados(base):
    vault, carpeta = base
    cfg = ajustar(vault, *VIDEO)
    _aprobar(vault)
    r, falso, g = _clips(vault, carpeta, cfg)
    assert [e.estado for e in r] == ["completada"] * 5, r
    cuerpo = falso.cuerpos[0]
    assert cuerpo["model"] == "seedance-2.0" and cuerpo["size"] == "9:16" and cuerpo["generate_audio"] is False
    assert set(clips.clips_descargados(carpeta, g)) == {"g", "s01", "s02", "s03", "s04"}


def test_solo_gancho(base):
    vault, carpeta = base
    cfg = ajustar(vault, *VIDEO)
    _aprobar(vault)
    r, falso, _ = _clips(vault, carpeta, cfg, solo_gancho=True)
    assert [e.id for e in r] == ["clip-ad09-g"] and len(falso.cuerpos) == 1


def test_ugc_exige_su_voz_y_la_manda(base):
    vault, carpeta = base
    cfg = ajustar(vault, *VIDEO)
    _aprobar(vault)
    fuente = carpeta / "fuente"
    sha = escribir_medio(fuente / "medios" / "e01.png", png(), base=vault)
    registrar_medio(fuente, "e01", "e01.png", sha, "apimart", base=vault)
    r, falso, _ = _clips(vault, carpeta, cfg, plantilla="ugc")
    assert any("primero la voz" in (e.motivo or "") for e in r)
    for clave in ("s01", "s02", "s03", "s04"):
        s = escribir_medio(fuente / "medios" / f"voz-ad09-{clave}.wav", wav(), base=vault)
        registrar_medio(fuente, f"voz-ad09-{clave}", f"voz-ad09-{clave}.wav", s, "apimart", base=vault)
    r, falso, _ = _clips(vault, carpeta, cfg, plantilla="ugc")
    assert all(e.estado in ("completada", "omitida") for e in r), r
    con_audio = [c for c in falso.cuerpos if "audio_urls" in c]
    assert len(con_audio) == 4 and all(c["image_urls"] for c in con_audio)


def test_clip_con_imagen_ajena_no_sale(base):
    vault, carpeta = base
    cfg = ajustar(vault, *VIDEO)
    _aprobar(vault)
    datos = guion_video("claymation")
    datos["segmentos"][0]["clip"] = {"prompt": "x", "tipo": "imagen", "ref": "anuncio-competidor"}
    ctx = cargar_contexto(vault, P, PAIS)
    g = validar_video("AD09", datos, cfg)
    falso = APIMartFalso()
    r = clips.generar_clips(vault, P, escenas.destino(vault, ctx, cfg, "t1"), carpeta, g, cfg,
                            propios=ctx.medios_propios, api=_api(falso), ahora=lambda: AHORA)
    assert any("nada ajeno" in (e.motivo or "") for e in r)


def test_musica_sin_licencia_no_sale(base):
    vault, carpeta = base
    cfg = ajustar(vault, *VIDEO)
    _aprobar(vault)
    ctx = cargar_contexto(vault, P, PAIS)
    falso = APIMartFalso()
    e = clips.generar_musica(vault, P, escenas.destino(vault, ctx, cfg, "t1"), carpeta, cfg, "piano suave",
                             api=_api(falso), ahora=lambda: AHORA)
    assert e.estado == "detenido" and "licencia" in e.motivo and not falso.rutas


def test_musica_con_licencia_al_lado(base):
    vault, carpeta = base
    cfg = ajustar(vault, *VIDEO, *MUSICA)
    _aprobar(vault)
    ctx = cargar_contexto(vault, P, PAIS)
    falso = APIMartFalso()
    e = clips.generar_musica(vault, P, escenas.destino(vault, ctx, cfg, "t1"), carpeta, cfg, "piano suave",
                             api=_api(falso), ahora=lambda: AHORA)
    assert e.estado == "completada", e
    assert falso.cuerpos[-1]["instrumental"] is True
    assert clips.ruta_musica(carpeta) is not None and (carpeta / "musica" / "LICENCIA.md").is_file()


def test_musica_propia_exige_licencia(base):
    vault, carpeta = base
    origen = vault / "config" / "creativos" / "musica" / "calma.mp3"
    origen.parent.mkdir(parents=True)
    origen.write_bytes(b"ID3" + b"\x00" * 64)
    with pytest.raises(ValueError, match="licencia"):
        clips.musica_propia(vault, carpeta, origen)
    origen.with_name("calma.mp3.licencia.md").write_text("Licencia comercial de la biblioteca X", encoding="utf-8")
    ruta = clips.musica_propia(vault, carpeta, origen)
    assert leer_manifiesto(carpeta / "fuente")["musica"]["origen"] == "propio" and ruta.is_file()
    t2 = ruta_tanda(vault, P, PAIS, "t2")
    clips.reutilizar_musica(vault, carpeta, t2)
    assert clips.ruta_musica(t2) is not None
