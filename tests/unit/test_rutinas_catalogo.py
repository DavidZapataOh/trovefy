"""Catálogo de rutinas, unidades genéricas, herramientas validadas, condición y fin (plan 24, Tarea 9).

Nunca systemd real: ``ejecutar`` falso; HOME, vault y buzón en tmp_path."""
import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml
from trovefy import rutinas
from trovefy.vault import frontmatter
from trovefy.vault.andamio import crear_vault
from trovefy.vault.escritura import ZONA_NEGOCIO

RAIZ = Path(__file__).resolve().parents[2]
META_TOOLS = ["ads_get_ad_accounts", "ads_get_ad_entities", "ads_get_field_context", "ads_get_dataset_stats",
              "ads_account_get_activity_logs", "ads_update_entity"]
P = "p-0099-prueba-abc123"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TROVEFY_SPOOL", str(tmp_path / "spool"))
    v = tmp_path / "vault"
    crear_vault(v)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    mercados = yaml.safe_load((v / "config" / "mercados.yaml").read_text(encoding="utf-8")) or {}
    mercados["ZZ"] = {"moneda": "EUR", "zona": "Europe/Sofia"}
    (v / "config" / "mercados.yaml").write_text(yaml.safe_dump(mercados), encoding="utf-8")
    return v


def _test_vivo(v: Path, t0: str = "2026-11-18T00:00:00-05:00") -> None:
    caja = yaml.safe_load((RAIZ / "templates/cerebro/config/caja.yaml").read_text(encoding="utf-8"))
    caja["cuenta"] = {"id": "act_0000000000000000", "moneda": "COP"}
    caja["tests"] = [{"producto": P, "pais": "ZZ", "campana_id": "120000000000000001", "estado": "vivo",
                      "prorroga": False, "ventas": None, "diario_usd": 25}]
    (v / "config" / "caja.yaml").write_text(yaml.safe_dump(caja), encoding="utf-8")
    frontmatter.escribir(v / "productos" / P / "PRODUCTO.md",
                         {"tipo": "producto", "id": P, "paises": {"ZZ": {"estado": "test", "trafico": {
                             "activado": t0, "inicio": t0}}}}, "\n# P\n")


def _planes(v, nombres, paises=(), meta_tools=META_TOOLS, catalogo=None):
    return rutinas.planificar(nombres, v, "/usr/bin/claude", paises, meta_tools=meta_tools, catalogo=catalogo,
                              trovefy="/home/u/.local/bin/trovefy")


def test_catalogo_carga_y_horas():
    cat = rutinas.cargar_catalogo()
    assert {"caza", "vigia", "parte", "cierre", "cierre-noche", "intradia", "base", "renovacion"} <= set(cat)
    assert cat["cierre"].calendario == "*-*-* 08:30:00 America/Bogota"
    assert cat["cierre-noche"].calendario == "*-*-* 23:30:00 America/Bogota" and not cat["cierre-noche"].persistente
    assert cat["vigia"].calendario.startswith("*-*-* 07:00:00")
    assert not cat["caza"].fin and cat["cierre"].fin


def test_caza_igual_que_antes():
    cat = rutinas.cargar_catalogo()
    assert rutinas.unidades(cat["caza"], Path("/v"), "/usr/bin/claude") == rutinas.unidad_caza(Path("/v"),
                                                                                                 "/usr/bin/claude")


def test_unidad_cierre(vault):
    (plan,), problemas = _planes(vault, ["cierre"])
    assert problemas == []
    assert "OnCalendar=*-*-* 08:30:00 America/Bogota" in plan.timer and "Persistent=true" in plan.timer
    assert "ExecStopPost=/home/u/.local/bin/trovefy rutinas fin cierre" in plan.servicio
    assert 'ExecStart=/usr/bin/claude -p "/trovefy:cierre --rutina" --allowedTools "Read,Bash(trovefy cierre *)' \
        in plan.servicio
    assert "ExecCondition" not in plan.servicio and "TimeoutStartSec=45min" in plan.servicio
    assert "dangerously" not in plan.servicio


def test_unidad_cierre_noche_2330(vault):
    (plan,), _ = _planes(vault, ["cierre-noche"])
    assert "OnCalendar=*-*-* 23:30:00 America/Bogota" in plan.timer and "Persistent=false" in plan.timer
    assert '"/trovefy:cierre --rutina --noche"' in plan.servicio


def test_unidad_intradia_zona_del_pais(vault):
    (plan,), problemas = _planes(vault, ["intradia"], ["ZZ"])
    assert problemas == [] and plan.instancia == "intradia-zz"
    assert "OnCalendar=*-*-* 00/2:00:00 Europe/Sofia" in plan.timer and "Persistent=false" in plan.timer
    assert "ExecCondition=/home/u/.local/bin/trovefy rutinas condicion intradia --pais ZZ" in plan.servicio
    assert '"/trovefy:leer --intradia --pais ZZ --rutina"' in plan.servicio


def test_unidad_base_23_del_pais(vault):
    (plan,), _ = _planes(vault, ["base"], ["ZZ"])
    assert "OnCalendar=*-*-* 23:00:00 Europe/Sofia" in plan.timer


def test_pais_sin_zona_no_se_instala(vault):
    planes, problemas = _planes(vault, ["intradia"], ["YY"])
    assert planes == [] and "zona" in problemas[0]


def test_renovacion_cada_48h_admite_yaml_de_la_tanda(vault):
    _test_vivo(vault)
    (plan,), problemas = _planes(vault, ["renovacion"], ["ZZ"])
    assert problemas == []
    assert f'"/trovefy:creativos {P} --pais ZZ --renovar --rutina"' in plan.servicio
    assert "Write(productos/*/creativos/*/*/brief.yaml)" in plan.servicio
    assert "ExecCondition=/home/u/.local/bin/trovefy rutinas condicion renovacion --pais ZZ" in plan.servicio


def test_renovacion_con_write_fuera_de_la_tanda_no_se_instala(vault):
    _test_vivo(vault)
    cat = rutinas.cargar_catalogo()
    mala = replace(cat["renovacion"], herramientas=(*cat["renovacion"].herramientas, "Write(productos/**)"))
    problemas = rutinas.validar_herramientas(mala, [*mala.herramientas], META_TOOLS, rutinas.catalogo_impultienda())
    assert any("Write(productos/**)" in p for p in problemas)
    otra = replace(cat["cierre"], herramientas=("Write(productos/*/creativos/*/*/brief.yaml)",))
    assert rutinas.validar_herramientas(otra, list(otra.herramientas), META_TOOLS, rutinas.catalogo_impultienda())


def test_rutina_con_escritura_de_meta_no_se_instala(vault):
    cat = rutinas.cargar_catalogo()
    mala = replace(cat["cierre"], herramientas=(*cat["cierre"].herramientas, "mcp__meta-ads__ads_update_entity"))
    problemas = rutinas.validar_herramientas(mala, list(mala.herramientas), META_TOOLS,
                                             rutinas.catalogo_impultienda())
    assert any("ads_update_entity" in p and "lectura" in p for p in problemas)
    impul = replace(cat["cierre"], herramientas=("mcp__impultienda__impultienda_ver_pago",))
    assert rutinas.validar_herramientas(impul, list(impul.herramientas), META_TOOLS, rutinas.catalogo_impultienda())


def test_rutina_fuera_de_la_skill_no_se_instala(vault):
    cat = rutinas.cargar_catalogo()
    mala = replace(cat["vigia"], herramientas=("Read", "Bash(trovefy caja *)"))
    problemas = rutinas.validar_herramientas(mala, rutinas.allowed_de_skill("vigia"), META_TOOLS,
                                             rutinas.catalogo_impultienda())
    assert problemas == ["vigia: Bash(trovefy caja *) no está en el allowed-tools de /vigia"]


def test_sin_meta_tools_no_instala_mcp_de_meta(vault):
    _, problemas = _planes(vault, ["cierre", "vigia"], meta_tools=None)
    assert any("meta_tools.json" in p for p in problemas)


def test_nunca_dangerously_ni_sudo(vault):
    cat = rutinas.cargar_catalogo()
    for h in ("Bash(sudo systemctl *)", "--dangerously-skip-permissions"):
        mala = replace(cat["vigia"], herramientas=(h,))
        assert rutinas.validar_herramientas(mala, [h], META_TOOLS, rutinas.catalogo_impultienda())
    for r in cat.values():
        assert "dangerously" not in r.argumentos and not any("sudo" in h for h in r.herramientas)


def test_todas_las_rutinas_del_catalogo_validan():
    cat = rutinas.cargar_catalogo()
    impul = rutinas.catalogo_impultienda()
    for r in cat.values():
        if r.plantilla != "caza":
            assert rutinas.validar_herramientas(r, rutinas.allowed_de_skill(r.skill), META_TOOLS, impul) == [], r.nombre


def test_ok_por_rutina(vault):
    dia = date(2026, 11, 20)
    rutinas.registrar_ejecucion(vault, "cierre", dia, "bien", ok=True)
    rutinas.registrar_ejecucion(vault, "leer-parte", dia, "mal", ok=False)
    carpeta = vault / "rutinas/log/2026-11-20"
    assert (carpeta / "cierre.ok").exists() and not (carpeta / "leer-parte.ok").exists()


def test_condicion_sin_test_vivo(vault):
    assert rutinas.condicion("parte", vault) == 1
    assert rutinas.condicion("intradia", vault, "ZZ") == 1
    assert rutinas.condicion("cierre", vault) == 0
    _test_vivo(vault)
    assert rutinas.condicion("parte", vault) == 0 and rutinas.condicion("intradia", vault, "ZZ") == 0
    assert rutinas.condicion("intradia", vault, "YY") == 1


def test_condicion_montado_sin_registrar(vault):
    frontmatter.escribir(vault / "productos" / P / "PRODUCTO.md",
                         {"tipo": "producto", "id": P, "paises": {"ZZ": {"estado": "montado", "trafico": {
                             "activar": "P-20261118-002"}}}}, "\n# P\n")
    assert rutinas.condicion("parte", vault) == 0  # resolución 12


def test_condicion_renovacion_cada_48h(vault):
    _test_vivo(vault)  # t0 = 18/11 00:00
    hora = lambda d: datetime(2026, 11, d, 20, 0, tzinfo=ZONA_NEGOCIO)
    assert [d for d in range(18, 27) if rutinas.condicion("renovacion", vault, "ZZ", hora(d)) == 0] == [19, 21, 23]


def test_fin_fallida_deposita_alerta(vault, tmp_path):
    from unit.montar.ejemplos import escribir_spool

    escribir_spool(tmp_path)
    ahora = datetime(2026, 11, 20, 8, 40, tzinfo=ZONA_NEGOCIO)
    linea = rutinas.fin("cierre", vault, "exit-code", "1", ahora)
    assert linea == "fallida: exit-code/1"
    log = (vault / "rutinas/log/2026-11-20/cierre.md").read_text()
    assert "· fallida" in log and not (vault / "rutinas/log/2026-11-20/cierre.ok").exists()
    entrada = list((tmp_path / "spool" / "entrada").glob("*.json"))
    assert len(entrada) == 1 and "falló a las 08:40" in entrada[0].read_text()


def test_fin_sin_buzon_queda_en_el_log(vault):
    ahora = datetime(2026, 11, 20, 8, 40, tzinfo=ZONA_NEGOCIO)
    (vault / ".trovefy").mkdir(exist_ok=True)
    (vault / ".trovefy" / "STOP").write_text("x")
    assert "sin aviso por Telegram" in rutinas.fin("intradia", vault, "timeout", "", ahora, pais="ZZ")
    assert (vault / "rutinas/log/2026-11-20/leer-intradia-zz.md").exists()


def test_fin_success_no_hace_nada(vault):
    assert rutinas.fin("cierre", vault, "success", "0") is None
    assert not (vault / "rutinas" / "log").exists() or not any((vault / "rutinas" / "log").rglob("*.md"))


def test_fin_omitida_no_avisa(vault):
    ahora = datetime(2026, 11, 20, 7, 30, tzinfo=ZONA_NEGOCIO)
    assert rutinas.fin("parte", vault, "exec-condition", "1", ahora) == "omitida"
    assert "· omitida" in (vault / "rutinas/log/2026-11-20/leer-parte.md").read_text()


def test_instalar_fase3_valida_antes_de_escribir(vault, tmp_path):
    llamadas = []
    with pytest.raises(rutinas.RutinaInvalida):
        rutinas.instalar(["cierre", "intradia"], vault, "/usr/bin/claude", ["YY"], ejecutar=llamadas.append,
                         meta_tools=META_TOOLS, trovefy="/t")
    assert llamadas == [] and not (tmp_path / "home/.config/systemd/user").exists()
    rutas = rutinas.instalar(["cierre", "intradia"], vault, "/usr/bin/claude", ["ZZ"], ejecutar=llamadas.append,
                             meta_tools=META_TOOLS, trovefy="/t")
    assert {r.name for r in rutas} == {"trovefy-cierre.service", "trovefy-cierre.timer",
                                       "trovefy-intradia-zz.service", "trovefy-intradia-zz.timer"}
    assert llamadas[0] == ["systemctl", "--user", "daemon-reload"]
    assert ["systemctl", "--user", "enable", "--now", "trovefy-intradia-zz.timer"] in llamadas
    assert rutinas.instaladas() == ["cierre", "intradia-zz"]
    rutinas.desinstalar(["intradia-zz"], ejecutar=llamadas.append)
    assert rutinas.instaladas() == ["cierre"]


def test_cli_instalar_fase3(vault, tmp_path, monkeypatch, capsys):
    from trovefy import cli

    _test_vivo(vault)
    (vault / "config" / "meta_tools.json").write_text(json.dumps(META_TOOLS), encoding="utf-8")
    llamadas = []
    monkeypatch.setattr(rutinas, "_systemctl", llamadas.append)
    monkeypatch.setattr(rutinas.shutil, "which", lambda n: f"/opt/bin/{n}")
    assert cli.main(["rutinas", "instalar", "fase3"]) == 0
    out = capsys.readouterr().out
    assert "Activa: cierre-noche" in out and "Activa: intradia (ZZ)" in out
    assert set(rutinas.instaladas()) == {"vigia", "parte", "cierre", "cierre-noche", "intradia-zz", "base-zz",
                                         "renovacion-zz"}


def test_cli_condicion_y_fin(vault, monkeypatch, capsys):
    from trovefy import cli

    assert cli.main(["rutinas", "condicion", "parte"]) == 1
    monkeypatch.setenv("SERVICE_RESULT", "success")
    assert cli.main(["rutinas", "fin", "cierre"]) == 0
