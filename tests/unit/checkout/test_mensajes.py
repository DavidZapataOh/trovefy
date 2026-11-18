"""Registro de los mensajes del usuario (Tarea 11): `trovefy checkout aprobar` solo acepta una cita que el usuario
escribió de verdad en el chat, después de ver el plan. El registro guarda huellas, nunca el texto."""
from __future__ import annotations

import json
import stat

from trovefy.checkout.mensajes import (
    MAX_MENSAJES,
    cerrar_mensajes,
    es_mensaje_del_usuario,
    huella_mensaje,
    normalizar_mensaje,
    plegar,
    registrar_mensaje,
    ruta_registro,
    usar_mensaje,
)


def test_registro_en_config_de_trovefy_y_sin_texto(tmp_path):
    assert registrar_mensaje("Sí, dale", ahora=100.0)
    ruta = ruta_registro()
    assert ruta == tmp_path / ".config" / "trovefy" / "mensajes-usuario.json"
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600
    assert stat.S_IMODE(ruta.parent.stat().st_mode) == 0o700
    texto = ruta.read_text(encoding="utf-8")
    assert "dale" not in texto.casefold()
    assert len(json.loads(texto)) == 1


def test_mensaje_entero_y_posterior(tmp_path):
    registrar_mensaje("  Sí,\n  dale  ", ahora=100.0)
    assert es_mensaje_del_usuario("Sí, dale", desde=50.0)
    assert not es_mensaje_del_usuario("Sí, dale", desde=150.0)   # anterior al plan
    assert not es_mensaje_del_usuario("dale", desde=50.0)         # un trozo no vale: el mensaje entero
    assert not es_mensaje_del_usuario("Sí, dale. Y cambia el precio", desde=50.0)


def test_normalizar_mensaje():
    assert normalizar_mensaje(" a\t b\n\nc ") == "a b c"
    assert normalizar_mensaje("Sí") == normalizar_mensaje("Sí")  # NFC


def test_solo_los_ultimos(tmp_path):
    for i in range(MAX_MENSAJES + 5):
        registrar_mensaje(f"m{i}", ahora=float(i))
    datos = json.loads(ruta_registro().read_text(encoding="utf-8"))
    assert len(datos) == MAX_MENSAJES
    assert not es_mensaje_del_usuario("m0", desde=0.0)
    assert es_mensaje_del_usuario(f"m{MAX_MENSAJES + 4}", desde=0.0)


def test_registro_roto_o_enlace_no_vale(tmp_path):
    ruta = ruta_registro()
    ruta.parent.mkdir(parents=True)
    ruta.write_text("no es json", encoding="utf-8")
    assert not es_mensaje_del_usuario("sí", desde=0.0)
    assert registrar_mensaje("sí", ahora=1.0)  # se rehace
    assert es_mensaje_del_usuario("sí", desde=0.0)
    ruta.unlink()
    (tmp_path / "otro.json").write_text("[]", encoding="utf-8")
    ruta.symlink_to(tmp_path / "otro.json")
    assert not registrar_mensaje("sí", ahora=2.0)
    assert not es_mensaje_del_usuario("sí", desde=0.0)


def test_vacio_no_se_registra(tmp_path):
    assert not registrar_mensaje("   ", ahora=1.0)
    assert not ruta_registro().exists()


# --- revisión de la Tarea 11 (H1, H3) ------------------------------------------------------------------------------


def test_la_huella_no_distingue_mayusculas_ni_tildes(tmp_path):
    assert huella_mensaje("Sí, aplica la etapa 1 (ab12)") == huella_mensaje("SI, APLICA LA ETAPA 1 (AB12)")
    assert huella_mensaje("sí, aplica la etapa 1 (ab12)") != huella_mensaje("sí, aplica la etapa 1 (ab12).")
    assert plegar("  Sí,\n APLICA ") == "si, aplica"


def test_un_mensaje_se_usa_para_un_solo_plan(tmp_path):
    registrar_mensaje("sí, aplica la etapa 1 (ab12)", ahora=100.0)
    assert usar_mensaje("sí, aplica la etapa 1 (ab12)", desde=50.0, huella="a" * 64) is not None
    # Ya marcado para el plan «a…»: no aprueba otro plan, sí se puede volver a comprobar para el suyo.
    assert usar_mensaje("sí, aplica la etapa 1 (ab12)", desde=50.0, huella="b" * 64) is None
    assert es_mensaje_del_usuario("sí, aplica la etapa 1 (ab12)", desde=50.0, huella="a" * 64)
    assert not es_mensaje_del_usuario("sí, aplica la etapa 1 (ab12)", desde=50.0, huella="b" * 64)
    # Sin marcar (nadie lo usó para aprobar), la guarda no lo acepta.
    registrar_mensaje("sí, aplica la etapa 2 (cd34)", ahora=200.0)
    assert not es_mensaje_del_usuario("sí, aplica la etapa 2 (cd34)", desde=50.0, huella="c" * 64)
    # Al releer, la aprobación se cierra: ya no vale ni para su plan.
    cerrar_mensajes("a" * 64)
    assert not es_mensaje_del_usuario("sí, aplica la etapa 1 (ab12)", desde=50.0, huella="a" * 64)
    assert usar_mensaje("sí, aplica la etapa 1 (ab12)", desde=50.0, huella="a" * 64) is None


def test_en_la_terminal_se_anota_con_su_marca(tmp_path):
    assert usar_mensaje("sí, aplica la etapa 1 (ab12)", desde=50.0, huella="a" * 64) is None
    e = usar_mensaje("sí, aplica la etapa 1 (ab12)", desde=50.0, huella="a" * 64, terminal=True, ahora=60.0)
    assert e is not None and e["u"] == "a" * 64
    assert es_mensaje_del_usuario("sí, aplica la etapa 1 (ab12)", desde=50.0, huella="a" * 64)


def test_las_marcadas_no_se_pierden_al_recortar(tmp_path):
    registrar_mensaje("frase", ahora=1.0)
    assert usar_mensaje("frase", desde=0.0, huella="a" * 64) is not None
    for i in range(MAX_MENSAJES + 5):
        registrar_mensaje(f"m{i}", ahora=10.0 + i)
    assert es_mensaje_del_usuario("frase", desde=0.0, huella="a" * 64)
