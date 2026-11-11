from datetime import date
from pathlib import Path

import pytest
import yaml
from trovefy import rutinas
from trovefy.rutinas import unidad_caza
from trovefy.vault.andamio import crear_vault


def test_unidad_de_caza():
    servicio, timer = unidad_caza(Path("/home/u/trovefy-cerebro"), "/usr/local/bin/claude")
    assert "OnCalendar=Mon..Sat *-*-* 06:30:00 America/Bogota" in timer
    assert "/trovefy:cazar --rutina" in servicio and "WorkingDirectory=/home/u/trovefy-cerebro" in servicio
    assert "dangerously" not in servicio


def test_unidad_lista_de_herramientas():
    servicio, timer = unidad_caza(Path("/home/u/trovefy-cerebro"), "/usr/local/bin/claude")
    assert ('ExecStart=/usr/local/bin/claude -p "/trovefy:cazar --rutina" '
            '--allowedTools "Read,Bash(trovefy caza *),Bash(trovefy cerebro *)"') in servicio
    assert 'Environment="TROVEFY_VAULT=/home/u/trovefy-cerebro"' in servicio
    assert "Unit=trovefy-caza.service" in timer and "WantedBy=timers.target" in timer


def test_unidad_con_espacios_y_porcentaje():
    servicio, _ = unidad_caza(Path("/home/u/mi cerebro 100%"), "/usr/local/bin/claude")
    assert "WorkingDirectory=/home/u/mi cerebro 100%%" in servicio
    assert 'Environment="TROVEFY_VAULT=/home/u/mi cerebro 100%%"' in servicio
    with pytest.raises(ValueError):
        unidad_caza(Path('/home/u/raro"'), "/usr/local/bin/claude")


def test_timer_persistente_documentado():
    _, timer = unidad_caza(Path("/v"), "/usr/bin/claude")
    assert "Persistent=true" in timer and "#" in timer


def test_instalar_escribe_en_home_y_activa_el_timer(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    llamadas = []
    rutas = rutinas.instalar_caza(tmp_path / "cerebro", "/usr/bin/claude", ejecutar=llamadas.append)
    unidad = tmp_path / ".config/systemd/user"
    assert rutas == [unidad / "trovefy-caza.service", unidad / "trovefy-caza.timer"]
    assert all(r.exists() for r in rutas)
    assert llamadas == [["systemctl", "--user", "daemon-reload"],
                        ["systemctl", "--user", "enable", "--now", "trovefy-caza.timer"]]


def test_registro_de_la_rutina(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    rutinas.registrar_ejecucion(v, "caza", date(2026, 11, 10), "Resumen uno", ok=True)
    carpeta = v / "rutinas/log/2026-11-10"
    assert (carpeta / "ok").exists() and "Resumen uno" in (carpeta / "caza.md").read_text()
    rutinas.registrar_ejecucion(v, "caza", date(2026, 11, 10), "Resumen dos: parada", ok=False)
    texto = (carpeta / "caza.md").read_text()
    assert "Resumen uno" in texto and "Resumen dos" in texto
    assert not (carpeta / "ok").exists()  # la última ejecución se paró: /vigia lo ve


def test_plantilla_caza_yaml_se_copia():
    raiz = Path(__file__).resolve().parents[2]
    datos = yaml.safe_load((raiz / "templates/cerebro/config/caza.yaml").read_text())
    assert datos["perfil"] == "tomi" and datos["nichos"] == [] and isinstance(datos["palabras"], dict)
    assert set(datos["regiones"]) == {"eeuu_gb", "br", "latam_es", "europa"}
    assert {"US", "GB"} <= set(datos["regiones"]["eeuu_gb"]) and datos["regiones"]["br"] == ["BR"]
    assert datos["rutina"] == {"max_busquedas": 20, "max_vigiladas_por_dia": 6}


def test_crear_vault_copia_caza_yaml(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    assert (v / "config/caza.yaml").exists()


def test_cli_rutinas_instalar(tmp_path, monkeypatch, capsys):
    from trovefy import cli
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TROVEFY_VAULT", str(tmp_path / "cerebro"))
    llamadas = []
    monkeypatch.setattr(rutinas, "_systemctl", llamadas.append)
    monkeypatch.setattr(rutinas.shutil, "which", lambda n: f"/opt/bin/{n}")
    assert cli.main(["rutinas", "instalar", "caza"]) == 0
    assert len(llamadas) == 2 and (tmp_path / ".config/systemd/user/trovefy-caza.timer").exists()
    assert "06:30" in capsys.readouterr().out


def test_cli_rutinas_sin_claude(tmp_path, monkeypatch, capsys):
    from trovefy import cli
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(rutinas.shutil, "which", lambda n: None)
    monkeypatch.setattr(rutinas, "_systemctl", lambda c: pytest.fail("no debe llamar a systemctl"))
    assert cli.main(["rutinas", "instalar", "caza"]) != 0
    assert "claude" in capsys.readouterr().err
