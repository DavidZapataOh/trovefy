import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from trovefy.aprobaciones.fuentes import Lectura
from trovefy.vigia import comprobaciones as c
from trovefy.vigia.comprobaciones import Comprobacion, Fuentes

COT = timezone(timedelta(hours=-5))
AHORA = datetime(2026, 11, 12, 10, 0, tzinfo=COT)  # jueves
CUENTA = "act_0000000000000000"


def iso(delta: timedelta) -> str:
    return (AHORA - delta).isoformat()


def latido_ok(**extra):
    d = {"fecha": iso(timedelta(seconds=20)), "version": "1", "modo": "simulado", "stop": False,
         "telegram": "ok", "pendientes": 0, "reloj_desfase_s": 0.1, "vault": "ok", "avisos": []}
    d.update(extra)
    return Lectura(d, None)


def meta_ok(**extra):
    d = {"fecha": iso(timedelta(hours=1)), "cuenta": CUENTA, "currency": "COP", "offset": 1, "account_status": 1,
         "validate_only": {"ok": True, "motivo": None}}
    d.update(extra)
    return Lectura(d, None)


NO = Lectura(None, "no medido: el ejecutor aún no está instalado (no existe /x)")


def env_apimart(tmp_path):
    ruta = tmp_path / "claude.env"
    ruta.write_text("APIMART_API_KEY=sk-secreta-123\n")
    ruta.chmod(0o600)
    return ruta


def test_vigia_sin_fuentes_no_mide_ni_alerta(tmp_path):
    fu = Fuentes(spool=tmp_path / "sin-spool", unidades=tmp_path / "sin-unidades", ruta_env=tmp_path / "sin.env")
    vault = tmp_path / "vault"
    vault.mkdir()
    res = c.vigilar(vault, AHORA, fu)
    por_nombre = {x.nombre: x for x in res}
    for n in ("latido", "tokens", "cuenta", "apimart"):
        assert por_nombre[n].nivel == "no_medido" and por_nombre[n].texto.startswith("no medido: "), n
        assert not re.search(r"\d", por_nombre[n].texto.replace(str(tmp_path), "")), por_nombre[n].texto
    assert c.alerta(res) is None


def test_latido_viejo_alerta():
    assert c.latido(AHORA, latido_ok()).nivel == "ok"
    assert c.latido(AHORA, latido_ok(fecha=iso(timedelta(minutes=11)))).nivel == "aviso"
    assert c.latido(AHORA, latido_ok(fecha=iso(timedelta(hours=3)))).nivel == "urgente"
    assert c.latido(AHORA, NO).nivel == "no_medido"
    assert c.latido(AHORA, Lectura({"fecha": "basura"}, None)).nivel == "no_medido"


def test_avisos_del_ejecutor_son_comprobaciones():
    res = c.avisos_ejecutor(latido_ok(avisos=["reloj desfasado"], telegram="sin red", vault="no escribible"))
    assert all(x.nivel == "aviso" for x in res) and len(res) == 3
    assert any("El ejecutor avisa: reloj desfasado" in x.texto for x in res)
    assert c.avisos_ejecutor(latido_ok()) == []
    assert c.avisos_ejecutor(NO) == []


def test_token_sin_dato_no_medido():
    r = c.tokens(AHORA, meta_ok())
    assert r.nivel == "no_medido" and r.texto == "no medido: el ejecutor no informa la caducidad del token"
    assert c.tokens(AHORA, NO).nivel == "no_medido"


def test_token_caduca():
    assert c.tokens(AHORA, meta_ok(token_caduca=(AHORA + timedelta(days=5)).isoformat())).nivel == "aviso"
    assert c.tokens(AHORA, meta_ok(token_caduca=(AHORA - timedelta(days=1)).isoformat())).nivel == "urgente"
    assert c.tokens(AHORA, meta_ok(token_caduca=(AHORA + timedelta(days=30)).isoformat())).nivel == "ok"


def test_validate_only_falla_por_token():
    m = meta_ok(validate_only={"ok": False, "motivo": "token caducado (code 190)"})
    assert c.tokens(AHORA, m).nivel == "urgente"


def test_cuenta_meta():
    assert c.cuenta_meta(meta_ok(), AHORA).nivel == "ok"
    assert c.cuenta_meta(meta_ok(account_status=2), AHORA).nivel == "urgente"
    r = c.cuenta_meta(meta_ok(fecha=iso(timedelta(hours=60))), AHORA)
    assert r.nivel == "info" and "dato del 2026-11-09" in r.texto
    assert c.cuenta_meta(NO, AHORA).nivel == "no_medido"


def test_stop_dos_fuentes(tmp_path):
    (tmp_path / ".trovefy").mkdir()
    assert c.stop(tmp_path, Lectura({"activo": False}, None)).nivel == "ok"
    r = c.stop(tmp_path, Lectura({"activo": True, "motivo": "a mano"}, None))
    assert r.nivel == "info" and "del ejecutor" in r.texto and "del cerebro" not in r.texto
    (tmp_path / ".trovefy" / "STOP").write_text("")
    r = c.stop(tmp_path, Lectura({"activo": True}, None))
    assert "del ejecutor" in r.texto and "del cerebro" in r.texto
    r = c.stop(tmp_path, NO)
    assert r.nivel == "info" and "del cerebro" in r.texto


def test_apimart_bajo(tmp_path, respuesta_json):
    env = env_apimart(tmp_path)
    abrir = respuesta_json(200, {"success": True, "remain_balance": 0.8})
    r = c.apimart(env, 100, abrir)
    assert r.nivel == "aviso" and r.texto == "Quedan 0,80 USD (aviso por debajo de 1,00)"
    ok = c.apimart(env, 100, respuesta_json(200, {"success": True, "remain_balance": 10.5}))
    assert ok.nivel == "ok" and "10,50" in ok.texto
    assert "sk-secreta" not in repr(abrir.peticiones[0][0].full_url)


@pytest.mark.parametrize("codigo,cuerpo", [(401, {}), (500, {}), (200, b"no json"), (200, {"success": False})])
def test_apimart_fallos_son_no_medido_sin_clave(tmp_path, respuesta_json, codigo, cuerpo):
    r = c.apimart(env_apimart(tmp_path), 100, respuesta_json(codigo, cuerpo))
    assert r.nivel == "no_medido" and "sk-secreta" not in r.texto


def test_apimart_red_caida_y_env_inseguro(tmp_path):
    def caida(req, timeout=None):
        raise OSError("sin red sk-secreta-123")

    r = c.apimart(env_apimart(tmp_path), 100, caida)
    assert r.nivel == "no_medido" and "sk-secreta" not in r.texto
    env = tmp_path / "otro.env"
    env.write_text("APIMART_API_KEY=sk-secreta-123\n")
    env.chmod(0o644)
    r = c.apimart(env, 100, caida)
    assert r.nivel == "no_medido" and "sk-secreta" not in r.texto


def test_disco_lleno(tmp_path):
    gib = 1 << 30
    assert c.disco(tmp_path, lambda p: (100 * gib, 50 * gib, 50 * gib)).nivel == "ok"
    assert c.disco(tmp_path, lambda p: (100 * gib, 95 * gib, 5 * gib)).nivel == "aviso"
    assert c.disco(tmp_path, lambda p: (10 * gib, 9 * gib, 1 * gib)).nivel == "aviso"

    def roto(p):
        raise OSError

    assert c.disco(tmp_path, roto).nivel == "no_medido"


def _timer(tmp_path):
    u = tmp_path / "unidades"
    u.mkdir()
    (u / "trovefy-caza.timer").write_text("")
    return u


def test_rutina_caza_falto(tmp_path):
    u = _timer(tmp_path)
    assert c.rutinas(tmp_path, AHORA, u).nivel == "aviso"
    log = tmp_path / "rutinas" / "log" / "2026-11-12"
    log.mkdir(parents=True)
    (log / "caza.md").write_text("# Rutina caza\n\n## 06:31 COT · ok\n\nx\n\n## 06:50 COT · parada\n")
    assert c.rutinas(tmp_path, AHORA, u).nivel == "aviso"
    (log / "caza.md").write_text("# Rutina caza\n\n## 06:31 COT · ok\n\nx\n")
    assert c.rutinas(tmp_path, AHORA, u).nivel == "ok"


def test_rutina_antes_de_las_siete_y_sin_timer(tmp_path):
    u = _timer(tmp_path)
    assert c.rutinas(tmp_path, AHORA.replace(hour=6, minute=45), u).nivel == "ok"
    assert c.rutinas(tmp_path, AHORA, tmp_path / "vacia").nivel == "no_medido"


def test_domingo_no_espera_caza(tmp_path):
    domingo = datetime(2026, 11, 15, 10, 0, tzinfo=COT)
    assert c.rutinas(tmp_path, domingo, _timer(tmp_path)).nivel == "ok"


def test_impultienda(tmp_path):
    r = c.impultienda(tmp_path)
    assert r.nivel == "no_medido" and r.texto == "no medido: requiere navegador (pídelo con /arranque 09)"
    ev = tmp_path / "config" / "evidencia"
    ev.mkdir(parents=True)
    (ev / "09-impultienda-2026-11-01.json").write_text("{}")
    (ev / "09-impultienda-2026-11-05.json").write_text("{}")
    r = c.impultienda(tmp_path)
    assert r.nivel == "info" and "2026-11-05" in r.texto


def test_no_medidas():
    res = c.no_medidas()
    assert len(res) == 4 and all(x.nivel == "no_medido" and "MCP oficial de Meta" in x.texto for x in res)


def test_alerta_unica_con_nivel_maximo():
    from trovefy_ejecutor.esquema import cargar_propuesta

    res = [Comprobacion("a", "aviso", "uno"), Comprobacion("b", "urgente", "dos"),
           Comprobacion("c", "info", "x"), Comprobacion("d", "no_medido", "no medido: y")]
    a = c.alerta(res)
    assert a["tipo"] == "alerta" and a["origen"] == "/vigia" and a["nivel"] == "urgente"
    assert a["titulo"] == "Vigía: 2 avisos" and a["texto"].splitlines() == ["a: uno", "b: dos"]
    cargar_propuesta({**a, "version": 1, "id": "P-20261112-001", "creada": AHORA.isoformat()})
    assert c.alerta([Comprobacion("a", "aviso", "uno")])["nivel"] == "aviso"


def test_sin_problemas_no_alerta():
    assert c.alerta([Comprobacion("a", "ok", "x"), Comprobacion("b", "info", "y"),
                     Comprobacion("c", "no_medido", "no medido: z")]) is None


def test_informe_iconos():
    t = c.informe([Comprobacion("a", "ok", "x"), Comprobacion("b", "no_medido", "no medido: z"),
                   Comprobacion("c", "urgente", "w")])
    assert "OK" in t and "NO MEDIDO" in t and "URGENTE" in t and len(t.strip().splitlines()) >= 3


def test_vigilar_completo(tmp_path):
    spool = tmp_path / "spool"
    (spool / "estado").mkdir(parents=True)
    (spool / "estado" / "latido.json").write_text(json.dumps(latido_ok(avisos=["x"]).datos))
    vault = tmp_path / "vault"
    (vault / "config").mkdir(parents=True)
    fu = Fuentes(spool=spool, unidades=tmp_path / "u", ruta_env=tmp_path / "no.env",
                 uso_disco=lambda p: (100 << 30, 1 << 30, 99 << 30))
    res = c.vigilar(vault, AHORA, fu)
    assert any("El ejecutor avisa: x" in x.texto for x in res)
    assert c.alerta(res)["titulo"] == "Vigía: 1 avisos"


LARGA = "act_1234567890123456"


def test_vigia_enmascara_ids_de_cuenta_en_informe_y_alerta():
    res = [Comprobacion("tokens", "urgente", f"el token de Meta falla: (#200) {LARGA} sin permiso"),
           Comprobacion("stop", "info", f"STOP del ejecutor activo ({LARGA})")]
    t = c.informe(res)
    a = c.alerta(res)
    assert LARGA not in t and LARGA not in a["texto"]
    assert "act_…3456" in t and "act_…3456" in a["texto"]


def _carpeta_referencia(base, dias_caduca):
    carpeta = base / "p-0001-x" / "123"
    carpeta.mkdir(parents=True)
    (carpeta / "caduca.json").write_text(json.dumps({"caduca": (AHORA + timedelta(days=dias_caduca)).isoformat()}))


def test_vigia_referencia_vencida(tmp_path):
    base = tmp_path / "cache"
    _carpeta_referencia(base, -1)
    r = c.referencia_cache(AHORA, base)
    assert r.nivel == "aviso"
    assert "1 carpetas o lotes de referencia pasaron sus 30 días" in r.texto
    assert "trovefy ver-anuncios limpiar" in r.texto


def test_vigia_referencia_sin_base_ok(tmp_path):
    r = c.referencia_cache(AHORA, tmp_path / "no-existe")
    assert r.nivel == "ok" and "sin medios de referencia" in r.texto


def test_vigia_referencia_vigente_ok(tmp_path):
    base = tmp_path / "cache"
    _carpeta_referencia(base, 5)
    assert c.referencia_cache(AHORA, base).nivel == "ok"


def test_vigilar_incluye_referencia(tmp_path):
    base = tmp_path / "cache"
    _carpeta_referencia(base, -1)
    fu = Fuentes(spool=tmp_path / "s", unidades=tmp_path / "u", ruta_env=tmp_path / "e", cache_referencia=base)
    vault = tmp_path / "vault"
    vault.mkdir()
    res = {x.nombre: x for x in c.vigilar(vault, AHORA, fu)}
    assert res["referencia"].nivel == "aviso"


def test_vigia_referencia_cuenta_lotes_mcp_vencidos(tmp_path):
    import os

    base = tmp_path / "cache"
    mcp = base / "p-0001-x" / "mcp"
    mcp.mkdir(parents=True)
    lote = mcp / "lote-a.json"
    lote.write_text("{}")
    t = (AHORA - timedelta(days=400)).timestamp()
    os.utime(lote, (t, t))
    r = c.referencia_cache(AHORA, base)
    assert r.nivel == "aviso" and r.texto.startswith("1 ")


def test_vigia_referencia_iterdir_falla_no_revienta(tmp_path, monkeypatch):
    from trovefy.referencia import cache as cache_ref

    base = tmp_path / "cache"
    base.mkdir()

    def falla(*a, **kw):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(cache_ref, "vencidos", falla)
    r = c.referencia_cache(AHORA, base)
    assert r.nivel == "aviso" and "no se pudo leer" in r.texto and "PermissionError" in r.texto


def test_vigia_referencia_usa_retencion_configurada(tmp_path):
    base = tmp_path / "cache"
    lote = base / "p-0001-x" / "mcp" / "lote-x.json"
    lote.parent.mkdir(parents=True)
    lote.write_text("{}")
    import os

    viejo = (AHORA - timedelta(days=45)).timestamp()
    os.utime(lote, (viejo, viejo))
    assert c.referencia_cache(AHORA, base, 60).nivel == "ok"
    assert c.referencia_cache(AHORA, base, 30).nivel == "aviso"


def test_retencion_referencia_sin_umbrales_usa_defecto(tmp_path):
    assert c._retencion_referencia(tmp_path) == 30
